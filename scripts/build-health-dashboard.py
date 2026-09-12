#!/usr/bin/env python3
"""Build one secret-free HTML and JSON summary of media-stack health."""

from __future__ import annotations

import argparse
import datetime
import html
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
UNITS = (
    "media-stack-healthcheck.timer",
    "media-stack-hardlink-audit.timer",
    "media-stack-imported-audio-audit.timer",
    "media-stack-language-repair-audit.timer",
    "media-stack-private-dispatch.timer",
    "media-stack-public-cleanup.timer",
    "media-stack-stalled-public-cleanup.timer",
    "media-stack-btarg-series.timer",
    "media-stack-torrent-notifications.timer",
    "media-stack-watchdog.timer",
    "media-stack-archive-spanish-dispatch.timer",
)
REPORTS = (
    ("Private trackers", "private-trackers.json", 26),
    ("Imported audio", "imported-audio-audit.json", 2),
    ("Language repairs", "language-repair-candidates.txt", 30),
)


class DashboardError(RuntimeError):
    pass


@dataclass(frozen=True)
class Component:
    name: str
    status: str
    detail: str


def age_hours(path: Path, now: float) -> float | None:
    try:
        return max(0.0, (now - path.stat().st_mtime) / 3600)
    except OSError:
        return None


def report_components(state_dir: Path, now: float) -> list[Component]:
    result: list[Component] = []
    for name, filename, maximum_age in REPORTS:
        age = age_hours(state_dir / filename, now)
        if age is None:
            result.append(Component(name, "missing", "report not created yet"))
        elif age > maximum_age:
            result.append(Component(name, "stale", f"last update {age:.1f} hours ago"))
        else:
            result.append(Component(name, "ok", f"updated {age:.1f} hours ago"))
    return result


def unit_components(timeout: int = 15) -> list[Component]:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", *UNITS],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DashboardError("unable to inspect scheduled tasks") from error
    states = [line.strip() for line in result.stdout.splitlines()]
    if len(states) != len(UNITS):
        raise DashboardError("scheduled-task status was incomplete")
    return [
        Component(unit.removesuffix(".timer"), "ok" if state == "active" else "failed", state)
        for unit, state in zip(UNITS, states, strict=True)
    ]


def audio_counts(state_dir: Path) -> dict[str, int]:
    path = state_dir / "imported-audio-audit.json"
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    counts = payload.get("counts") if isinstance(payload, dict) else None
    if not isinstance(counts, dict):
        return {}
    return {str(key): int(value) for key, value in counts.items() if isinstance(value, int)}


def btarg_progress_component(state_dir: Path, now: float) -> tuple[Component, bool]:
    path = state_dir / "btarg-series-progress.json"
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Component("BTArg progress", "ok", "no active progress report"), False
    status = str(payload.get("status") or "idle").casefold()
    updated = float(payload.get("updatedAt") or 0)
    age = max(0.0, (now - updated) / 3600) if updated else float("inf")
    active = status in {"importando", "descargando"}
    stalled = active and age > 2
    if stalled:
        return Component("BTArg progress", "failed", f"no progress for {age:.1f} hours"), True
    if "error" in status or "revisión" in status:
        return Component("BTArg progress", "attention", status), False
    return Component("BTArg progress", "ok", f"{status}; updated {age:.1f} hours ago"), False


def stop_stalled_btarg(timeout: int) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", "media-stack-btarg-series.service"],
            check=False,
            timeout=timeout,
        )
        if result.returncode != 0:
            return False
        subprocess.run(
            ["systemctl", "stop", "media-stack-btarg-series.service"],
            check=True,
            timeout=timeout,
        )
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise DashboardError("unable to stop stalled BTArg work safely") from error


def write_dashboard(stack_dir: Path, components: list[Component]) -> tuple[Path, Path]:
    state_dir = stack_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    disk = shutil.disk_usage("/volume1/Family" if Path("/volume1/Family").exists() else stack_dir)
    counts = audio_counts(state_dir)
    overall = "attention" if any(item.status != "ok" for item in components) else "ok"
    payload = {
        "updated": now.isoformat(),
        "overall": overall,
        "disk": {"free_gib": round(disk.free / 1024**3, 1), "used_percent": round(disk.used / disk.total * 100, 1)},
        "audio_counts": counts,
        "components": [asdict(item) for item in components],
    }
    json_path = state_dir / "media-health.json"
    json_tmp = json_path.with_suffix(".tmp")
    json_tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    json_tmp.replace(json_path)
    rows = "".join(
        f"<tr><td>{html.escape(item.name)}</td><td>{html.escape(item.status)}</td>"
        f"<td>{html.escape(item.detail)}</td></tr>" for item in components
    )
    count_text = ", ".join(f"{html.escape(key)}: {value}" for key, value in sorted(counts.items())) or "sin datos todavía"
    document = (
        "<!doctype html><meta charset='utf-8'><title>Estado del media stack</title>"
        "<style>body{font-family:system-ui;margin:2rem;max-width:1100px}"
        "table{border-collapse:collapse;width:100%}td,th{padding:.55rem;border:1px solid #ccc}"
        "th{text-align:left;background:#eee}</style>"
        f"<h1>Estado del media stack: {html.escape(overall)}</h1>"
        f"<p>Actualizado: {html.escape(now.isoformat())}</p>"
        f"<p>Espacio libre: {payload['disk']['free_gib']} GiB; audio: {count_text}</p>"
        f"<table><thead><tr><th>Componente</th><th>Estado</th><th>Detalle</th></tr></thead><tbody>{rows}</tbody></table>"
    )
    html_path = state_dir / "media-health.html"
    html_tmp = html_path.with_suffix(".tmp")
    html_tmp.write_text(document, encoding="utf-8")
    html_tmp.replace(html_path)
    return json_path, html_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument(
        "--stop-stalled-btarg",
        action="store_true",
        help="Stop the BTArg worker if its active progress has not changed for two hours.",
    )
    args = parser.parse_args()
    state_dir = args.stack_dir / "state"
    components = unit_components(args.timeout)
    components.extend(report_components(state_dir, datetime.datetime.now().timestamp()))
    btarg, stalled = btarg_progress_component(state_dir, datetime.datetime.now().timestamp())
    components.append(btarg)
    if stalled and args.stop_stalled_btarg:
        stopped = stop_stalled_btarg(args.timeout)
        if stopped:
            components[-1] = Component(
                "BTArg progress",
                "attention",
                "stalled worker stopped safely; torrent and temporary files retained",
            )
        else:
            components[-1] = Component(
                "BTArg progress",
                "attention",
                "stale progress report; worker is already inactive",
            )
    json_path, html_path = write_dashboard(args.stack_dir, components)
    print(f"MEDIA HEALTH DASHBOARD: {json_path} {html_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DashboardError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
