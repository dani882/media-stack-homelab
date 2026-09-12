#!/usr/bin/env python3
"""Fail safely before a deployment when the NAS is too busy or unhealthy."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_DATA_ROOT = Path("/volume1/Family")


class PreflightError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreflightSnapshot:
    normalized_load: float
    stack_free_gib: float
    data_free_gib: float
    data_used_percent: float


def evaluate_snapshot(
    snapshot: PreflightSnapshot,
    minimum_free_gib: float,
    maximum_used_percent: float,
    maximum_normalized_load: float,
) -> list[str]:
    problems: list[str] = []
    if snapshot.stack_free_gib < minimum_free_gib:
        problems.append(f"stack has only {snapshot.stack_free_gib:.1f} GiB free")
    if snapshot.data_free_gib < minimum_free_gib:
        problems.append(f"data volume has only {snapshot.data_free_gib:.1f} GiB free")
    if snapshot.data_used_percent >= maximum_used_percent:
        problems.append(f"data volume is {snapshot.data_used_percent:.1f}% full")
    if snapshot.normalized_load >= maximum_normalized_load:
        problems.append(
            f"normalized system load is {snapshot.normalized_load:.1f}x CPU capacity"
        )
    return problems


def disk_values(path: Path) -> tuple[float, float]:
    usage = shutil.disk_usage(path)
    free_gib = usage.free / 1024**3
    used_percent = (usage.used / usage.total * 100) if usage.total else 100.0
    return free_gib, used_percent


def snapshot(stack_dir: Path, data_root: Path) -> PreflightSnapshot:
    cpu_count = max(os.cpu_count() or 1, 1)
    normalized_load = os.getloadavg()[0] / cpu_count
    stack_free, _ = disk_values(stack_dir)
    data_free, data_used = disk_values(data_root)
    return PreflightSnapshot(normalized_load, stack_free, data_free, data_used)


def check_docker(timeout: int) -> None:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreflightError(f"Docker did not respond within {timeout} seconds") from error
    if result.returncode != 0 or not result.stdout.strip():
        raise PreflightError("Docker is not responding normally")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--minimum-free-gib", type=float, default=10.0)
    parser.add_argument("--maximum-used-percent", type=float, default=95.0)
    parser.add_argument("--maximum-normalized-load", type=float, default=8.0)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    check_docker(args.timeout)
    current = snapshot(args.stack_dir, args.data_root)
    problems = evaluate_snapshot(
        current,
        args.minimum_free_gib,
        args.maximum_used_percent,
        args.maximum_normalized_load,
    )
    print(
        "NAS PREFLIGHT: "
        f"load={current.normalized_load:.2f}x "
        f"stack_free={current.stack_free_gib:.1f}GiB "
        f"data_free={current.data_free_gib:.1f}GiB "
        f"data_used={current.data_used_percent:.1f}%"
    )
    if problems:
        raise PreflightError("; ".join(problems))
    print("NAS PREFLIGHT OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightError as error:
        print(f"ERROR: deployment postponed: {error}", file=sys.stderr)
        raise SystemExit(1)
