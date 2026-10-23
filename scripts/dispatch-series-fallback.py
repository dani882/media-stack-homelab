#!/usr/bin/env python3
"""Dispatch one guarded fallback or upgrade for monitored TV episodes.

Candidates are ranked by language first, then by private/public source and
tracker priority. Exact single-episode torrents and exact season packs are
eligible. Existing non-Spanish episodes may only be upgraded from known
private trackers. The selected torrent is added stopped, its privacy flag and
member paths are inspected, and only then is it started. At most one torrent
is started per run.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STACK = Path("/volume1/docker/media-stack")
SEERR_URL = "http://127.0.0.1:5055"
SONARR_URL = "http://127.0.0.1:8989"
PROWLARR_URL = "http://127.0.0.1:9696"
QBITTORRENT_URL = "http://127.0.0.1:8888"
INSPECTION_POLICY_VERSION = 3
VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mp4", ".ts", ".webm"}
SPANISH_AUDIO_VALUES = {
    "es",
    "esl",
    "spa",
    "spanish",
    "spanish (latino)",
    "spanish (spain)",
    "castilian",
    "latino",
}
ENGLISH_AUDIO_VALUES = {"en", "eng", "english"}

SCRIPT_ROOT = Path(__file__).resolve().parent
for module_dir in (SCRIPT_ROOT / "media", STACK / "scripts"):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from common.btarg import BTArgCache, BTArgClient, BTArgError, enrich_release
from common.language import (
    LanguageRank,
    language_rank,
    release_is_safe_language_upgrade,
    rejection_is_overridable,
    rejection_reasons,
)
from common.qbittorrent import QBittorrentClient, read_credentials
from common.release_safety import (
    dangerous_release_title,
    dangerous_torrent_paths,
    unacceptable_source_title,
)


SPEC = importlib.util.spec_from_file_location(
    "guarded_grab", SCRIPT_ROOT / "grab-prowlarr-release.py"
)
assert SPEC and SPEC.loader
GRAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAB)


class SeriesFallbackError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourcePolicy:
    name: str
    private: bool
    priority: int
    minimum_seeders: int
    seed_minutes: int
    ratio_limit: float | None = None


PRIVATE_SOURCES = (
    SourcePolicy("lat-team", True, 1, 1, 4920),
    SourcePolicy("btarg", True, 2, 1, -2, 1.0),
    SourcePolicy("milnueve", True, 4, 1, 6360),
    SourcePolicy("retrotoon", True, 8, 1, 4920),
    SourcePolicy("dreadvault", True, 9, 1, 7800),
    SourcePolicy("torrenthaven", True, 9, 1, 4920),
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SeriesFallbackError(f"Unable to read {path}: {error}") from error
    if not isinstance(payload, dict):
        raise SeriesFallbackError(f"Expected an object in {path}")
    return payload


def get_json(base_url: str, path: str, api_key: str, timeout: int = 90) -> Any:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", headers={"X-Api-Key": api_key}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        raise SeriesFallbackError(f"GET {path} failed: {error}") from error


def post_json(base_url: str, path: str, api_key: str, payload: dict[str, Any]) -> Any:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Api-Key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        raise SeriesFallbackError(f"POST {path} failed: {error}") from error


def seerr_api_key(stack: Path) -> str:
    key = str(
        read_json(stack / "config/jellyseerr/settings.json")
        .get("main", {})
        .get("apiKey", "")
    ).strip()
    if not key:
        raise SeriesFallbackError("Seerr API key is missing")
    return key


def seerr_requests(stack: Path) -> list[dict[str, Any]]:
    payload = get_json(
        SEERR_URL,
        "/api/v1/request?" + urllib.parse.urlencode({"take": 100, "skip": 0}),
        seerr_api_key(stack),
        timeout=60,
    )
    return [
        item
        for item in payload.get("results", [])
        if item.get("type") == "tv"
        and item.get("status") in {2, 5}
        and isinstance(item.get("media"), dict)
        and item["media"].get("tvdbId")
    ]


def requested_seasons(request: dict[str, Any]) -> set[int]:
    return {
        int(item["seasonNumber"])
        for item in request.get("seasons", [])
        if int(item.get("seasonNumber", 0) or 0) > 0
        and item.get("status") in {2, 5}
    }


def monitored_seasons(series: dict[str, Any]) -> set[int]:
    return {
        int(item["seasonNumber"])
        for item in series.get("seasons", [])
        if int(item.get("seasonNumber", 0) or 0) > 0
        and item.get("monitored") is True
    }


def monitored_series_targets(
    series_items: list[dict[str, Any]],
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requests_by_tvdb = {
        int(item["media"]["tvdbId"]): dict(item)
        for item in requests
        if isinstance(item.get("media"), dict)
        and int(item["media"].get("tvdbId", 0) or 0) > 0
    }
    targets: list[dict[str, Any]] = []
    for series in series_items:
        tvdb_id = int(series.get("tvdbId", 0) or 0)
        seasons = monitored_seasons(series)
        if not series.get("monitored") or tvdb_id <= 0 or not seasons:
            continue
        request = requests_by_tvdb.get(tvdb_id)
        requested = requested_seasons(request) if request else set()
        target = dict(request or {})
        target.update(
            {
                "id": (
                    int(request["id"])
                    if request
                    else -int(series["id"])
                ),
                "createdAt": (
                    str(request.get("createdAt") or "")
                    if request
                    else str(series.get("added") or "")
                ),
                "media": {"tvdbId": tvdb_id},
                "seasons": [
                    {"seasonNumber": number, "status": 2}
                    for number in sorted(seasons | requested)
                ],
                "monitoredSeriesId": int(series["id"]),
            }
        )
        targets.append(target)
    return sorted(targets, key=lambda item: int(item["monitoredSeriesId"]))


def target_tags(request: dict[str, Any], series: dict[str, Any]) -> list[str]:
    tags = [f"monitored-series-{int(series['id'])}"]
    if int(request.get("id", 0) or 0) > 0:
        tags.append(f"seerr-request-{int(request['id'])}")
    return tags


def target_label(request: dict[str, Any]) -> str:
    request_id = int(request.get("id", 0) or 0)
    return (
        f"request={request_id}"
        if request_id > 0
        else f"monitored-series={int(request['monitoredSeriesId'])}"
    )


def read_policy(path: Path) -> dict[str, Any]:
    try:
        raw = read_json(path)["automaticSeriesFallback"]
        policy = {
            "minimum_resolution": int(raw["minimumTitleResolution"]),
            "english_fallback_days": int(raw["englishFallbackAfterDays"]),
            "public_enabled": bool(raw["publicFallbackEnabled"]),
            "public_minimum_seeders": int(raw["publicMinimumSeeders"]),
            "public_seed_minutes": int(raw["publicSeedTimeMinutes"]),
            "max_searches": int(raw["maxEpisodeSearchesPerRun"]),
            "max_active_downloads": int(raw["maxActiveDownloads"]),
            "minimum_free_space_gib": int(raw["minimumFreeSpaceGiB"]),
            "stalled_after_hours": int(raw["stalledAfterHours"]),
            "max_stalled_removals": int(raw["maxStalledRemovalsPerRun"]),
            "season_packs_enabled": bool(raw["seasonPacksEnabled"]),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise SeriesFallbackError(f"Invalid series fallback policy in {path}") from error
    if (
        policy["minimum_resolution"] < 720
        or policy["english_fallback_days"] < 0
        or policy["public_minimum_seeders"] < 1
        or policy["public_seed_minutes"] < 1
        or policy["max_searches"] < 1
        or policy["max_active_downloads"] < 1
        or policy["minimum_free_space_gib"] < 1
        or policy["stalled_after_hours"] < 1
        or policy["max_stalled_removals"] < 1
    ):
        raise SeriesFallbackError(f"Unsafe series fallback policy in {path}")
    return policy


def request_age_days(request: dict[str, Any], now: datetime) -> float:
    value = str(request.get("createdAt") or "")
    if not value:
        return 0.0
    try:
        created = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return max(0.0, (now - created).total_seconds() / 86400)


def language_floor(request: dict[str, Any], policy: dict[str, Any], now: datetime) -> LanguageRank:
    if request_age_days(request, now) >= policy["english_fallback_days"]:
        return LanguageRank.ENGLISH
    return LanguageRank.CASTILIAN


def source_policy(release: dict[str, Any], policy: dict[str, Any]) -> SourcePolicy | None:
    indexer = str(release.get("indexer") or "").casefold()
    if "docspedia" in indexer:
        return None
    for source in PRIVATE_SOURCES:
        if source.name in indexer:
            return source
    if not policy["public_enabled"]:
        return None
    return SourcePolicy(
        "public",
        False,
        int(release.get("indexerPriority", 100) or 100),
        int(policy["public_minimum_seeders"]),
        int(policy["public_seed_minutes"]),
    )


def exact_single_episode(release: dict[str, Any], episode: dict[str, Any]) -> bool:
    return release_episode_numbers(release, episode) == {
        int(episode["episodeNumber"])
    }


def release_episode_numbers(
    release: dict[str, Any], episode: dict[str, Any]
) -> set[int]:
    season = int(episode["seasonNumber"])
    number = int(episode["episodeNumber"])
    release_season = release.get("seasonNumber")
    numbers = release.get("episodeNumbers")
    if release_season is not None and isinstance(numbers, list):
        try:
            if int(release_season) != season:
                return set()
            return {int(value) for value in numbers if int(value) > 0}
        except (TypeError, ValueError):
            return set()
    marker = re.compile(
        rf"(?<![A-Z0-9])S0*{season}E0*{number}(?![0-9])", re.IGNORECASE
    )
    return {number} if marker.search(str(release.get("title") or "")) else set()


def release_coverage_allowed(
    release: dict[str, Any],
    episode: dict[str, Any],
    missing_numbers: set[int] | None,
    season_packs_enabled: bool,
) -> bool:
    coverage = release_episode_numbers(release, episode)
    if coverage == {int(episode["episodeNumber"])}:
        return True
    return bool(
        season_packs_enabled
        and missing_numbers
        and len(coverage) > 1
        and coverage == missing_numbers
    )


def candidate_allowed(
    release: dict[str, Any],
    episode: dict[str, Any],
    floor: LanguageRank,
    policy: dict[str, Any],
    missing_numbers: set[int] | None = None,
) -> bool:
    title = str(release.get("title") or "")
    source = source_policy(release, policy)
    return bool(
        source
        and release.get("approved") is True
        and not release.get("rejected", False)
        and release.get("downloadAllowed", True) is not False
        and release.get("protocol") == "torrent"
        and release.get("downloadUrl")
        and release_coverage_allowed(
            release,
            episode,
            missing_numbers,
            bool(policy["season_packs_enabled"]),
        )
        and not dangerous_release_title(title)
        and not unacceptable_source_title(title)
        and GRAB.title_resolution(release) >= policy["minimum_resolution"]
        and int(release.get("seeders", 0) or 0) >= source.minimum_seeders
        and language_rank(release) >= floor
    )


def candidate_sort_key(
    release: dict[str, Any], policy: dict[str, Any]
) -> tuple[int, int, int, int, int, str]:
    source = source_policy(release, policy)
    assert source is not None
    return (
        -int(language_rank(release)),
        0 if source.private else 1,
        source.priority,
        -int(release.get("customFormatScore", 0) or 0),
        -int(release.get("seeders", 0) or 0),
        str(release.get("title") or ""),
    )


def select_candidate(
    releases: list[dict[str, Any]],
    episode: dict[str, Any],
    floor: LanguageRank,
    policy: dict[str, Any],
    missing_numbers: set[int] | None = None,
) -> dict[str, Any] | None:
    candidates = eligible_candidates(
        releases, episode, floor, policy, missing_numbers
    )
    return candidates[0] if candidates else None


def eligible_candidates(
    releases: list[dict[str, Any]],
    episode: dict[str, Any],
    floor: LanguageRank,
    policy: dict[str, Any],
    missing_numbers: set[int] | None = None,
) -> list[dict[str, Any]]:
    candidates = [
        release
        for release in releases
        if candidate_allowed(
            release, episode, floor, policy, missing_numbers
        )
    ]
    candidates.sort(key=lambda item: candidate_sort_key(item, policy))
    return candidates


def candidates_with_retry(
    fetch: Any,
    classify: Any,
    label: str,
    delay_seconds: float = 2,
) -> list[dict[str, Any]]:
    last_error: SeriesFallbackError | None = None
    completed = False
    for attempt in range(2):
        try:
            candidates = classify(fetch())
            completed = True
            if candidates or attempt == 1:
                return candidates
        except SeriesFallbackError as error:
            last_error = error
            if attempt == 1:
                break
        print(f"SEARCH RETRY: {label}")
        time.sleep(delay_seconds)
    if last_error is not None and not completed:
        raise last_error
    return []


def normalize_direct_latteam_release(
    release: dict[str, Any], expected_tvdb_id: int
) -> dict[str, Any] | None:
    """Add the Sonarr scope fields missing from Prowlarr's UNIT3D result."""
    if (
        "lat-team" not in str(release.get("indexer") or "").casefold()
        or int(release.get("tvdbId", 0) or 0) != expected_tvdb_id
    ):
        return None
    title = str(release.get("title") or "")
    season_match = re.search(
        r"(?i)(?<![A-Z0-9])S(\d{1,2})(?=E\d|[^A-Z0-9]|$)", title
    )
    if season_match is None:
        return None
    season = int(season_match.group(1))
    episode_numbers = {
        int(value)
        for value in re.findall(r"(?i)E(\d{1,3})(?![0-9])", title)
        if int(value) > 0
    }
    normalized = dict(release)
    normalized.update(
        {
            "approved": True,
            "customFormatScore": int(release.get("customFormatScore", 0) or 0),
            "downloadAllowed": release.get("downloadAllowed") is not False,
            "episodeNumbers": sorted(episode_numbers),
            "fullSeason": not episode_numbers,
            "indexerPriority": 1,
            "rejected": False,
            "seasonNumber": season,
        }
    )
    return normalized


def direct_latteam_releases(
    query: str,
    tvdb_id: int,
    indexer_ids: list[int],
    prowlarr_key: str,
) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for indexer_id in indexer_ids:
        try:
            results = GRAB.prowlarr_search(
                PROWLARR_URL,
                prowlarr_key,
                query,
                indexer_id,
                "tv",
            )
        except GRAB.GrabError as error:
            print(f"LAT-TEAM DIRECT SEARCH SKIP: reason={error}")
            continue
        releases.extend(
            normalized
            for item in results
            if (normalized := normalize_direct_latteam_release(item, tvdb_id))
            is not None
        )
    return releases


def merge_release_results(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for release in group:
            merged.setdefault(release_tag(release), release)
    return list(merged.values())


def enrich_btarg(
    releases: list[dict[str, Any]],
    expected_imdb: str | None,
    client: BTArgClient,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for release in releases:
        if "btarg" not in str(release.get("indexer") or "").casefold():
            enriched.append(release)
            continue
        try:
            candidate = enrich_release(dict(release), client, expected_imdb)
        except BTArgError as error:
            print(f"BTARG DETAIL SKIP: title={release.get('title', '')} reason={error}")
            continue
        if candidate.get("downloadAllowed") is not False:
            enriched.append(candidate)
    return enriched


def torrent_tags(item: dict[str, Any]) -> set[str]:
    return {
        value.strip()
        for value in str(item.get("tags") or "").split(",")
        if value.strip()
    }


def active_episode_tags(torrents: list[dict[str, Any]]) -> set[str]:
    return {
        tag
        for torrent in torrents
        if "language-mismatch" not in torrent_tags(torrent)
        for tag in torrent_tags(torrent)
        if tag.startswith("sonarr-episode-")
    }


def inflight_episode_tags(torrents: list[dict[str, Any]]) -> set[str]:
    return {
        tag
        for torrent in torrents
        if "language-mismatch" not in torrent_tags(torrent)
        and "series-fallback-import-verified" not in torrent_tags(torrent)
        for tag in torrent_tags(torrent)
        if tag.startswith("sonarr-episode-")
    }


def blocked_release_tags(torrents: list[dict[str, Any]]) -> set[str]:
    return {
        tag
        for torrent in torrents
        if "language-mismatch" in torrent_tags(torrent)
        for tag in torrent_tags(torrent)
        if tag.startswith("release-series-")
    }


def release_tag(release: dict[str, Any]) -> str:
    stable = "|".join(
        str(release.get(key) or "") for key in ("guid", "indexer", "title")
    )
    return "release-series-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:12]


def tag_number(tags: set[str], prefix: str) -> int | None:
    for tag in tags:
        match = re.fullmatch(rf"{re.escape(prefix)}([1-9][0-9]*)", tag)
        if match:
            return int(match.group(1))
    return None


def tag_numbers(tags: set[str], prefix: str) -> set[int]:
    return {
        int(match.group(1))
        for tag in tags
        if (match := re.fullmatch(rf"{re.escape(prefix)}([1-9][0-9]*)", tag))
    }


def fallback_torrents(torrents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in torrents if "series-fallback" in torrent_tags(item)]


def active_fallback_torrents(torrents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for torrent in fallback_torrents(torrents):
        tags = torrent_tags(torrent)
        if (
            "series-fallback-import-verified" not in tags
            and "language-mismatch" not in tags
            and str(torrent.get("state") or "") not in {"stoppedDL", "pausedDL"}
        ):
            active.append(torrent)
    return active


def stalled_public_torrents(
    torrents: list[dict[str, Any]], now_timestamp: int, stalled_after_hours: int
) -> list[dict[str, Any]]:
    minimum_age = stalled_after_hours * 3600
    stalled_states = {"metaDL", "stalledDL", "unknownDL"}
    return [
        item
        for item in fallback_torrents(torrents)
        if "public" in torrent_tags(item)
        and "private" not in torrent_tags(item)
        and float(item.get("progress", 0) or 0) < 1
        and str(item.get("state") or "") in stalled_states
        and int(item.get("dlspeed", 0) or 0) == 0
        and now_timestamp - int(item.get("added_on", now_timestamp) or now_timestamp)
        >= minimum_age
    ]


def release_fingerprint_from_torrent(torrent: dict[str, Any]) -> str | None:
    return next(
        (
            tag
            for tag in torrent_tags(torrent)
            if tag.startswith("release-series-")
        ),
        None,
    )


def remove_stalled_public(
    qbit: QBittorrentClient,
    torrents: list[dict[str, Any]],
    rejected: set[str],
    policy: dict[str, Any],
    apply: bool,
) -> int:
    candidates = stalled_public_torrents(
        torrents,
        int(time.time()),
        int(policy["stalled_after_hours"]),
    )[: int(policy["max_stalled_removals"])]
    for torrent in candidates:
        fingerprint = release_fingerprint_from_torrent(torrent)
        print(
            f"{'REMOVE' if apply else 'WOULD REMOVE'} STALLED PUBLIC: "
            f"progress={float(torrent.get('progress', 0) or 0) * 100:.1f}% "
            f"state={torrent.get('state')}"
        )
        if not apply:
            continue
        if fingerprint:
            rejected.add(fingerprint)
        qbit.post_form(
            "/api/v2/torrents/delete",
            {"hashes": str(torrent["hash"]), "deleteFiles": "true"},
        )
    return len(candidates)


def remove_unsafe_public(
    qbit: QBittorrentClient,
    torrents: list[dict[str, Any]],
    rejected: set[str],
    apply: bool,
) -> int:
    candidates: list[dict[str, Any]] = []
    for torrent in fallback_torrents(torrents):
        tags = torrent_tags(torrent)
        if "public" not in tags or "private" in tags:
            continue
        query = urllib.parse.urlencode({"hash": str(torrent["hash"])})
        files = qbit.get_json(f"/api/v2/torrents/files?{query}")
        unsafe = dangerous_torrent_paths(
            str(item.get("name", "")) for item in files
        )
        if unsafe:
            candidates.append(torrent)

    for torrent in candidates:
        fingerprint = release_fingerprint_from_torrent(torrent)
        print(
            f"{'REMOVE' if apply else 'WOULD REMOVE'} UNSAFE PUBLIC: "
            "executable-like payload"
        )
        if not apply:
            continue
        if fingerprint:
            rejected.add(fingerprint)
        qbit.post_form(
            "/api/v2/torrents/delete",
            {"hashes": str(torrent["hash"]), "deleteFiles": "true"},
        )
    return len(candidates)


def audio_values(media_file: dict[str, Any]) -> set[str]:
    values = {
        str(item.get("name") or "").strip().casefold()
        for item in media_file.get("languages") or []
        if isinstance(item, dict) and item.get("name")
    }
    raw = str((media_file.get("mediaInfo") or {}).get("audioLanguages") or "")
    values.update(
        value.strip().casefold()
        for value in re.split(r"[,/;+]", raw)
        if value.strip()
    )
    return values


def detected_audio_rank(media_file: dict[str, Any]) -> LanguageRank:
    values = audio_values(media_file)
    if any("latino" in value for value in values):
        return LanguageRank.LATINO
    if any(
        value in SPANISH_AUDIO_VALUES
        or "spanish" in value
        or "castilian" in value
        for value in values
    ):
        return LanguageRank.CASTILIAN
    if values & ENGLISH_AUDIO_VALUES:
        return LanguageRank.ENGLISH
    return LanguageRank.UNKNOWN


def request_completed_imports(
    qbit: QBittorrentClient,
    torrents: list[dict[str, Any]],
    sonarr_key: str,
    apply: bool,
) -> int:
    """Ask Sonarr to scan completed direct grabs exactly once."""
    requested = 0
    for torrent in fallback_torrents(torrents):
        tags = torrent_tags(torrent)
        if (
            float(torrent.get("progress", 0) or 0) < 1
            or "series-fallback-import-requested" in tags
            or "series-fallback-import-verified" in tags
            or "language-mismatch" in tags
        ):
            continue
        content_path = str(torrent.get("content_path") or "")
        if not content_path.startswith("/data/Downloads/"):
            print("IMPORT REVIEW: completed series path is outside Downloads")
            continue
        print(
            f"{'REQUEST' if apply else 'WOULD REQUEST'} SONARR IMPORT: "
            f"episodes={len(tag_numbers(tags, 'sonarr-episode-'))}"
        )
        if not apply:
            requested += 1
            continue
        post_json(
            SONARR_URL,
            "/api/v3/command",
            sonarr_key,
            {
                "name": "DownloadedEpisodesScan",
                "path": content_path,
                "downloadClientId": str(torrent["hash"]),
                "importMode": "Auto",
            },
        )
        qbit.post_form(
            "/api/v2/torrents/addTags",
            {
                "hashes": str(torrent["hash"]),
                "tags": "series-fallback-import-requested",
            },
        )
        torrent["tags"] = (
            f"{torrent.get('tags', '')},series-fallback-import-requested"
        )
        requested += 1
    return requested


def expected_language_from_tags(tags: set[str]) -> LanguageRank:
    mapping = {
        "fallback-language-latino": LanguageRank.LATINO,
        "fallback-language-castilian": LanguageRank.CASTILIAN,
        "fallback-language-english": LanguageRank.ENGLISH,
    }
    return next((rank for tag, rank in mapping.items() if tag in tags), LanguageRank.UNKNOWN)


def reconcile_imports(
    qbit: QBittorrentClient,
    torrents: list[dict[str, Any]],
    sonarr_key: str,
    apply: bool,
) -> tuple[int, int]:
    verified = 0
    mismatches = 0
    for torrent in fallback_torrents(torrents):
        tags = torrent_tags(torrent)
        if (
            "series-fallback-import-verified" in tags
            or "language-mismatch" in tags
            or float(torrent.get("progress", 0) or 0) < 1
        ):
            continue
        episode_ids = tag_numbers(tags, "sonarr-episode-")
        if not episode_ids:
            continue
        media_files: dict[int, dict[str, Any]] = {}
        ready = True
        try:
            for episode_id in sorted(episode_ids):
                episode = get_json(
                    SONARR_URL, f"/api/v3/episode/{episode_id}", sonarr_key
                )
                file_id = int(episode.get("episodeFileId", 0) or 0)
                if not episode.get("hasFile") or file_id <= 0:
                    ready = False
                    break
                if file_id not in media_files:
                    media_files[file_id] = get_json(
                        SONARR_URL, f"/api/v3/episodefile/{file_id}", sonarr_key
                    )
        except SeriesFallbackError as error:
            print(f"IMPORT CHECK SKIP: {error}")
            continue
        if not ready:
            continue
        original_file_ids = tag_numbers(tags, "sonarr-original-file-")
        if (
            "series-language-upgrade" in tags
            and original_file_ids.intersection(media_files)
        ):
            print(
                "IMPORT PENDING: Sonarr still references an original "
                "episode file"
            )
            continue
        expected = expected_language_from_tags(tags)
        detected = [detected_audio_rank(item) for item in media_files.values()]
        if not detected or any(rank == LanguageRank.UNKNOWN for rank in detected):
            print("IMPORT REVIEW: Sonarr imported the episode but audio is undefined")
            continue
        minimum = (
            LanguageRank.CASTILIAN
            if expected >= LanguageRank.CASTILIAN
            else LanguageRank.ENGLISH
        )
        tag = (
            "series-fallback-import-verified"
            if all(rank >= minimum for rank in detected)
            else "language-mismatch"
        )
        print(
            f"{'VERIFY' if tag.endswith('verified') else 'MISMATCH'} IMPORT: "
            f"episodes={len(episode_ids)} audio={','.join(rank.name.lower() for rank in detected)}"
        )
        if apply:
            qbit.post_form(
                "/api/v2/torrents/addTags",
                {"hashes": str(torrent["hash"]), "tags": tag},
            )
            torrent["tags"] = f"{torrent.get('tags', '')},{tag}"
        if tag.endswith("verified"):
            verified += 1
        else:
            mismatches += 1
    return verified, mismatches


def validate_pack_members(
    paths: list[str], season: int, expected_numbers: set[int]
) -> None:
    found: list[int] = []
    marker = re.compile(
        rf"(?<![A-Z0-9])S0*{season}E0*([1-9][0-9]*)(?![0-9])",
        re.IGNORECASE,
    )
    for value in paths:
        suffix = Path(value).suffix.casefold()
        if suffix not in VIDEO_EXTENSIONS:
            continue
        matches = marker.findall(value)
        if len(matches) != 1:
            raise GRAB.GrabError(
                "Season pack contains a video without one exact episode marker."
            )
        found.append(int(matches[0]))
    if set(found) != expected_numbers or len(found) != len(expected_numbers):
        raise GRAB.GrabError(
            "Season pack members do not exactly cover the expected episodes."
        )


def free_space_allows(
    download_root: Path, release_size: int, minimum_free_space_gib: int
) -> bool:
    reserve = minimum_free_space_gib * 1024**3
    return shutil.disk_usage(download_root).free - max(0, release_size) >= reserve


def status_payload(
    torrents: list[dict[str, Any]],
    series_by_id: dict[int, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    downloads: list[dict[str, Any]] = []
    for torrent in fallback_torrents(torrents):
        tags = torrent_tags(torrent)
        series_id = tag_number(tags, "sonarr-series-")
        series = series_by_id.get(series_id or -1, {})
        if "series-fallback-import-verified" in tags:
            status = "imported"
        elif "language-mismatch" in tags:
            status = "language-mismatch"
        elif float(torrent.get("progress", 0) or 0) >= 1:
            status = "awaiting-import"
        else:
            status = str(torrent.get("state") or "unknown")
        downloads.append(
            {
                "series": str(series.get("title") or f"Sonarr {series_id or '?'}"),
                "episodes": len(tag_numbers(tags, "sonarr-episode-")),
                "progressPercent": round(float(torrent.get("progress", 0) or 0) * 100, 1),
                "status": status,
            }
        )
    return {
        "activeDownloads": len(active_fallback_torrents(torrents)),
        "generatedAt": datetime.now(UTC).isoformat(),
        "limits": {
            "maxActiveDownloads": int(policy["max_active_downloads"]),
            "minimumFreeSpaceGiB": int(policy["minimum_free_space_gib"]),
            "stalledAfterHours": int(policy["stalled_after_hours"]),
        },
        "downloads": downloads,
    }


def write_status(stack: Path, payload: dict[str, Any]) -> None:
    state_dir = stack / "state"
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    json_path = state_dir / "series-fallback-status.json"
    html_path = state_dir / "series-fallback-status.html"
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item['series']))}</td>"
        f"<td>{int(item['episodes'])}</td>"
        f"<td>{float(item['progressPercent']):.1f}%</td>"
        f"<td>{html.escape(str(item['status']))}</td>"
        "</tr>"
        for item in payload["downloads"]
    ) or "<tr><td colspan='4'>Sin descargas activas</td></tr>"
    document = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Fallback de series</title>
<style>body{{font-family:system-ui;background:#101827;color:#eef2ff;max-width:900px;margin:40px auto;padding:0 20px}}
table{{width:100%;border-collapse:collapse;background:#1f2937}}th,td{{padding:10px;border-bottom:1px solid #374151;text-align:left}}
small{{color:#a5b4fc}}</style></head><body><h1>Fallback de series</h1>
<p>Activas: {int(payload['activeDownloads'])}/{int(payload['limits']['maxActiveDownloads'])}</p>
<table><thead><tr><th>Serie</th><th>Episodios</th><th>Progreso</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table>
<p><small>Actualizado: {html.escape(str(payload['generatedAt']))}</small></p></body></html>"""
    for path, content in (
        (json_path, json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"),
        (html_path, document),
    ):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o644)
        temporary.replace(path)


def queued_episode_ids(payload: Any) -> set[int]:
    records = payload.get("records", []) if isinstance(payload, dict) else []
    queued: set[int] = set()
    for item in records:
        for value in item.get("episodeIds", []):
            if int(value or 0) > 0:
                queued.add(int(value))
        if int(item.get("episodeId", 0) or 0) > 0:
            queued.add(int(item["episodeId"]))
    return queued


def aired(value: Any, now: datetime) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= now


def missing_episodes(
    episodes: list[dict[str, Any]],
    seasons: set[int],
    queued: set[int],
    existing_tags: set[str],
    now: datetime,
) -> list[dict[str, Any]]:
    result = [
        episode
        for episode in episodes
        if int(episode.get("seasonNumber", 0) or 0) in seasons
        and episode.get("monitored") is True
        and not episode.get("hasFile", False)
        and not int(episode.get("episodeFileId", 0) or 0)
        and int(episode["id"]) not in queued
        and f"sonarr-episode-{episode['id']}" not in existing_tags
        and aired(episode.get("airDateUtc"), now)
    ]
    return sorted(
        result,
        key=lambda item: (
            int(item.get("seasonNumber", 0)),
            int(item.get("episodeNumber", 0)),
        ),
    )


def upgradeable_seasons(
    episodes: list[dict[str, Any]],
    seasons: set[int],
    files_by_id: dict[int, dict[str, Any]],
    queued: set[int],
    inflight_tags: set[str],
    now: datetime,
) -> dict[int, list[dict[str, Any]]]:
    by_season: dict[int, list[dict[str, Any]]] = {}
    for episode in episodes:
        season = int(episode.get("seasonNumber", 0) or 0)
        if (
            season not in seasons
            or episode.get("monitored") is not True
            or not aired(episode.get("airDateUtc"), now)
        ):
            continue
        by_season.setdefault(season, []).append(episode)

    result: dict[int, list[dict[str, Any]]] = {}
    for season, season_episodes in by_season.items():
        if not season_episodes:
            continue
        targets: list[dict[str, Any]] = []
        for episode in season_episodes:
            episode_id = int(episode["id"])
            file_id = int(episode.get("episodeFileId", 0) or 0)
            episode_file = files_by_id.get(file_id)
            current_rank = language_rank(episode_file)
            needs_latino = (
                not episode.get("hasFile")
                or episode_file is None
                or current_rank < LanguageRank.CASTILIAN
            )
            if not needs_latino:
                continue
            if (
                episode_id in queued
                or f"sonarr-episode-{episode_id}" in inflight_tags
            ):
                targets = []
                break
            targets.append(episode)
        if targets:
            result[season] = sorted(
                targets,
                key=lambda item: int(item.get("episodeNumber", 0)),
            )
    return result


def upgradeable_episodes(
    episodes: list[dict[str, Any]],
    seasons: set[int],
    files_by_id: dict[int, dict[str, Any]],
    queued: set[int],
    inflight_tags: set[str],
    now: datetime,
) -> list[dict[str, Any]]:
    result = []
    for episode in episodes:
        episode_id = int(episode["id"])
        file_id = int(episode.get("episodeFileId", 0) or 0)
        episode_file = files_by_id.get(file_id)
        if not (
            int(episode.get("seasonNumber", 0) or 0) in seasons
            and episode.get("monitored") is True
            and episode.get("hasFile") is True
            and episode_file is not None
            and language_rank(episode_file) < LanguageRank.CASTILIAN
            and episode_id not in queued
            and f"sonarr-episode-{episode_id}" not in inflight_tags
            and aired(episode.get("airDateUtc"), now)
        ):
            continue
        result.append(episode)
    return sorted(
        result,
        key=lambda item: (
            int(item.get("seasonNumber", 0)),
            int(item.get("episodeNumber", 0)),
        ),
    )


def language_upgrade_candidates(
    releases: list[dict[str, Any]],
    episode: dict[str, Any],
    installed_file: dict[str, Any],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = []
    for release in releases:
        source = source_policy(release, policy)
        title = str(release.get("title") or "")
        if not (
            source
            and source.private
            and (
                release.get("approved") is True
                or (
                    release.get("rejected", False)
                    and bool(rejection_reasons(release))
                    and all(
                        rejection_is_overridable(reason)
                        for reason in rejection_reasons(release)
                    )
                )
            )
            and release_is_safe_language_upgrade(installed_file, release)
            and release.get("protocol") == "torrent"
            and release.get("downloadUrl")
            and release_episode_numbers(release, episode)
            == {int(episode["episodeNumber"])}
            and not dangerous_release_title(title)
            and not unacceptable_source_title(title)
            and GRAB.title_resolution(release) >= policy["minimum_resolution"]
            and int(release.get("seeders", 0) or 0) >= source.minimum_seeders
        ):
            continue
        candidates.append(release)
    candidates.sort(key=lambda item: candidate_sort_key(item, policy))
    return candidates


def latino_season_pack_candidates(
    releases: list[dict[str, Any]],
    season: int,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = []
    for release in releases:
        source = source_policy(release, policy)
        title = str(release.get("title") or "")
        if not (
            source
            and source.private
            and release.get("fullSeason") is True
            and int(release.get("seasonNumber", -1) or -1) == season
            and (
                release.get("approved") is True
                or (
                    release.get("rejected", False)
                    and bool(rejection_reasons(release))
                    and all(
                        rejection_is_overridable(reason)
                        for reason in rejection_reasons(release)
                    )
                )
            )
            and release.get("downloadAllowed", True) is not False
            and release.get("protocol") == "torrent"
            and release.get("downloadUrl")
            and language_rank(release) >= LanguageRank.LATINO
            and not dangerous_release_title(title)
            and not unacceptable_source_title(title)
            and GRAB.title_resolution(release) >= policy["minimum_resolution"]
            and int(release.get("seeders", 0) or 0) >= source.minimum_seeders
        ):
            continue
        candidates.append(release)
    candidates.sort(key=lambda item: candidate_sort_key(item, policy))
    return candidates


def rotate_after(items: list[dict[str, Any]], last_id: int | None) -> list[dict[str, Any]]:
    if not items or last_id is None:
        return items
    for index, item in enumerate(items):
        if int(item["id"]) == last_id:
            return items[index + 1 :] + items[: index + 1]
    return items


def load_state(path: Path) -> tuple[dict[str, int], set[str], int | None]:
    if not path.is_file():
        return {}, set(), None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cursors = payload.get("requestCursors", {})
        rejected = (
            payload.get("inspectionRejectedReleases", [])
            if payload.get("inspectionPolicyVersion") == INSPECTION_POLICY_VERSION
            else []
        )
        return (
            {str(key): int(value) for key, value in cursors.items()},
            {str(value) for value in rejected if str(value).startswith("release-series-")},
            int(payload["lastRequestId"]) if payload.get("lastRequestId") else None,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}, set(), None


def save_state(
    path: Path,
    cursors: dict[str, int],
    rejected: set[str],
    last_request_id: int | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "inspectionRejectedReleases": sorted(rejected),
                "inspectionPolicyVersion": INSPECTION_POLICY_VERSION,
                "lastRequestId": last_request_id,
                "requestCursors": cursors,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def rotate_requests(
    requests: list[dict[str, Any]], last_request_id: int | None
) -> list[dict[str, Any]]:
    ordered = sorted(requests, key=lambda item: int(item.get("id", 0)))
    if not ordered or last_request_id is None:
        return ordered
    for index, request in enumerate(ordered):
        if int(request.get("id", 0)) == last_request_id:
            return ordered[index + 1 :] + ordered[: index + 1]
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=STACK)
    parser.add_argument("--request-id", type=int)
    parser.add_argument("--series")
    parser.add_argument("--max-searches", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    stack = args.stack_dir
    policy = read_policy(stack / "private-release-policy.json")
    max_searches = args.max_searches or int(policy["max_searches"])
    if max_searches < 1:
        raise SeriesFallbackError("--max-searches must be positive")

    sonarr_key = GRAB.read_api_key(stack / "config/sonarr/config.xml")
    prowlarr_key = GRAB.read_api_key(stack / "config/prowlarr/config.xml")
    try:
        prowlarr_indexers = get_json(
            PROWLARR_URL, "/api/v1/indexer", prowlarr_key, timeout=30
        )
        latteam_indexer_ids = [
            int(item["id"])
            for item in prowlarr_indexers
            if item.get("enable")
            and "lat-team" in str(item.get("name") or "").casefold()
        ]
    except SeriesFallbackError as error:
        print(f"LAT-TEAM DIRECT DISCOVERY SKIP: reason={error}")
        latteam_indexer_ids = []
    series_items = get_json(SONARR_URL, "/api/v3/series", sonarr_key)
    series_by_tvdb = {
        int(item.get("tvdbId", 0)): item
        for item in series_items
        if int(item.get("tvdbId", 0) or 0) > 0
    }
    series_by_id = {
        int(item["id"]): item
        for item in series_items
        if int(item.get("id", 0) or 0) > 0
    }
    queue = get_json(
        SONARR_URL,
        "/api/v3/queue?" + urllib.parse.urlencode({"page": 1, "pageSize": 1000}),
        sonarr_key,
    )
    queued = queued_episode_ids(queue)

    username, password = read_credentials(stack / "secrets/qbittorrent.json")
    qbit = QBittorrentClient(QBITTORRENT_URL, username, password)
    qbit.login()
    torrents = qbit.get_json("/api/v2/torrents/info")

    state_path = stack / "state/series-fallback.json"
    cursors, inspection_rejected, last_request_id = load_state(state_path)
    unsafe_removed = remove_unsafe_public(
        qbit,
        torrents,
        inspection_rejected,
        args.apply,
    )
    if args.apply and unsafe_removed:
        save_state(
            state_path,
            cursors,
            inspection_rejected,
            last_request_id,
        )
        torrents = qbit.get_json("/api/v2/torrents/info")
    import_requests = request_completed_imports(
        qbit, torrents, sonarr_key, args.apply
    )
    verified, mismatches = reconcile_imports(
        qbit, torrents, sonarr_key, args.apply
    )
    removed = remove_stalled_public(
        qbit,
        torrents,
        inspection_rejected,
        policy,
        args.apply,
    )
    if args.apply and (
        import_requests or verified or mismatches or removed or unsafe_removed
    ):
        save_state(
            state_path,
            cursors,
            inspection_rejected,
            last_request_id,
        )
        torrents = qbit.get_json("/api/v2/torrents/info")
    write_status(stack, status_payload(torrents, series_by_id, policy))
    existing_tags = active_episode_tags(torrents)
    inflight_tags = inflight_episode_tags(torrents)
    blocked_tags = blocked_release_tags(torrents)
    active_downloads = len(active_fallback_torrents(torrents))
    if args.apply and active_downloads >= int(policy["max_active_downloads"]):
        print(
            "SERIES FALLBACK CAP: "
            f"active={active_downloads} max={policy['max_active_downloads']}"
        )
        return 0

    requests = monitored_series_targets(series_items, seerr_requests(stack))
    if args.request_id is not None:
        requests = [
            item
            for item in requests
            if int(item.get("id", -1)) == args.request_id
        ]

    now = datetime.now(UTC)
    searches = 0
    btarg = BTArgClient(
        stack / "secrets/prowlarr-private-indexers.json",
        BTArgCache(stack / "state/btarg-language-cache.json"),
    )

    for request in rotate_requests(requests, last_request_id):
        last_request_id = int(request.get("id", 0))
        tvdb_id = int(request["media"]["tvdbId"])
        series = series_by_tvdb.get(tvdb_id)
        if not series:
            print(f"SERIES SKIP: {target_label(request)} tvdb={tvdb_id} not found in Sonarr")
            continue
        if args.series and args.series.casefold() not in str(series.get("title") or "").casefold():
            continue
        seasons = requested_seasons(request)
        if not seasons:
            continue
        episodes = get_json(
            SONARR_URL,
            "/api/v3/episode?" + urllib.parse.urlencode({"seriesId": series["id"]}),
            sonarr_key,
        )
        episode_files = get_json(
            SONARR_URL,
            "/api/v3/episodefile?"
            + urllib.parse.urlencode({"seriesId": series["id"]}),
            sonarr_key,
        )
        files_by_id = {
            int(item["id"]): item
            for item in episode_files
            if int(item.get("id", 0) or 0) > 0
        }
        season_upgrades = upgradeable_seasons(
            episodes,
            seasons,
            files_by_id,
            queued,
            inflight_tags,
            now,
        )
        season_search_limit = min(
            max_searches,
            searches + max(1, (max_searches - searches) // 2),
        )
        for season, covered_episodes in sorted(season_upgrades.items()):
            if searches >= season_search_limit:
                break
            searches += 1
            print(
                f"UPGRADE SEARCH: {target_label(request)} "
                f"series={series['title']} season=S{season:02d} "
                "language-floor=latino"
            )
            def fetch_season_releases() -> list[dict[str, Any]]:
                # Query the priority-one source before Sonarr fans out to all
                # indexers. This avoids overlapping Lat-Team requests hitting
                # the tracker's request-delay protection.
                direct_releases = direct_latteam_releases(
                    f"{series['title']} S{season:02d}",
                    tvdb_id,
                    latteam_indexer_ids,
                    prowlarr_key,
                )
                sonarr_releases = get_json(
                    SONARR_URL,
                    "/api/v3/release?"
                    + urllib.parse.urlencode(
                        {
                            "seriesId": series["id"],
                            "seasonNumber": season,
                        }
                    ),
                    sonarr_key,
                    timeout=180,
                )
                return merge_release_results(sonarr_releases, direct_releases)

            def classify_season_releases(
                releases: list[dict[str, Any]],
            ) -> list[dict[str, Any]]:
                enriched = enrich_btarg(
                    releases,
                    str(series.get("imdbId") or "") or None,
                    btarg,
                )
                eligible = [
                    item
                    for item in enriched
                    if release_tag(item)
                    not in (blocked_tags | inspection_rejected)
                ]
                return latino_season_pack_candidates(
                    eligible,
                    season,
                    policy,
                )

            try:
                candidates = candidates_with_retry(
                    fetch_season_releases,
                    classify_season_releases,
                    f"series={series['title']} season=S{season:02d}",
                )
            except SeriesFallbackError as error:
                print(
                    f"UPGRADE SEARCH SKIP: season=S{season:02d} "
                    f"reason={error}"
                )
                continue
            expected_numbers = {
                int(item["episodeNumber"])
                for item in episodes
                if int(item.get("seasonNumber", 0) or 0) == season
                and item.get("monitored") is True
                and aired(item.get("airDateUtc"), now)
            }
            if not candidates:
                print(f"NO SAFE LATINO PACK: season=S{season:02d}")
                continue

            for selected in candidates[:5]:
                source = source_policy(selected, policy)
                assert source is not None and source.private
                fingerprint = release_tag(selected)
                tag_values = [
                    "private",
                    source.name,
                    "series-fallback",
                    "series-language-upgrade",
                    "series-fallback-season-pack",
                    "fallback-language-latino",
                    f"sonarr-series-{series['id']}",
                    fingerprint,
                ]
                tag_values.extend(target_tags(request, series))
                tag_values.extend(
                    f"sonarr-episode-{item['id']}"
                    for item in covered_episodes
                )
                tag_values.extend(
                    f"sonarr-original-file-{int(item.get('episodeFileId', 0))}"
                    for item in covered_episodes
                    if int(item.get("episodeFileId", 0) or 0) > 0
                )
                tags = ",".join(tag_values)
                print(
                    f"{'UPGRADE' if args.apply else 'WOULD UPGRADE'}: "
                    f"series={series['title']} season=S{season:02d} "
                    f"episodes={len(covered_episodes)} language=latino "
                    f"source={source.name} title={selected['title']}"
                )
                if not args.apply:
                    return 0
                if not free_space_allows(
                    Path("/volume1/Family/Downloads"),
                    int(selected.get("size", 0) or 0),
                    int(policy["minimum_free_space_gib"]),
                ):
                    print(
                        "SPACE GUARD: selected release would reduce free "
                        f"space below {policy['minimum_free_space_gib']} GiB"
                    )
                    save_state(
                        state_path,
                        cursors,
                        inspection_rejected,
                        last_request_id,
                    )
                    return 0
                display_name = f"{selected['title']} [LATINO]"
                try:
                    GRAB.add_to_qbittorrent(
                        qbit,
                        selected,
                        "tv",
                        tags,
                        source.seed_minutes,
                        False,
                        ratio_limit=source.ratio_limit,
                        display_name=display_name,
                        require_private=True,
                        policy_label="PRIVATE LANGUAGE UPGRADE",
                        member_validator=(
                            lambda paths,
                            season=season,
                            numbers=set(expected_numbers): validate_pack_members(
                                paths,
                                season,
                                numbers,
                            )
                        ),
                    )
                except GRAB.GrabError as error:
                    transient = isinstance(error, GRAB.TorrentFetchError)
                    if not transient:
                        inspection_rejected.add(fingerprint)
                    save_state(
                        state_path,
                        cursors,
                        inspection_rejected,
                        last_request_id,
                    )
                    print(
                        f"{'UPGRADE DELIVERY DEFERRED' if transient else 'UPGRADE INSPECTION REJECTED'}: "
                        f"season=S{season:02d} "
                        f"release={fingerprint} reason={error}"
                    )
                    continue
                save_state(
                    state_path,
                    cursors,
                    inspection_rejected,
                    last_request_id,
                )
                refreshed = qbit.get_json("/api/v2/torrents/info")
                write_status(
                    stack,
                    status_payload(refreshed, series_by_id, policy),
                )
                return 0
            print(f"NO LATINO PACK PASSED INSPECTION: season=S{season:02d}")

        missing = missing_episodes(episodes, seasons, queued, existing_tags, now)
        upgrades = upgradeable_episodes(
            episodes,
            seasons,
            files_by_id,
            queued,
            inflight_tags,
            now,
        )
        request_key = str(request["id"])
        work = rotate_after(missing + upgrades, cursors.get(request_key))
        missing_ids = {int(item["id"]) for item in missing}
        fallback_floor = language_floor(request, policy, now)

        for episode in work:
            if searches >= max_searches:
                if args.apply:
                    save_state(
                        state_path,
                        cursors,
                        inspection_rejected,
                        last_request_id,
                    )
                print(f"SERIES FALLBACK LIMIT: searched={searches} dispatched=0")
                return 0
            searches += 1
            label = f"S{int(episode['seasonNumber']):02d}E{int(episode['episodeNumber']):02d}"
            is_upgrade = int(episode["id"]) not in missing_ids
            floor = (
                LanguageRank.CASTILIAN if is_upgrade else fallback_floor
            )
            print(
                f"{'UPGRADE ' if is_upgrade else ''}SEARCH: "
                f"{target_label(request)} series={series['title']} "
                f"episode={label} language-floor={floor.name.lower()}"
            )
            rejected_tags = blocked_tags | inspection_rejected
            same_season_missing = {
                int(item["episodeNumber"]): item
                for item in missing
                if int(item["seasonNumber"]) == int(episode["seasonNumber"])
            }

            def fetch_episode_releases() -> list[dict[str, Any]]:
                direct_releases = direct_latteam_releases(
                    f"{series['title']} {label}",
                    tvdb_id,
                    latteam_indexer_ids,
                    prowlarr_key,
                )
                sonarr_releases = get_json(
                    SONARR_URL,
                    "/api/v3/release?"
                    + urllib.parse.urlencode({"episodeId": episode["id"]}),
                    sonarr_key,
                    timeout=180,
                )
                return merge_release_results(sonarr_releases, direct_releases)

            def classify_episode_releases(
                releases: list[dict[str, Any]],
            ) -> list[dict[str, Any]]:
                enriched = enrich_btarg(
                    releases,
                    str(series.get("imdbId") or "") or None,
                    btarg,
                )
                eligible = [
                    item
                    for item in enriched
                    if release_tag(item) not in rejected_tags
                ]
                if is_upgrade:
                    installed_file = files_by_id[
                        int(episode["episodeFileId"])
                    ]
                    return language_upgrade_candidates(
                        eligible,
                        episode,
                        installed_file,
                        policy,
                    )
                return eligible_candidates(
                    eligible,
                    episode,
                    floor,
                    policy,
                    set(same_season_missing),
                )

            try:
                candidates = candidates_with_retry(
                    fetch_episode_releases,
                    classify_episode_releases,
                    f"series={series['title']} episode={label}",
                )
            except SeriesFallbackError as error:
                print(f"SEARCH SKIP: episode={label} reason={error}")
                cursors[request_key] = int(episode["id"])
                continue
            cursors[request_key] = int(episode["id"])
            if not candidates:
                print(f"NO SAFE CANDIDATE: episode={label}")
                continue

            for selected in candidates[:5]:
                source = source_policy(selected, policy)
                assert source is not None
                fingerprint = release_tag(selected)
                source_tag = source.name if source.private else "public"
                coverage = release_episode_numbers(selected, episode)
                covered_episodes = (
                    [episode]
                    if is_upgrade
                    else [
                        same_season_missing[number]
                        for number in sorted(coverage)
                        if number in same_season_missing
                    ]
                )
                if set(coverage) != {
                    int(item["episodeNumber"]) for item in covered_episodes
                }:
                    continue
                tag_values = ["private" if source.private else "public"]
                if source.private:
                    tag_values.append(source_tag)
                tag_values.extend(
                    (
                        "series-fallback",
                        f"sonarr-series-{series['id']}",
                        fingerprint,
                    )
                )
                if is_upgrade:
                    tag_values.append("series-language-upgrade")
                tag_values.extend(target_tags(request, series))
                tag_values.extend(
                    f"sonarr-episode-{item['id']}" for item in covered_episodes
                )
                tag_values.extend(
                    f"sonarr-original-file-{int(item.get('episodeFileId', 0))}"
                    for item in covered_episodes
                    if int(item.get("episodeFileId", 0) or 0) > 0
                )
                tags = ",".join(tag_values)
                language = language_rank(selected)
                language_tag = {
                    LanguageRank.LATINO: "fallback-language-latino",
                    LanguageRank.CASTILIAN: "fallback-language-castilian",
                    LanguageRank.ENGLISH: "fallback-language-english",
                }.get(language)
                if language_tag:
                    tag_values.append(language_tag)
                if len(covered_episodes) > 1:
                    tag_values.append("series-fallback-season-pack")
                tags = ",".join(tag_values)
                dispatch_label = (
                    label
                    if len(covered_episodes) == 1
                    else f"S{int(episode['seasonNumber']):02d} pack ({len(covered_episodes)} episodes)"
                )
                action = (
                    "UPGRADE"
                    if args.apply and is_upgrade
                    else "DISPATCH"
                    if args.apply
                    else "WOULD UPGRADE"
                    if is_upgrade
                    else "WOULD DISPATCH"
                )
                print(
                    f"{action}: "
                    f"series={series['title']} episode={dispatch_label} "
                    f"language={language.name.lower()} source={source_tag} "
                    f"title={selected['title']}"
                )
                if not args.apply:
                    return 0
                if not free_space_allows(
                    Path("/volume1/Family/Downloads"),
                    int(selected.get("size", 0) or 0),
                    int(policy["minimum_free_space_gib"]),
                ):
                    print(
                        "SPACE GUARD: selected release would reduce free "
                        f"space below {policy['minimum_free_space_gib']} GiB"
                    )
                    save_state(
                        state_path,
                        cursors,
                        inspection_rejected,
                        last_request_id,
                    )
                    return 0
                marker = {
                    LanguageRank.LATINO: "LATINO",
                    LanguageRank.CASTILIAN: "CASTELLANO",
                }.get(language)
                display_name = str(selected["title"])
                if marker:
                    display_name += f" [{marker}]"
                try:
                    GRAB.add_to_qbittorrent(
                        qbit,
                        selected,
                        "tv",
                        tags,
                        source.seed_minutes,
                        False,
                        ratio_limit=source.ratio_limit,
                        display_name=display_name,
                        require_private=source.private,
                        policy_label=(
                            "PRIVATE POLICY"
                            if source.private
                            else "PUBLIC FALLBACK POLICY"
                        ),
                        allow_public_private_flag=not source.private,
                        member_validator=(
                            lambda paths,
                            season=int(episode["seasonNumber"]),
                            numbers=set(coverage): validate_pack_members(
                                paths, season, numbers
                            )
                        )
                        if len(coverage) > 1
                        else None,
                    )
                except GRAB.GrabError as error:
                    transient = isinstance(error, GRAB.TorrentFetchError)
                    if not transient:
                        inspection_rejected.add(fingerprint)
                    save_state(
                        state_path,
                        cursors,
                        inspection_rejected,
                        last_request_id,
                    )
                    print(
                        f"{'DELIVERY DEFERRED' if transient else 'INSPECTION REJECTED'}: "
                        f"episode={label} "
                        f"release={fingerprint} reason={error}"
                    )
                    continue
                save_state(
                    state_path,
                    cursors,
                    inspection_rejected,
                    last_request_id,
                )
                refreshed = qbit.get_json("/api/v2/torrents/info")
                write_status(
                    stack, status_payload(refreshed, series_by_id, policy)
                )
                return 0
            print(f"NO CANDIDATE PASSED INSPECTION: episode={label}")

    if args.apply:
        save_state(
            state_path,
            cursors,
            inspection_rejected,
            last_request_id,
        )
    print(f"SERIES FALLBACK OK: searched={searches} dispatched=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SeriesFallbackError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
