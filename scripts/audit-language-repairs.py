#!/usr/bin/env python3
"""Create a quiet, reviewable report of monitored language repairs."""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_STACK = Path("/volume1/docker/media-stack")
SONARR_URL = "http://127.0.0.1:8989"
RADARR_URL = "http://127.0.0.1:7878"

SCRIPT_ROOT = Path(__file__).resolve().parent
for module_dir in (SCRIPT_ROOT / "media", DEFAULT_STACK / "scripts"):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from common.arr import ArrClient, ArrError, read_api_key
from common.language import language_name


class RepairAuditError(RuntimeError):
    pass


def run_helper(command: list[str], timeout: int = 60 * 60) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        return 124, f"TIMEOUT after {timeout // 60} minutes\n{error.stdout or ''}"
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def build_report(stack: Path) -> tuple[str, int]:
    commands = (
        (
            "SONARR",
            [
                sys.executable,
                str(stack / "dispatch-series-fallback.py"),
                "--dry-run",
                "--max-searches",
                "4",
            ],
        ),
        (
            "RADARR",
            [sys.executable, str(stack / "dispatch-private-seerr.py"), "--dry-run"],
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


def language_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in ("latino", "castilian", "english", "unknown")}
    for item in items:
        counts[language_name(item)] += 1
    return counts


def collect_language_inventory(stack: Path) -> dict[str, Any]:
    sonarr = ArrClient(
        SONARR_URL,
        read_api_key(stack / "config/sonarr/config.xml"),
    )
    radarr = ArrClient(
        RADARR_URL,
        read_api_key(stack / "config/radarr/config.xml"),
    )

    series_rows = sonarr.get("/series")
    episode_files: list[dict[str, Any]] = []
    series_review: list[dict[str, Any]] = []
    for series in series_rows:
        files = sonarr.get(f"/episodefile?seriesId={int(series['id'])}")
        episode_files.extend(files)
        review_counts = language_counts(files)
        if review_counts["english"] or review_counts["unknown"]:
            series_review.append(
                {
                    "id": int(series["id"]),
                    "title": str(series.get("title") or ""),
                    "monitored": bool(series.get("monitored")),
                    "counts": review_counts,
                }
            )

    movies = radarr.get("/movie")
    movie_files = [
        movie["movieFile"]
        for movie in movies
        if movie.get("hasFile") and isinstance(movie.get("movieFile"), dict)
    ]
    movie_review = []
    for movie in movies:
        movie_file = movie.get("movieFile")
        if not movie.get("hasFile") or not isinstance(movie_file, dict):
            continue
        detected = language_name(movie_file)
        if detected in {"english", "unknown"}:
            movie_review.append(
                {
                    "id": int(movie["id"]),
                    "title": str(movie.get("title") or ""),
                    "year": int(movie.get("year", 0) or 0),
                    "monitored": bool(movie.get("monitored")),
                    "language": detected,
                }
            )

    return {
        "generatedAt": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "seriesFiles": {
            "total": len(episode_files),
            "counts": language_counts(episode_files),
            "review": series_review,
        },
        "movieFiles": {
            "total": len(movie_files),
            "counts": language_counts(movie_files),
            "review": movie_review,
        },
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.stack_dir / "state/language-repair-candidates.txt"
    inventory_path = args.stack_dir / "state/library-language-inventory.json"
    try:
        inventory = collect_language_inventory(args.stack_dir)
    except ArrError as error:
        raise RepairAuditError(f"Unable to inventory library languages: {error}") from error
    write_json_atomic(inventory_path, inventory)
    report, failures = build_report(args.stack_dir)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(output)
    print(
        f"LANGUAGE REPAIR REPORT: {output} inventory={inventory_path} "
        f"failures={failures}"
    )
    if failures:
        raise RepairAuditError(f"{failures} repair audit helper(s) failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RepairAuditError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)

