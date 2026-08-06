#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_URL = "http://127.0.0.1:7878"

LATINO_MARKERS = (
    "latino",
    "latam",
    "es-419",
    "es.419",
    "es_419",
    "spa lat",
    "spa-lat",
    "spa.lat",
    "esp lat",
    "esp-lat",
    "esp.lat",
    "spanish latino",
    "audio latino",
    "yerisan710",
    "userhevc",
    "urbin4hd",
    "dav1nci",
)


class AuditError(RuntimeError):
    pass


def read_api_key(config_file: Path) -> str:
    environment_key = os.environ.get("RADARR_KEY", "").strip()

    if environment_key:
        return environment_key

    if not config_file.is_file():
        raise AuditError(
            f"Radarr configuration file not found: {config_file}"
        )

    try:
        root = ET.parse(config_file).getroot()
    except ET.ParseError as error:
        raise AuditError(
            f"Unable to parse Radarr configuration: {error}"
        ) from error

    element = root.find("ApiKey")

    if element is None or not (element.text or "").strip():
        raise AuditError(
            f"Radarr API key not found in {config_file}"
        )

    return (element.text or "").strip()


class RadarrClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "X-Api-Key": api_key,
        }

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}/api/v3{path}",
            headers=self.headers,
            method="GET",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=120,
            ) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            body = error.read().decode(
                "utf-8",
                errors="replace",
            )
            raise AuditError(
                f"GET {path} failed with HTTP "
                f"{error.code}:\n{body}"
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise AuditError(
                f"GET {path} failed: {error}"
            ) from error


def normalized_title(value: str) -> str:
    return " ".join(
        value.casefold()
        .replace("_", " ")
        .replace(".", " ")
        .replace("-", " ")
        .split()
    )


def contains_latino_marker(title: str) -> bool:
    normalized = normalized_title(title)

    return any(
        normalized_title(marker) in normalized
        for marker in LATINO_MARKERS
    )


def custom_format_names(release: dict[str, Any]) -> list[str]:
    return [
        item.get("name", "")
        for item in release.get("customFormats", [])
        if item.get("name")
    ]


def has_latino_signal(release: dict[str, Any]) -> bool:
    if any(
        name.startswith("[Latino]")
        for name in custom_format_names(release)
    ):
        return True

    return contains_latino_marker(
        release.get("title", "")
    )


def is_qualifying_latino_release(
    release: dict[str, Any],
) -> bool:
    return (
        has_latino_signal(release)
        and int(release.get("customFormatScore") or 0) >= 7000
    )


def print_release(release: dict[str, Any]) -> None:
    languages = ", ".join(
        item.get("name", "")
        for item in release.get("languages", [])
        if item.get("name")
    ) or "Unknown"

    formats = ", ".join(
        custom_format_names(release)
    ) or "None"

    quality = (
        release.get("quality", {})
        .get("quality", {})
        .get("name", "Unknown")
    )

    print(
        f"Score:   {release.get('customFormatScore', 0)}"
    )
    print(f"Quality: {quality}")
    print(f"Indexer: {release.get('indexer', 'Unknown')}")
    print(f"Language: {languages}")
    print(f"Formats: {formats}")
    print(f"Title:   {release.get('title', '')}")
    print()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Radarr search results for Latino releases."
        ),
    )

    parser.add_argument(
        "--movie-id",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--stack-dir",
        type=Path,
        default=DEFAULT_STACK_DIR,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show all releases, not only Latino candidates.",
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    try:
        api_key = read_api_key(
            arguments.stack_dir / "config/radarr/config.xml"
        )
        client = RadarrClient(arguments.url, api_key)

        movie = client.get(
            f"/movie/{arguments.movie_id}"
        )

        query = urllib.parse.urlencode(
            {"movieId": arguments.movie_id}
        )
        releases = client.get(f"/release?{query}")

        ordered = sorted(
            releases,
            key=lambda item: int(
                item.get("customFormatScore") or 0
            ),
            reverse=True,
        )

        detected = [
            release
            for release in ordered
            if has_latino_signal(release)
        ]

        qualifying = [
            release
            for release in detected
            if is_qualifying_latino_release(release)
        ]

        rejected = [
            release
            for release in detected
            if not is_qualifying_latino_release(release)
        ]

        print(
            f"Movie: {movie.get('title')} "
            f"({movie.get('year')})"
        )
        print(f"Total releases: {len(ordered)}")
        print(f"Latino signals detected: {len(detected)}")
        print(f"Qualifying Latino releases: {len(qualifying)}")
        print(
            "Latino releases below score threshold: "
            f"{len(rejected)}"
        )
        print()

        selected = ordered if arguments.all else qualifying

        if not selected:
            print(
                "No Latino release meets the configured "
                "minimum custom-format score."
            )
            return 0

        for release in selected:
            print_release(release)

        return 0

    except AuditError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
