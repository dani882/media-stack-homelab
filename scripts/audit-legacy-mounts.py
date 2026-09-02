#!/usr/bin/env python3

"""Audit the remaining consumers of the legacy /downloads and /media mounts.

This command is intentionally read-only.  It does not recommend removing a
compatibility mount while qBittorrent still has a torrent using an old path,
or while a Servarr root folder has not moved to /data.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEPLOYED_SCRIPT_DIR = DEFAULT_STACK_DIR / "scripts"
if str(DEPLOYED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYED_SCRIPT_DIR))

from common.arr import ArrClient, ArrError, read_api_key
from common.qbittorrent import (
    QBittorrentClient,
    QBittorrentError,
    read_credentials,
)


LEGACY_PATHS = ("/downloads", "/media")
ARR_SOURCES = (
    ("Sonarr", "http://127.0.0.1:8989"),
    ("Radarr", "http://127.0.0.1:7878"),
)


class LegacyMountAuditError(RuntimeError):
    pass


def mounted_paths(container: str) -> list[str]:
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{range .Mounts}}{{println .Source \" -> \" .Destination}}{{end}}",
            container,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    mounts = [line.strip() for line in result.stdout.splitlines()]
    return [
        mount
        for mount in mounts
        if " -> " in mount
        and any(
            mount.rsplit(" -> ", 1)[1].strip() == path
            for path in LEGACY_PATHS
        )
    ]


def audit_containers() -> list[str]:
    blockers: list[str] = []
    print("Legacy compatibility mounts:")
    for container in ("qbittorrent", "sonarr", "radarr", "bazarr", "jellyfin"):
        try:
            paths = mounted_paths(container)
        except subprocess.CalledProcessError as error:
            raise LegacyMountAuditError(
                f"Unable to inspect {container} mounts."
            ) from error

        if paths:
            print(f"  {container}: " + "; ".join(paths))
            blockers.append(container)
        else:
            print(f"  {container}: no legacy mount")
    return blockers


def audit_arr_roots(stack_dir: Path) -> list[str]:
    blockers: list[str] = []
    print("\nServarr root folders:")
    for name, url in ARR_SOURCES:
        service = name.lower()
        config_file = stack_dir / "config" / service / "config.xml"
        try:
            client = ArrClient(url, read_api_key(config_file))
            roots = client.get("/rootfolder")
        except (ArrError, OSError, element_tree.ParseError) as error:
            raise LegacyMountAuditError(
                f"Unable to read {name} root folders: {error}"
            ) from error

        paths = [str(root.get("path", "")) for root in roots]
        legacy = [
            path for path in paths
            if any(path == prefix or path.startswith(prefix + "/") for prefix in LEGACY_PATHS)
        ]
        print(f"  {name}: " + ", ".join(paths))
        if legacy:
            blockers.append(name)
    return blockers


def audit_old_path_torrents(stack_dir: Path) -> list[str]:
    print("\nqBittorrent torrents still using /downloads:")
    try:
        username, password = read_credentials(
            stack_dir / "secrets/qbittorrent.json"
        )
        client = QBittorrentClient("http://127.0.0.1:8888", username, password)
        client.login()
        torrents: list[dict[str, Any]] = client.get_json("/api/v2/torrents/info")
    except QBittorrentError as error:
        raise LegacyMountAuditError(str(error)) from error

    old_path = [
        torrent for torrent in torrents
        if str(torrent.get("save_path", "")).startswith("/downloads")
    ]
    if not old_path:
        print("  none")
        return []

    for torrent in old_path:
        progress = float(torrent.get("progress", 0) or 0) * 100
        print(
            "  "
            f"hash={str(torrent.get('hash', ''))[:12].upper()} "
            f"private={bool(torrent.get('private'))} "
            f"progress={progress:.1f}% "
            f"state={torrent.get('state', '')} "
            f"name={torrent.get('name', '')}"
        )
    return [str(torrent.get("hash", "")) for torrent in old_path]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    args = parser.parse_args()

    mount_blockers = audit_containers()
    root_blockers = audit_arr_roots(args.stack_dir)
    torrent_blockers = audit_old_path_torrents(args.stack_dir)

    print("\n=== Result ===")
    if root_blockers:
        print(
            "NOT READY: Servarr still has legacy root folder(s): "
            + ", ".join(root_blockers)
        )
        return 1
    if torrent_blockers:
        print(
            "NOT READY: qBittorrent has old-path torrent(s); keep "
            "/downloads until they are individually resolved."
        )
        return 1
    if mount_blockers:
        print(
            "READY FOR A SEPARATE REMOVAL PLAN: no configured Servarr "
            "roots or qBittorrent torrents require old paths, but containers "
            "still expose compatibility mounts. Do not remove them automatically."
        )
        return 0

    print("NO LEGACY MOUNTS DETECTED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LegacyMountAuditError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
