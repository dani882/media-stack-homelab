#!/usr/bin/env python3


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
    release_is_private,
)
from common.btarg import BTArgCache, BTArgClient, enrich_releases


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")


def queued_movie_ids(client: RadarrClient) -> set[int]:
    query = urllib.parse.urlencode(
        {
            "page": 1,
            "pageSize": 1000,
            "includeUnknownMovieItems": "true",
        }
    )
    queue = client.get(f"/queue?{query}")
    return {
        int(record["movieId"])
        for record in queue.get("records", [])
        if record.get("movieId") is not None
    }


def is_qbittorrent_duplicate(error: UpgradeError) -> bool:
    message = str(error)
    return (
        "qBittorrent" in message
        and "409:Conflict" in message
        and "/api/v2/torrents/add" in message
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
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)

    args = parser.parse_args()

    api_key = read_api_key(
        Path(args.config_file)
    )

    client = RadarrClient(
        args.radarr_url,
        api_key,
    )
    btarg = BTArgClient(
        args.stack_dir / "secrets/prowlarr-private-indexers.json",
        BTArgCache(args.stack_dir / "state/btarg-language-cache.json"),
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
    already_queued = 0
    queued_ids = queued_movie_ids(client)

    for movie in selected:
        movie_id = int(movie["id"])
        title = movie.get("title", "")
        year = int(movie.get("year", 0) or 0)

        if movie_id in queued_ids:
            already_queued += 1
            print(
                f"ALREADY QUEUED: {title} ({year})",
                file=sys.stderr,
                flush=True,
            )
            continue

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

        try:
            releases = client.get(
                f"/release?{query}"
            )
        except UpgradeError as error:
            print(
                f"SKIPPED: {title} ({year}): {error}",
                file=sys.stderr,
                flush=True,
            )
            continue

        releases = enrich_releases(
            releases,
            btarg,
            str(movie.get("imdbId") or "") or None,
        )

        best = best_language_upgrade(
            movie_file,
            [
                release
                for release in releases
                if release_is_private(release)
            ],
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
        print(
            f"  tracker: {best.get('indexer', '')}"
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

        try:
            client.request(
                "POST",
                "/release",
                {
                    "guid": guid,
                    "indexerId": indexer_id,
                },
            )
        except UpgradeError as error:
            # Radarr can report qBittorrent's duplicate-torrent
            # response as a generic HTTP 500. Confirm the movie is
            # queued, or require the exact qBittorrent conflict, before
            # treating that response as safe.
            queued_ids = queued_movie_ids(client)
            if (
                movie_id not in queued_ids
                and not is_qbittorrent_duplicate(error)
            ):
                raise
            already_queued += 1
            print(
                f"ALREADY QUEUED: {title} ({year})",
                file=sys.stderr,
                flush=True,
            )
            continue

        grabbed += 1
        queued_ids.add(movie_id)

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
        print(
            f"Movies already queued: {already_queued}"
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
