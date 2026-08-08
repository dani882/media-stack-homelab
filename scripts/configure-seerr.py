#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_SEERR_URL = "http://127.0.0.1:5055"
DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")

JELLYFIN_MEDIA_SERVER_TYPE = 2

JELLYFIN_LIBRARIES = (
    "Movies",
    "Kids",
    "Series",
)

PROFILE_NAME = "Latino 1080p"

SONARR_NAME = "Sonarr Main"
SONARR_HOST = "sonarr"
SONARR_PORT = 8989
SONARR_ROOT = "/media/TV Shows"

RADARR_HOST = "radarr"
RADARR_PORT = 7878

RADARR_INSTANCES = (
    {
        "name": "Radarr Movies",
        "directory": "/media/Movies",
        "isDefault": True,
    },
    {
        "name": "Radarr Kids Movies",
        "directory": "/media/Kids Movies",
        "isDefault": False,
    },
)


class SeerrError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise SeerrError(
            f"Unable to read {path}: {error}"
        ) from error

    if not isinstance(payload, dict):
        raise SeerrError(
            f"{path} does not contain a JSON object."
        )

    return payload


def read_seerr_api_key(stack_dir: Path) -> str:
    settings_file = (
        stack_dir
        / "config"
        / "jellyseerr"
        / "settings.json"
    )

    settings = read_json(settings_file)

    api_key = str(
        settings.get("main", {}).get("apiKey", "")
    ).strip()

    if not api_key:
        raise SeerrError(
            f"Seerr API key not found in {settings_file}"
        )

    return api_key


def read_arr_api_key(
    stack_dir: Path,
    service: str,
) -> str:
    config_file = (
        stack_dir
        / "config"
        / service
        / "config.xml"
    )

    try:
        root = ET.parse(config_file).getroot()
    except (ET.ParseError, OSError) as error:
        raise SeerrError(
            f"Unable to read {service} configuration "
            f"{config_file}: {error}"
        ) from error

    api_key = root.findtext("ApiKey", "").strip()

    if not api_key:
        raise SeerrError(
            f"ApiKey was not found in {config_file}"
        )

    return api_key


class SeerrClient:
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
        payload: dict[str, Any] | None = None,
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

            raise SeerrError(
                f"{method} {path} failed with HTTP "
                f"{error.code}:\n{response_body}"
            ) from error

        except urllib.error.URLError as error:
            raise SeerrError(
                f"{method} {path} failed: {error}"
            ) from error

        except (ConnectionError, OSError) as error:
            raise SeerrError(
                f"{method} {path} failed: {error}"
            ) from error

    def wait_until_ready(
        self,
        attempts: int = 30,
    ) -> dict[str, Any]:
        for attempt in range(1, attempts + 1):
            try:
                public = self.request(
                    "GET",
                    "/settings/public",
                )

                print(
                    "Seerr is ready. "
                    f"initialized="
                    f"{public.get('initialized', False)} "
                    f"mediaServerType="
                    f"{public.get('mediaServerType')}"
                )

                return public

            except SeerrError:
                if attempt == attempts:
                    raise

                time.sleep(2)

        raise SeerrError(
            "Seerr did not become ready."
        )


def find_profile(
    probe: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    for profile in probe.get("profiles", []):
        if profile.get("name") == name:
            return profile

    available = ", ".join(
        str(item.get("name"))
        for item in probe.get("profiles", [])
    )

    raise SeerrError(
        f"Profile not found: {name}. "
        f"Available profiles: {available}"
    )


def find_root_folder(
    probe: dict[str, Any],
    path: str,
) -> dict[str, Any]:
    for folder in probe.get("rootFolders", []):
        if folder.get("path") == path:
            return folder

    available = ", ".join(
        str(item.get("path"))
        for item in probe.get("rootFolders", [])
    )

    raise SeerrError(
        f"Root folder not found: {path}. "
        f"Available root folders: {available}"
    )


def test_arr(
    client: SeerrClient,
    service: str,
    hostname: str,
    port: int,
    api_key: str,
) -> dict[str, Any]:
    print(f"Testing {service.capitalize()} connection...")

    result = client.request(
        "POST",
        f"/settings/{service}/test",
        {
            "hostname": hostname,
            "port": port,
            "apiKey": api_key,
            "useSsl": False,
            "baseUrl": "",
        },
    )

    print(
        f"{service.capitalize()} connection OK."
    )

    return result


def configure_jellyfin_libraries(
    client: SeerrClient,
    dry_run: bool,
) -> None:
    libraries = client.request(
        "GET",
        "/settings/jellyfin/library?sync=true",
    )

    if not isinstance(libraries, list):
        raise SeerrError(
            "Unexpected Jellyfin library response."
        )

    by_name = {
        str(library.get("name")): library
        for library in libraries
    }

    missing = [
        name
        for name in JELLYFIN_LIBRARIES
        if name not in by_name
    ]

    if missing:
        raise SeerrError(
            "Jellyfin libraries not found: "
            + ", ".join(missing)
        )

    desired_ids = [
        str(by_name[name]["id"])
        for name in JELLYFIN_LIBRARIES
    ]

    enabled_names = {
        str(item.get("name"))
        for item in libraries
        if item.get("enabled")
    }

    desired_names = set(JELLYFIN_LIBRARIES)

    if enabled_names == desired_names:
        print(
            "JELLYFIN LIBRARIES OK: "
            + ", ".join(JELLYFIN_LIBRARIES)
        )
        return

    if dry_run:
        print(
            "WOULD ENABLE JELLYFIN LIBRARIES: "
            + ", ".join(JELLYFIN_LIBRARIES)
        )
        return

    query = urllib.parse.urlencode(
        {
            "sync": "true",
            "enable": ",".join(desired_ids),
        },
        safe=",",
    )

    client.request(
        "GET",
        f"/settings/jellyfin/library?{query}",
    )

    persisted = client.request(
        "GET",
        "/settings/jellyfin/library",
    )

    if not isinstance(persisted, list):
        raise SeerrError(
            "Unexpected persisted Jellyfin library response."
        )

    persisted_names = {
        str(item.get("name"))
        for item in persisted
        if item.get("enabled")
    }

    if persisted_names == desired_names:
        print(
            "JELLYFIN LIBRARIES OK: "
            + ", ".join(JELLYFIN_LIBRARIES)
        )
        return

    print(
        "WARNING: Seerr accepted the Jellyfin library "
        "update but did not persist it."
    )
    print(
        "Expected: "
        + ", ".join(JELLYFIN_LIBRARIES)
    )
    print(
        "Persisted: "
        + (
            ", ".join(sorted(persisted_names))
            if persisted_names
            else "none"
        )
    )


def managed_service_matches(
    current: dict[str, Any],
    desired: dict[str, Any],
) -> bool:
    keys = (
        "name",
        "hostname",
        "port",
        "useSsl",
        "baseUrl",
        "activeProfileId",
        "activeProfileName",
        "activeDirectory",
        "is4k",
        "isDefault",
        "syncEnabled",
        "preventSearch",
    )

    for key in keys:
        if current.get(key) != desired.get(key):
            return False

    for key in (
        "enableSeasonFolders",
        "minimumAvailability",
    ):
        if key in desired:
            if current.get(key) != desired.get(key):
                return False

    return True


def reconcile_service(
    client: SeerrClient,
    service: str,
    desired: dict[str, Any],
    dry_run: bool,
) -> None:
    existing = client.request(
        "GET",
        f"/settings/{service}",
    )

    if not isinstance(existing, list):
        raise SeerrError(
            f"Unexpected {service} settings response."
        )

    current = next(
        (
            item
            for item in existing
            if item.get("name") == desired["name"]
        ),
        None,
    )

    label = desired["name"]

    if current is None:
        if dry_run:
            print(f"WOULD CREATE: {label}")
            return

        result = client.request(
            "POST",
            f"/settings/{service}",
            desired,
        )

        print(
            f"CREATED: {label} "
            f"ID={result.get('id')}"
        )
        return

    if managed_service_matches(
        current,
        desired,
    ):
        print(
            f"SERVICE OK: {label} "
            f"ID={current.get('id')}"
        )
        return

    if dry_run:
        print(
            f"WOULD UPDATE: {label} "
            f"ID={current.get('id')}"
        )
        return

    result = client.request(
        "PUT",
        f"/settings/{service}/{current['id']}",
        desired,
    )

    print(
        f"UPDATED: {label} "
        f"ID={result.get('id')}"
    )


def build_sonarr_settings(
    api_key: str,
    probe: dict[str, Any],
) -> dict[str, Any]:
    profile = find_profile(
        probe,
        PROFILE_NAME,
    )

    folder = find_root_folder(
        probe,
        SONARR_ROOT,
    )

    return {
        "name": SONARR_NAME,
        "hostname": SONARR_HOST,
        "port": SONARR_PORT,
        "apiKey": api_key,
        "useSsl": False,
        "baseUrl": "",
        "activeProfileId": profile["id"],
        "activeProfileName": profile["name"],
        "activeDirectory": folder["path"],
        "activeLanguageProfileId": 1,
        "activeAnimeProfileId": None,
        "activeAnimeLanguageProfileId": None,
        "activeAnimeProfileName": None,
        "activeAnimeDirectory": None,
        "is4k": False,
        "enableSeasonFolders": True,
        "isDefault": True,
        "externalUrl": "",
        "syncEnabled": True,
        "preventSearch": False,
    }


def build_radarr_settings(
    api_key: str,
    probe: dict[str, Any],
    instance: dict[str, Any],
) -> dict[str, Any]:
    profile = find_profile(
        probe,
        PROFILE_NAME,
    )

    folder = find_root_folder(
        probe,
        str(instance["directory"]),
    )

    return {
        "name": instance["name"],
        "hostname": RADARR_HOST,
        "port": RADARR_PORT,
        "apiKey": api_key,
        "useSsl": False,
        "baseUrl": "",
        "activeProfileId": profile["id"],
        "activeProfileName": profile["name"],
        "activeDirectory": folder["path"],
        "is4k": False,
        "minimumAvailability": "released",
        "isDefault": instance["isDefault"],
        "externalUrl": "",
        "syncEnabled": True,
        "preventSearch": False,
    }


def initialize_seerr(
    client: SeerrClient,
    public: dict[str, Any],
    dry_run: bool,
) -> None:
    if public.get("initialized"):
        print("SEERR INITIALIZATION OK")
        return

    if dry_run:
        print("WOULD INITIALIZE SEERR")
        return

    result = client.request(
        "POST",
        "/settings/initialize",
    )

    if not result.get("initialized"):
        raise SeerrError(
            "Seerr initialization did not complete."
        )

    print("INITIALIZED SEERR")


def print_summary(
    client: SeerrClient,
) -> None:
    public = client.request(
        "GET",
        "/settings/public",
    )
    sonarr = client.request(
        "GET",
        "/settings/sonarr",
    )
    radarr = client.request(
        "GET",
        "/settings/radarr",
    )
    libraries = client.request(
        "GET",
        "/settings/jellyfin/library",
    )

    enabled_libraries = [
        item.get("name")
        for item in libraries
        if item.get("enabled")
    ]

    print()
    print("Seerr configuration summary:")
    print(
        f"Initialized: "
        f"{'yes' if public.get('initialized') else 'no'}"
    )
    print(
        f"Media server type: "
        f"{public.get('mediaServerType')}"
    )
    print(
        "Jellyfin libraries: "
        + (
            ", ".join(enabled_libraries)
            if enabled_libraries
            else "none enabled"
        )
    )
    print(
        "Sonarr instances: "
        + ", ".join(
            item.get("name", "unknown")
            for item in sonarr
        )
    )
    print(
        "Radarr instances: "
        + ", ".join(
            item.get("name", "unknown")
            for item in radarr
        )
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Seerr."
    )

    parser.add_argument(
        "--url",
        default=DEFAULT_SEERR_URL,
    )

    parser.add_argument(
        "--stack-dir",
        type=Path,
        default=DEFAULT_STACK_DIR,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show intended changes without applying them."
        ),
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    try:
        seerr_api_key = read_seerr_api_key(
            arguments.stack_dir
        )

        sonarr_api_key = read_arr_api_key(
            arguments.stack_dir,
            "sonarr",
        )

        radarr_api_key = read_arr_api_key(
            arguments.stack_dir,
            "radarr",
        )

        client = SeerrClient(
            arguments.url,
            seerr_api_key,
        )

        public = client.wait_until_ready()

        if (
            public.get("mediaServerType")
            != JELLYFIN_MEDIA_SERVER_TYPE
        ):
            raise SeerrError(
                "Seerr has not been bootstrapped with "
                "Jellyfin. Complete the initial Jellyfin "
                "administrator login first."
            )

        configure_jellyfin_libraries(
            client,
            arguments.dry_run,
        )

        sonarr_probe = test_arr(
            client,
            "sonarr",
            SONARR_HOST,
            SONARR_PORT,
            sonarr_api_key,
        )

        sonarr_settings = build_sonarr_settings(
            sonarr_api_key,
            sonarr_probe,
        )

        reconcile_service(
            client,
            "sonarr",
            sonarr_settings,
            arguments.dry_run,
        )

        radarr_probe = test_arr(
            client,
            "radarr",
            RADARR_HOST,
            RADARR_PORT,
            radarr_api_key,
        )

        for instance in RADARR_INSTANCES:
            radarr_settings = build_radarr_settings(
                radarr_api_key,
                radarr_probe,
                instance,
            )

            reconcile_service(
                client,
                "radarr",
                radarr_settings,
                arguments.dry_run,
            )

        initialize_seerr(
            client,
            public,
            arguments.dry_run,
        )

        if not arguments.dry_run:
            print_summary(client)

        return 0

    except SeerrError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
