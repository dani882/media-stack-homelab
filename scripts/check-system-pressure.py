#!/usr/bin/env python3
"""Record NAS resource pressure and defer background media work when overloaded."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_STATE_FILE = Path("/volume1/docker/media-stack/state/system-pressure.json")


class PressureError(RuntimeError):
    pass


@dataclass(frozen=True)
class PressureSnapshot:
    normalized_load: float
    io_wait_percent: float
    io_full_avg10: float
    memory_full_avg10: float
    swap_used_percent: float


def pressure_value(path: Path, category: str, field: str) -> float:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise PressureError(f"unable to read {path}: {error}") from error
    for line in lines:
        parts = line.split()
        if parts and parts[0] == category:
            values = dict(item.split("=", 1) for item in parts[1:] if "=" in item)
            try:
                return float(values[field])
            except (KeyError, ValueError) as error:
                raise PressureError(f"invalid {category} {field} in {path}") from error
    raise PressureError(f"missing {category} pressure data in {path}")


def cpu_counters(path: Path = Path("/proc/stat")) -> tuple[int, int]:
    try:
        values = [int(value) for value in path.read_text(encoding="utf-8").splitlines()[0].split()[1:]]
    except (OSError, ValueError, IndexError) as error:
        raise PressureError(f"unable to read CPU counters: {error}") from error
    if len(values) < 5:
        raise PressureError("CPU counters are incomplete")
    return sum(values[:8]), values[4]


def io_wait_percent(sample_seconds: float) -> float:
    if sample_seconds <= 0:
        raise PressureError("sample duration must be positive")
    total_before, wait_before = cpu_counters()
    time.sleep(sample_seconds)
    total_after, wait_after = cpu_counters()
    total_delta = total_after - total_before
    wait_delta = wait_after - wait_before
    if total_delta <= 0 or wait_delta < 0:
        raise PressureError("CPU counters did not advance normally")
    return wait_delta / total_delta * 100


def swap_used_percent(path: Path = Path("/proc/meminfo")) -> float:
    try:
        values = {
            fields[0].removesuffix(":"): int(fields[1])
            for line in path.read_text(encoding="utf-8").splitlines()
            if len(fields := line.split()) >= 2 and fields[1].isdigit()
        }
    except OSError as error:
        raise PressureError(f"unable to read memory counters: {error}") from error
    total = values.get("SwapTotal", 0)
    free = values.get("SwapFree", 0)
    return ((total - free) / total * 100) if total else 0.0


def snapshot(sample_seconds: float) -> PressureSnapshot:
    cpu_count = max(os.cpu_count() or 1, 1)
    return PressureSnapshot(
        normalized_load=os.getloadavg()[0] / cpu_count,
        io_wait_percent=io_wait_percent(sample_seconds),
        io_full_avg10=pressure_value(Path("/proc/pressure/io"), "full", "avg10"),
        memory_full_avg10=pressure_value(Path("/proc/pressure/memory"), "full", "avg10"),
        swap_used_percent=swap_used_percent(),
    )


def defer_reasons(current: PressureSnapshot) -> list[str]:
    reasons: list[str] = []
    if current.normalized_load >= 4.0:
        reasons.append(f"system load is {current.normalized_load:.1f}x CPU capacity")
    if current.io_wait_percent >= 30.0:
        reasons.append(f"disk I/O wait is {current.io_wait_percent:.1f}%")
    if current.io_full_avg10 >= 25.0:
        reasons.append(f"full disk pressure is {current.io_full_avg10:.1f}%")
    if current.memory_full_avg10 >= 20.0:
        reasons.append(f"full memory pressure is {current.memory_full_avg10:.1f}%")
    if current.swap_used_percent >= 75.0:
        reasons.append(f"swap is {current.swap_used_percent:.1f}% used")
    return reasons


def write_state(path: Path, current: PressureSnapshot, reasons: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "updated": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "status": "defer" if reasons else "ok",
        "deployment_allowed": not reasons,
        "recommended_action": (
            "Do not deploy or start background audits. Wait for disk and memory pressure to settle."
            if reasons
            else "Normal operation; deployment is allowed."
        ),
        "reasons": reasons,
        "metrics": asdict(current),
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--sample-seconds", type=float, default=1.0)
    parser.add_argument(
        "--guard",
        action="store_true",
        help="Return a non-zero status when background work should be deferred.",
    )
    args = parser.parse_args()
    current = snapshot(args.sample_seconds)
    reasons = defer_reasons(current)
    write_state(args.state_file, current, reasons)
    print(
        "SYSTEM PRESSURE: "
        f"load={current.normalized_load:.2f}x "
        f"io_wait={current.io_wait_percent:.1f}% "
        f"io_full={current.io_full_avg10:.1f}% "
        f"memory_full={current.memory_full_avg10:.1f}% "
        f"swap_used={current.swap_used_percent:.1f}%"
    )
    if reasons:
        print("DEFER BACKGROUND WORK: " + "; ".join(reasons))
        return 1 if args.guard else 0
    print("SYSTEM PRESSURE OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PressureError as error:
        print(f"ERROR: {error}")
        raise SystemExit(2)
