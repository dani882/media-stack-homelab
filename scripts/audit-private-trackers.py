#!/usr/bin/env python3

"""Audit private-tracker seeding obligations without exposing announce URLs."""

from __future__ import annotations

import argparse
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")

# The Make target streams this script to a temporary NAS path. Make the
# deployed shared modules importable in that mode as well as when installed.
DEPLOYED_SCRIPT_DIR = DEFAULT_STACK_DIR / "scripts"
if str(DEPLOYED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYED_SCRIPT_DIR))

from common.qbittorrent import (
    QBittorrentClient,
    QBittorrentError,
    read_credentials,
)


@dataclass(frozen=True)
class TrackerPolicy:
    name: str
    host_suffixes: tuple[str, ...]
    minimum_seed_minutes: int


TRACKER_POLICIES = (
    TrackerPolicy(
        name="Milnueve",
        host_suffixes=("milnueve.cc",),
        minimum_seed_minutes=5760,
    ),
    TrackerPolicy(
        name="RetroToon World",
        host_suffixes=("retrotoon.world",),
        minimum_seed_minutes=4320,
    ),
)


class PrivateTrackerAuditError(RuntimeError):
    pass


def tracker_host(url: str) -> str | None:
    host = urllib.parse.urlparse(url).hostname
    return host.casefold() if host else None


def matching_policy(
    hosts: set[str],
) -> TrackerPolicy | None:
    for policy in TRACKER_POLICIES:
        for host in hosts:
            if any(
                host == suffix or host.endswith(f".{suffix}")
                for suffix in policy.host_suffixes
            ):
                return policy

    return None


def torrent_hosts(
    client: QBittorrentClient,
    torrent_hash: str,
) -> set[str]:
    trackers = client.get_json(
        "/api/v2/torrents/trackers?"
        + urllib.parse.urlencode({"hash": torrent_hash})
    )

    return {
        host
        for tracker in trackers
        for host in [tracker_host(str(tracker.get("url", "")))]
        if host
    }


def audit_torrent(
    torrent: dict[str, Any],
    hosts: set[str],
) -> tuple[bool, str]:
    torrent_hash = str(torrent.get("hash", ""))[:12].upper()
    policy = matching_policy(hosts)

    if policy is None:
        display_hosts = ", ".join(sorted(hosts)) or "no host reported"
        return False, (
            f"UNRECOGNIZED PRIVATE TRACKER hash={torrent_hash} "
            f"hosts={display_hosts}"
        )

    limit = int(torrent.get("seeding_time_limit", -1) or -1)
    seeded_minutes = int(torrent.get("seeding_time", 0) or 0) / 60
    complete = float(torrent.get("progress", 0) or 0) >= 1
    prefix = f"{policy.name} hash={torrent_hash}"

    if limit <= 0:
        return False, (
            f"AT RISK {prefix}: no finite qBittorrent seed limit"
        )

    if limit < policy.minimum_seed_minutes:
        return False, (
            f"AT RISK {prefix}: qBittorrent limit={limit}m is below "
            f"policy={policy.minimum_seed_minutes}m"
        )

    required_minutes = max(limit, policy.minimum_seed_minutes)

    if not complete:
        return True, (
            f"DOWNLOADING {prefix}: required={required_minutes}m "
            "after completion"
        )

    remaining_minutes = max(required_minutes - seeded_minutes, 0)

    if remaining_minutes:
        return True, (
            f"PENDING {prefix}: seeded={seeded_minutes:.0f}m "
            f"remaining={remaining_minutes:.0f}m"
        )

    return True, (
        f"SATISFIED {prefix}: seeded={seeded_minutes:.0f}m "
        f"required={required_minutes}m"
    )


def run_audit(
    client: QBittorrentClient,
) -> int:
    torrents = client.get_json("/api/v2/torrents/info")
    private_torrents = [
        torrent
        for torrent in torrents
        if torrent.get("private") is True
    ]

    if not private_torrents:
        print("PRIVATE TRACKER AUDIT OK: no private torrents present")
        return 0

    failures = 0

    for torrent in private_torrents:
        hosts = torrent_hosts(client, str(torrent.get("hash", "")))
        safe, message = audit_torrent(torrent, hosts)
        print(message)
        if not safe:
            failures += 1

    if failures:
        raise PrivateTrackerAuditError(
            f"Private tracker audit found {failures} at-risk torrent(s)."
        )

    print(
        "PRIVATE TRACKER AUDIT OK: "
        f"{len(private_torrents)} private torrent(s) protected"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit private tracker seeding requirements without logging "
            "announce URLs or passkeys."
        )
    )
    parser.add_argument(
        "--stack-dir",
        type=Path,
        default=DEFAULT_STACK_DIR,
    )
    parser.add_argument(
        "--qbittorrent-url",
        default="http://127.0.0.1:8888",
    )
    args = parser.parse_args()

    username, password = read_credentials(
        args.stack_dir / "secrets/qbittorrent.json"
    )
    client = QBittorrentClient(
        args.qbittorrent_url,
        username,
        password,
    )
    client.login()
    return run_audit(client)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        PrivateTrackerAuditError,
        QBittorrentError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
