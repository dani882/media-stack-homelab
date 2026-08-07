#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_RADARR_URL = "http://127.0.0.1:7878"
DEFAULT_CONFIG_FILE = (
    "/volume1/docker/media-stack/config/radarr/config.xml"
)

LATINO_FORMAT_PREFIXES = (
    "[Latino] Spanish Latino",
    "[Latino] Spanish Latino + English",
)


class UpgradeError(RuntimeError):
    pass


def read_api_key(config_file: Path) -> str:
    if not config_file.is_file():
        raise UpgradeError(
            f"Radarr configuration file not found: {config_file}"
        )

    root = ET.parse(config_file).getroot()
    api_key = root.findtext("ApiKey", "").strip()

    if not api_key:
        raise UpgradeError(
            f"ApiKey was not found in {config_file}"
        )

    return api_key


class RadarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
    ) -> None:
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

        except urllib.error.HTTPError as error:
            response_body = error.read().decode(
                "utf-8",
                errors="replace",
            )

            raise UpgradeError(
                f"{method} {path} failed with HTTP "
                f"{error.code}: {response_body}"
            ) from error

        except urllib.error.URLError as error:
            raise UpgradeError(
                f"{method} {path} failed: {error.reason}"
            ) from error

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(
        self,
        path: str,
        payload: Any | None = None,
    ) -> Any:
        return self.request(
            "POST",
            path,
            payload,
        )


def custom_format_names(
    payload: dict[str, Any],
) -> list[str]:
    return [
        item.get("name", "")
        for item in payload.get(
            "customFormats",
            [],
        )
    ]


def has_latino_format(
    payload: dict[str, Any],
) -> bool:
    names = custom_format_names(payload)

    return any(
        any(
            name.startswith(prefix)
            for prefix in LATINO_FORMAT_PREFIXES
        )
        for name in names
    )


def release_sort_key(
    release: dict[str, Any],
) -> tuple[int, int]:
    return (
        int(
            release.get(
                "customFormatScore",
                0,
            )
            or 0
        ),
        int(
            release.get(
                "seeders",
                0,
            )
            or 0
        ),
    )


def movie_matches(
    movie: dict[str, Any],
    title: str,
) -> bool:
    return (
        (movie.get("title") or "").casefold()
        == title.casefold()
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Upgrade monitored Radarr movies to approved "
            "Latino releases."
        )
    )

    parser.add_argument(
        "--movie",
        help="Only process one movie by exact title.",
    )

    parser.add_argument(
        "--movie-id",
        type=int,
        help="Only process one Radarr movie ID.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended grabs without downloading.",
    )

    parser.add_argument(
        "--radarr-url",
        default=DEFAULT_RADARR_URL,
    )

    parser.add_argument(
        "--config-file",
        default=DEFAULT_CONFIG_FILE,
    )

    args = parser.parse_args()

    api_key = read_api_key(
        Path(args.config_file)
    )

    client = RadarrClient(
        args.radarr_url,
        api_key,
    )

    movies = client.get("/movie")

    selected: list[dict[str, Any]] = []

    for movie in movies:
        if not movie.get("monitored", False):
            continue

        if (
            args.movie_id is not None
            and int(movie["id"]) != args.movie_id
        ):
            continue

        if (
            args.movie is not None
            and not movie_matches(
                movie,
                args.movie,
            )
        ):
            continue

        selected.append(movie)

    if not selected:
        raise UpgradeError(
            "No matching monitored Radarr movies found."
        )

    actionable = 0
    grabbed = 0

    for movie in selected:
        movie_id = int(movie["id"])
        title = movie.get("title", "")
        year = int(movie.get("year", 0) or 0)

        movie_file = (
            movie.get("movieFile")
            if movie.get("hasFile")
            else None
        )

        installed_score = 0
        installed_latino = False

        if movie_file:
            installed_score = int(
                movie_file.get(
                    "customFormatScore",
                    0,
                )
                or 0
            )

            installed_latino = (
                has_latino_format(movie_file)
            )

        if installed_latino:
            continue

        print(
            f"Checking {title} ({year})...",
            file=sys.stderr,
            flush=True,
        )

        query = urllib.parse.urlencode(
            {"movieId": movie_id}
        )

        releases = client.get(
            f"/release?{query}"
        )

        usable = [
            release
            for release in releases
            if (
                has_latino_format(release)
                and int(
                    release.get(
                        "customFormatScore",
                        0,
                    )
                    or 0
                ) >= 7000
                and not bool(
                    release.get(
                        "rejected",
                        False,
                    )
                )
                and bool(
                    release.get(
                        "downloadAllowed",
                        True,
                    )
                )
            )
        ]

        usable.sort(
            key=release_sort_key,
            reverse=True,
        )

        if not usable:
            continue

        best = usable[0]

        best_score = int(
            best.get(
                "customFormatScore",
                0,
            )
            or 0
        )

        if best_score <= installed_score:
            continue

        actionable += 1

        print()
        print(
            f"{'WOULD GRAB' if args.dry_run else 'GRABBING'}: "
            f"{title} ({year})"
        )
        print(
            f"  movie ID: {movie_id}"
        )
        print(
            f"  current score: {installed_score}"
        )
        print(
            f"  Latino score: {best_score}"
        )
        print(
            f"  seeders: "
            f"{int(best.get('seeders', 0) or 0)}"
        )
        print(
            f"  quality: "
            f"{best.get('quality', {}).get('quality', {}).get('name', '')}"
        )
        print(
            f"  release: {best.get('title', '')}"
        )

        if args.dry_run:
            continue

        guid = best.get("guid")
        indexer_id = best.get("indexerId")

        if not guid or indexer_id is None:
            raise UpgradeError(
                f"Release for {title} is missing "
                "guid or indexerId."
            )

        client.post(
            "/release",
            {
                "guid": guid,
                "indexerId": indexer_id,
            },
        )

        grabbed += 1

    print()
    print("=== Summary ===")
    print(
        f"Movies processed: {len(selected)}"
    )
    print(
        f"Actionable Latino upgrades: "
        f"{actionable}"
    )

    if args.dry_run:
        print(
            "Dry run: no releases were grabbed."
        )
    else:
        print(
            f"Releases grabbed: {grabbed}"
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
