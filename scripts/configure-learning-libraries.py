#!/usr/bin/env python3
"""Create the DocsPedia learning folders and Jellyfin Courses library."""

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_STACK = Path("/volume1/docker/media-stack")
DEFAULT_DATA = Path("/volume1/Family")
DEFAULT_JELLYFIN_URL = "http://127.0.0.1:8899"
COURSES_NAME = "Cursos"
COURSES_PATH = "/data/Learning/Videos"


class LearningLibraryError(RuntimeError):
    pass


def read_api_key(settings_file: Path) -> str:
    try:
        payload = json.loads(settings_file.read_text(encoding="utf-8"))
        key = str(payload.get("jellyfin", {}).get("apiKey", "")).strip()
    except (OSError, json.JSONDecodeError) as error:
        raise LearningLibraryError("Unable to read Jellyfin integration settings") from error
    if not key:
        raise LearningLibraryError("Jellyfin integration key is unavailable")
    return key


class JellyfinClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-Emby-Token": api_key, "Content-Type": "application/json"}

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
    ) -> Any:
        suffix = ""
        if query:
            suffix = "?" + urllib.parse.urlencode(query, doseq=True)
        request = urllib.request.Request(
            f"{self.base_url}{path}{suffix}",
            data=b"{}" if method == "POST" else None,
            headers=self.headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
        except (OSError, urllib.error.URLError) as error:
            raise LearningLibraryError("Jellyfin library request failed") from error
        return json.loads(body) if body else None


def ensure_courses_library(client: JellyfinClient, dry_run: bool) -> bool:
    libraries = client.request("GET", "/Library/VirtualFolders")
    if not isinstance(libraries, list):
        raise LearningLibraryError("Jellyfin returned an invalid library list")
    existing = next((item for item in libraries if item.get("Name") == COURSES_NAME), None)
    if existing is not None:
        locations = {str(path) for path in existing.get("Locations") or []}
        if COURSES_PATH not in locations:
            raise LearningLibraryError("Cursos exists but points to an unexpected folder")
        if str(existing.get("CollectionType") or "") != "homevideos":
            raise LearningLibraryError("Cursos exists with an unexpected content type")
        print("JELLYFIN LEARNING LIBRARY OK: Cursos")
        return False
    if dry_run:
        print("WOULD CREATE JELLYFIN LEARNING LIBRARY: Cursos")
        return True
    client.request(
        "POST",
        "/Library/VirtualFolders",
        query={
            "name": COURSES_NAME,
            "collectionType": "homevideos",
            "paths": [COURSES_PATH],
            "refreshLibrary": "true",
        },
    )
    print("CREATED JELLYFIN LEARNING LIBRARY: Cursos")
    return True


def run(stack: Path, data_root: Path, base_url: str, dry_run: bool) -> int:
    videos = data_root / "Media/Learning/Videos"
    documents = data_root / "Media/Learning/Documents"
    downloads = data_root / "Downloads/complete/learning"
    if dry_run:
        for path in (videos, documents, downloads):
            print(f"WOULD ENSURE DIRECTORY: {path}")
    else:
        for path in (videos, documents, downloads):
            path.mkdir(parents=True, exist_ok=True)
    key = read_api_key(stack / "config/jellyseerr/settings.json")
    ensure_courses_library(JellyfinClient(base_url, key), dry_run)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--jellyfin-url", default=DEFAULT_JELLYFIN_URL)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(run(args.stack_dir, args.data_root, args.jellyfin_url, args.dry_run))
