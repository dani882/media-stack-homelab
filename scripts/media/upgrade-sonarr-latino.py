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
    ArrError as UpgradeError,
    read_api_key,
)
from common.latino import (
    best_latino_release,
    installed_is_latino,
)


def format_episode(
    season_number: int,
    episode_number: int,
) -> str:
    return f"S{season_number:02d}E{episode_number:02d}"


def resolve_series(
    all_series: list[dict[str, Any]],
    title: str,
) -> dict[str, Any]:
    exact = [
        item
        for item in all_series
        if (item.get("title") or "").casefold()
        == title.casefold()
    ]

    if len(exact) == 1:
        return exact[0]

    partial = [
        item
        for item in all_series
        if title.casefold()
        in (item.get("title") or "").casefold()
    ]

    if len(partial) == 1:
        return partial[0]

    if not exact and not partial:
        raise UpgradeError(
            f"Series not found in Sonarr: {title}"
        )

    names = ", ".join(
        item.get("title", "")
        for item in (exact or partial)
    )

    raise UpgradeError(
        f"Series name is ambiguous: {names}"
    )


def process_series(
    client: SonarrClient,
    series: dict[str, Any],
    season_filter: int | None,
    dry_run: bool,
) -> tuple[int, int]:
    series_id = int(series["id"])
    title = series.get("title", "")

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

    actionable = 0
    grabbed = 0

    print()
    print(
        f"=== {title} (ID={series_id}) ==="
    )

    for episode in episodes:
        season_number = int(
            episode.get("seasonNumber", 0)
        )
        episode_number = int(
            episode.get("episodeNumber", 0)
        )

        if season_number == 0:
            continue

        if (
            season_filter is not None
            and season_number != season_filter
        ):
            continue

        if not episode.get("monitored", False):
            continue

        episode_id = int(episode["id"])

        file_payload = None
        episode_file_id = episode.get(
            "episodeFileId"
        )

        if episode_file_id:
            file_payload = files_by_id.get(
                int(episode_file_id)
            )

        if installed_is_latino(file_payload):
            continue

        label = format_episode(
            season_number,
            episode_number,
        )

        print(
            f"Checking {label} "
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

        best = best_latino_release(
            releases
        )

        if best is None:
            continue

        approved = bool(
            best.get("approved", False)
        )
        rejected = bool(
            best.get("rejected", False)
        )

        if not approved or rejected:
            continue

        score = int(
            best.get(
                "customFormatScore",
                0,
            )
            or 0
        )

        seeders = int(
            best.get(
                "seeders",
                0,
            )
            or 0
        )

        release_title = best.get(
            "title",
            "",
        )

        actionable += 1

        prefix = (
            "WOULD GRAB"
            if dry_run
            else "GRABBING"
        )

        print(
            f"{prefix}: {label} "
            f"score={score} "
            f"seeders={seeders}"
        )
        print(
            f"  {release_title}"
        )

        if dry_run:
            continue

        client.post(
            "/release",
            best,
        )

        grabbed += 1

    return actionable, grabbed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Upgrade monitored Sonarr episodes to "
            "approved Latino releases."
        )
    )

    parser.add_argument(
        "--series",
        help=(
            "Only process one series. "
            "Default: all monitored series."
        ),
    )

    parser.add_argument(
        "--season",
        type=int,
        help=(
            "Only process one season. "
            "Requires --series."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show upgrades without grabbing releases."
        ),
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

    if (
        args.season is not None
        and not args.series
    ):
        parser.error(
            "--season requires --series"
        )

    api_key = read_api_key(
        Path(args.config_file)
    )

    client = SonarrClient(
        args.sonarr_url,
        api_key,
    )

    all_series = client.get("/series")

    if args.series:
        selected = [
            resolve_series(
                all_series,
                args.series,
            )
        ]
    else:
        selected = [
            item
            for item in all_series
            if item.get(
                "monitored",
                False,
            )
        ]

    total_actionable = 0
    total_grabbed = 0

    for series in selected:
        actionable, grabbed = process_series(
            client,
            series,
            args.season,
            args.dry_run,
        )

        total_actionable += actionable
        total_grabbed += grabbed

    print()
    print("=== Summary ===")
    print(
        f"Series processed: {len(selected)}"
    )
    print(
        f"Actionable Latino upgrades: "
        f"{total_actionable}"
    )

    if args.dry_run:
        print(
            "Dry run: no releases were grabbed."
        )
    else:
        print(
            f"Releases grabbed: "
            f"{total_grabbed}"
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except UpgradeError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
