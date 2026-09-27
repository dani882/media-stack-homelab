#!/usr/bin/env python3

"""Configure Bazarr for managed Spanish subtitles."""

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


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_URL = "http://127.0.0.1:6767"
PROFILE_NAME = "Español"
PROFILE_LANGUAGE = "es"
MANAGED_PROVIDERS = (
    "argenteam",
    "embeddedsubtitles",
    "gestdown",
    "subtitulamostv",
    "yifysubtitles",
)
MISSING_SUBTITLE_TASKS = (
    ("movies", "wanted_search_missing_subtitles_movies"),
    ("episodes", "wanted_search_missing_subtitles_series"),
)


class BazarrError(RuntimeError):
    pass


def read_arr_api_key(stack_dir: Path, service: str) -> str:
    path = stack_dir / "config" / service / "config.xml"
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise BazarrError(f"Unable to read {service} configuration: {error}") from error
    api_key = root.findtext("ApiKey", "").strip()
    if not api_key:
        raise BazarrError(f"ApiKey was not found in {path}")
    return api_key


def read_yaml_scalar(path: Path, section: str, key: str) -> str:
    """Read one scalar from Bazarr's simple top-level YAML structure."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise BazarrError(f"Unable to read {path}: {error}") from error

    current_section = ""
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if not raw_line.startswith((" ", "\t")) and raw_line.rstrip().endswith(":"):
            current_section = raw_line.strip()[:-1]
            continue
        if current_section != section or not raw_line.startswith("  "):
            continue
        stripped = raw_line.strip()
        prefix = f"{key}:"
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value in {"", "null", "None"}:
            break
        return value

    raise BazarrError(f"{section}.{key} was not found in {path}")


def read_bazarr_api_key(stack_dir: Path) -> str:
    return read_yaml_scalar(
        stack_dir / "config" / "bazarr" / "config" / "config.yaml",
        "auth",
        "apikey",
    )


class BazarrClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        headers = {"Accept": "application/json", "X-API-KEY": self.api_key}
        if payload is not None:
            data = urllib.parse.urlencode(payload, doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(
            f"{self.base_url}/api/{path.lstrip('/')}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise BazarrError(
                f"{method} {path} failed with HTTP {error.code}: {body}"
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise BazarrError(f"{method} {path} failed: {error}") from error

    def wait_until_ready(self, attempts: int = 30) -> None:
        for attempt in range(1, attempts + 1):
            try:
                self.request("GET", "system/status")
                print("Bazarr is ready.")
                return
            except BazarrError:
                if attempt == attempts:
                    raise
                time.sleep(2)


def managed_profile(profile_id: int) -> dict[str, Any]:
    return {
        "profileId": profile_id,
        "name": PROFILE_NAME,
        "cutoff": 1,
        "items": [
            {
                "id": 1,
                "language": PROFILE_LANGUAGE,
                "audio_exclude": "True",
                "audio_only_include": "False",
                "hi": "False",
                "forced": "False",
            }
        ],
        "mustContain": [],
        "mustNotContain": [],
        "originalFormat": 0,
        "tag": None,
    }


def merge_managed_profile(
    profiles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, bool]:
    existing = next(
        (profile for profile in profiles if profile.get("name") == PROFILE_NAME),
        None,
    )
    used_ids = {int(item.get("profileId") or 0) for item in profiles}
    profile_id = int(existing.get("profileId")) if existing else 1
    while not existing and profile_id in used_ids:
        profile_id += 1
    desired = managed_profile(profile_id)
    merged = [item for item in profiles if item.get("name") != PROFILE_NAME]
    merged.append(desired)
    merged.sort(key=lambda item: int(item.get("profileId") or 0))
    return merged, profile_id, existing != desired


def build_settings_payload(
    settings: dict[str, Any],
    languages: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    profile_id: int,
    sonarr_key: str,
    radarr_key: str,
) -> dict[str, Any]:
    general = settings.get("general", {})
    providers = sorted(
        set(general.get("enabled_providers") or []) | set(MANAGED_PROVIDERS)
    )
    enabled_languages = sorted(
        {
            str(item.get("code2"))
            for item in languages
            if item.get("enabled") and item.get("code2")
        }
        | {PROFILE_LANGUAGE}
    )
    return {
        "languages-enabled": enabled_languages,
        "languages-profiles": json.dumps(profiles, separators=(",", ":")),
        "settings-general-enabled_providers": providers,
        "settings-general-use_radarr": "true",
        "settings-general-use_sonarr": "true",
        "settings-general-parse_embedded_audio_track": "true",
        "settings-general-use_embedded_subs": "true",
        "settings-general-movie_default_enabled": "true",
        "settings-general-movie_default_profile": str(profile_id),
        "settings-general-serie_default_enabled": "true",
        "settings-general-serie_default_profile": str(profile_id),
        "settings-radarr-ip": "radarr",
        "settings-radarr-port": "7878",
        "settings-radarr-base_url": "/",
        "settings-radarr-ssl": "false",
        "settings-radarr-apikey": radarr_key,
        "settings-radarr-movies_sync_on_live": "true",
        "settings-sonarr-ip": "sonarr",
        "settings-sonarr-port": "8989",
        "settings-sonarr-base_url": "/",
        "settings-sonarr-ssl": "false",
        "settings-sonarr-apikey": sonarr_key,
        "settings-sonarr-series_sync_on_live": "true",
    }


def total(payload: Any) -> int:
    return int(payload.get("total") or 0) if isinstance(payload, dict) else 0


def arr_inventory_counts(
    sonarr_key: str,
    radarr_key: str,
    timeout: int = 60,
) -> tuple[int, int]:
    def get(url: str, api_key: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "X-Api-Key": api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as error:
            raise BazarrError(f"Unable to read Arr inventory: {error}") from error

    movies = get("http://127.0.0.1:7878/api/v3/movie", radarr_key)
    series = get("http://127.0.0.1:8989/api/v3/series", sonarr_key)
    expected_movies = sum(
        1
        for movie in movies
        if movie.get("hasFile")
        and isinstance(movie.get("movieFile"), dict)
        and int(movie["movieFile"].get("size") or 0) > 20 * 1024 * 1024
    )
    return expected_movies, len(series)


def wait_for_sync(
    client: BazarrClient,
    expected_movies: int,
    expected_series: int,
    attempts: int = 450,
) -> tuple[int, int]:
    for attempt in range(1, attempts + 1):
        movies = total(client.request("GET", "movies?start=0&length=1"))
        series = total(client.request("GET", "series?start=0&length=1"))
        if movies >= expected_movies and series >= expected_series:
            return movies, series
        if attempt < attempts:
            time.sleep(2)
    raise BazarrError(
        "Bazarr did not synchronize the complete inventory in time: "
        f"movies={movies}/{expected_movies} series={series}/{expected_series}"
    )


def assign_profile(
    client: BazarrClient,
    endpoint: str,
    id_key: str,
    response_id_key: str,
    profile_id: int,
) -> int:
    payload = client.request("GET", f"{endpoint}?start=0&length=-1") or {}
    entries = payload.get("data", []) if isinstance(payload, dict) else []
    pending = [
        int(item[response_id_key])
        for item in entries
        if int(item.get("profileId") or 0) != profile_id
    ]
    for offset in range(0, len(pending), 100):
        identifiers = pending[offset:offset + 100]
        client.request(
            "POST",
            endpoint,
            {id_key: identifiers, "profileid": [str(profile_id)] * len(identifiers)},
        )
    return len(pending)


def validate_configuration(
    settings: dict[str, Any],
    profiles: list[dict[str, Any]],
    profile_id: int,
) -> list[str]:
    problems: list[str] = []
    general = settings.get("general", {})
    radarr = settings.get("radarr", {})
    sonarr = settings.get("sonarr", {})
    expected = {
        "use_radarr": True,
        "use_sonarr": True,
        "parse_embedded_audio_track": True,
        "use_embedded_subs": True,
        "movie_default_enabled": True,
        "serie_default_enabled": True,
    }
    for key, value in expected.items():
        if general.get(key) is not value:
            problems.append(f"general.{key} is not enabled")
    if int(general.get("movie_default_profile") or 0) != profile_id:
        problems.append("movie default profile is not managed Spanish")
    if int(general.get("serie_default_profile") or 0) != profile_id:
        problems.append("series default profile is not managed Spanish")
    missing_providers = set(MANAGED_PROVIDERS) - set(
        general.get("enabled_providers") or []
    )
    if missing_providers:
        problems.append("missing providers: " + ", ".join(sorted(missing_providers)))
    if radarr.get("ip") != "radarr" or not radarr.get("apikey"):
        problems.append("Radarr connection is not configured")
    if sonarr.get("ip") != "sonarr" or not sonarr.get("apikey"):
        problems.append("Sonarr connection is not configured")
    if managed_profile(profile_id) not in profiles:
        problems.append(f"language profile {PROFILE_NAME} is missing or drifted")
    return problems


def start_missing_subtitle_searches(client: BazarrClient) -> None:
    """Queue Bazarr's wanted searches for movies and episodes missing Spanish."""
    for media_type, task_id in MISSING_SUBTITLE_TASKS:
        client.request("POST", "system/tasks", {"taskid": task_id})
        print(f"BAZARR MISSING SPANISH SEARCH STARTED: {media_type}")


def configure(args: argparse.Namespace) -> int:
    stack_dir = args.stack_dir
    client = BazarrClient(args.url, read_bazarr_api_key(stack_dir), args.timeout)
    client.wait_until_ready()
    settings = client.request("GET", "system/settings") or {}
    languages = client.request("GET", "system/languages") or []
    profiles = client.request("GET", "system/languages/profiles") or []
    merged_profiles, profile_id, profile_changed = merge_managed_profile(profiles)
    sonarr_key = read_arr_api_key(stack_dir, "sonarr")
    radarr_key = read_arr_api_key(stack_dir, "radarr")
    expected_movies, expected_series = arr_inventory_counts(
        sonarr_key, radarr_key, args.timeout
    )

    if args.check_only:
        problems = validate_configuration(settings, profiles, profile_id)
        movies = total(client.request("GET", "movies?start=0&length=1"))
        series = total(client.request("GET", "series?start=0&length=1"))
        if movies < expected_movies:
            problems.append(
                f"incomplete Radarr sync: {movies}/{expected_movies} movies"
            )
        if series < expected_series:
            problems.append(
                f"incomplete Sonarr sync: {series}/{expected_series} series"
            )
        if problems:
            raise BazarrError("; ".join(problems))
        print(
            f"BAZARR CONFIGURATION OK: profile={PROFILE_NAME} "
            f"movies={movies} series={series}"
        )
        return 0

    payload = build_settings_payload(
        settings,
        languages,
        merged_profiles,
        profile_id,
        sonarr_key,
        radarr_key,
    )
    if args.dry_run:
        current_problems = validate_configuration(settings, profiles, profile_id)
        print(
            f"WOULD CONFIGURE BAZARR: profile={PROFILE_NAME} id={profile_id} "
            f"profile_changed={profile_changed} drift={len(current_problems)} "
            f"providers={','.join(payload['settings-general-enabled_providers'])}"
        )
        return 0

    current_problems = validate_configuration(settings, profiles, profile_id)
    spanish_enabled = any(
        item.get("code2") == PROFILE_LANGUAGE and item.get("enabled")
        for item in languages
    )
    settings_changed = profile_changed or bool(current_problems) or not spanish_enabled
    current_movies = total(client.request("GET", "movies?start=0&length=1"))
    current_series = total(client.request("GET", "series?start=0&length=1"))
    inventory_incomplete = (
        current_movies < expected_movies or current_series < expected_series
    )

    if settings_changed:
        client.request("POST", "system/settings", payload)
    if settings_changed or inventory_incomplete:
        client.request("POST", "system/tasks", {"taskid": "update_movies"})
        client.request("POST", "system/tasks", {"taskid": "update_series"})
        movies, series = wait_for_sync(
            client, expected_movies, expected_series
        )
    else:
        movies, series = current_movies, current_series
        print("BAZARR CONFIGURATION UNCHANGED")
    changed_movies = assign_profile(
        client, "movies", "radarrid", "radarrId", profile_id
    )
    changed_series = assign_profile(
        client, "series", "seriesid", "sonarrSeriesId", profile_id
    )
    refreshed_settings = client.request("GET", "system/settings") or {}
    refreshed_profiles = client.request("GET", "system/languages/profiles") or []
    problems = validate_configuration(
        refreshed_settings, refreshed_profiles, profile_id
    )
    if problems:
        raise BazarrError("; ".join(problems))
    print(
        f"BAZARR CONFIGURATION OK: profile={PROFILE_NAME} "
        f"movies={movies} series={series} "
        f"assigned_movies={changed_movies} assigned_series={changed_series}"
    )
    if args.search_missing:
        start_missing_subtitle_searches(client)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="maximum seconds for slow Bazarr inventory and settings requests",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument(
        "--search-missing",
        action="store_true",
        help="start wanted searches for movies and episodes missing Spanish",
    )
    return parser.parse_args()


def main() -> int:
    try:
        return configure(parse_args())
    except BazarrError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
