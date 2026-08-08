#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROFILE_NAME = "Latino 1080p"

SCORES = {
    "[Latino] Spanish Latino": 7000,
    "[Latino] Spanish Latino + English": 7000,
    "[Latino] French Bonus": 250,
    "[Audio] Audio Description": -10000,
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
        description="Configure Sonarr and Radarr Latino custom formats."
    )
    parser.add_argument(
        "--stack-dir",
        default="/volume1/docker/media-stack",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended changes without writing them.",
    )
    return parser.parse_args()


def load_definitions(path: Path) -> list[dict[str, Any]]:
    data = load_json(path)

    if not isinstance(data, list):
        raise ServarrError(f"Expected a JSON array in {path}")

    return data



def comparable_custom_format(
    payload: dict[str, Any],
) -> dict[str, Any]:
    comparable = dict(payload)
    comparable.pop("id", None)

    return comparable


def configure_custom_formats(
    client: ApiClient,
    definitions: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, int]:
    existing = client.request("GET", "/api/v3/customformat")
    existing_by_name = {
        item["name"]: item
        for item in existing
    }

    ids_by_name: dict[str, int] = {}

    for definition in definitions:
        name = definition["name"]
        current = existing_by_name.get(name)

        if current is None:
            if dry_run:
                print(f"WOULD CREATE: {name}")
                continue

            created = client.request(
                "POST",
                "/api/v3/customformat",
                definition,
            )
            ids_by_name[name] = created["id"]
            print(f"CREATED: ID={created['id']} name={name}")
            continue

        payload = dict(definition)
        payload["id"] = current["id"]

        if (
            comparable_custom_format(current)
            == comparable_custom_format(definition)
        ):
            ids_by_name[name] = current["id"]
            print(
                f"CUSTOM FORMAT OK: "
                f"ID={current['id']} name={name}"
            )
            continue

        if dry_run:
            print(
                f"WOULD UPDATE: "
                f"ID={current['id']} name={name}"
            )
            ids_by_name[name] = current["id"]
            continue

        updated = client.request(
            "PUT",
            f"/api/v3/customformat/{current['id']}",
            payload,
        )
        ids_by_name[name] = updated["id"]
        print(f"UPDATED: ID={updated['id']} name={name}")

    return ids_by_name


def configure_profile_scores(
    client: ApiClient,
    ids_by_name: dict[str, int],
    dry_run: bool,
) -> None:
    profiles = client.request("GET", "/api/v3/qualityprofile")

    profile = next(
        (
            item
            for item in profiles
            if item["name"] == PROFILE_NAME
        ),
        None,
    )

    if profile is None:
        raise ServarrError(
            f"Quality profile not found: {PROFILE_NAME}"
        )

    items_by_format = {
        item["format"]: item
        for item in profile.get("formatItems", [])
    }

    changed = False

    for name, score in SCORES.items():
        custom_format_id = ids_by_name.get(name)
        if custom_format_id is None:
            continue

        item = items_by_format.get(custom_format_id)

        if item is None:
            profile.setdefault("formatItems", []).append(
                {
                    "format": custom_format_id,
                    "name": name,
                    "score": score,
                }
            )
            changed = True
            print(f"ADD SCORE: {name}={score}")
            continue

        if item.get("score") != score:
            print(
                f"UPDATE SCORE: {name} "
                f"{item.get('score')} -> {score}"
            )
            item["score"] = score
            changed = True
        else:
            print(f"SCORE OK: {name}={score}")

    if not changed:
        print(f"Profile already correct: {PROFILE_NAME}")
        return

    if dry_run:
        print(f"WOULD UPDATE PROFILE: {PROFILE_NAME}")
        return

    client.request(
        "PUT",
        f"/api/v3/qualityprofile/{profile['id']}",
        profile,
    )
    print(f"UPDATED PROFILE: {PROFILE_NAME}")


def configure_app(app: AppConfig, dry_run: bool) -> None:
    api_key = read_api_key(app.config_file)
    client = ApiClient(app.base_url, api_key)

    print()
    print(f"=== {app.name} ===")

    wait_until_ready(client, app.name)

    definitions = load_definitions(app.data_path)
    ids_by_name = configure_custom_formats(
        client,
        definitions,
        dry_run,
    )
    configure_profile_scores(
        client,
        ids_by_name,
        dry_run,
    )


def main() -> int:
    arguments = parse_arguments()
    stack_dir = Path(arguments.stack_dir)

    apps = [
        AppConfig(
            name="Sonarr",
            base_url="http://127.0.0.1:8989",
            config_file=stack_dir / "config/sonarr/config.xml",
            data_path=(
                stack_dir
                / "servarr/custom-formats/sonarr-latino.json"
            ),
        ),
        AppConfig(
            name="Radarr",
            base_url="http://127.0.0.1:7878",
            config_file=stack_dir / "config/radarr/config.xml",
            data_path=(
                stack_dir
                / "servarr/custom-formats/radarr-latino.json"
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
