#!/usr/bin/env python3
"""Create a quiet, reviewable report of monitored language repairs."""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path


DEFAULT_STACK = Path("/volume1/docker/media-stack")


class RepairAuditError(RuntimeError):
    pass


def run_helper(command: list[str], timeout: int = 4 * 60 * 60) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        return 124, f"TIMEOUT after {timeout // 60} minutes\n{error.stdout or ''}"
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def build_report(stack: Path) -> tuple[str, int]:
    commands = (
        (
            "SONARR",
            [sys.executable, str(stack / "scripts/upgrade-sonarr-latino.py"), "--dry-run"],
        ),
        (
            "RADARR",
            [sys.executable, str(stack / "scripts/upgrade-radarr-latino.py"), "--dry-run"],
        ),
    )
    sections = [
        "Language repair candidates",
        datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "No downloads are started by this report.",
    ]
    failures = 0
    for name, command in commands:
        code, output = run_helper(command)
        failures += int(code != 0)
        sections.extend(("", f"=== {name} status={code} ===", output.strip()))
    return "\n".join(sections).rstrip() + "\n", failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.stack_dir / "state/language-repair-candidates.txt"
    report, failures = build_report(args.stack_dir)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(output)
    print(f"LANGUAGE REPAIR REPORT: {output} failures={failures}")
    if failures:
        raise RepairAuditError(f"{failures} repair audit helper(s) failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RepairAuditError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)

