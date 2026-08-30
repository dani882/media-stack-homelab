#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path
from typing import Any


DEFAULT_RADARR_URL = "http://127.0.0.1:7878"
DEFAULT_CONFIG_FILE = (
    "/volume1/docker/media-stack/config/radarr/config.xml"
)

from common.arr import (
    ArrClient as RadarrClient,
    ArrError as UpgradeError,
    read_api_key,
)
from common.language import (
    best_language_upgrade,
    language_name,
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

        if movie_file:
            installed_score = int(
                movie_file.get(
                    "customFormatScore",
                    0,
                )
                or 0
            )

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

        best = best_language_upgrade(
            movie_file,
            releases,
        )

        if best is None:
            continue

        best_score = int(
            best.get(
                "customFormatScore",
                0,
            )
            or 0
        )

        installed_language = language_name(
            movie_file
        )
        candidate_language = language_name(
            best
        )

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
            f"  language: {installed_language} -> "
            f"{candidate_language}"
        )
        print(
            f"  current score: {installed_score}"
        )
        print(
            f"  candidate score: {best_score}"
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

        client.request(
            "POST",
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
        f"Actionable language upgrades: "
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
