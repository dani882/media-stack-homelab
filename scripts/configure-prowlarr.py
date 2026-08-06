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
from pathlib import Path
from typing import Any


DEFAULT_PROWLARR_URL = "http://127.0.0.1:9696"
DEFAULT_CONFIG_FILE = (
    "/volume1/docker/media-stack/config/prowlarr/config.xml"
)

INDEXERS = [
    {
        "definition": "1337x",
        "enabled": True,
        "priority": 10,
        "minimum_seeders": 5,
        "fields": {
            "baseUrl": "https://1337x.st/",
            "torrentBaseSettings.preferMagnetUrl": True,
            "downloadlink": 1,
            "downloadlink2": 0,
            "sort": 0,
            "type": 1,
        },
    },
    {
        "definition": "Knaben",
        "priority": 15,
        "minimum_seeders": 5,
        "fields": {
            "torrentBaseSettings.preferMagnetUrl": True,
        },
    },
    {
        "definition": "limetorrents",
        "priority": 20,
        "minimum_seeders": 5,
        "fields": {
            "torrentBaseSettings.preferMagnetUrl": True,
        },
    },
    {
        "definition": "torrentdownloads",
        "priority": 25,
        "minimum_seeders": 5,
        "fields": {
            "torrentBaseSettings.preferMagnetUrl": True,
        },
    },
    {
        "definition": "thepiratebay",
        "priority": 30,
        "minimum_seeders": 5,
        "fields": {
            "torrentBaseSettings.preferMagnetUrl": True,
        },
    },
    {
        "definition": "eztv",
        "priority": 35,
        "minimum_seeders": 5,
        "fields": {
            "torrentBaseSettings.preferMagnetUrl": True,
        },
    },
]


class ProwlarrError(RuntimeError):
    pass


def read_api_key(config_file: Path) -> str:
    environment_key = os.environ.get("PROWLARR_KEY", "").strip()

    if environment_key:
        return environment_key

    if not config_file.is_file():
        raise ProwlarrError(
            f"Prowlarr configuration file not found: {config_file}"
        )

    try:
        root = ET.parse(config_file).getroot()
    except ET.ParseError as error:
        raise ProwlarrError(
            f"Unable to parse {config_file}: {error}"
        ) from error

    api_key = root.findtext("ApiKey", "").strip()

    if not api_key:
        raise ProwlarrError(
            f"ApiKey was not found in {config_file}"
        )

    return api_key


class ProwlarrClient:
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
        payload: dict[str, Any] | list[Any] | None = None,
    ) -> Any:
        body = None

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url}/api/v1{path}",
            data=body,
            headers=self.headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=60,
            ) as response:
                content = response.read()

                if not content:
                    return None

                return json.loads(content)
        except urllib.error.HTTPError as error:
            response_body = error.read().decode(
                "utf-8",
                errors="replace",
            )

            raise ProwlarrError(
                f"{method} {path} failed with HTTP "
                f"{error.code}:\n{response_body}"
            ) from error
        except urllib.error.URLError as error:
            raise ProwlarrError(
                f"{method} {path} failed: {error}"
            ) from error
        except (ConnectionError, OSError) as error:
            raise ProwlarrError(
                f"{method} {path} failed: {error}"
            ) from error

    def wait_until_ready(self, attempts: int = 30) -> None:
        for attempt in range(1, attempts + 1):
            try:
                status = self.request("GET", "/system/status")
                version = status.get("version", "unknown")
                print(f"Prowlarr is ready. Version: {version}")
                return
            except ProwlarrError:
                if attempt == attempts:
                    raise

                time.sleep(2)

    def test_indexer(self, payload: dict[str, Any]) -> None:
        self.request("POST", "/indexer/test", payload)


def field_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        field["name"]: field
        for field in payload.get("fields", [])
        if field.get("name")
    }


def apply_field_settings(
    payload: dict[str, Any],
    minimum_seeders: int,
    settings: dict[str, Any],
) -> None:
    fields = field_map(payload)

    desired_settings = {
        "torrentBaseSettings.appMinimumSeeders": minimum_seeders,
        **settings,
    }

    for name, value in desired_settings.items():
        field = fields.get(name)

        if field is None:
            print(
                f"  Warning: field not supported by "
                f"{payload.get('name')}: {name}"
            )
            continue

        field["value"] = value


def normalized_definition(value: str | None) -> str:
    return (value or "").strip().casefold()


def managed_indexer_matches(
    payload: dict[str, Any],
    desired: dict[str, Any],
) -> bool:
    if bool(payload.get("enable")) != desired.get("enabled", True):
        return False

    if int(payload.get("priority") or 0) != desired["priority"]:
        return False

    fields = field_map(payload)

    expected_fields = {
        "torrentBaseSettings.appMinimumSeeders": (
            desired["minimum_seeders"]
        ),
        **desired["fields"],
    }

    for name, expected_value in expected_fields.items():
        field = fields.get(name)

        if field is None:
            continue

        if field.get("value") != expected_value:
            return False

    return True


def configure_indexer(
    client: ProwlarrClient,
    schema_by_definition: dict[str, dict[str, Any]],
    existing_by_definition: dict[str, dict[str, Any]],
    desired: dict[str, Any],
    dry_run: bool,
) -> None:
    definition = desired["definition"]
    normalized = normalized_definition(definition)
    existing = existing_by_definition.get(normalized)
    enabled = desired.get("enabled", True)

    if existing:
        payload = client.request(
            "GET",
            f"/indexer/{existing['id']}",
        )
        action = "UPDATE"
    else:
        if not enabled:
            print(
                f"INDEXER DISABLED: {definition} "
                f"(not configured)"
            )
            return

        schema = schema_by_definition.get(normalized)

        if schema is None:
            print(f"SKIPPED: definition unavailable: {definition}")
            return

        payload = json.loads(json.dumps(schema))
        action = "CREATE"

    name = payload.get("name", definition)

    if not enabled:
        if not payload.get("enable"):
            print(
                f"INDEXER DISABLED: ID={payload['id']} "
                f"name={name}"
            )
            return

        if dry_run:
            print(
                f"WOULD DISABLE INDEXER: "
                f"ID={payload['id']} name={name}"
            )
            return

        payload["enable"] = False

        result = client.request(
            "PUT",
            f"/indexer/{payload['id']}",
            payload,
        )

        print(
            f"DISABLED INDEXER: ID={result['id']} "
            f"name={result['name']}"
        )
        return

    if existing and managed_indexer_matches(payload, desired):
        print(
            f"INDEXER OK: ID={payload['id']} "
            f"name={name} "
            f"priority={payload['priority']}"
        )
        return

    payload["enable"] = True
    payload["priority"] = desired["priority"]

    if int(payload.get("appProfileId") or 0) <= 0:
        payload["appProfileId"] = 1

    apply_field_settings(
        payload,
        desired["minimum_seeders"],
        desired["fields"],
    )

    print(
        f"Testing {name}: priority={desired['priority']}, "
        f"minimum_seeders={desired['minimum_seeders']}"
    )

    try:
        client.test_indexer(payload)
    except ProwlarrError as error:
        print(f"FAILED TEST: {name}")
        print(error)
        return

    if dry_run:
        print(f"DRY RUN: would {action.lower()} {name}")
        return

    if existing:
        result = client.request(
            "PUT",
            f"/indexer/{existing['id']}",
            payload,
        )
    else:
        result = client.request(
            "POST",
            "/indexer",
            payload,
        )

    print(
        f"{action}D: ID={result['id']} "
        f"name={result['name']} "
        f"priority={result['priority']}"
    )


def print_summary(client: ProwlarrClient) -> None:
    indexers = client.request("GET", "/indexer")

    print("\nConfigured indexers:")
    print(f"{'ID':<5} {'Priority':<10} {'Enabled':<9} Name")

    for indexer in sorted(
        indexers,
        key=lambda item: (
            item.get("priority", 50),
            item.get("name", ""),
        ),
    ):
        definition = normalized_definition(
            indexer.get("definitionName")
        )

        configured_definitions = {
            normalized_definition(item["definition"])
            for item in INDEXERS
        }

        if definition not in configured_definitions:
            continue

        enabled = "yes" if indexer.get("enable") else "no"

        print(
            f"{indexer['id']:<5} "
            f"{indexer['priority']:<10} "
            f"{enabled:<9} "
            f"{indexer['name']}"
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Prowlarr public indexers.",
    )

    parser.add_argument(
        "--url",
        default=os.environ.get(
            "PROWLARR_URL",
            DEFAULT_PROWLARR_URL,
        ),
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=Path(
            os.environ.get(
                "PROWLARR_CONFIG_FILE",
                DEFAULT_CONFIG_FILE,
            )
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show intended indexer changes without applying them."
        ),
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    try:
        api_key = read_api_key(arguments.config_file)
        client = ProwlarrClient(arguments.url, api_key)
        client.wait_until_ready()

        schemas = client.request("GET", "/indexer/schema")
        existing = client.request("GET", "/indexer")

        schema_by_definition = {
            normalized_definition(item.get("definitionName")): item
            for item in schemas
        }

        existing_by_definition = {
            normalized_definition(item.get("definitionName")): item
            for item in existing
        }

        for desired in INDEXERS:
            configure_indexer(
                client,
                schema_by_definition,
                existing_by_definition,
                desired,
                arguments.dry_run,
            )

        print_summary(client)
        return 0

    except ProwlarrError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
