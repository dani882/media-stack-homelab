#!/usr/bin/env python3


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
ARCHIVE_PROFILE_NAME = "Archivo Español"

SCORES = {
    "[Latino] Spanish Latino": 7000,
    "[Latino] Spanish Latino + English": 7000,
    "[Spanish] Castellano": 5000,
    "[Spanish] Castellano + English": 5000,
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
    profile_name: str = PROFILE_NAME,
) -> None:
    profiles = client.request("GET", "/api/v3/qualityprofile")

    profile = next(
        (
            item
            for item in profiles
            if item["name"] == profile_name
        ),
        None,
    )

    if profile is None:
        raise ServarrError(
            f"Quality profile not found: {profile_name}"
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
        print(f"Profile already correct: {profile_name}")
        return

    if dry_run:
        print(f"WOULD UPDATE PROFILE: {profile_name}")
        return

    client.request(
        "PUT",
        f"/api/v3/qualityprofile/{profile['id']}",
        profile,
    )
    print(f"UPDATED PROFILE: {profile_name}")


def configure_archive_profile(
    client: ApiClient,
    ids_by_name: dict[str, int],
    dry_run: bool,
) -> None:
    """Create a Spanish-only legacy-quality lane without weakening defaults."""
    profiles = client.request("GET", "/api/v3/qualityprofile")
    base = next((item for item in profiles if item["name"] == PROFILE_NAME), None)
    archive = next(
        (item for item in profiles if item["name"] == ARCHIVE_PROFILE_NAME),
        None,
    )

    if base is None:
        raise ServarrError(f"Quality profile not found: {PROFILE_NAME}")

    if archive is None:
        archive = json.loads(json.dumps(base))
        archive.pop("id", None)
        archive["name"] = ARCHIVE_PROFILE_NAME
        archive["minFormatScore"] = 5000
        archive["cutoffFormatScore"] = 7000
        for item in archive.get("items", []):
            if item.get("name") in {"WEB 480p", "WEB 720p", "WEB 1080p"}:
                item["allowed"] = True

        if dry_run:
            print(f"WOULD CREATE PROFILE: {ARCHIVE_PROFILE_NAME}")
            return

        archive = client.request("POST", "/api/v3/qualityprofile", archive)
        print(f"CREATED PROFILE: {ARCHIVE_PROFILE_NAME}")
    else:
        changed = False
        for key, value in (("minFormatScore", 5000), ("cutoffFormatScore", 7000)):
            if archive.get(key) != value:
                archive[key] = value
                changed = True
        for item in archive.get("items", []):
            if item.get("name") in {"WEB 480p", "WEB 720p", "WEB 1080p"} and not item.get("allowed"):
                item["allowed"] = True
                changed = True
        if changed:
            if dry_run:
                print(f"WOULD UPDATE PROFILE: {ARCHIVE_PROFILE_NAME}")
            else:
                archive = client.request(
                    "PUT", f"/api/v3/qualityprofile/{archive['id']}", archive
                )
                print(f"UPDATED PROFILE: {ARCHIVE_PROFILE_NAME}")

    # The high minimum score makes English ineligible.  Re-use the same
    # trusted custom formats as the normal profile, while accepting SD/720p
    # Spanish releases for titles that otherwise have no viable source.
    configure_profile_scores(client, ids_by_name, dry_run, ARCHIVE_PROFILE_NAME)


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
    if app.name == "Radarr":
        configure_archive_profile(client, ids_by_name, dry_run)


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
