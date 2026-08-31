#!/usr/bin/env python3

from __future__ import annotations

import argparse
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "http://127.0.0.1:6868"
DEFAULT_SECRET_FILE = Path(
    "/volume1/docker/media-stack/secrets/profilarr-admin.txt"
)
DEFAULT_CONFIG = {
    "database": "Dictionarry",
    "instances": [
        {
            "name": "Sonarr Main",
            "qualityProfiles": [
                "1080p Balanced",
            ],
        },
        {
            "name": "Radarr Movies",
            "qualityProfiles": [
                "1080p Balanced",
            ],
        },
    ],
}


class ProfilarrSyncError(RuntimeError):
    pass


def load_credentials(
    secret_file: Path,
) -> tuple[str, str]:
    if not secret_file.exists():
        raise ProfilarrSyncError(
            f"Missing Profilarr credentials file: {secret_file}"
        )

    values: dict[str, str] = {}

    for raw_line in secret_file.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    username = values.get("username", "")
    password = values.get("password", "")

    if not username or not password:
        raise ProfilarrSyncError(
            f"Incomplete Profilarr credentials in {secret_file}"
        )

    return username, password


def load_config(config_path: Path | None) -> dict:
    if config_path is None:
        return DEFAULT_CONFIG

    try:
        loaded = json.loads(
            config_path.read_text(encoding="utf-8")
        )
    except FileNotFoundError as error:
        raise ProfilarrSyncError(
            f"Missing Profilarr sync config: {config_path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ProfilarrSyncError(
            f"Invalid JSON in Profilarr sync config {config_path}: "
            f"{error}"
        ) from error

    if not isinstance(loaded, dict):
        raise ProfilarrSyncError(
            "Profilarr sync config must be a JSON object."
        )

    return loaded


def validate_config(
    config: dict,
) -> tuple[str, list[dict[str, object]]]:
    database_name = config.get("database")
    instances = config.get("instances")

    if not isinstance(database_name, str) or not database_name.strip():
        raise ProfilarrSyncError(
            "Profilarr sync config must define a non-empty "
            '"database" string.'
        )

    if not isinstance(instances, list) or not instances:
        raise ProfilarrSyncError(
            "Profilarr sync config must define a non-empty "
            '"instances" list.'
        )

    normalized: list[dict[str, object]] = []

    for index, item in enumerate(instances, start=1):
        if not isinstance(item, dict):
            raise ProfilarrSyncError(
                f"Instance entry #{index} must be an object."
            )

        name = item.get("name")
        quality_profiles = item.get("qualityProfiles")

        if not isinstance(name, str) or not name.strip():
            raise ProfilarrSyncError(
                f"Instance entry #{index} is missing a valid name."
            )

        if (
            not isinstance(quality_profiles, list)
            or not quality_profiles
            or not all(
                isinstance(profile, str) and profile.strip()
                for profile in quality_profiles
            )
        ):
            raise ProfilarrSyncError(
                f'Instance "{name}" must define a non-empty '
                '"qualityProfiles" string list.'
            )

        normalized.append(
            {
                "name": name.strip(),
                "qualityProfiles": [
                    profile.strip()
                    for profile in quality_profiles
                ],
            }
        )

    return database_name.strip(), normalized


def build_opener() -> urllib.request.OpenerDirector:
    cookie_jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar)
    )


def urlopen_json(
    opener: urllib.request.OpenerDirector,
    request: urllib.request.Request,
) -> object:
    try:
        with opener.open(request, timeout=30) as response:
            payload = response.read().decode(
                "utf-8",
                errors="replace",
            )
    except urllib.error.HTTPError as error:
        body = error.read().decode(
            "utf-8",
            errors="replace",
        )
        raise ProfilarrSyncError(
            f"Profilarr HTTP {error.code} for {request.full_url}: "
            f"{body}"
        ) from error
    except urllib.error.URLError as error:
        raise ProfilarrSyncError(
            f"Unable to reach Profilarr at {request.full_url}: {error}"
        ) from error

    try:
        return json.loads(payload)
    except json.JSONDecodeError as error:
        raise ProfilarrSyncError(
            f"Expected JSON from {request.full_url}, got: {payload[:200]}"
        ) from error


def get_json(
    opener: urllib.request.OpenerDirector,
    url: str,
) -> object:
    request = urllib.request.Request(
        url,
        method="GET",
    )
    return urlopen_json(opener, request)


def post_form(
    opener: urllib.request.OpenerDirector,
    url: str,
    fields: dict[str, str],
    referer: str,
) -> object:
    parsed = urllib.parse.urlparse(url)
    origin = urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "",
            "",
            "",
            "",
        )
    )
    encoded = urllib.parse.urlencode(fields).encode(
        "utf-8"
    )
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
            "Origin": origin,
            "Referer": referer,
        },
        method="POST",
    )
    return urlopen_json(opener, request)


def login(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    username: str,
    password: str,
) -> None:
    login_url = f"{base_url.rstrip('/')}/auth/login"

    try:
        with opener.open(login_url, timeout=30):
            pass
    except urllib.error.URLError as error:
        raise ProfilarrSyncError(
            f"Unable to reach Profilarr login page: {error}"
        ) from error

    post_form(
        opener,
        login_url,
        {
            "username": username,
            "password": password,
        },
        referer=login_url,
    )


def get_instances(
    opener: urllib.request.OpenerDirector,
    base_url: str,
) -> dict[str, dict]:
    payload = get_json(
        opener,
        f"{base_url.rstrip('/')}/api/v1/arr",
    )

    if not isinstance(payload, list):
        raise ProfilarrSyncError(
            "Unexpected Profilarr /api/v1/arr response."
        )

    return {
        str(item["name"]): item
        for item in payload
        if isinstance(item, dict) and "name" in item
    }


def get_database_id(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    database_name: str,
) -> int:
    payload = get_json(
        opener,
        f"{base_url.rstrip('/')}/api/v1/databases",
    )

    if not isinstance(payload, list):
        raise ProfilarrSyncError(
            "Unexpected Profilarr /api/v1/databases response."
        )

    for item in payload:
        if (
            isinstance(item, dict)
            and item.get("name") == database_name
            and isinstance(item.get("id"), int)
        ):
            return item["id"]

    raise ProfilarrSyncError(
        f'Profilarr database "{database_name}" was not found.'
    )


def save_quality_profile_config(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    instance_id: int,
    database_id: int,
    profile_names: list[str],
) -> None:
    selections = [
        {
            "databaseId": database_id,
            "profileName": profile_name,
        }
        for profile_name in profile_names
    ]
    page_url = f"{base_url.rstrip('/')}/arr/{instance_id}/sync"
    response = post_form(
        opener,
        f"{page_url}?/saveQualityProfiles",
        {
            "selections": json.dumps(selections),
            "priorities": "[]",
            "trigger": "manual",
            "cron": "",
        },
        referer=page_url,
    )

    if (
        not isinstance(response, dict)
        or response.get("type") != "success"
    ):
        raise ProfilarrSyncError(
            f"Unexpected save response for Arr instance {instance_id}: "
            f"{response}"
        )


def queue_quality_profile_sync(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    instance_id: int,
) -> None:
    page_url = f"{base_url.rstrip('/')}/arr/{instance_id}/sync"
    response = post_form(
        opener,
        f"{page_url}?/syncQualityProfiles",
        {
            "run": "1",
        },
        referer=page_url,
    )

    if (
        not isinstance(response, dict)
        or response.get("type") != "success"
    ):
        raise ProfilarrSyncError(
            f"Unexpected sync response for Arr instance {instance_id}: "
            f"{response}"
        )


def get_quality_sync_status(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    instance_id: int,
) -> dict:
    payload = get_json(
        opener,
        f"{base_url.rstrip('/')}/api/v1/status",
    )

    if not isinstance(payload, dict):
        raise ProfilarrSyncError(
            "Unexpected Profilarr /api/v1/status response."
        )

    arrs = payload.get("arrs")
    if not isinstance(arrs, list):
        raise ProfilarrSyncError(
            "Profilarr status response is missing arrs."
        )

    for item in arrs:
        if (
            isinstance(item, dict)
            and item.get("id") == instance_id
            and isinstance(item.get("sync"), dict)
            and isinstance(
                item["sync"].get("qualityProfiles"), dict
            )
        ):
            return item["sync"]["qualityProfiles"]

    raise ProfilarrSyncError(
        f"Unable to find quality sync status for instance {instance_id}."
    )


def wait_for_quality_sync(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    instance_id: int,
    timeout_seconds: int,
) -> dict:
    deadline = time.time() + timeout_seconds
    last_status: dict | None = None

    while time.time() < deadline:
        last_status = get_quality_sync_status(
            opener,
            base_url,
            instance_id,
        )
        state = str(last_status.get("status"))

        if state not in {
            "pending",
            "in_progress",
        }:
            return last_status

        time.sleep(2)

    raise ProfilarrSyncError(
        f"Timed out waiting for Profilarr quality sync on instance "
        f"{instance_id}. Last status: {last_status}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Configure a safe Profilarr quality-profile pilot for "
            "Sonarr Main and Radarr Movies."
        )
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
    )
    parser.add_argument(
        "--secret-file",
        type=Path,
        default=DEFAULT_SECRET_FILE,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--run-sync",
        action="store_true",
        help=(
            "Queue the Profilarr quality-profile sync after saving "
            "the pilot configuration."
        ),
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help=(
            "Wait for each queued quality-profile sync to finish. "
            "Requires --run-sync."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
    )
    args = parser.parse_args()

    if args.wait and not args.run_sync:
        raise ProfilarrSyncError(
            "--wait requires --run-sync."
        )

    database_name, instance_configs = validate_config(
        load_config(args.config)
    )
    username, password = load_credentials(args.secret_file)

    opener = build_opener()

    if args.dry_run:
        print(
            f"WOULD_LOGIN_PROFILE_USER: {username}"
        )
        print(
            f"WOULD_TARGET_DATABASE: {database_name}"
        )
        for instance_config in instance_configs:
            print(
                "WOULD_CONFIGURE_INSTANCE: "
                f"{instance_config['name']} -> "
                f"{', '.join(instance_config['qualityProfiles'])}"
            )
            if args.run_sync:
                print(
                    "WOULD_QUEUE_QUALITY_SYNC: "
                    f"{instance_config['name']}"
                )
        return 0

    login(
        opener,
        args.base_url,
        username,
        password,
    )

    instances = get_instances(
        opener,
        args.base_url,
    )
    database_id = get_database_id(
        opener,
        args.base_url,
        database_name,
    )

    for instance_config in instance_configs:
        instance_name = str(instance_config["name"])
        instance = instances.get(instance_name)

        if not instance or not isinstance(
            instance.get("id"), int
        ):
            raise ProfilarrSyncError(
                f'Profilarr Arr instance "{instance_name}" was not found.'
            )

        instance_id = instance["id"]
        profile_names = list(
            instance_config["qualityProfiles"]
        )

        save_quality_profile_config(
            opener,
            args.base_url,
            instance_id,
            database_id,
            profile_names,
        )
        print(
            "CONFIGURED_QUALITY_SYNC: "
            f"{instance_name} -> {', '.join(profile_names)}"
        )

        if not args.run_sync:
            continue

        queue_quality_profile_sync(
            opener,
            args.base_url,
            instance_id,
        )
        print(
            f"QUEUED_QUALITY_SYNC: {instance_name}"
        )

        if not args.wait:
            continue

        status = wait_for_quality_sync(
            opener,
            args.base_url,
            instance_id,
            args.timeout_seconds,
        )
        print(
            "QUALITY_SYNC_STATUS: "
            f"{instance_name} -> {status.get('status')} "
            f"(count={status.get('count')}, "
            f"lastSyncedAt={status.get('lastSyncedAt')})"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
