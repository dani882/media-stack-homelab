#!/usr/bin/env python3

"""Audit private-tracker seeding obligations without exposing announce URLs."""


import argparse
import datetime
import html
import json
import sys
import time
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
    minimum_seed_minutes: int | None = None
    minimum_ratio: float | None = None
    completion_window_minutes: int | None = None


TRACKER_POLICIES = (
    TrackerPolicy(
        name="Milnueve",
        host_suffixes=("milnueve.cc",),
        # Rule: 96 h. Retention: rule + 10 h tracker-accounting margin.
        minimum_seed_minutes=6360,
    ),
    TrackerPolicy(
        name="RetroToon World",
        host_suffixes=("retrotoon.world",),
        # Rule: 72 h. Retention: rule + 10 h tracker-accounting margin.
        minimum_seed_minutes=4920,
        # RetroToon requires the full 72 hours within ten days of a completed
        # download. This audit only alerts; it never changes torrent state.
        completion_window_minutes=10 * 24 * 60,
    ),
    TrackerPolicy(
        name="Torrent Haven",
        host_suffixes=("torrenthaven.org",),
        # Rule: 72 h. Retention: rule + 10 h tracker-accounting margin.
        minimum_seed_minutes=4920,
    ),
    TrackerPolicy(
        name="DreadVault",
        host_suffixes=("dreadvault.org",),
        # Rule: 120 h. Retention: rule + 10 h tracker-accounting margin.
        minimum_seed_minutes=7800,
    ),
    TrackerPolicy(
        name="BTArg",
        host_suffixes=("btarg.org", "btarg.com.ar"),
        # BTArg publishes no fixed seed-time threshold. Its FAQ describes
        # seeding to 1:1 as the expected sharing behavior, while the global
        # account ratio must remain at or above 0.5.
        minimum_ratio=1.0,
    ),
)


class PrivateTrackerAuditError(RuntimeError):
    pass


def audit_status(safe: bool, message: str) -> str:
    if not safe:
        return "risk"
    if message.startswith("SATISFIED"):
        return "satisfied"
    if message.startswith("DOWNLOADING"):
        return "downloading"
    return "pending"


def write_dashboard(path: Path, statistics: dict[str, dict[str, int]]) -> None:
    updated = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    rows = []
    names = [policy.name for policy in TRACKER_POLICIES]
    names.extend(sorted(set(statistics) - set(names)))
    for name in names:
        totals = statistics.get(
            name,
            {
                "torrents": 0,
                "uploaded": 0,
                "downloaded": 0,
                "satisfied": 0,
                "pending": 0,
                "downloading": 0,
                "risk": 0,
            },
        )
        rows.append({"tracker": name, **totals})
    payload = {"updatedAt": updated, "trackers": rows}
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    json_path = path.with_suffix(".json")
    json_temp = json_path.with_suffix(".tmp")
    json_temp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    json_temp.replace(json_path)

    table_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row['tracker'])}</td>"
        f"<td>{row['torrents']}</td>"
        f"<td>{row['downloading']}</td>"
        f"<td>{row['pending']}</td>"
        f"<td>{row['satisfied']}</td>"
        f"<td class={'risk' if row['risk'] else 'ok'}>{row['risk']}</td>"
        f"<td>{row['uploaded'] / 1024**3:.1f} GiB</td>"
        f"<td>{row['downloaded'] / 1024**3:.1f} GiB</td>"
        "</tr>"
        for row in rows
    )
    document = f"""<!doctype html>
<html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Trackers privados</title>
<style>body{{font:16px system-ui;background:#101827;color:#e5e7eb;margin:2rem}}table{{border-collapse:collapse;width:100%;max-width:1100px}}th,td{{padding:.7rem;border-bottom:1px solid #334155;text-align:right}}th:first-child,td:first-child{{text-align:left}}.ok{{color:#4ade80}}.risk{{color:#fb7185;font-weight:700}}small{{color:#94a3b8}}</style>
<h1>Estado de trackers privados</h1><small>Actualizado: {html.escape(updated)}</small>
<table><thead><tr><th>Tracker</th><th>Torrents</th><th>Descargando</th><th>Pendientes</th><th>Cumplidos</th><th>Riesgo</th><th>Subido</th><th>Descargado</th></tr></thead><tbody>{table_rows}</tbody></table>
</html>"""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(document, encoding="utf-8")
    temporary.replace(path)


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
    *,
    now: float | None = None,
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

    if policy.minimum_ratio is not None:
        ratio_limit = float(torrent.get("ratio_limit", -1) or -1)
        ratio = float(torrent.get("ratio", 0) or 0)
        if ratio_limit <= 0:
            return False, (
                f"AT RISK {prefix}: no finite qBittorrent ratio limit"
            )
        if ratio_limit < policy.minimum_ratio:
            return False, (
                f"AT RISK {prefix}: qBittorrent ratio limit={ratio_limit:.2f} "
                f"is below policy={policy.minimum_ratio:.2f}"
            )
        required_ratio = max(ratio_limit, policy.minimum_ratio)
        if not complete:
            return True, (
                f"DOWNLOADING {prefix}: required ratio={required_ratio:.2f}"
            )
        if ratio < required_ratio:
            return True, (
                f"PENDING {prefix}: ratio={ratio:.2f} "
                f"required={required_ratio:.2f}"
            )
        return True, (
            f"SATISFIED {prefix}: ratio={ratio:.2f} "
            f"required={required_ratio:.2f}"
        )

    if policy.minimum_seed_minutes is None:
        return False, f"AT RISK {prefix}: tracker policy has no retention rule"

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

    if policy.completion_window_minutes is not None and remaining_minutes:
        completed_on = float(torrent.get("completion_on", 0) or 0)
        if completed_on <= 0:
            return False, (
                f"AT RISK {prefix}: completion timestamp is unavailable; "
                "cannot verify the tracker deadline"
            )

        current_time = time.time() if now is None else now
        deadline = completed_on + policy.completion_window_minutes * 60
        latest_completion = current_time + remaining_minutes * 60
        deadline_remaining_minutes = (deadline - current_time) / 60

        if latest_completion > deadline:
            status = "OVERDUE" if current_time > deadline else "AT RISK"
            return False, (
                f"{status} {prefix}: seeded={seeded_minutes:.0f}m "
                f"remaining={remaining_minutes:.0f}m "
                f"deadline_remaining={deadline_remaining_minutes:.0f}m"
            )

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
    *,
    enforce_limits: bool = False,
    dashboard_path: Path | None = None,
) -> int:
    torrents = client.get_json("/api/v2/torrents/info")
    private_torrents = [
        torrent
        for torrent in torrents
        if torrent.get("private") is True
    ]

    if not private_torrents:
        if dashboard_path is not None:
            write_dashboard(dashboard_path, {})
        print("PRIVATE TRACKER AUDIT OK: no private torrents present")
        return 0

    failures = 0
    statistics: dict[str, dict[str, int]] = {}

    for torrent in private_torrents:
        hosts = torrent_hosts(client, str(torrent.get("hash", "")))
        policy = matching_policy(hosts)
        limit = int(torrent.get("seeding_time_limit", -1) or -1)
        ratio_limit = float(torrent.get("ratio_limit", -1) or -1)
        if (
            enforce_limits
            and policy is not None
            and policy.minimum_seed_minutes is not None
            and limit < policy.minimum_seed_minutes
        ):
            client.post_form(
                "/api/v2/torrents/setShareLimits",
                {
                    "hashes": torrent["hash"],
                    "ratioLimit": -2,
                    "seedingTimeLimit": policy.minimum_seed_minutes,
                    "inactiveSeedingTimeLimit": -2,
                    "shareLimitAction": "Default",
                },
            )
            print(
                f"ENFORCED {policy.name} hash={str(torrent['hash'])[:12].upper()}: "
                f"{limit}m -> {policy.minimum_seed_minutes}m"
            )
            torrent = dict(torrent)
            torrent["seeding_time_limit"] = policy.minimum_seed_minutes
        if (
            enforce_limits
            and policy is not None
            and policy.minimum_ratio is not None
            and ratio_limit < policy.minimum_ratio
        ):
            client.post_form(
                "/api/v2/torrents/setShareLimits",
                {
                    "hashes": torrent["hash"],
                    "ratioLimit": policy.minimum_ratio,
                    "seedingTimeLimit": -1,
                    "inactiveSeedingTimeLimit": -1,
                    "shareLimitAction": "Default",
                },
            )
            print(
                f"ENFORCED {policy.name} hash={str(torrent['hash'])[:12].upper()}: "
                f"ratio {ratio_limit:.2f} -> {policy.minimum_ratio:.2f}"
            )
            torrent = dict(torrent)
            torrent["ratio_limit"] = policy.minimum_ratio
        safe, message = audit_torrent(torrent, hosts)
        print(message)
        if not safe:
            failures += 1
        dashboard_name = policy.name if policy is not None else "Unrecognized"
        totals = statistics.setdefault(
            dashboard_name,
            {
                "torrents": 0,
                "uploaded": 0,
                "downloaded": 0,
                "satisfied": 0,
                "pending": 0,
                "downloading": 0,
                "risk": 0,
            },
        )
        totals["torrents"] += 1
        totals["uploaded"] += int(torrent.get("uploaded", 0) or 0)
        totals["downloaded"] += int(torrent.get("downloaded", 0) or 0)
        totals[audit_status(safe, message)] += 1

    for name in sorted(statistics):
        totals = statistics[name]
        print(
            "TRACKER STATS "
            f"{name}: torrents={totals['torrents']} "
            f"uploaded={totals['uploaded']}B "
            f"downloaded={totals['downloaded']}B"
        )

    if dashboard_path is not None:
        write_dashboard(dashboard_path, statistics)

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
        "--dashboard-path",
        type=Path,
        help="Write a secret-free HTML and JSON tracker summary.",
    )
    parser.add_argument(
        "--enforce-limits",
        action="store_true",
        help="Raise managed private torrent limits to the retention policy.",
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
    dashboard_path = args.dashboard_path or args.stack_dir / "state/private-trackers.html"
    return run_audit(
        client,
        enforce_limits=args.enforce_limits,
        dashboard_path=dashboard_path,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        PrivateTrackerAuditError,
        QBittorrentError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
