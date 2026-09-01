#!/usr/bin/env python3
"""Hardlink unambiguous episode files into a Sonarr series library.

This is intentionally conservative.  It imports only files named with an
English episode title that has exactly one match in Sonarr.  Files with
alternate numbering, multi-episode releases, or localized-only titles are
reported and left untouched for manual review.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as element_tree
from pathlib import Path


EPISODE_NAME = re.compile(r"\bS\d{1,2}E\d{1,3}\s*-\s*(.+)\.(mkv|mp4)$", re.I)


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def api_get(base_url: str, api_key: str, path: str) -> object:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", headers={"X-Api-Key": api_key}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def api_post(base_url: str, api_key: str, path: str, payload: object) -> object:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def read_api_key(config_file: Path) -> str:
    api_key = element_tree.parse(config_file).findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"ApiKey missing from {config_file}")
    return api_key


def safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", value).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series-id", type=int, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("/volume1/Family"),
        help="Host path mounted as /data inside Sonarr.",
    )
    parser.add_argument("--sonarr-url", default="http://127.0.0.1:8989")
    parser.add_argument(
        "--config-file",
        type=Path,
        default=Path("/volume1/docker/media-stack/config/sonarr/config.xml"),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    api_key = read_api_key(args.config_file)
    series = api_get(args.sonarr_url, api_key, f"/api/v3/series/{args.series_id}")
    episodes = api_get(
        args.sonarr_url, api_key, f"/api/v3/episode?seriesId={args.series_id}"
    )
    by_title: dict[str, list[dict[str, object]]] = {}
    for episode in episodes:
        by_title.setdefault(normalized(str(episode["title"])), []).append(episode)

    planned: list[tuple[Path, Path, dict[str, object]]] = []
    skipped = 0
    for source in sorted(args.source.rglob("*")):
        if not source.is_file():
            continue
        match = EPISODE_NAME.search(source.name)
        if not match:
            skipped += 1
            continue
        matches = by_title.get(normalized(match.group(1)), [])
        if len(matches) != 1:
            skipped += 1
            continue
        episode = matches[0]
        season = int(episode["seasonNumber"])
        number = int(episode["episodeNumber"])
        filename = (
            f"{safe_name(str(series['title']))} - S{season:02d}E{number:02d} - "
            f"{safe_name(str(episode['title']))}{source.suffix.lower()}"
        )
        sonarr_path = Path(str(series["path"]))
        try:
            library_path = args.data_root / sonarr_path.relative_to("/data")
        except ValueError:
            library_path = sonarr_path
        destination = library_path / f"Season {season:02d}" / filename
        planned.append((source, destination, episode))

    print(f"Series: {series['title']}")
    print(f"Candidates: {len(planned)}; skipped for manual review: {skipped}")
    changed = 0
    for source, destination, episode in planned:
        state = "EXISTS" if destination.exists() else "PLAN"
        print(
            f"{state}: {source.name} -> S{episode['seasonNumber']:02d}"
            f"E{episode['episodeNumber']:02d} {destination.name}"
        )
        if not args.apply or destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(source, destination)
        changed += 1

    if changed:
        command = api_post(
            args.sonarr_url,
            api_key,
            "/api/v3/command",
            {"name": "RescanSeries", "seriesId": args.series_id},
        )
        print(f"RescanSeries command queued: {command['id']}")
    print("No files changed." if not changed else f"Hardlinks created: {changed}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
