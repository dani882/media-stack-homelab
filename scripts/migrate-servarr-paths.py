#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")

MAPPINGS = {
    "sonarr": (
        ("/media/TV Shows", "/data/Media/TV Shows"),
    ),
    "radarr": (
        ("/media/Movies", "/data/Media/Movies"),
        (
            "/media/Kids Movies",
            "/data/Media/Kids Movies",
        ),
    ),
}


class MigrationError(RuntimeError):
    pass


def read_api_key(config_file: Path) -> str:
    root = ET.parse(config_file).getroot()
    api_key = root.findtext("ApiKey", "").strip()

    if not api_key:
        raise MigrationError(
            f"ApiKey not found in {config_file}"
        )

    return api_key


class Client:
    def __init__(
        self,
        base_url: str,
        api_key: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
    ) -> Any:
        data = None

        if payload is not None:
            data = json.dumps(payload).encode()

        request = urllib.request.Request(
            self.base_url + "/api/v3" + path,
            data=data,
            headers=self.headers,
            method=method,
        )

        with urllib.request.urlopen(
            request,
            timeout=60,
        ) as response:
            body = response.read()

        if not body:
            return None

        return json.loads(body)


def resolve_new_path(
    path: str,
    mappings: tuple[tuple[str, str], ...],
) -> tuple[str, str] | None:
    for old_root, new_root in mappings:
        if path == old_root:
            return new_root, new_root

        prefix = old_root + "/"

        if path.startswith(prefix):
            suffix = path[len(old_root):]
            return new_root + suffix, new_root

    for _, new_root in mappings:
        if path == new_root or path.startswith(new_root + "/"):
            return None

    raise MigrationError(
        f"Unexpected path outside managed roots: {path}"
    )


def verify_root_exists(
    client: Client,
    path: str,
) -> None:
    roots = client.request("GET", "/rootfolder")

    available = {
        item.get("path")
        for item in roots
        if item.get("accessible")
    }

    if path not in available:
        raise MigrationError(
            f"Destination root is not accessible: {path}"
        )


def migrate_radarr(
    client: Client,
    apply_changes: bool,
) -> tuple[int, int]:
    mappings = MAPPINGS["radarr"]

    for _, new_root in mappings:
        verify_root_exists(client, new_root)

    movies = client.request("GET", "/movie")

    changed = 0
    skipped = 0

    for movie in movies:
        movie_id = int(movie["id"])
        title = movie.get("title", "")
        current_path = str(movie.get("path", ""))

        resolved = resolve_new_path(
            current_path,
            mappings,
        )

        if resolved is None:
            skipped += 1
            continue

        new_path, new_root = resolved

        print(
            f"RADARR ID={movie_id}: "
            f"{title}"
        )
        print(f"  {current_path}")
        print(f"  -> {new_path}")

        changed += 1

        if not apply_changes:
            continue

        payload = dict(movie)
        payload["path"] = new_path
        payload["rootFolderPath"] = new_root

        query = urllib.parse.urlencode({
            "moveFiles": "false",
        })

        client.request(
            "PUT",
            f"/movie/{movie_id}?{query}",
            payload,
        )

    return changed, skipped


def migrate_sonarr(
    client: Client,
    apply_changes: bool,
) -> tuple[int, int]:
    mappings = MAPPINGS["sonarr"]

    for _, new_root in mappings:
        verify_root_exists(client, new_root)

    series = client.request("GET", "/series")

    changed = 0
    skipped = 0

    for item in series:
        series_id = int(item["id"])
        title = item.get("title", "")
        current_path = str(item.get("path", ""))

        resolved = resolve_new_path(
            current_path,
            mappings,
        )

        if resolved is None:
            skipped += 1
            continue

        new_path, new_root = resolved

        print(
            f"SONARR ID={series_id}: "
            f"{title}"
        )
        print(f"  {current_path}")
        print(f"  -> {new_path}")

        changed += 1

        if not apply_changes:
            continue

        payload = dict(item)
        payload["path"] = new_path
        payload["rootFolderPath"] = new_root

        query = urllib.parse.urlencode({
            "moveFiles": "false",
        })

        client.request(
            "PUT",
            f"/series/{series_id}?{query}",
            payload,
        )

    return changed, skipped


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate Sonarr/Radarr internal paths "
            "from /media to /data without moving files."
        )
    )

    parser.add_argument(
        "app",
        choices=("sonarr", "radarr"),
    )

    parser.add_argument(
        "--stack-dir",
        type=Path,
        default=DEFAULT_STACK_DIR,
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply changes. Default is dry-run."
        ),
    )

    args = parser.parse_args()

    if args.app == "sonarr":
        port = 8989
    else:
        port = 7878

    config_file = (
        args.stack_dir
        / "config"
        / args.app
        / "config.xml"
    )

    api_key = read_api_key(config_file)

    client = Client(
        f"http://127.0.0.1:{port}",
        api_key,
    )

    if args.app == "radarr":
        changed, skipped = migrate_radarr(
            client,
            args.apply,
        )
    else:
        changed, skipped = migrate_sonarr(
            client,
            args.apply,
        )

    print()
    print("=== Summary ===")
    print(
        "Mode:",
        "APPLY" if args.apply else "DRY-RUN",
    )
    print("Would change:", changed)
    print("Already migrated:", skipped)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        MigrationError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        OSError,
        ET.ParseError,
    ) as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
