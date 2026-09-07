#!/usr/bin/env python3
"""Dispatch rare Spanish movie releases only for the Archivo Español profile.

This intentionally bypasses neither identity nor language validation: an
archive candidate must be an exact Prowlarr TMDB match, have at least one
seeder, claim 480p or higher, and be Latino or Castilian.  It never uses an
English fallback and does not alter Prowlarr's global five-seeder setting.
"""

import argparse
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


STACK = Path("/volume1/docker/media-stack")
sys.path.insert(0, str(STACK / "scripts"))

from common.language import LanguageRank, language_rank
from common.qbittorrent import QBittorrentClient, read_credentials

SPEC = importlib.util.spec_from_file_location(
    "archive_grab", STACK / "grab-prowlarr-release.py"
)
assert SPEC and SPEC.loader
GRAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAB)


ARCHIVE_PROFILE_NAME = "Archivo Español"
PRIVATE_INDEXER_NAMES = {"milnueve", "retrotoon", "torrenthaven"}
# EZTV is TV-only and rejects movie-search queries with HTTP 400.
MOVIE_INDEXER_EXCLUSIONS = {"eztv"}


def radarr_json(stack: Path, endpoint: str) -> Any:
    key = GRAB.read_api_key(stack / "config/radarr/config.xml")
    request = urllib.request.Request(
        f"http://127.0.0.1:7878/api/v3/{endpoint.lstrip('/')}",
        headers={"X-Api-Key": key},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def radarr_movies(stack: Path) -> list[dict[str, Any]]:
    payload = radarr_json(stack, "movie")
    return [item for item in payload if isinstance(item, dict)]


def archive_profile_id(stack: Path) -> int:
    profiles = radarr_json(stack, "qualityprofile")
    profile = next(
        (item for item in profiles if item.get("name") == ARCHIVE_PROFILE_NAME),
        None,
    )
    if profile is None:
        raise RuntimeError(f"Missing Radarr profile: {ARCHIVE_PROFILE_NAME}")
    return int(profile["id"])


def public_movie_indexers(stack: Path) -> list[int]:
    """Discover enabled public movie indexers; never rely on mutable IDs."""
    key = GRAB.read_api_key(stack / "config/prowlarr/config.xml")
    request = urllib.request.Request(
        "http://127.0.0.1:9696/api/v1/indexer", headers={"X-Api-Key": key}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    return [
        int(item["id"])
        for item in payload
        if item.get("enable")
        and not any(marker in str(item.get("name", "")).casefold() for marker in PRIVATE_INDEXER_NAMES)
        and str(item.get("name", "")).casefold() not in MOVIE_INDEXER_EXCLUSIONS
    ]


def existing_tags(qbit: QBittorrentClient) -> set[str]:
    return {
        tag.strip()
        for torrent in qbit.get_json("/api/v2/torrents/info")
        for tag in str(torrent.get("tags", "")).split(",")
        if tag.strip().startswith("archive-spanish-movie-")
    }


def is_candidate(release: dict[str, Any], tmdb_id: int) -> bool:
    return (
        release.get("protocol") == "torrent"
        and int(release.get("tmdbId", -1) or -1) == tmdb_id
        and int(release.get("seeders", 0) or 0) >= 1
        and language_rank(release) >= LanguageRank.CASTILIAN
        and GRAB.title_resolution(release) >= 480
        and bool(release.get("downloadUrl"))
    )


def add_release(
    qbit: QBittorrentClient,
    release: dict[str, Any],
    tag: str,
) -> None:
    qbit.post_form(
        "/api/v2/torrents/add",
        {
            "urls": GRAB.download_url_for_qbittorrent(str(release["downloadUrl"])),
            "category": "radarr",
            "tags": f"archive-spanish,{tag}",
        },
    )
    print(
        "ARCHIVE DISPATCHED: "
        f"tmdb={release['tmdbId']} indexer={release['indexerId']} "
        f"title={release['title']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=STACK)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    stack = args.stack_dir
    prowlarr_key = GRAB.read_api_key(stack / "config/prowlarr/config.xml")
    profile_id = archive_profile_id(stack)
    indexer_ids = public_movie_indexers(stack)
    movies = [
        movie
        for movie in radarr_movies(stack)
        if movie.get("monitored")
        and not movie.get("hasFile")
        and int(movie.get("qualityProfileId", -1)) == profile_id
        and movie.get("tmdbId")
    ]
    if not movies:
        print("ARCHIVE DISPATCH OK: no missing movies use Archivo Español")
        return 0

    qbit: QBittorrentClient | None = None
    dispatched: set[str] = set()
    if not args.dry_run:
        username, password = read_credentials(stack / "secrets/qbittorrent.json")
        qbit = QBittorrentClient("http://127.0.0.1:8888", username, password)
        qbit.login()
        dispatched = existing_tags(qbit)

    for movie in movies:
        tmdb_id = int(movie["tmdbId"])
        tag = f"archive-spanish-movie-{movie['id']}"
        if tag in dispatched:
            print(f"ARCHIVE ALREADY DISPATCHED: movie={movie['id']} tmdb={tmdb_id}")
            continue
        releases: list[dict[str, Any]] = []
        for indexer_id in indexer_ids:
            try:
                releases.extend(
                    GRAB.prowlarr_search(
                        "http://127.0.0.1:9696", prowlarr_key,
                        str(movie.get("title") or tmdb_id), indexer_id, "movie"
                    )
                )
            except Exception as error:
                # One broken public indexer must not prevent a safe result
                # from another. Its failure never relaxes the candidate gate.
                print(f"SKIP INDEXER: id={indexer_id} reason={error}")
        candidates = [r for r in releases if is_candidate(r, tmdb_id)]
        if not candidates:
            print(f"NO SAFE ARCHIVE CANDIDATE: movie={movie['id']} tmdb={tmdb_id}")
            continue
        candidates.sort(
            key=lambda r: (
                -int(language_rank(r)),
                -GRAB.title_resolution(r),
                -int(r.get("seeders", 0) or 0),
                str(r.get("title", "")),
            )
        )
        chosen = candidates[0]
        if args.dry_run:
            print(
                "WOULD ARCHIVE DISPATCH: "
                f"movie={movie['id']} tmdb={tmdb_id} "
                f"title={chosen['title']}"
            )
            continue
        assert qbit is not None
        add_release(qbit, chosen, tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
