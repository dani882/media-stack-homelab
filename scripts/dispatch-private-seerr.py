#!/usr/bin/env python3
"""Dispatch safe private movie releases for outstanding Seerr requests.

This is deliberately narrow: it handles only movies, only requests that are
not available, and only a single exact TMDB-matched private candidate which
passes the repository private-release policy.  It never removes public grabs.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

STACK = Path("/volume1/docker/media-stack")
ROOT = STACK
sys.path.insert(0, str(STACK / "scripts"))

from common.qbittorrent import QBittorrentClient, read_credentials

SPEC = importlib.util.spec_from_file_location("private_grab", STACK / "grab-prowlarr-release.py")
assert SPEC and SPEC.loader
GRAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAB)

# Lower priority is preferred once the language/quality policy has accepted a
# result. This intentionally does not override the policy itself.
PRIVATE_INDEXERS = {
    7: ("milnueve", 5760, 7),
    8: ("retrotoon", 4320, 8),
    9: ("torrenthaven", 4320, 9),
}


def api_key(path: Path) -> str:
    payload = json.loads(path.read_text())
    return str(payload["main"]["apiKey"])


def get_json(url: str, headers: dict[str, str]) -> Any:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
        return json.load(response)


def requests_to_dispatch(stack: Path) -> list[dict[str, Any]]:
    key = api_key(stack / "config/jellyseerr/settings.json")
    payload = get_json("http://127.0.0.1:5055/api/v1/request?take=100&skip=0", {"X-Api-Key": key})
    return [
        item for item in payload.get("results", [])
        if item.get("type") == "movie" and item.get("status") == 2
        and isinstance(item.get("media"), dict) and item["media"].get("tmdbId")
        and item["media"].get("status") != 5
    ]


def existing_request_tags(qbit: QBittorrentClient) -> set[str]:
    """Return dispatcher tags already attached to qBittorrent torrents."""
    torrents = qbit.get_json("/api/v2/torrents/info")
    return {
        tag.strip()
        for torrent in torrents
        for tag in str(torrent.get("tags", "")).split(",")
        if tag.strip().startswith("seerr-request-")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=STACK)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    stack = args.stack_dir
    policy_language, policy_resolution = GRAB.read_private_policy(stack / "private-release-policy.json")
    prowlarr_key = GRAB.read_api_key(stack / "config/prowlarr/config.xml")
    pending = requests_to_dispatch(stack)
    if not pending:
        print("PRIVATE DISPATCH OK: no eligible outstanding movie requests")
        return 0
    qbit: QBittorrentClient | None = None
    dispatched_tags: set[str] = set()
    if args.apply:
        username, password = read_credentials(stack / "secrets/qbittorrent.json")
        qbit = QBittorrentClient("http://127.0.0.1:8888", username, password)
        qbit.login()
        dispatched_tags = existing_request_tags(qbit)

    for request in pending:
        media = request["media"]
        tmdb_id = int(media["tmdbId"])
        title = str(media.get("title") or tmdb_id)
        request_tag = f"seerr-request-{request['id']}"
        if request_tag in dispatched_tags:
            print(f"ALREADY DISPATCHED: request={request['id']} tmdb={tmdb_id}")
            continue
        releases = []
        for indexer_id in PRIVATE_INDEXERS:
            releases.extend(GRAB.prowlarr_search("http://127.0.0.1:9696", prowlarr_key, title, indexer_id, "movie"))
        candidates = [r for r in releases if int(r.get("tmdbId", -1)) == tmdb_id and int(r.get("indexerId", -1)) in PRIVATE_INDEXERS and int(r.get("seeders", 0) or 0) >= 1 and GRAB.release_meets_private_policy(r, policy_language, policy_resolution)]
        if not candidates:
            print(f"NO PRIVATE CANDIDATE: request={request['id']} tmdb={tmdb_id}")
            continue
        candidates.sort(
            key=lambda r: (
                PRIVATE_INDEXERS[int(r["indexerId"])][2],
                -int(r.get("seeders", 0) or 0),
                str(r.get("title", "")),
            )
        )
        release = candidates[0]
        indexer_id = int(release["indexerId"])
        tracker, seed_minutes, _ = PRIVATE_INDEXERS[indexer_id]
        tags = f"private,{tracker},{request_tag}"
        print(f"{'DISPATCH' if args.apply else 'WOULD DISPATCH'} request={request['id']} tmdb={tmdb_id} indexer={indexer_id} title={release['title']}")
        if args.apply:
            assert qbit is not None
            GRAB.add_to_qbittorrent(qbit, release, "radarr", tags, seed_minutes, False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
