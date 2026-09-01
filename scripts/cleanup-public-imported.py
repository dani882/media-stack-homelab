#!/usr/bin/env python3

"""Remove public torrents after a confirmed Servarr import and 30m seed."""

from __future__ import annotations

import argparse
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEPLOYED_SCRIPT_DIR = DEFAULT_STACK_DIR / "scripts"
LOCAL_MEDIA_SCRIPT_DIR = Path(__file__).resolve().parent / "media"
for script_dir in (LOCAL_MEDIA_SCRIPT_DIR, DEPLOYED_SCRIPT_DIR):
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

from common.arr import ArrClient, ArrError, read_api_key
from common.qbittorrent import (
    QBittorrentClient,
    QBittorrentError,
    read_credentials,
)


MINIMUM_SEEDING_MINUTES = 30.0
MAX_DELETE_DEFAULT = 10
SAFE_TORRENT_STATES = {
    "stoppedUP",
    "stalledUP",
    "queuedUP",
    "pausedUP",
    "uploading",
}


class PublicCleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArrSource:
    name: str
    base_url: str
    config_file: Path


def history_import_hashes(client: ArrClient) -> set[str]:
    history = client.get(
        "/history?"
        + urllib.parse.urlencode(
            {
                "page": 1,
                "pageSize": 1000,
                "sortDirection": "descending",
            }
        )
    )
    records = history if isinstance(history, list) else history.get("records", [])

    return {
        str(record.get("downloadId", "")).upper()
        for record in records
        if record.get("eventType") == "downloadFolderImported"
        and record.get("downloadId")
    }


def public_torrent_is_removable(torrent: dict[str, Any]) -> tuple[bool, str]:
    if torrent.get("private") is not False:
        return False, "torrent is not explicitly public"
    if float(torrent.get("progress", 0) or 0) < 1:
        return False, "torrent is not complete"
    if int(torrent.get("amount_left", 0) or 0) != 0:
        return False, "torrent has data remaining"
    if bool(torrent.get("force_start", False)):
        return False, "Force Start is enabled"
    if str(torrent.get("state", "")) not in SAFE_TORRENT_STATES:
        return False, f"state {torrent.get('state')!r} is not eligible"

    seeded_minutes = int(torrent.get("seeding_time", 0) or 0) / 60
    if seeded_minutes < MINIMUM_SEEDING_MINUTES:
        return False, (
            f"seeded only {seeded_minutes:.1f} minutes; requires "
            f"{MINIMUM_SEEDING_MINUTES:.1f} minutes"
        )

    return True, "safe"


def run_cleanup(
    stack_dir: Path,
    dry_run: bool,
    max_delete: int,
) -> int:
    sources = (
        ArrSource("Sonarr", "http://127.0.0.1:8989", stack_dir / "config/sonarr/config.xml"),
        ArrSource("Radarr", "http://127.0.0.1:7878", stack_dir / "config/radarr/config.xml"),
    )

    try:
        imported_hashes: set[str] = set()
        for source in sources:
            imported_hashes.update(
                history_import_hashes(
                    ArrClient(source.base_url, read_api_key(source.config_file))
                )
            )

        username, password = read_credentials(stack_dir / "secrets/qbittorrent.json")
        qbittorrent = QBittorrentClient("http://127.0.0.1:8888", username, password)
        qbittorrent.login()
        torrents = qbittorrent.get_json("/api/v2/torrents/info")
    except (ArrError, QBittorrentError) as error:
        raise PublicCleanupError(str(error)) from error

    candidates: list[dict[str, Any]] = []
    skipped = 0
    for torrent in torrents:
        torrent_hash = str(torrent.get("hash", "")).upper()
        if torrent_hash not in imported_hashes:
            continue

        safe, reason = public_torrent_is_removable(torrent)
        if not safe:
            print(f"SKIP: {torrent.get('name', '')}\n  reason: {reason}")
            skipped += 1
            continue
        candidates.append(torrent)

    if not dry_run and len(candidates) > max_delete:
        raise PublicCleanupError(
            f"Refusing to remove {len(candidates)} torrents in one run; "
            f"increase --max-delete above {max_delete} after reviewing a dry run."
        )

    for torrent in candidates:
        seeded_minutes = int(torrent.get("seeding_time", 0) or 0) / 60
        prefix = "WOULD REMOVE" if dry_run else "REMOVING"
        print(
            f"{prefix}: {torrent.get('name', '')}\n"
            f"  hash: {str(torrent.get('hash', ''))[:12].upper()}\n"
            f"  seeded: {seeded_minutes:.1f} minutes"
        )
        if not dry_run:
            qbittorrent.post_form(
                "/api/v2/torrents/delete",
                {
                    "hashes": str(torrent.get("hash", "")),
                    "deleteFiles": "true",
                },
            )

    print("\n=== Summary ===")
    print(f"Confirmed public import candidates: {len(candidates)}")
    print(f"Skipped imported torrents: {skipped}")
    print("Dry run: nothing was deleted." if dry_run else f"Public torrents removed: {len(candidates)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Remove only explicitly public qBittorrent torrents that have a "
            "confirmed Sonarr/Radarr import and at least 30 minutes of seed time."
        )
    )
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-delete", type=int, default=MAX_DELETE_DEFAULT)
    args = parser.parse_args()
    return run_cleanup(args.stack_dir, args.dry_run, args.max_delete)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicCleanupError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
