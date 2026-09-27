#!/usr/bin/env python3
"""Dispatch one guarded fallback for a missing requested TV episode.

Candidates are ranked by language first, then by private/public source and
tracker priority.  Only exact single-episode torrents accepted by Sonarr are
eligible.  The selected torrent is added stopped, its privacy flag and member
paths are inspected, and only then is it started.  At most one torrent is
started per run.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
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
QBITTORRENT_URL = "http://127.0.0.1:8888"
INSPECTION_POLICY_VERSION = 2

SCRIPT_ROOT = Path(__file__).resolve().parent
for module_dir in (SCRIPT_ROOT / "media", STACK / "scripts"):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from common.btarg import BTArgCache, BTArgClient, BTArgError, enrich_release
from common.language import LanguageRank, language_rank
from common.qbittorrent import QBittorrentClient, read_credentials
from common.release_safety import dangerous_release_title, unacceptable_source_title


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
        }
    except (KeyError, TypeError, ValueError) as error:
        raise SeriesFallbackError(f"Invalid series fallback policy in {path}") from error
    if (
        policy["minimum_resolution"] < 720
        or policy["english_fallback_days"] < 0
        or policy["public_minimum_seeders"] < 1
        or policy["public_seed_minutes"] < 1
        or policy["max_searches"] < 1
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
    season = int(episode["seasonNumber"])
    number = int(episode["episodeNumber"])
    release_season = release.get("seasonNumber")
    numbers = release.get("episodeNumbers")
    if release_season is not None and isinstance(numbers, list):
        try:
            return int(release_season) == season and [int(value) for value in numbers] == [number]
        except (TypeError, ValueError):
            return False
    marker = re.compile(
        rf"(?<![A-Z0-9])S0*{season}E0*{number}(?![0-9])", re.IGNORECASE
    )
    return bool(marker.search(str(release.get("title") or "")))


def candidate_allowed(
    release: dict[str, Any],
    episode: dict[str, Any],
    floor: LanguageRank,
    policy: dict[str, Any],
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
        and exact_single_episode(release, episode)
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
) -> dict[str, Any] | None:
    candidates = eligible_candidates(releases, episode, floor, policy)
    return candidates[0] if candidates else None


def eligible_candidates(
    releases: list[dict[str, Any]],
    episode: dict[str, Any],
    floor: LanguageRank,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = [
        release
        for release in releases
        if candidate_allowed(release, episode, floor, policy)
    ]
    candidates.sort(key=lambda item: candidate_sort_key(item, policy))
    return candidates


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
    series_items = get_json(SONARR_URL, "/api/v3/series", sonarr_key)
    series_by_tvdb = {
        int(item.get("tvdbId", 0)): item
        for item in series_items
        if int(item.get("tvdbId", 0) or 0) > 0
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
    existing_tags = active_episode_tags(torrents)
    blocked_tags = blocked_release_tags(torrents)

    state_path = stack / "state/series-fallback.json"
    cursors, inspection_rejected, last_request_id = load_state(state_path)
    requests = seerr_requests(stack)
    if args.request_id is not None:
        requests = [item for item in requests if int(item.get("id", -1)) == args.request_id]

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
            print(f"SERIES SKIP: request={request['id']} tvdb={tvdb_id} not found in Sonarr")
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
        missing = missing_episodes(episodes, seasons, queued, existing_tags, now)
        request_key = str(request["id"])
        missing = rotate_after(missing, cursors.get(request_key))
        floor = language_floor(request, policy, now)

        for episode in missing:
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
            print(
                f"SEARCH: request={request['id']} series={series['title']} "
                f"episode={label} language-floor={floor.name.lower()}"
            )
            try:
                releases = get_json(
                    SONARR_URL,
                    "/api/v3/release?" + urllib.parse.urlencode({"episodeId": episode["id"]}),
                    sonarr_key,
                    timeout=180,
                )
            except SeriesFallbackError as error:
                print(f"SEARCH SKIP: episode={label} reason={error}")
                cursors[request_key] = int(episode["id"])
                continue
            releases = enrich_btarg(
                releases,
                str(series.get("imdbId") or "") or None,
                btarg,
            )
            rejected_tags = blocked_tags | inspection_rejected
            releases = [item for item in releases if release_tag(item) not in rejected_tags]
            candidates = eligible_candidates(releases, episode, floor, policy)
            cursors[request_key] = int(episode["id"])
            if not candidates:
                print(f"NO SAFE CANDIDATE: episode={label}")
                continue

            for selected in candidates[:5]:
                source = source_policy(selected, policy)
                assert source is not None
                fingerprint = release_tag(selected)
                source_tag = source.name if source.private else "public"
                tag_values = ["private" if source.private else "public"]
                if source.private:
                    tag_values.append(source_tag)
                tag_values.extend(
                    (
                        "series-fallback",
                        f"seerr-request-{request['id']}",
                        f"sonarr-series-{series['id']}",
                        f"sonarr-episode-{episode['id']}",
                        fingerprint,
                    )
                )
                tags = ",".join(tag_values)
                language = language_rank(selected)
                print(
                    f"{'DISPATCH' if args.apply else 'WOULD DISPATCH'}: "
                    f"series={series['title']} episode={label} "
                    f"language={language.name.lower()} source={source_tag} "
                    f"title={selected['title']}"
                )
                if not args.apply:
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
                    )
                except GRAB.GrabError as error:
                    inspection_rejected.add(fingerprint)
                    save_state(
                        state_path,
                        cursors,
                        inspection_rejected,
                        last_request_id,
                    )
                    print(
                        f"INSPECTION REJECTED: episode={label} "
                        f"release={fingerprint} reason={error}"
                    )
                    continue
                save_state(
                    state_path,
                    cursors,
                    inspection_rejected,
                    last_request_id,
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
