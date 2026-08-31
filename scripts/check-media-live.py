#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_TIMEOUT = 15


class LiveCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpTarget:
    name: str
    url: str
    optional: bool = False
    expected_statuses: tuple[int, ...] = (
        200,
        204,
        302,
        303,
        401,
    )


def run_compose_ps(
    stack_dir: Path,
) -> list[dict[str, object]]:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "ps",
            "--format",
            "json",
        ],
        cwd=stack_dir,
        capture_output=True,
        check=True,
        text=True,
    )

    payload = result.stdout.strip()
    if not payload:
        return []

    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError:
        entries = []
        for line in payload.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise LiveCheckError(
                    "Unexpected docker compose ps entry."
                )
            entries.append(item)
    else:
        if isinstance(loaded, list):
            entries = loaded
        elif isinstance(loaded, dict):
            entries = [loaded]
        else:
            raise LiveCheckError(
                "Unexpected docker compose ps output."
            )

    normalized: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise LiveCheckError(
                "Unexpected docker compose ps entry."
            )
        normalized.append(entry)

    return normalized


def check_http_target(
    target: HttpTarget,
    timeout: int,
) -> tuple[bool, str]:
    request = urllib.request.Request(
        target.url,
        method="GET",
        headers={
            "User-Agent": "homelab-media-live-check/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            status = response.getcode()
    except urllib.error.HTTPError as error:
        status = error.code
    except urllib.error.URLError as error:
        if target.optional:
            return True, (
                f"optional target unreachable: {error.reason}"
            )
        return False, (
            f"unreachable: {error.reason}"
        )

    if status not in target.expected_statuses:
        if target.optional:
            return True, (
                f"optional target returned HTTP {status}"
            )
        return False, (
            f"unexpected HTTP {status}"
        )

    return True, f"HTTP {status}"


def service_map(
    profilarr_running: bool,
) -> list[HttpTarget]:
    targets = [
        HttpTarget(
            "Prowlarr",
            "http://127.0.0.1:9696/",
        ),
        HttpTarget(
            "Sonarr",
            "http://127.0.0.1:8989/",
        ),
        HttpTarget(
            "Radarr",
            "http://127.0.0.1:7878/",
        ),
        HttpTarget(
            "Bazarr",
            "http://127.0.0.1:6767/",
        ),
        HttpTarget(
            "Seerr",
            "http://127.0.0.1:5055/api/v1/status",
            expected_statuses=(200,),
        ),
        HttpTarget(
            "qBittorrent",
            "http://127.0.0.1:8888/",
        ),
        HttpTarget(
            "Jellyfin",
            "http://127.0.0.1:8899/health",
            expected_statuses=(200,),
        ),
        HttpTarget(
            "FlareSolverr",
            "http://127.0.0.1:8191/",
            expected_statuses=(200, 405),
        ),
    ]

    if profilarr_running:
        targets.append(
            HttpTarget(
                "Profilarr",
                "http://127.0.0.1:6868/auth/login",
            )
        )

    return targets


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run quick live health checks for the NAS media stack."
        )
    )
    parser.add_argument(
        "--stack-dir",
        type=Path,
        default=DEFAULT_STACK_DIR,
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
    )
    args = parser.parse_args()

    try:
        compose_entries = run_compose_ps(args.stack_dir)
    except (
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        LiveCheckError,
    ) as error:
        raise LiveCheckError(
            f"Unable to inspect live Compose state: {error}"
        ) from error

    running_names = {
        str(entry.get("Service", ""))
        for entry in compose_entries
        if "running" in str(entry.get("State", "")).lower()
    }

    required_services = (
        "prowlarr",
        "sonarr",
        "radarr",
        "bazarr",
        "seerr",
        "qbittorrent",
        "jellyfin",
        "flaresolverr",
    )

    missing = [
        name
        for name in required_services
        if name not in running_names
    ]

    if missing:
        raise LiveCheckError(
            "Required services not running: "
            + ", ".join(missing)
        )

    print("Compose services running:")
    for name in sorted(running_names):
        print(f"  - {name}")

    print()
    print("HTTP reachability:")

    failed = False
    profilarr_running = "profilarr" in running_names

    for target in service_map(profilarr_running):
        ok, message = check_http_target(
            target,
            args.timeout,
        )
        status = "OK" if ok else "FAIL"
        print(f"  {status}: {target.name} -> {message}")
        failed = failed or not ok

    print()
    print("Quick policy checks:")
    if profilarr_running:
        print("  OK: Profilarr pilot is running")
    else:
        print(
            "  OK: Profilarr pilot is not running "
            "(optional profile)"
        )

    print(
        "  OK: Recyclarr remains a one-shot tool service "
        "and is not expected in compose ps"
    )

    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LiveCheckError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
