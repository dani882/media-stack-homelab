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


from servarr_config.common import (
    ApiClient,
    AppConfig,
    ServarrError,
    load_json,
    read_api_key,
    wait_until_ready,
)


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
    data_path: Path,
    dry_run: bool,
) -> None:
    desired_clients = load_json(
        data_path / "download-clients.json"
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
    data_path: Path,
    dry_run: bool,
) -> None:
    desired_folders = load_json(
        data_path / "root-folders.json"
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
        app.data_path,
        dry_run,
    )

    configure_root_folders(
        client,
        app.data_path,
        dry_run,
    )

    configure_singleton(
        client,
        app.data_path / "naming.json",
        "/api/v3/config/naming",
        "naming configuration",
        dry_run,
    )

    configure_singleton(
        client,
        app.data_path / "media-management.json",
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
            data_path=(
                stack_dir / "servarr/sonarr"
            ),
        ),
        AppConfig(
            name="Radarr",
            base_url="http://127.0.0.1:7878",
            config_file=(
                stack_dir / "config/radarr/config.xml"
            ),
            data_path=(
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
