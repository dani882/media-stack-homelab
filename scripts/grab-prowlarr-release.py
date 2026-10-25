#!/usr/bin/env python3

"""Grab one explicitly selected Prowlarr torrent without exposing secrets.

Use this only for a known release that Prowlarr can find by title but which an
*arr application cannot discover through an ID-based search.  The script does
not replace normal Sonarr/Radarr selection; it adds a guarded escape hatch for
private indexers with incomplete Torznab metadata.
"""


import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_PRIVATE_POLICY_FILE = DEFAULT_STACK_DIR / "private-release-policy.json"
DEFAULT_PRIVATE_INDEXER_SECRETS = (
    DEFAULT_STACK_DIR / "secrets/prowlarr-private-indexers.json"
)
DEPLOYED_SCRIPT_DIR = DEFAULT_STACK_DIR / "scripts"
LOCAL_MEDIA_SCRIPT_DIR = Path(__file__).resolve().parent / "media"
for script_dir in (LOCAL_MEDIA_SCRIPT_DIR, DEPLOYED_SCRIPT_DIR):
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

from common.language import LanguageRank, language_rank
from common.qbittorrent import QBittorrentClient, QBittorrentError, read_credentials
from common.release_safety import (
    dangerous_release_title,
    dangerous_torrent_paths,
    english_only_torrent_paths,
    transcode_codec_title,
    unacceptable_noncodec_source_title,
    unacceptable_source_title,
)


class GrabError(RuntimeError):
    pass


class TorrentFetchError(GrabError):
    """A transient tracker/Prowlarr delivery failure, not a release rejection."""

    pass


class TrackerAccountGuardError(TorrentFetchError):
    """A temporary private-tracker account condition blocks a new grab."""

    pass


LATTEAM_API_URL = "https://lat-team.com/api/torrents/filter"
LATTEAM_USER_API_URL = "https://lat-team.com/api/user"
LATTEAM_HOST = "lat-team.com"
LATTEAM_MINIMUM_ACCOUNT_RATIO = 0.25
TRACKER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/140 Safari/537.36"
)


LANGUAGE_FLOORS = {
    "unknown": LanguageRank.UNKNOWN,
    "english": LanguageRank.ENGLISH,
    "castilian": LanguageRank.CASTILIAN,
    "latino": LanguageRank.LATINO,
}


def title_resolution(release: dict[str, Any]) -> int:
    """Return a conservative resolution claim without trusting it as media data."""
    title = str(release.get("title", "")).casefold()
    for resolution in (2160, 1080, 720, 540, 480):
        if f"{resolution}p" in title:
            return resolution
    return 0


def release_meets_private_policy(
    release: dict[str, Any],
    minimum_language: str,
    minimum_title_resolution: int,
    allow_transcode: bool = False,
) -> bool:
    title = str(release.get("title", ""))
    if dangerous_release_title(title) or unacceptable_noncodec_source_title(title):
        return False
    if transcode_codec_title(title) and not allow_transcode:
        return False
    if language_rank(release) < LANGUAGE_FLOORS[minimum_language]:
        return False
    return title_resolution(release) >= minimum_title_resolution


def read_api_key(config_file: Path) -> str:
    try:
        key = ET.parse(config_file).getroot().findtext("ApiKey", "").strip()
    except (ET.ParseError, OSError) as error:
        raise GrabError(f"Unable to read {config_file}: {error}") from error

    if not key:
        raise GrabError(f"No API key found in {config_file}")

    return key


def read_private_policy(policy_file: Path) -> tuple[str, int]:
    try:
        payload = json.loads(policy_file.read_text(encoding="utf-8"))
        automatic = payload["automaticPrivateGrab"]
        language = str(automatic["minimumLanguage"])
        resolution = int(automatic["minimumTitleResolution"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GrabError(f"Unable to read private release policy {policy_file}: {error}") from error

    if language not in LANGUAGE_FLOORS or resolution < 0:
        raise GrabError(f"Invalid private release policy in {policy_file}")
    return language, resolution


def prowlarr_search(
    base_url: str,
    api_key: str,
    query: str,
    indexer_id: int,
    media_type: str,
) -> list[dict[str, Any]]:
    parameters = urllib.parse.urlencode(
        {
            "query": query,
            "indexerIds": indexer_id,
            "type": "tvsearch" if media_type == "tv" else "movie",
        }
    )
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/search?{parameters}",
        headers={"X-Api-Key": api_key},
    )

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read())
            if not isinstance(payload, list):
                raise GrabError(
                    "Prowlarr search returned an unexpected payload."
                )
            releases = [item for item in payload if isinstance(item, dict)]
            if releases or attempt == 1:
                return releases
        except (OSError, json.JSONDecodeError, GrabError) as error:
            last_error = error
            if attempt == 1:
                break
        print(
            f"PROWLARR SEARCH RETRY: indexer={indexer_id} "
            f"media={media_type}"
        )
        time.sleep(2)

    raise GrabError(f"Prowlarr search failed: {last_error}") from last_error


def select_release(
    releases: list[dict[str, Any]],
    expected_title: str,
    indexer_id: int,
    expected_media_id: int | None,
    media_type: str,
    minimum_seeders: int,
    minimum_language: str = "unknown",
    minimum_title_resolution: int = 0,
) -> dict[str, Any]:
    title = expected_title.casefold()
    candidates = [
        item
        for item in releases
        if str(item.get("title", "")).casefold() == title
        and int(item.get("indexerId", -1)) == indexer_id
    ]

    if len(candidates) != 1:
        raise GrabError(
            "Expected exactly one exact-title result from the requested "
            f"indexer; found {len(candidates)}."
        )

    release = candidates[0]
    if release.get("protocol") != "torrent":
        raise GrabError("Selected release is not a torrent.")

    media_id_field = "tvdbId" if media_type == "tv" else "tmdbId"
    if expected_media_id is not None and int(
        release.get(media_id_field, -1)
    ) != expected_media_id:
        raise GrabError(
            f"Selected release has an unexpected {media_id_field}."
        )

    if int(release.get("seeders", 0) or 0) < minimum_seeders:
        raise GrabError("Selected release has too few seeders.")

    if not release_meets_private_policy(
        release,
        minimum_language,
        minimum_title_resolution,
    ):
        actual_language = language_rank(release).name.lower()
        actual_resolution = title_resolution(release)
        raise GrabError(
            "Selected release does not meet the private fallback policy: "
            f"language={actual_language} (requires {minimum_language}), "
            f"title_resolution={actual_resolution}p "
            f"(requires {minimum_title_resolution}p)."
        )

    if not release.get("downloadUrl"):
        raise GrabError("Selected release does not provide a download URL.")

    return release


def download_url_for_qbittorrent(
    download_url: str,
) -> str:
    """Translate Prowlarr's local-loopback URL for the Docker network."""
    parsed = urllib.parse.urlsplit(download_url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return download_url

    port = f":{parsed.port}" if parsed.port else ""
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            f"prowlarr{port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def fetch_torrent_payload(download_url: str) -> bytes:
    """Resolve a Prowlarr download privately and reject login/error pages."""
    request = urllib.request.Request(
        download_url,
        headers={"User-Agent": "homelab-release-grab/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = response.read()
            content_type = str(response.headers.get("Content-Type", "")).casefold()
    except OSError as error:
        raise TorrentFetchError(
            "Prowlarr could not retrieve the selected torrent from its tracker."
        ) from error
    if not payload.startswith(b"d") or b"announce" not in payload[:4096]:
        kind = "HTML" if "html" in content_type or payload.lstrip().startswith(b"<") else "non-torrent data"
        raise TorrentFetchError(
            "The tracker returned " + kind + " instead of a torrent; "
            "nothing was sent to qBittorrent."
        )
    return payload


def is_latteam_release(release: dict[str, Any]) -> bool:
    return "lat-team" in str(release.get("indexer") or "").casefold()


def normalized_latteam_title(value: str) -> str:
    return re.sub(r"(?i)\s+SPANiSH\s*$", "", value).strip()


def read_latteam_api_key(secret_file: Path) -> str:
    try:
        payload = json.loads(secret_file.read_text(encoding="utf-8"))
        api_key = str(payload["lat-team-api"]["apikey"]).strip()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise TorrentFetchError(
            "Lat-Team direct delivery is unavailable because its NAS-local "
            "API configuration could not be read."
        ) from error
    if not api_key:
        raise TorrentFetchError(
            "Lat-Team direct delivery is unavailable because its NAS-local "
            "API key is empty."
        )
    return api_key


def latteam_api_json(url: str, api_key: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer " + api_key,
            "User-Agent": TRACKER_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise TorrentFetchError(
            "Lat-Team could not be reached through its API."
        ) from error


def ensure_latteam_account_healthy(
    secret_file: Path = DEFAULT_PRIVATE_INDEXER_SECRETS,
) -> str:
    api_key = read_latteam_api_key(secret_file)
    payload = latteam_api_json(LATTEAM_USER_API_URL, api_key)
    try:
        ratio = float(str(payload["ratio"]).strip())
    except (KeyError, TypeError, ValueError) as error:
        raise TrackerAccountGuardError(
            "Lat-Team did not provide a usable account ratio; new grabs are "
            "paused safely."
        ) from error
    if ratio < LATTEAM_MINIMUM_ACCOUNT_RATIO:
        raise TrackerAccountGuardError(
            "Lat-Team account ratio is below 0.25; new grabs are paused while "
            "existing torrents continue seeding."
        )
    return api_key


def fetch_latteam_torrent_payload(
    release: dict[str, Any],
    secret_file: Path = DEFAULT_PRIVATE_INDEXER_SECRETS,
) -> bytes:
    """Resolve one exact Lat-Team result without exposing its signed URL."""
    api_key = read_latteam_api_key(secret_file)
    expected_title = normalized_latteam_title(str(release.get("title") or ""))
    expected_size = int(release.get("size", 0) or 0)
    if not expected_title or expected_size <= 0:
        raise TorrentFetchError(
            "Lat-Team direct delivery requires an exact title and size."
        )

    query = urllib.parse.urlencode({"name": expected_title, "perPage": 100})
    payload = latteam_api_json(f"{LATTEAM_API_URL}?{query}", api_key)

    rows = payload.get("data", []) if isinstance(payload, dict) else []
    matches = []
    for row in rows:
        attributes = row.get("attributes", {}) if isinstance(row, dict) else {}
        title = normalized_latteam_title(str(attributes.get("name") or ""))
        size = int(attributes.get("size", 0) or 0)
        if title.casefold() == expected_title.casefold() and size == expected_size:
            matches.append(attributes)
    if len(matches) != 1:
        raise TorrentFetchError(
            "Lat-Team direct delivery did not return one exact title-and-size match."
        )

    download_url = str(matches[0].get("download_link") or "")
    parsed = urllib.parse.urlsplit(download_url)
    if not (
        parsed.scheme == "https"
        and parsed.hostname == LATTEAM_HOST
        and re.fullmatch(r"/torrent/download/\d+\.[A-Za-z0-9_-]+", parsed.path)
        and not parsed.query
        and not parsed.fragment
    ):
        raise TorrentFetchError(
            "Lat-Team returned an unexpected download-link format."
        )

    torrent_headers = {
        "Accept": "application/x-bittorrent, application/octet-stream;q=0.9, */*;q=0.8",
        "Authorization": "Bearer " + api_key,
        "Referer": "https://lat-team.com/",
        "User-Agent": TRACKER_USER_AGENT,
    }
    torrent_request = urllib.request.Request(download_url, headers=torrent_headers)
    try:
        with urllib.request.urlopen(torrent_request, timeout=90) as response:
            torrent_payload = response.read()
            content_type = str(response.headers.get("Content-Type", "")).casefold()
    except urllib.error.HTTPError as error:
        raise TorrentFetchError(
            f"Lat-Team rejected the selected torrent with HTTP {error.code}."
        ) from error
    except OSError as error:
        raise TorrentFetchError(
            "Lat-Team could not deliver the selected torrent."
        ) from error
    if not torrent_payload.startswith(b"d") or b"announce" not in torrent_payload[:4096]:
        kind = (
            "HTML"
            if "html" in content_type or torrent_payload.lstrip().startswith(b"<")
            else "non-torrent data"
        )
        raise TorrentFetchError(
            f"Lat-Team returned {kind} instead of a torrent; nothing was sent "
            "to qBittorrent."
        )
    return torrent_payload


def fetch_torrent_payload_for_release(release: dict[str, Any]) -> bytes:
    if is_latteam_release(release):
        ensure_latteam_account_healthy()
    try:
        return fetch_torrent_payload(str(release["downloadUrl"]))
    except TorrentFetchError:
        if not is_latteam_release(release):
            raise
        return fetch_latteam_torrent_payload(release)


def add_to_qbittorrent(
    client: QBittorrentClient,
    release: dict[str, Any],
    category: str,
    tags: str,
    seed_time_minutes: int,
    dry_run: bool,
    ratio_limit: float | None = None,
    display_name: str | None = None,
    require_private: bool = True,
    policy_label: str = "PRIVATE POLICY",
    allow_public_private_flag: bool = False,
    member_validator: Callable[[list[str]], None] | None = None,
) -> None:
    title = str(release["title"])
    seeders = int(release.get("seeders", 0) or 0)
    size = int(release.get("size", 0) or 0)

    print(
        f"SELECTED: {title} indexer={release['indexerId']} "
        f"seeders={seeders} size={size} category={category}"
    )
    policy_parts = [f"tags={tags}"]
    if seed_time_minutes > 0:
        policy_parts.append(f"seed-time={seed_time_minutes}m")
    if ratio_limit is not None:
        policy_parts.append(f"ratio={ratio_limit:.2f}")
    print(f"{policy_label}: " + " ".join(policy_parts))

    if dry_run:
        print("DRY RUN: would add the selected torrent to qBittorrent")
        return

    tag_set = {
        tag.strip()
        for tag in tags.split(",")
        if tag.strip()
    }
    if not tag_set:
        raise GrabError("At least one non-empty tag is required.")

    def active_tags(item: dict[str, Any]) -> set[str]:
        item_tags = {
            tag.strip()
            for tag in str(item.get("tags", "")).split(",")
            if tag.strip()
        }
        return set() if "language-mismatch" in item_tags else item_tags

    existing = [
        item
        for item in client.get_json("/api/v2/torrents/info")
        if tag_set.issubset(active_tags(item))
    ]
    if existing:
        raise GrabError(
            "A torrent already has all requested tags; refusing a duplicate "
            "grab."
        )

    add_form = {
        "category": category,
        "tags": tags,
        "stopped": "true",
        "paused": "true",
    }
    if display_name:
        add_form["rename"] = display_name

    torrent_payload = fetch_torrent_payload_for_release(release)
    client.post_multipart(
        "/api/v2/torrents/add",
        add_form,
        "selected.torrent",
        torrent_payload,
    )

    for _ in range(30):
        torrents = client.get_json("/api/v2/torrents/info")
        matches = [
            item
            for item in torrents
            if tag_set.issubset(active_tags(item))
        ]
        if len(matches) == 1:
            torrent = matches[0]
            torrent_hash = str(torrent["hash"])
            try:
                is_private = torrent.get("private")
                if require_private and is_private not in (True, 1):
                    raise GrabError(
                        "Selected private-indexer torrent is not explicitly private."
                    )
                if not require_private and is_private not in (False, 0):
                    if not allow_public_private_flag:
                        raise GrabError(
                            "Selected public-indexer torrent is not explicitly public."
                        )
                    trackers = client.get_json(
                        "/api/v2/torrents/trackers?"
                        + urllib.parse.urlencode({"hash": torrent_hash})
                    )
                    tracker_hosts = {
                        str(urllib.parse.urlsplit(str(item.get("url") or "")).hostname or "").casefold()
                        for item in trackers
                        if urllib.parse.urlsplit(
                            str(item.get("url") or "")
                        ).scheme
                        in {"http", "https", "udp"}
                    }
                    private_markers = (
                        "lat-team",
                        "btarg",
                        "milnueve",
                        "retrotoon",
                        "dreadvault",
                        "torrenthaven",
                        "docspedia",
                    )
                    if not tracker_hosts:
                        raise GrabError(
                            "Public-indexer torrent has no verifiable tracker host."
                        )
                    if any(
                        marker in host
                        for host in tracker_hosts
                        for marker in private_markers
                    ):
                        raise GrabError(
                            "Public-indexer torrent announces to a known private tracker."
                        )
                    print(
                        "PUBLIC ORIGIN VERIFIED: private flag retained; "
                        "no known private tracker host"
                    )
                files = client.get_json(
                    "/api/v2/torrents/files?"
                    + urllib.parse.urlencode({"hash": torrent_hash})
                )
                unsafe_paths = dangerous_torrent_paths(
                    str(item.get("name", "")) for item in files
                )
                if unsafe_paths:
                    raise GrabError(
                        "Selected torrent contains a dangerous file type."
                    )
                member_paths = [str(item.get("name", "")) for item in files]
                if member_validator is not None:
                    member_validator(member_paths)
                if (
                    language_rank(release) >= LanguageRank.CASTILIAN
                    and english_only_torrent_paths(
                        str(item.get("name", "")) for item in files
                    )
                ):
                    raise GrabError(
                        "Selected torrent payload conflicts with its claimed "
                        "Spanish audio language."
                    )
            except (GrabError, QBittorrentError):
                client.post_form(
                    "/api/v2/torrents/delete",
                    {"hashes": torrent_hash, "deleteFiles": "true"},
                )
                raise
            try:
                client.post_form(
                    "/api/v2/torrents/setShareLimits",
                    {
                        "hashes": torrent_hash,
                        "ratioLimit": (
                            ratio_limit if ratio_limit is not None else -2
                        ),
                        "seedingTimeLimit": (
                            seed_time_minutes if seed_time_minutes > 0 else -2
                        ),
                        "inactiveSeedingTimeLimit": -2,
                        "shareLimitAction": "Default",
                        "shareLimitsMode": "Default",
                    },
                )
                client.post_form(
                    "/api/v2/torrents/start",
                    {"hashes": torrent_hash},
                )
            except QBittorrentError as error:
                client.post_form(
                    "/api/v2/torrents/delete",
                    {"hashes": torrent_hash, "deleteFiles": "true"},
                )
                raise GrabError(
                    "qBittorrent rejected the required share policy; "
                    "the stopped torrent was removed."
                ) from error
            print(
                "ADDED: "
                f"hash={torrent_hash[:12].upper()} "
                f"path={torrent.get('save_path')}"
            )
            return

        if len(matches) > 1:
            raise GrabError(
                "More than one torrent has the requested tags; refusing to "
                "choose a torrent for the guarded policy."
            )

        time.sleep(2)

    raise GrabError(
        "qBittorrent did not report the selected torrent after adding it."
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grab one exact Prowlarr torrent through qBittorrent."
    )
    parser.add_argument("--query", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--indexer-id", required=True, type=int)
    parser.add_argument("--media-type", choices=("tv", "movie"), default="tv")
    parser.add_argument("--tvdb-id", type=int)
    parser.add_argument("--tmdb-id", type=int)
    parser.add_argument("--minimum-seeders", type=int, default=1)
    parser.add_argument(
        "--minimum-language",
        choices=tuple(LANGUAGE_FLOORS),
        default=None,
        help="Private auto-grabs require Spanish by default; English is opt-in.",
    )
    parser.add_argument(
        "--minimum-title-resolution",
        type=int,
        default=None,
        help="Reject titles that do not claim at least this resolution.",
    )
    parser.add_argument("--seed-time-minutes", required=True, type=int)
    parser.add_argument("--category", default="tv")
    parser.add_argument("--tags", required=True)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--policy-file", type=Path)
    parser.add_argument("--prowlarr-url", default="http://127.0.0.1:9696")
    parser.add_argument("--qbittorrent-url", default="http://127.0.0.1:8888")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.seed_time_minutes <= 0:
        raise GrabError("--seed-time-minutes must be positive.")
    if arguments.minimum_seeders < 1:
        raise GrabError("--minimum-seeders must be at least one.")
    policy_file = arguments.policy_file or arguments.stack_dir / "private-release-policy.json"
    policy_language, policy_resolution = read_private_policy(policy_file)
    minimum_language = arguments.minimum_language or policy_language
    minimum_title_resolution = (
        policy_resolution
        if arguments.minimum_title_resolution is None
        else arguments.minimum_title_resolution
    )
    if minimum_title_resolution < 0:
        raise GrabError("--minimum-title-resolution must not be negative.")
    expected_media_id = (
        arguments.tvdb_id
        if arguments.media_type == "tv"
        else arguments.tmdb_id
    )
    if expected_media_id is None:
        required = "--tvdb-id" if arguments.media_type == "tv" else "--tmdb-id"
        raise GrabError(f"{required} is required for {arguments.media_type} releases.")

    prowlarr_key = read_api_key(
        arguments.stack_dir / "config/prowlarr/config.xml"
    )
    username, password = read_credentials(
        arguments.stack_dir / "secrets/qbittorrent.json"
    )
    client = QBittorrentClient(
        arguments.qbittorrent_url,
        username,
        password,
    )
    client.login()

    releases = prowlarr_search(
        arguments.prowlarr_url,
        prowlarr_key,
        arguments.query,
        arguments.indexer_id,
        arguments.media_type,
    )
    release = select_release(
        releases,
        arguments.title,
        arguments.indexer_id,
        expected_media_id,
        arguments.media_type,
        arguments.minimum_seeders,
        minimum_language,
        minimum_title_resolution,
    )
    add_to_qbittorrent(
        client,
        release,
        arguments.category,
        arguments.tags,
        arguments.seed_time_minutes,
        arguments.dry_run,
        display_name=arguments.title,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (GrabError, QBittorrentError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
