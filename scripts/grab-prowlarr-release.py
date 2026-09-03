#!/usr/bin/env python3

"""Grab one explicitly selected Prowlarr torrent without exposing secrets.

Use this only for a known release that Prowlarr can find by title but which an
*arr application cannot discover through an ID-based search.  The script does
not replace normal Sonarr/Radarr selection; it adds a guarded escape hatch for
private indexers with incomplete Torznab metadata.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEPLOYED_SCRIPT_DIR = DEFAULT_STACK_DIR / "scripts"
LOCAL_MEDIA_SCRIPT_DIR = Path(__file__).resolve().parent / "media"
for script_dir in (LOCAL_MEDIA_SCRIPT_DIR, DEPLOYED_SCRIPT_DIR):
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

from common.qbittorrent import QBittorrentClient, QBittorrentError, read_credentials


class GrabError(RuntimeError):
    pass


def read_api_key(config_file: Path) -> str:
    try:
        key = ET.parse(config_file).getroot().findtext("ApiKey", "").strip()
    except (ET.ParseError, OSError) as error:
        raise GrabError(f"Unable to read {config_file}: {error}") from error

    if not key:
        raise GrabError(f"No API key found in {config_file}")

    return key


def prowlarr_search(
    base_url: str,
    api_key: str,
    query: str,
    indexer_id: int,
    media_type: str,
) -> list[dict[str, Any]]:
    parameters = urllib.parse.urlencode(
        {
            "query": query,
            "indexerIds": indexer_id,
            "type": "tvsearch" if media_type == "tv" else "movie",
        }
    )
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/search?{parameters}",
        headers={"X-Api-Key": api_key},
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read())
    except (OSError, json.JSONDecodeError) as error:
        raise GrabError(f"Prowlarr search failed: {error}") from error

    if not isinstance(payload, list):
        raise GrabError("Prowlarr search returned an unexpected payload.")

    return [item for item in payload if isinstance(item, dict)]


def select_release(
    releases: list[dict[str, Any]],
    expected_title: str,
    indexer_id: int,
    expected_media_id: int | None,
    media_type: str,
    minimum_seeders: int,
) -> dict[str, Any]:
    title = expected_title.casefold()
    candidates = [
        item
        for item in releases
        if str(item.get("title", "")).casefold() == title
        and int(item.get("indexerId", -1)) == indexer_id
    ]

    if len(candidates) != 1:
        raise GrabError(
            "Expected exactly one exact-title result from the requested "
            f"indexer; found {len(candidates)}."
        )

    release = candidates[0]
    if release.get("protocol") != "torrent":
        raise GrabError("Selected release is not a torrent.")

    media_id_field = "tvdbId" if media_type == "tv" else "tmdbId"
    if expected_media_id is not None and int(
        release.get(media_id_field, -1)
    ) != expected_media_id:
        raise GrabError(
            f"Selected release has an unexpected {media_id_field}."
        )

    if int(release.get("seeders", 0) or 0) < minimum_seeders:
        raise GrabError("Selected release has too few seeders.")

    if not release.get("downloadUrl"):
        raise GrabError("Selected release does not provide a download URL.")

    return release


def download_url_for_qbittorrent(
    download_url: str,
) -> str:
    """Translate Prowlarr's local-loopback URL for the Docker network."""
    parsed = urllib.parse.urlsplit(download_url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return download_url

    port = f":{parsed.port}" if parsed.port else ""
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            f"prowlarr{port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def add_to_qbittorrent(
    client: QBittorrentClient,
    release: dict[str, Any],
    category: str,
    tags: str,
    seed_time_minutes: int,
    dry_run: bool,
) -> None:
    title = str(release["title"])
    seeders = int(release.get("seeders", 0) or 0)
    size = int(release.get("size", 0) or 0)

    print(
        f"SELECTED: {title} indexer={release['indexerId']} "
        f"seeders={seeders} size={size} category={category}"
    )
    print(
        f"PRIVATE POLICY: seed-time={seed_time_minutes}m tags={tags}"
    )

    if dry_run:
        print("DRY RUN: would add the selected torrent to qBittorrent")
        return

    tag_set = {
        tag.strip()
        for tag in tags.split(",")
        if tag.strip()
    }
    if not tag_set:
        raise GrabError("At least one non-empty tag is required.")

    existing = [
        item
        for item in client.get_json("/api/v2/torrents/info")
        if tag_set.issubset(
            {
                tag.strip()
                for tag in str(item.get("tags", "")).split(",")
                if tag.strip()
            }
        )
    ]
    if existing:
        raise GrabError(
            "A torrent already has all requested tags; refusing a duplicate "
            "grab."
        )

    client.post_form(
        "/api/v2/torrents/add",
        {
            "urls": download_url_for_qbittorrent(
                str(release["downloadUrl"])
            ),
            "category": category,
            "tags": tags,
        },
    )

    for _ in range(15):
        torrents = client.get_json("/api/v2/torrents/info")
        matches = [
            item
            for item in torrents
            if tag_set.issubset(
                {
                    tag.strip()
                    for tag in str(item.get("tags", "")).split(",")
                    if tag.strip()
                }
            )
        ]
        if len(matches) == 1:
            torrent = matches[0]
            client.post_form(
                "/api/v2/torrents/setShareLimits",
                {
                    "hashes": torrent["hash"],
                    "ratioLimit": -2,
                    "seedingTimeLimit": seed_time_minutes,
                    "inactiveSeedingTimeLimit": -2,
                    "shareLimitAction": "Default",
                },
            )
            print(
                "ADDED: "
                f"hash={str(torrent['hash'])[:12].upper()} "
                f"path={torrent.get('save_path')}"
            )
            return

        if len(matches) > 1:
            raise GrabError(
                "More than one torrent has the requested tags; refusing to "
                "choose a torrent for the private-tracker policy."
            )

        time.sleep(2)

    raise GrabError(
        "qBittorrent did not report the selected torrent after adding it."
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grab one exact Prowlarr torrent through qBittorrent."
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--indexer-id", required=True, type=int)
    parser.add_argument("--media-type", choices=("tv", "movie"), default="tv")
    parser.add_argument("--tvdb-id", type=int)
    parser.add_argument("--tmdb-id", type=int)
    parser.add_argument("--minimum-seeders", type=int, default=1)
    parser.add_argument("--seed-time-minutes", required=True, type=int)
    parser.add_argument("--category", default="tv")
    parser.add_argument("--tags", required=True)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--prowlarr-url", default="http://127.0.0.1:9696")
    parser.add_argument("--qbittorrent-url", default="http://127.0.0.1:8888")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.seed_time_minutes <= 0:
        raise GrabError("--seed-time-minutes must be positive.")
    if arguments.minimum_seeders < 1:
        raise GrabError("--minimum-seeders must be at least one.")
    expected_media_id = (
        arguments.tvdb_id
        if arguments.media_type == "tv"
        else arguments.tmdb_id
    )
    if expected_media_id is None:
        required = "--tvdb-id" if arguments.media_type == "tv" else "--tmdb-id"
        raise GrabError(f"{required} is required for {arguments.media_type} releases.")

    prowlarr_key = read_api_key(
        arguments.stack_dir / "config/prowlarr/config.xml"
    )
    username, password = read_credentials(
        arguments.stack_dir / "secrets/qbittorrent.json"
    )
    client = QBittorrentClient(
        arguments.qbittorrent_url,
        username,
        password,
    )
    client.login()

    releases = prowlarr_search(
        arguments.prowlarr_url,
        prowlarr_key,
        arguments.query,
        arguments.indexer_id,
        arguments.media_type,
    )
    release = select_release(
        releases,
        arguments.title,
        arguments.indexer_id,
        expected_media_id,
        arguments.media_type,
        arguments.minimum_seeders,
    )
    add_to_qbittorrent(
        client,
        release,
        arguments.category,
        arguments.tags,
        arguments.seed_time_minutes,
        arguments.dry_run,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GrabError, QBittorrentError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
