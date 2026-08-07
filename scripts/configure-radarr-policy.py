#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_URL = "http://127.0.0.1:7878"
PROFILE_NAME = "Latino 1080p"
# Let Radarr accept the original release language as a fallback.
# Latino preference is enforced through the [Latino] custom formats.
LANGUAGE_NAME = "Original"
QUALITY_NAME = "HDTV-1080p"
MIN_SIZE_MB_PER_MINUTE = 15.0


class RadarrPolicyError(RuntimeError):
    pass


def read_api_key(config_file: Path) -> str:
    environment_key = os.environ.get("RADARR_KEY", "").strip()

    if environment_key:
        return environment_key

    if not config_file.is_file():
        raise RadarrPolicyError(
            f"Radarr configuration file not found: {config_file}"
        )

    try:
        root = ET.parse(config_file).getroot()
    except ET.ParseError as error:
        raise RadarrPolicyError(
            f"Unable to parse Radarr configuration: {error}"
        ) from error

    api_key = (root.findtext("ApiKey") or "").strip()

    if not api_key:
        raise RadarrPolicyError(
            f"Radarr API key not found in {config_file}"
        )

    return api_key


class RadarrClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Accept": "application/json",
            "X-Api-Key": api_key,
        }

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
    ) -> Any:
        body = None
        headers = dict(self.headers)

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{self.base_url}/api/v3{path}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=120,
            ) as response:
                response_body = response.read()

                if not response_body:
                    return None

                return json.loads(response_body)
        except urllib.error.HTTPError as error:
            response_body = error.read().decode(
                "utf-8",
                errors="replace",
            )
            raise RadarrPolicyError(
                f"{method} {path} failed with HTTP "
                f"{error.code}:\n{response_body}"
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise RadarrPolicyError(
                f"{method} {path} failed: {error}"
            ) from error


def find_named(
    items: list[dict[str, Any]],
    name: str,
) -> dict[str, Any]:
    for item in items:
        if item.get("name") == name:
            return item

    raise RadarrPolicyError(f"Unable to find: {name}")


def enable_quality_item(
    items: list[dict[str, Any]],
    quality_name: str,
) -> bool:
    changed = False

    for item in items:
        quality = item.get("quality")

        if isinstance(quality, dict):
            if quality.get("name") == quality_name:
                if item.get("allowed") is not True:
                    item["allowed"] = True
                    changed = True

        nested_items = item.get("items")

        if isinstance(nested_items, list):
            if enable_quality_item(
                nested_items,
                quality_name,
            ):
                changed = True

    return changed


def configure_profile(
    client: RadarrClient,
    dry_run: bool,
) -> None:
    profiles = client.request(
        "GET",
        "/qualityprofile",
    )

    profile_summary = find_named(
        profiles,
        PROFILE_NAME,
    )

    profile_id = int(profile_summary["id"])

    profile = client.request(
        "GET",
        f"/qualityprofile/{profile_id}",
    )

    languages = client.request(
        "GET",
        "/language",
    )

    language = find_named(
        languages,
        LANGUAGE_NAME,
    )

    changes: list[str] = []

    current_language = profile.get("language") or {}

    if current_language.get("id") != language.get("id"):
        changes.append(
            "language: "
            f"{current_language.get('name')} -> {LANGUAGE_NAME}"
        )
        profile["language"] = language

    if enable_quality_item(
        profile.get("items", []),
        QUALITY_NAME,
    ):
        changes.append(f"enabled quality: {QUALITY_NAME}")

    if not changes:
        print("RADARR PROFILE OK")
        return

    if dry_run:
        print("WOULD UPDATE RADARR PROFILE")
        for change in changes:
            print(f"  {change}")
        return

    client.request(
        "PUT",
        f"/qualityprofile/{profile_id}",
        profile,
    )

    print("UPDATED RADARR PROFILE")
    for change in changes:
        print(f"  {change}")


def configure_quality_definition(
    client: RadarrClient,
    dry_run: bool,
) -> None:
    definitions = client.request(
        "GET",
        "/qualitydefinition",
    )

    definition = None

    for item in definitions:
        quality = item.get("quality") or {}

        if quality.get("name") == QUALITY_NAME:
            definition = item
            break

    if definition is None:
        raise RadarrPolicyError(
            f"Quality definition not found: {QUALITY_NAME}"
        )

    current_min_size = float(
        definition.get("minSize") or 0
    )

    if current_min_size == MIN_SIZE_MB_PER_MINUTE:
        print(
            f"QUALITY DEFINITION OK: "
            f"{QUALITY_NAME} minSize={current_min_size:g}"
        )
        return

    print(
        f"{'WOULD UPDATE' if dry_run else 'UPDATING'} "
        f"QUALITY DEFINITION: {QUALITY_NAME}"
    )
    print(
        f"  minSize: {current_min_size:g} "
        f"-> {MIN_SIZE_MB_PER_MINUTE:g}"
    )

    if dry_run:
        return

    definition["minSize"] = MIN_SIZE_MB_PER_MINUTE

    client.request(
        "PUT",
        f"/qualitydefinition/{definition['id']}",
        definition,
    )

    print(
        f"UPDATED QUALITY DEFINITION: "
        f"{QUALITY_NAME} "
        f"minSize={MIN_SIZE_MB_PER_MINUTE:g}"
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enforce the post-Recyclarr Radarr Latino policy."
        ),
    )

    parser.add_argument(
        "--stack-dir",
        type=Path,
        default=DEFAULT_STACK_DIR,
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended changes without applying them.",
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    try:
        api_key = read_api_key(
            arguments.stack_dir / "config/radarr/config.xml"
        )

        client = RadarrClient(
            arguments.url,
            api_key,
        )

        configure_profile(
            client,
            arguments.dry_run,
        )

        configure_quality_definition(
            client,
            arguments.dry_run,
        )

        print()
        print("Radarr Latino policy completed successfully.")
        return 0

    except RadarrPolicyError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
