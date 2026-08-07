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


class AuditError(RuntimeError):
    pass


def read_api_key(config_file: Path) -> str:
    if not config_file.is_file():
        raise AuditError(
            f"Radarr configuration file not found: {config_file}"
        )

    root = ET.parse(config_file).getroot()
    api_key = root.findtext("ApiKey", "").strip()

    if not api_key:
        raise AuditError(
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
        }

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}/api/v3{path}",
            headers=self.headers,
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
                f"{error.code}: {body}"
            ) from error
        except urllib.error.URLError as error:
            raise AuditError(
                f"GET {path} failed: {error.reason}"
            ) from error


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
) -> tuple[bool, bool, int, int]:
    return (
        bool(release.get("approved", False)),
        not bool(release.get("rejected", False)),
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
            "Audit Radarr movies for currently available "
            "Latino upgrades."
        )
    )

    parser.add_argument(
        "--movie",
        help="Only audit one movie by title.",
    )

    parser.add_argument(
        "--movie-id",
        type=int,
        help="Only audit one movie by Radarr ID.",
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
        raise AuditError(
            "No matching monitored Radarr movies found."
        )

    rows: list[dict[str, Any]] = []

    for movie in selected:
        movie_id = int(movie["id"])
        title = movie.get("title", "")
        year = int(movie.get("year", 0) or 0)

        print(
            f"Searching {title} ({year})...",
            file=sys.stderr,
            flush=True,
        )

        query = urllib.parse.urlencode(
            {"movieId": movie_id}
        )

        releases = client.get(
            f"/release?{query}"
        )

        detected_latino_releases = [
            release
            for release in releases
            if has_latino_format(release)
        ]

        qualifying_latino_releases = [
            release
            for release in detected_latino_releases
            if int(
                release.get(
                    "customFormatScore",
                    0,
                )
                or 0
            ) >= 7000
        ]

        usable_latino_releases = [
            release
            for release in qualifying_latino_releases
            if (
                not bool(
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

        detected_latino_releases.sort(
            key=release_sort_key,
            reverse=True,
        )

        qualifying_latino_releases.sort(
            key=release_sort_key,
            reverse=True,
        )

        usable_latino_releases.sort(
            key=release_sort_key,
            reverse=True,
        )

        movie_file = (
            movie.get("movieFile")
            if movie.get("hasFile")
            else None
        )

        installed_score = 0
        installed_languages: list[str] = []
        installed_latino = False

        if movie_file:
            installed_score = int(
                movie_file.get(
                    "customFormatScore",
                    0,
                )
                or 0
            )

            installed_languages = [
                item.get("name", "")
                for item in movie_file.get(
                    "languages",
                    [],
                )
            ]

            installed_latino = (
                has_latino_format(
                    movie_file
                )
            )

        best = (
            usable_latino_releases[0]
            if usable_latino_releases
            else None
        )

        best_detected = (
            qualifying_latino_releases[0]
            if qualifying_latino_releases
            else None
        )

        rows.append(
            {
                "movie_id": movie_id,
                "movie": title,
                "year": year,
                "installed": (
                    "latino"
                    if installed_latino
                    else (
                        "fallback"
                        if movie_file
                        else "missing"
                    )
                ),
                "installed_score": installed_score,
                "installed_languages": (
                    installed_languages
                ),
                "latino_detected": bool(
                    detected_latino_releases
                ),
                "latino_detected_count": len(
                    detected_latino_releases
                ),
                "latino_qualifying_count": len(
                    qualifying_latino_releases
                ),
                "latino_available": bool(
                    usable_latino_releases
                ),
                "latino_count": len(
                    usable_latino_releases
                ),
                "best_detected_title": (
                    best_detected.get("title", "")
                    if best_detected
                    else ""
                ),
                "best_detected_score": (
                    int(
                        best_detected.get(
                            "customFormatScore",
                            0,
                        )
                        or 0
                    )
                    if best_detected
                    else 0
                ),
                "best_detected_rejections": (
                    best_detected.get(
                        "rejections",
                        [],
                    )
                    if best_detected
                    else []
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

    print()
    print(
        "Movie                           "
        "Installed  Score  "
        "Latino detected  Usable  Best score  Seeders"
    )
    print(
        "------------------------------  "
        "---------  -----  "
        "---------------  ------  ----------  -------"
    )

    for row in rows:
        label = (
            f"{row['movie']} ({row['year']})"
        )

        detected = (
            f"yes ({row['latino_detected_count']})"
            if row["latino_detected"]
            else "no"
        )

        usable = (
            f"yes ({row['latino_count']})"
            if row["latino_available"]
            else "no"
        )

        print(
            f"{label[:30]:<30}  "
            f"{row['installed']:<9}  "
            f"{row['installed_score']:<5}  "
            f"{detected:<15}  "
            f"{usable:<6}  "
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
            and row["best_score"]
            > row["installed_score"]
        )
    ]

    if not actionable:
        print(
            "No movies currently have an approved "
            "Latino upgrade."
        )
    else:
        for row in actionable:
            print()
            print(
                f"{row['movie']} "
                f"({row['year']})"
            )
            print(
                f"  movie ID: "
                f"{row['movie_id']}"
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
