#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_SONARR_URL = "http://127.0.0.1:8989"
DEFAULT_CONFIG_FILE = (
    "/volume1/docker/media-stack/config/sonarr/config.xml"
)

LATINO_FORMAT_PREFIX = "[Latino]"


class UpgradeError(RuntimeError):
    pass


def read_api_key(config_file: Path) -> str:
    if not config_file.is_file():
        raise UpgradeError(
            f"Sonarr configuration file not found: {config_file}"
        )

    root = ET.parse(config_file).getroot()
    api_key = root.findtext("ApiKey", "").strip()

    if not api_key:
        raise UpgradeError(
            f"ApiKey was not found in {config_file}"
        )

    return api_key


class SonarrClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
    ) -> Any:
        body = None

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}/api/v3{path}",
            data=body,
            headers=self.headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=120,
            ) as response:
                content = response.read()

                if not content:
                    return None

                return json.loads(content)
        except Exception as error:
            raise UpgradeError(
                f"{method} {path} failed: {error}"
            ) from error

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(
        self,
        path: str,
        payload: Any,
    ) -> Any:
        return self.request(
            "POST",
            path,
            payload,
        )


def format_episode(
    season_number: int,
    episode_number: int,
) -> str:
    return f"S{season_number:02d}E{episode_number:02d}"


def is_latino_release(release: dict[str, Any]) -> bool:
    formats = [
        item.get("name", "")
        for item in release.get("customFormats", [])
    ]

    if any(
        name.startswith(LATINO_FORMAT_PREFIX)
        for name in formats
    ):
        return True

    languages = {
        item.get("name", "")
        for item in release.get("languages", [])
    }

    if "Spanish (Latino)" in languages:
        return True

    title = (release.get("title") or "").upper()

    markers = (
        "LATINO",
        "LATAM",
        "SPA ENG",
        "SPA-ENG",
        "SPA.ENG",
        "ESP ENG",
        "ESP-ENG",
        "ESP.ENG",
        "DUAL AUDIO",
        "DUAL-AUDIO",
        "DUAL.AUDIO",
    )

    return any(marker in title for marker in markers)


def installed_is_latino(
    file_payload: dict[str, Any] | None,
) -> bool:
    if not file_payload:
        return False

    return any(
        (
            item.get("name", "")
            .startswith(LATINO_FORMAT_PREFIX)
        )
        for item in file_payload.get(
            "customFormats",
            [],
        )
    )


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


def best_latino_release(
    releases: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = [
        release
        for release in releases
        if is_latino_release(release)
    ]

    candidates.sort(
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

    if not candidates:
        return None

    return candidates[0]


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
