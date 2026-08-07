#!/usr/bin/env python3

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_SONARR_URL = "http://127.0.0.1:8989"
DEFAULT_SONARR_CONFIG = (
    "/volume1/docker/media-stack/config/sonarr/config.xml"
)

DEFAULT_QBITTORRENT_URL = "http://127.0.0.1:8888"
DEFAULT_QBITTORRENT_SECRET = (
    "/volume1/docker/media-stack/secrets/qbittorrent.json"
)

MINIMUM_SEEDING_MINUTES = 30.0

SAFE_TORRENT_STATES = {
    "stoppedUP",
    "stalledUP",
    "queuedUP",
    "pausedUP",
}

SAFE_WARNING_MARKERS = (
    "Not a Custom Format upgrade",
)


class CleanupError(RuntimeError):
    pass


def read_sonarr_api_key(config_file: Path) -> str:
    if not config_file.is_file():
        raise CleanupError(
            f"Sonarr configuration file not found: {config_file}"
        )

    try:
        root = ET.parse(config_file).getroot()
    except ET.ParseError as error:
        raise CleanupError(
            f"Unable to parse {config_file}: {error}"
        ) from error

    api_key = root.findtext("ApiKey", "").strip()

    if not api_key:
        raise CleanupError(
            f"ApiKey was not found in {config_file}"
        )

    return api_key


def read_qbittorrent_credentials(
    secret_file: Path,
) -> tuple[str, str]:
    if not secret_file.is_file():
        raise CleanupError(
            f"qBittorrent secret file not found: {secret_file}"
        )

    try:
        payload = json.loads(
            secret_file.read_text()
        )
    except json.JSONDecodeError as error:
        raise CleanupError(
            f"Unable to parse {secret_file}: {error}"
        ) from error

    username = str(
        payload.get("username", "")
    ).strip()

    password = str(
        payload.get("password", "")
    )

    if not username or not password:
        raise CleanupError(
            f"Missing qBittorrent credentials in {secret_file}"
        )

    return username, password


class SonarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
    ) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}/api/v3{path}",
            headers=self.headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=60,
            ) as response:
                body = response.read()

                if not body:
                    return None

                return json.loads(body)
        except urllib.error.HTTPError as error:
            body = error.read().decode(
                "utf-8",
                errors="replace",
            )

            raise CleanupError(
                f"{method} {path} failed with HTTP "
                f"{error.code}: {body}"
            ) from error
        except urllib.error.URLError as error:
            raise CleanupError(
                f"{method} {path} failed: {error.reason}"
            ) from error

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def delete(self, path: str) -> None:
        self.request("DELETE", path)


class QBittorrentClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

        cookie_jar = http.cookiejar.CookieJar()

        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(
                cookie_jar
            )
        )

        self.headers = {
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "User-Agent": "homelab-cleanup/1.0",
        }

    def request(
        self,
        method: str,
        path: str,
        form: dict[str, Any] | None = None,
    ) -> bytes:
        data = None

        if form is not None:
            normalized = {
                key: (
                    json.dumps(value)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                for key, value in form.items()
            }

            data = urllib.parse.urlencode(
                normalized
            ).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=self.headers,
            method=method,
        )

        try:
            with self.opener.open(
                request,
                timeout=30,
            ) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            body = error.read().decode(
                "utf-8",
                errors="replace",
            )

            raise CleanupError(
                f"{method} {path} failed with HTTP "
                f"{error.code}: {body}"
            ) from error
        except urllib.error.URLError as error:
            raise CleanupError(
                f"{method} {path} failed: {error.reason}"
            ) from error

    def login(self) -> None:
        body = self.request(
            "POST",
            "/api/v2/auth/login",
            {
                "username": self.username,
                "password": self.password,
            },
        ).decode("utf-8")

        if body and body != "Ok.":
            raise CleanupError(
                f"qBittorrent authentication failed: {body}"
            )

    def get_json(self, path: str) -> Any:
        body = self.request("GET", path)

        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise CleanupError(
                f"Invalid JSON returned by {path}"
            ) from error

    def post_form(
        self,
        path: str,
        form: dict[str, Any],
    ) -> None:
        self.request(
            "POST",
            path,
            form,
        )


def queue_warning_messages(
    queue_item: dict[str, Any],
) -> list[str]:
    messages: list[str] = []

    for status_message in queue_item.get(
        "statusMessages",
        [],
    ):
        for message in status_message.get(
            "messages",
            [],
        ):
            messages.append(
                str(message)
            )

    return messages


def has_safe_warning(
    queue_item: dict[str, Any],
) -> bool:
    messages = queue_warning_messages(
        queue_item
    )

    return any(
        marker in message
        for marker in SAFE_WARNING_MARKERS
        for message in messages
    )


def torrent_is_safe_to_remove(
    torrent: dict[str, Any],
) -> tuple[bool, str]:
    progress = float(
        torrent.get("progress", 0)
        or 0
    )

    amount_left = int(
        torrent.get("amount_left", 0)
        or 0
    )

    force_start = bool(
        torrent.get("force_start", False)
    )

    state = str(
        torrent.get("state", "")
    )

    category = str(
        torrent.get("category", "")
    )

    seeding_seconds = int(
        torrent.get("seeding_time", 0)
        or 0
    )

    seeding_minutes = (
        seeding_seconds / 60
    )

    if category != "tv":
        return False, (
            f"category is {category!r}, not 'tv'"
        )

    if progress < 1:
        return False, "torrent is not complete"

    if amount_left != 0:
        return False, (
            f"amount_left is {amount_left}"
        )

    if force_start:
        return False, "Force Start is enabled"

    if state not in SAFE_TORRENT_STATES:
        return False, (
            f"state {state!r} is not safe"
        )

    if seeding_minutes < MINIMUM_SEEDING_MINUTES:
        return False, (
            f"seeded only {seeding_minutes:.1f} minutes"
        )

    return True, "safe"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clean completed Sonarr downloads that can no longer "
            "be imported because they are not Custom Format upgrades."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned without deleting anything.",
    )

    parser.add_argument(
        "--sonarr-url",
        default=DEFAULT_SONARR_URL,
    )

    parser.add_argument(
        "--sonarr-config",
        default=DEFAULT_SONARR_CONFIG,
    )

    parser.add_argument(
        "--qbittorrent-url",
        default=DEFAULT_QBITTORRENT_URL,
    )

    parser.add_argument(
        "--qbittorrent-secret",
        default=DEFAULT_QBITTORRENT_SECRET,
    )

    args = parser.parse_args()

    api_key = read_sonarr_api_key(
        Path(args.sonarr_config)
    )

    username, password = (
        read_qbittorrent_credentials(
            Path(args.qbittorrent_secret)
        )
    )

    sonarr = SonarrClient(
        args.sonarr_url,
        api_key,
    )

    qbittorrent = QBittorrentClient(
        args.qbittorrent_url,
        username,
        password,
    )

    qbittorrent.login()

    queue = sonarr.get(
        "/queue?"
        + urllib.parse.urlencode(
            {
                "page": 1,
                "pageSize": 500,
                "includeUnknownSeriesItems": "true",
            }
        )
    )

    torrents = qbittorrent.get_json(
        "/api/v2/torrents/info"
    )

    torrents_by_hash = {
        str(
            torrent.get("hash", "")
        ).upper(): torrent
        for torrent in torrents
    }

    candidates = 0
    cleaned = 0

    for item in queue.get(
        "records",
        [],
    ):
        if item.get("status") != "completed":
            continue

        if (
            item.get("trackedDownloadState")
            != "importPending"
        ):
            continue

        if (
            item.get("trackedDownloadStatus")
            != "warning"
        ):
            continue

        if not has_safe_warning(item):
            continue

        download_id = str(
            item.get("downloadId", "")
        ).upper()

        if not download_id:
            continue

        torrent = torrents_by_hash.get(
            download_id
        )

        if torrent is None:
            print(
                "SKIP: qBittorrent torrent not found:"
            )
            print(
                f"  {item.get('title', '')}"
            )
            continue

        safe, reason = (
            torrent_is_safe_to_remove(
                torrent
            )
        )

        if not safe:
            print(
                f"SKIP: {item.get('title', '')}"
            )
            print(
                f"  reason: {reason}"
            )
            continue

        candidates += 1

        seeding_minutes = (
            int(
                torrent.get(
                    "seeding_time",
                    0,
                )
                or 0
            )
            / 60
        )

        prefix = (
            "WOULD CLEAN"
            if args.dry_run
            else "CLEANING"
        )

        print()
        print(
            f"{prefix}: "
            f"{item.get('title', '')}"
        )
        print(
            f"  queue ID: {item.get('id')}"
        )
        print(
            f"  torrent: {torrent.get('name', '')}"
        )
        print(
            f"  state: {torrent.get('state', '')}"
        )
        print(
            f"  seeding: {seeding_minutes:.1f} minutes"
        )

        warnings = queue_warning_messages(
            item
        )

        for warning in warnings:
            print(
                f"  warning: {warning}"
            )

        if args.dry_run:
            continue

        #
        # First delete the torrent and its download data.
        #
        qbittorrent.post_form(
            "/api/v2/torrents/delete",
            {
                "hashes": download_id.lower(),
                "deleteFiles": "true",
            },
        )

        #
        # Then remove Sonarr's stale queue entry.
        # The torrent is already gone, so Sonarr must not try
        # to remove it from the download client again.
        #
        queue_id = int(
            item["id"]
        )

        sonarr.delete(
            f"/queue/{queue_id}?"
            + urllib.parse.urlencode(
                {
                    "removeFromClient": "false",
                    "blocklist": "false",
                    "skipRedownload": "true",
                }
            )
        )

        cleaned += 1

        print("  cleaned")

    print()
    print("=== Summary ===")
    print(
        f"Safe cleanup candidates: {candidates}"
    )

    if args.dry_run:
        print(
            "Dry run: nothing was deleted."
        )
    else:
        print(
            f"Downloads cleaned: {cleaned}"
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CleanupError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
