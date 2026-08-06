#!/usr/bin/env python3

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class QBittorrentError(RuntimeError):
    pass


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
            urllib.request.HTTPCookieProcessor(cookie_jar)
        )

        self.headers = {
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "User-Agent": "homelab-configurator/1.0",
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

            data = urllib.parse.urlencode(normalized).encode("utf-8")

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

            raise QBittorrentError(
                f"{method} {path} failed with HTTP "
                f"{error.code}: {body}"
            ) from error

        except urllib.error.URLError as error:
            raise QBittorrentError(
                f"{method} {path} failed: {error.reason}"
            ) from error

        except (ConnectionError, OSError) as error:
            raise QBittorrentError(
                f"{method} {path} failed: {error}"
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

        # qBittorrent 5.x commonly responds with HTTP 204 and no body.
        # Older versions return HTTP 200 with "Ok.".
        if body and body != "Ok.":
            raise QBittorrentError(
                f"Authentication failed: {body}"
            )

    def get_json(self, path: str) -> Any:
        body = self.request("GET", path)

        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise QBittorrentError(
                f"Invalid JSON returned by {path}"
            ) from error

    def get_text(self, path: str) -> str:
        return self.request(
            "GET",
            path,
        ).decode("utf-8").strip()

    def post_form(
        self,
        path: str,
        form: dict[str, Any],
    ) -> None:
        self.request("POST", path, form)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure qBittorrent."
    )

    parser.add_argument(
        "--stack-dir",
        default="/volume1/docker/media-stack",
    )

    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8888",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended changes without applying them.",
    )

    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise QBittorrentError(
            f"Unable to read {path}: {error}"
        ) from error


def wait_until_ready(
    client: QBittorrentClient,
    attempts: int = 30,
    delay_seconds: int = 2,
) -> str:
    for attempt in range(1, attempts + 1):
        try:
            client.login()
            version = client.get_text("/api/v2/app/version")
            print(f"qBittorrent is ready. Version: {version}")
            return version

        except QBittorrentError:
            if attempt == attempts:
                raise

            time.sleep(delay_seconds)

    raise QBittorrentError("qBittorrent did not become ready.")


def configure_categories(
    client: QBittorrentClient,
    desired_categories: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    current = client.get_json(
        "/api/v2/torrents/categories"
    )

    for desired in desired_categories:
        name = desired["name"]
        save_path = desired["save_path"]

        existing = current.get(name)

        if (
            existing is not None
            and existing.get("savePath", "") == save_path
        ):
            print(
                f"CATEGORY OK: "
                f"{name} -> {save_path}"
            )
            continue

        if existing is None:
            if dry_run:
                print(
                    f"WOULD CREATE CATEGORY: "
                    f"{name} -> {save_path}"
                )
                continue

            client.post_form(
                "/api/v2/torrents/createCategory",
                {
                    "category": name,
                    "savePath": save_path,
                },
            )

            print(
                f"CREATED CATEGORY: "
                f"{name} -> {save_path}"
            )
            continue

        if dry_run:
            print(
                f"WOULD UPDATE CATEGORY: "
                f"{name} -> {save_path}"
            )
            continue

        client.post_form(
            "/api/v2/torrents/editCategory",
            {
                "category": name,
                "savePath": save_path,
            },
        )

        print(
            f"UPDATED CATEGORY: "
            f"{name} -> {save_path}"
        )


def comparable_preferences(
    preferences: dict[str, Any],
    managed_keys: set[str],
) -> dict[str, Any]:
    return {
        key: preferences.get(key)
        for key in sorted(managed_keys)
    }


def configure_preferences(
    client: QBittorrentClient,
    desired: dict[str, Any],
    dry_run: bool,
) -> None:
    current = client.get_json(
        "/api/v2/app/preferences"
    )

    managed_keys = set(desired)

    current_managed = comparable_preferences(
        current,
        managed_keys,
    )

    desired_managed = comparable_preferences(
        desired,
        managed_keys,
    )

    if current_managed == desired_managed:
        print("PREFERENCES OK")
        return

    changed = {
        key: {
            "current": current_managed.get(key),
            "desired": desired_managed.get(key),
        }
        for key in sorted(managed_keys)
        if (
            current_managed.get(key)
            != desired_managed.get(key)
        )
    }

    if dry_run:
        print("WOULD UPDATE PREFERENCES:")
        print(json.dumps(changed, indent=2))
        return

    client.post_form(
        "/api/v2/app/setPreferences",
        {
            "json": json.dumps(desired),
        },
    )

    print("UPDATED PREFERENCES")

    for key, values in changed.items():
        print(
            f"  {key}: "
            f"{values['current']!r} -> "
            f"{values['desired']!r}"
        )


def main() -> int:
    arguments = parse_arguments()
    stack_dir = Path(arguments.stack_dir)

    secret_file = (
        stack_dir / "secrets/qbittorrent.json"
    )

    categories_file = (
        stack_dir / "qbittorrent/categories.json"
    )

    preferences_file = (
        stack_dir / "qbittorrent/preferences.json"
    )

    try:
        secret = load_json(secret_file)
        categories = load_json(categories_file)
        preferences = load_json(preferences_file)

        username = secret.get("username")
        password = secret.get("password")

        if not username or not password:
            raise QBittorrentError(
                f"Missing credentials in {secret_file}"
            )

        if not isinstance(categories, list):
            raise QBittorrentError(
                f"Expected a JSON array in {categories_file}"
            )

        if not isinstance(preferences, dict):
            raise QBittorrentError(
                f"Expected a JSON object in {preferences_file}"
            )

        client = QBittorrentClient(
            arguments.url,
            username,
            password,
        )

        wait_until_ready(client)

        configure_categories(
            client,
            categories,
            arguments.dry_run,
        )

        configure_preferences(
            client,
            preferences,
            arguments.dry_run,
        )

        print()
        print(
            "qBittorrent configuration completed successfully."
        )

        return 0

    except QBittorrentError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
