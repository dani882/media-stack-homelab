#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SENSITIVE_FIELDS = {
    "apiKey",
    "username",
    "password",
}


class ServarrError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppConfig:
    name: str
    base_url: str
    config_file: Path
    settings_dir: Path


class ApiClient:
    def __init__(self, base_url: str, api_key: str) -> None:
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
            data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=self.headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else None

        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise ServarrError(
                f"{method} {path} failed with HTTP "
                f"{error.code}:\n{body}"
            ) from error

        except urllib.error.URLError as error:
            raise ServarrError(
                f"{method} {path} failed: {error.reason}"
            ) from error


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Sonarr and Radarr application settings."
    )
    parser.add_argument(
        "--stack-dir",
        default="/volume1/docker/media-stack",
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
        raise ServarrError(
            f"Unable to read {path}: {error}"
        ) from error


def read_api_key(config_file: Path) -> str:
    try:
        root = ET.parse(config_file).getroot()
    except (ET.ParseError, OSError) as error:
        raise ServarrError(
            f"Unable to read {config_file}: {error}"
        ) from error

    element = root.find("ApiKey")

    if element is None or not element.text:
        raise ServarrError(
            f"No ApiKey found in {config_file}"
        )

    return element.text.strip()


def wait_until_ready(
    client: ApiClient,
    app_name: str,
    attempts: int = 30,
    delay_seconds: int = 2,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            status = client.request(
                "GET",
                "/api/v3/system/status",
            )
            print(
                f"{app_name} is ready. "
                f"Version: {status.get('version', 'unknown')}"
            )
            return
        except ServarrError:
            if attempt == attempts:
                raise
            time.sleep(delay_seconds)


def field_map(item: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        field["name"]: field
        for field in item.get("fields", [])
        if "name" in field
    }


def preserve_sensitive_fields(
    desired: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(desired)
    payload["id"] = current["id"]

    desired_fields = field_map(payload)
    current_fields = field_map(current)

    for name in SENSITIVE_FIELDS:
        desired_field = desired_fields.get(name)
        current_field = current_fields.get(name)

        if desired_field is None or current_field is None:
            continue

        desired_field["value"] = current_field.get("value")

    return payload



def comparable_download_client(
    payload: dict[str, Any],
) -> dict[str, Any]:
    managed_keys = (
        "name",
        "enable",
        "priority",
        "removeCompletedDownloads",
        "removeFailedDownloads",
        "implementation",
        "configContract",
        "protocol",
        "tags",
    )

    comparable = {
        key: payload.get(key)
        for key in managed_keys
        if key in payload
    }

    comparable["fields"] = sorted(
        (
            {
                "name": field["name"],
                "value": field.get("value"),
            }
            for field in payload.get("fields", [])
            if field.get("name")
            and "value" in field
            and field.get("value") is not None
        ),
        key=lambda field: field["name"],
    )

    return comparable


def configure_download_clients(
    client: ApiClient,
    settings_dir: Path,
    dry_run: bool,
) -> None:
    desired_clients = load_json(
        settings_dir / "download-clients.json"
    )
    current_clients = client.request(
        "GET",
        "/api/v3/downloadclient",
    )

    current_by_name = {
        item["name"]: item
        for item in current_clients
    }

    for desired in desired_clients:
        name = desired["name"]
        current = current_by_name.get(name)

        if current is None:
            raise ServarrError(
                f"Download client '{name}' does not exist. "
                "Creation requires credentials that are intentionally "
                "not stored in Git."
            )

        payload = preserve_sensitive_fields(
            desired,
            current,
        )

        current_cmp = comparable_download_client(current)
        desired_cmp = comparable_download_client(payload)

        if current_cmp == desired_cmp:
            print(
                f"DOWNLOAD CLIENT OK: "
                f"ID={current['id']} name={name}"
            )
            continue

        if dry_run:
            print(
                f"WOULD UPDATE DOWNLOAD CLIENT: "
                f"ID={current['id']} name={name}"
            )
            continue

        client.request(
            "PUT",
            f"/api/v3/downloadclient/{current['id']}",
            payload,
        )
        print(
            f"UPDATED DOWNLOAD CLIENT: "
            f"ID={current['id']} name={name}"
        )


def configure_root_folders(
    client: ApiClient,
    settings_dir: Path,
    dry_run: bool,
) -> None:
    desired_folders = load_json(
        settings_dir / "root-folders.json"
    )
    current_folders = client.request(
        "GET",
        "/api/v3/rootfolder",
    )

    current_paths = {
        item["path"]
        for item in current_folders
    }

    for desired in desired_folders:
        path = desired["path"]

        if path in current_paths:
            print(f"ROOT FOLDER OK: {path}")
            continue

        payload = {"path": path}

        if dry_run:
            print(f"WOULD CREATE ROOT FOLDER: {path}")
            continue

        created = client.request(
            "POST",
            "/api/v3/rootfolder",
            payload,
        )
        print(
            f"CREATED ROOT FOLDER: "
            f"ID={created['id']} path={path}"
        )


def configure_singleton(
    client: ApiClient,
    desired_file: Path,
    endpoint: str,
    label: str,
    dry_run: bool,
) -> None:
    desired = load_json(desired_file)
    current = client.request("GET", endpoint)

    payload = dict(desired)
    payload["id"] = current["id"]

    comparable_current = dict(current)
    comparable_current.pop("id", None)

    if comparable_current == desired:
        print(f"{label} already correct")
        return

    if dry_run:
        print(f"WOULD UPDATE {label}")
        return

    client.request(
        "PUT",
        f"{endpoint}/{current['id']}",
        payload,
    )
    print(f"UPDATED {label}")


def configure_app(
    app: AppConfig,
    dry_run: bool,
) -> None:
    api_key = read_api_key(app.config_file)
    client = ApiClient(app.base_url, api_key)

    print()
    print(f"=== {app.name} settings ===")

    wait_until_ready(client, app.name)

    configure_download_clients(
        client,
        app.settings_dir,
        dry_run,
    )

    configure_root_folders(
        client,
        app.settings_dir,
        dry_run,
    )

    configure_singleton(
        client,
        app.settings_dir / "naming.json",
        "/api/v3/config/naming",
        "naming configuration",
        dry_run,
    )

    configure_singleton(
        client,
        app.settings_dir / "media-management.json",
        "/api/v3/config/mediamanagement",
        "media-management configuration",
        dry_run,
    )


def main() -> int:
    arguments = parse_arguments()
    stack_dir = Path(arguments.stack_dir)

    apps = [
        AppConfig(
            name="Sonarr",
            base_url="http://127.0.0.1:8989",
            config_file=(
                stack_dir / "config/sonarr/config.xml"
            ),
            settings_dir=(
                stack_dir / "servarr/sonarr"
            ),
        ),
        AppConfig(
            name="Radarr",
            base_url="http://127.0.0.1:7878",
            config_file=(
                stack_dir / "config/radarr/config.xml"
            ),
            settings_dir=(
                stack_dir / "servarr/radarr"
            ),
        ),
    ]

    try:
        for app in apps:
            configure_app(app, arguments.dry_run)
        return 0

    except ServarrError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
