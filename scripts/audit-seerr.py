#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request


DEFAULT_SEERR_URL = "http://127.0.0.1:5055"
DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
EXPECTED_LIBRARIES = {"Movies", "Kids", "Series"}
EXPECTED_PROFILE = "Latino 1080p"


def detect_jellyfin_external_hostname() -> str:
    hostname = socket.gethostname().split(".", 1)[0].lower()
    if not re.fullmatch(r"[a-z0-9-]+", hostname):
        raise SeerrAuditError(
            "NAS hostname cannot be used for a local URL: "
            + hostname
        )

    try:
        result = subprocess.run(
            ["docker", "port", "jellyfin", "8096/tcp"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SeerrAuditError(
            "Unable to discover Jellyfin's published port."
        ) from error

    for line in result.stdout.splitlines():
        match = re.search(r":(\d+)$", line.strip())
        if match:
            return f"http://{hostname}.local:{match.group(1)}"

    raise SeerrAuditError("Jellyfin has no published TCP port.")


class SeerrAuditError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise SeerrAuditError(
            f"Unable to read {path}: {error}"
        ) from error

    if not isinstance(payload, dict):
        raise SeerrAuditError(
            f"{path} does not contain a JSON object."
        )

    return payload


def read_seerr_api_key(stack_dir: Path) -> str:
    settings = read_json(
        stack_dir / "config/jellyseerr/settings.json"
    )
    api_key = str(
        settings.get("main", {}).get("apiKey", "")
    ).strip()

    if not api_key:
        raise SeerrAuditError(
            "Seerr API key was not found."
        )

    return api_key


def read_arr_api_key(
    stack_dir: Path,
    service: str,
) -> str:
    config_file = (
        stack_dir / "config" / service / "config.xml"
    )

    try:
        root = ET.parse(config_file).getroot()
    except (ET.ParseError, OSError) as error:
        raise SeerrAuditError(
            f"Unable to read {config_file}: {error}"
        ) from error

    api_key = root.findtext("ApiKey", "").strip()

    if not api_key:
        raise SeerrAuditError(
            f"ApiKey not found in {config_file}"
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

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}/api/v1{path}",
            headers=self.headers,
            method="GET",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                payload = response.read()
        except urllib.error.HTTPError as error:
            body = error.read().decode(
                "utf-8",
                errors="replace",
            )
            raise SeerrAuditError(
                f"GET {path} failed with HTTP {error.code}: {body}"
            ) from error
        except urllib.error.URLError as error:
            raise SeerrAuditError(
                f"GET {path} failed: {error}"
            ) from error

        return json.loads(payload)


def validate_libraries(
    client: SeerrClient,
) -> None:
    jellyfin = client.get("/settings/jellyfin")
    libraries = jellyfin.get("libraries")
    if not isinstance(libraries, list):
        raise SeerrAuditError(
            "Unexpected Jellyfin library payload."
        )

    enabled = {
        str(item.get("name"))
        for item in libraries
        if item.get("enabled")
    }

    if enabled != EXPECTED_LIBRARIES:
        raise SeerrAuditError(
            "Unexpected Jellyfin library set: "
            + ", ".join(sorted(enabled))
        )

    print(
        "SEERR JELLYFIN LIBRARIES OK: "
        + ", ".join(sorted(enabled))
    )

    external_hostname = str(
        jellyfin.get("externalHostname", "")
    ).rstrip("/")
    expected_hostname = detect_jellyfin_external_hostname()
    if external_hostname != expected_hostname:
        raise SeerrAuditError(
            "Unexpected Seerr Jellyfin external URL: "
            f"{external_hostname or 'none'}"
        )

    print(
        "SEERR JELLYFIN EXTERNAL URL OK: " + external_hostname
    )


def validate_services(
    client: SeerrClient,
    sonarr_api_key: str,
    radarr_api_key: str,
) -> None:
    sonarr = client.get("/settings/sonarr")
    radarr = client.get("/settings/radarr")

    if not isinstance(sonarr, list) or not isinstance(
        radarr,
        list,
    ):
        raise SeerrAuditError(
            "Unexpected Seerr service settings payload."
        )

    sonarr_main = next(
        (item for item in sonarr if item.get("name") == "Sonarr Main"),
        None,
    )
    if sonarr_main is None:
        raise SeerrAuditError("Sonarr Main not found in Seerr.")

    if sonarr_main.get("activeProfileName") != EXPECTED_PROFILE:
        raise SeerrAuditError(
            "Unexpected Sonarr profile in Seerr: "
            f"{sonarr_main.get('activeProfileName')}"
        )

    if sonarr_main.get("activeDirectory") != "/data/Media/TV Shows":
        raise SeerrAuditError(
            "Unexpected Sonarr root in Seerr: "
            f"{sonarr_main.get('activeDirectory')}"
        )

    if sonarr_main.get("apiKey") != sonarr_api_key:
        raise SeerrAuditError(
            "Seerr Sonarr API key does not match live Sonarr config."
        )

    radarr_movies = next(
        (
            item
            for item in radarr
            if item.get("name") == "Radarr Movies"
        ),
        None,
    )
    radarr_kids = next(
        (
            item
            for item in radarr
            if item.get("name") == "Radarr Kids Movies"
        ),
        None,
    )

    if radarr_movies is None or radarr_kids is None:
        raise SeerrAuditError(
            "Expected Radarr Movies and Radarr Kids Movies in Seerr."
        )

    for item, expected_directory, default in (
        (radarr_movies, "/data/Media/Movies", True),
        (radarr_kids, "/data/Media/Kids Movies", False),
    ):
        if item.get("activeProfileName") != EXPECTED_PROFILE:
            raise SeerrAuditError(
                f"Unexpected profile for {item.get('name')}: "
                f"{item.get('activeProfileName')}"
            )
        if item.get("activeDirectory") != expected_directory:
            raise SeerrAuditError(
                f"Unexpected root for {item.get('name')}: "
                f"{item.get('activeDirectory')}"
            )
        if bool(item.get("isDefault")) != default:
            raise SeerrAuditError(
                f"Unexpected default flag for {item.get('name')}."
            )
        if item.get("apiKey") != radarr_api_key:
            raise SeerrAuditError(
                f"Seerr {item.get('name')} API key does not match live Radarr config."
            )

    print("SEERR SONARR/RADARR ROUTING OK")


def validate_public(
    client: SeerrClient,
) -> None:
    public = client.get("/settings/public")
    if not public.get("initialized"):
        raise SeerrAuditError("Seerr is not initialized.")
    if public.get("mediaServerType") != 2:
        raise SeerrAuditError(
            f"Unexpected Seerr media server type: {public.get('mediaServerType')}"
        )
    print("SEERR PUBLIC STATE OK")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit live Seerr configuration."
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
    args = parser.parse_args()

    client = SeerrClient(
        args.url,
        read_seerr_api_key(args.stack_dir),
    )
    validate_public(client)
    validate_libraries(client)
    validate_services(
        client,
        read_arr_api_key(args.stack_dir, "sonarr"),
        read_arr_api_key(args.stack_dir, "radarr"),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SeerrAuditError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
