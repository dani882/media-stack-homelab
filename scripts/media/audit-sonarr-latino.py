#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path
from typing import Any


DEFAULT_SONARR_URL = "http://127.0.0.1:8989"
DEFAULT_CONFIG_FILE = (
    "/volume1/docker/media-stack/config/sonarr/config.xml"
)

from common.arr import (
    ArrClient as SonarrClient,
    ArrError as AuditError,
    read_api_key,
)
from common.latino import (
    installed_is_latino,
    is_latino_release,
)


def format_episode(
    season_number: int,
    episode_number: int,
) -> str:
    return f"S{season_number:02d}E{episode_number:02d}"


def resolve_series(
    client: SonarrClient,
    title: str,
) -> dict[str, Any]:
    series = client.get("/series")

    exact = [
        item
        for item in series
        if (item.get("title") or "").casefold()
        == title.casefold()
    ]

    if len(exact) == 1:
        return exact[0]

    partial = [
        item
        for item in series
        if title.casefold()
        in (item.get("title") or "").casefold()
    ]

    if len(partial) == 1:
        return partial[0]

    if not exact and not partial:
        raise AuditError(
            f"Series not found in Sonarr: {title}"
        )

    matches = exact or partial
    names = ", ".join(
        item.get("title", "")
        for item in matches
    )

    raise AuditError(
        f"Series name is ambiguous: {names}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Sonarr episodes for currently available "
            "Latino releases."
        )
    )

    parser.add_argument(
        "--series",
        required=True,
        help="Series title as it appears in Sonarr.",
    )

    parser.add_argument(
        "--season",
        type=int,
        help="Only audit one season, for example --season 2.",
    )

    parser.add_argument(
        "--sonarr-url",
        default=DEFAULT_SONARR_URL,
    )

    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE,
    )

    args = parser.parse_args()

    api_key = read_api_key(Path(args.config_file))

    client = SonarrClient(
        args.sonarr_url,
        api_key,
    )

    series = resolve_series(client, args.series)
    series_id = int(series["id"])

    episodes = client.get(
        f"/episode?seriesId={series_id}"
    )

    files = client.get(
        f"/episodefile?seriesId={series_id}"
    )

    files_by_id = {
        int(item["id"]): item
        for item in files
    }

    rows: list[dict[str, Any]] = []

    for episode in episodes:
        season_number = int(
            episode.get("seasonNumber", 0)
        )
        episode_number = int(
            episode.get("episodeNumber", 0)
        )

        if season_number == 0:
            continue

        if args.season is not None and season_number != args.season:
            continue

        if not episode.get("monitored", False):
            continue

        episode_id = int(episode["id"])
        episode_label = format_episode(
            season_number,
            episode_number,
        )

        print(
            f"Searching {episode_label} "
            f"{episode.get('title', '')}...",
            file=sys.stderr,
            flush=True,
        )

        releases = client.get(
            "/release?"
            + urllib.parse.urlencode(
                {"episodeId": episode_id}
            )
        )

        latino_releases = [
            release
            for release in releases
            if is_latino_release(release)
        ]

        # Prefer releases Sonarr can actually grab. Only after that
        # compare custom-format score and seed count. This prevents a
        # rejected 2160p release from hiding an approved 1080p release.
        latino_releases.sort(
            key=lambda item: (
                bool(item.get("approved", False)),
                not bool(item.get("rejected", False)),
                int(
                    item.get(
                        "customFormatScore",
                        0,
                    )
                    or 0
                ),
                int(
                    item.get(
                        "seeders",
                        0,
                    )
                    or 0
                ),
            ),
            reverse=True,
        )

        file_payload = None

        episode_file_id = episode.get(
            "episodeFileId"
        )

        if episode_file_id:
            file_payload = files_by_id.get(
                int(episode_file_id)
            )

        installed_score = 0
        installed_languages: list[str] = []
        installed_latino = False

        if file_payload:
            installed_score = int(
                file_payload.get(
                    "customFormatScore",
                    0,
                )
                or 0
            )

            installed_languages = [
                item.get("name", "")
                for item in file_payload.get(
                    "languages",
                    [],
                )
            ]

            installed_latino = installed_is_latino(
                file_payload
            )

        best = (
            latino_releases[0]
            if latino_releases
            else None
        )

        rows.append(
            {
                "episode": format_episode(
                    season_number,
                    episode_number,
                ),
                "title": episode.get(
                    "title",
                    "",
                ),
                "installed": (
                    "latino"
                    if installed_latino
                    else (
                        "fallback"
                        if file_payload
                        else "missing"
                    )
                ),
                "installed_score": installed_score,
                "installed_languages": (
                    installed_languages
                ),
                "latino_available": bool(
                    latino_releases
                ),
                "latino_count": len(
                    latino_releases
                ),
                "best_title": (
                    best.get("title", "")
                    if best
                    else ""
                ),
                "best_score": (
                    int(
                        best.get(
                            "customFormatScore",
                            0,
                        )
                        or 0
                    )
                    if best
                    else 0
                ),
                "best_seeders": (
                    int(
                        best.get(
                            "seeders",
                            0,
                        )
                        or 0
                    )
                    if best
                    else 0
                ),
                "best_approved": (
                    bool(
                        best.get(
                            "approved",
                            False,
                        )
                    )
                    if best
                    else False
                ),
                "best_rejected": (
                    bool(
                        best.get(
                            "rejected",
                            False,
                        )
                    )
                    if best
                    else False
                ),
                "best_rejections": (
                    best.get(
                        "rejections",
                        [],
                    )
                    if best
                    else []
                ),
            }
        )

    print(
        f"Series: {series.get('title')} "
        f"(ID={series_id})"
    )

    print()

    print(
        "Episode  Installed  Score  "
        "Latino available  Best score  Seeders"
    )

    print(
        "-------  ---------  -----  "
        "----------------  ----------  -------"
    )

    for row in rows:
        available = (
            f"yes ({row['latino_count']})"
            if row["latino_available"]
            else "no"
        )

        print(
            f"{row['episode']:<7}  "
            f"{row['installed']:<9}  "
            f"{row['installed_score']:<5}  "
            f"{available:<16}  "
            f"{row['best_score']:<10}  "
            f"{row['best_seeders']}"
        )

    print()
    print("=== Actionable upgrades ===")

    actionable = [
        row
        for row in rows
        if (
            row["latino_available"]
            and row["best_approved"]
            and not row["best_rejected"]
            and row["installed"] != "latino"
        )
    ]

    if not actionable:
        print(
            "No fallback episodes currently have an approved "
            "Latino upgrade that is not already queued."
        )
    else:
        for row in actionable:
            print()
            print(
                f"{row['episode']} "
                f"{row['title']}"
            )
            print(
                f"  current score: "
                f"{row['installed_score']}"
            )
            print(
                f"  best Latino score: "
                f"{row['best_score']}"
            )
            print(
                f"  seeders: "
                f"{row['best_seeders']}"
            )
            print(
                f"  approved: "
                f"{row['best_approved']}"
            )
            print(
                f"  release: "
                f"{row['best_title']}"
            )

            if row["best_rejections"]:
                print(
                    "  rejections: "
                    + "; ".join(
                        row[
                            "best_rejections"
                        ]
                    )
                )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
