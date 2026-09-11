#!/usr/bin/env python3
"""Dispatch the best safe private release for outstanding Seerr movies.

Language is ranked before tracker priority. New requests wait for Spanish;
after the configured grace period an English/original private fallback may be
used. Public indexers are never queried by this dispatcher.
"""

import argparse
import hashlib
import importlib.util
import json
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STACK = Path("/volume1/docker/media-stack")
SCRIPT_ROOT = Path(__file__).resolve().parent
for module_dir in (SCRIPT_ROOT / "media", STACK / "scripts"):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from common.btarg import BTArgCache, BTArgClient, BTArgError, enrich_release
from common.language import language_rank
from common.qbittorrent import QBittorrentClient, read_credentials


SPEC = importlib.util.spec_from_file_location(
    "private_grab", SCRIPT_ROOT / "grab-prowlarr-release.py"
)
assert SPEC and SPEC.loader
GRAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAB)


PRIVATE_INDEXER_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "definition": "btarg",
        "tracker": "btarg",
        "priority": 2,
        "minimum_seeders": 1,
        "seed_minutes": -2,
        "ratio_limit": 1.0,
    },
    {
        "definition": "milnueve-api",
        "tracker": "milnueve",
        "priority": 4,
        "minimum_seeders": 1,
        "seed_minutes": 6360,
        "ratio_limit": None,
    },
    {
        "definition": "torznab",
        "name": "retrotoon world",
        "tracker": "retrotoon",
        "priority": 8,
        "minimum_seeders": 1,
        "seed_minutes": 4920,
        "ratio_limit": None,
    },
    {
        "definition": "dreadvault-api",
        "tracker": "dreadvault",
        "priority": 9,
        "minimum_seeders": 1,
        "seed_minutes": 7800,
        "ratio_limit": None,
    },
    {
        "definition": "torrenthaven-api",
        "tracker": "torrenthaven",
        "priority": 9,
        "minimum_seeders": 1,
        "seed_minutes": 4920,
        "ratio_limit": None,
    },
)


def api_key(path: Path) -> str:
    payload = json.loads(path.read_text())
    return str(payload["main"]["apiKey"])


def get_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)


def requests_to_dispatch(stack: Path) -> list[dict[str, Any]]:
    key = api_key(stack / "config/jellyseerr/settings.json")
    payload = get_json(
        "http://127.0.0.1:5055/api/v1/request?take=100&skip=0",
        {"X-Api-Key": key},
    )
    return [item for item in payload.get("results", []) if eligible_request(item)]


def eligible_request(item: dict[str, Any]) -> bool:
    media = item.get("media")
    return bool(
        item.get("type") == "movie"
        # 2=approved; 5=completed. A completed request becomes eligible again
        # when its library file is later removed as incorrect.
        and item.get("status") in {2, 5}
        and isinstance(media, dict)
        and media.get("tmdbId")
        # 5=available. Other media states still require attention.
        and media.get("status") != 5
    )


def torrent_tag_set(torrent: dict[str, Any]) -> set[str]:
    return {
        tag.strip()
        for tag in str(torrent.get("tags", "")).split(",")
        if tag.strip()
    }


def existing_request_tags(qbit: QBittorrentClient) -> set[str]:
    torrents = qbit.get_json("/api/v2/torrents/info")
    return {
        tag.strip()
        for torrent in torrents
        if "language-mismatch" not in torrent_tag_set(torrent)
        for tag in str(torrent.get("tags", "")).split(",")
        if tag.strip().startswith("seerr-request-")
    }


def blocked_release_tags(qbit: QBittorrentClient) -> set[str]:
    return {
        tag
        for torrent in qbit.get_json("/api/v2/torrents/info")
        if "language-mismatch" in torrent_tag_set(torrent)
        for tag in torrent_tag_set(torrent)
        if tag.startswith("release-")
    }


def release_tag(
    release: dict[str, Any],
    indexers: dict[int, dict[str, Any]],
) -> str:
    tracker = str(indexers[int(release["indexerId"])]["tracker"])
    info_url = str(release.get("infoUrl") or "")
    torrent_id = urllib.parse.parse_qs(
        urllib.parse.urlsplit(info_url).query
    ).get("id", [])
    if torrent_id and str(torrent_id[0]).isdigit():
        fingerprint = str(torrent_id[0])
    else:
        stable_value = "|".join(
            str(release.get(key) or "")
            for key in ("guid", "downloadUrl", "title")
        )
        fingerprint = hashlib.sha256(stable_value.encode("utf-8")).hexdigest()[:12]
    return f"release-{tracker}-{fingerprint}"


def matches_policy(indexer: dict[str, Any], policy: dict[str, Any]) -> bool:
    definition = str(
        indexer.get("definitionName") or indexer.get("definition") or ""
    ).casefold()
    if definition != str(policy["definition"]).casefold():
        return False
    expected_name = str(policy.get("name") or "").casefold()
    return not expected_name or str(indexer.get("name") or "").casefold() == expected_name


def discover_private_indexers(
    prowlarr_url: str,
    prowlarr_key: str,
) -> dict[int, dict[str, Any]]:
    payload = get_json(
        f"{prowlarr_url.rstrip('/')}/api/v1/indexer",
        {"X-Api-Key": prowlarr_key},
    )
    discovered: dict[int, dict[str, Any]] = {}
    for indexer in payload:
        for policy in PRIVATE_INDEXER_POLICIES:
            if matches_policy(indexer, policy):
                discovered[int(indexer["id"])] = dict(policy)
                break
    return discovered


def read_dispatch_policy(policy_file: Path) -> dict[str, Any]:
    payload = json.loads(policy_file.read_text(encoding="utf-8"))
    automatic = payload["automaticPrivateGrab"]
    minimum_language = str(automatic["minimumLanguage"])
    minimum_resolution = int(automatic["minimumTitleResolution"])
    fallback_days = automatic.get("englishFallbackAfterDays")
    if fallback_days is not None:
        fallback_days = int(fallback_days)
        if fallback_days < 1:
            raise GRAB.GrabError("englishFallbackAfterDays must be positive")
    if minimum_language not in GRAB.LANGUAGE_FLOORS or minimum_resolution < 0:
        raise GRAB.GrabError("Invalid automatic private-grab policy")
    return {
        "minimum_language": minimum_language,
        "minimum_resolution": minimum_resolution,
        "english_fallback_days": fallback_days,
    }


def request_age_days(request: dict[str, Any], now: datetime) -> float:
    created = str(request.get("createdAt") or "")
    if not created:
        return 0.0
    try:
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return max(0.0, (now - created_at).total_seconds() / 86400)


def language_floor_for_request(
    request: dict[str, Any],
    policy: dict[str, Any],
    now: datetime,
) -> str:
    fallback_days = policy["english_fallback_days"]
    if fallback_days is not None and request_age_days(request, now) >= fallback_days:
        return "english"
    return str(policy["minimum_language"])


def candidate_sort_key(
    release: dict[str, Any],
    indexers: dict[int, dict[str, Any]],
) -> tuple[int, int, int, int, str]:
    indexer = indexers[int(release["indexerId"])]
    return (
        -int(language_rank(release)),
        int(indexer["priority"]),
        -GRAB.title_resolution(release),
        -int(release.get("seeders", 0) or 0),
        str(release.get("title", "")),
    )


def select_candidate(
    releases: list[dict[str, Any]],
    tmdb_id: int,
    indexers: dict[int, dict[str, Any]],
    minimum_language: str,
    minimum_resolution: int,
) -> dict[str, Any] | None:
    candidates = [
        release
        for release in releases
        if int(release.get("tmdbId", -1)) == tmdb_id
        and int(release.get("indexerId", -1)) in indexers
        and release.get("protocol") == "torrent"
        and release.get("downloadUrl")
        and int(release.get("seeders", 0) or 0)
        >= int(indexers[int(release["indexerId"])]["minimum_seeders"])
        and GRAB.release_meets_private_policy(
            release,
            minimum_language,
            minimum_resolution,
        )
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: candidate_sort_key(item, indexers))
    return candidates[0]


def enrich_btarg_candidates(
    releases: list[dict[str, Any]],
    tmdb_id: int,
    expected_imdb: str | None,
    indexers: dict[int, dict[str, Any]],
    client: BTArgClient,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for release in releases:
        indexer = indexers.get(int(release.get("indexerId", -1)))
        if not indexer or indexer["tracker"] != "btarg":
            enriched.append(release)
            continue
        candidate = dict(release)
        candidate.setdefault("indexer", "BTArg")
        try:
            candidate = enrich_release(candidate, client, expected_imdb)
        except BTArgError as error:
            print(
                "BTARG DETAIL SKIP: "
                f"title={candidate.get('title', '')} reason={error}"
            )
            continue
        if candidate.get("downloadAllowed") is False:
            continue
        if expected_imdb and candidate.get("btargVerifiedLanguage"):
            candidate["tmdbId"] = tmdb_id
        enriched.append(candidate)
    return enriched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=STACK)
    parser.add_argument("--request-id", type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    stack = args.stack_dir
    policy = read_dispatch_policy(stack / "private-release-policy.json")
    prowlarr_url = "http://127.0.0.1:9696"
    prowlarr_key = GRAB.read_api_key(stack / "config/prowlarr/config.xml")
    indexers = discover_private_indexers(prowlarr_url, prowlarr_key)
    radarr_key = GRAB.read_api_key(stack / "config/radarr/config.xml")
    radarr_movies = get_json(
        "http://127.0.0.1:7878/api/v3/movie",
        {"X-Api-Key": radarr_key},
    )
    movie_by_tmdb = {
        int(movie.get("tmdbId", 0)): movie
        for movie in radarr_movies
        if int(movie.get("tmdbId", 0) or 0) > 0
    }
    btarg = BTArgClient(
        stack / "secrets/prowlarr-private-indexers.json",
        BTArgCache(stack / "state/btarg-language-cache.json"),
    )
    pending = requests_to_dispatch(stack)
    if args.request_id is not None:
        pending = [item for item in pending if int(item.get("id", -1)) == args.request_id]
    if not pending:
        print("PRIVATE DISPATCH OK: no eligible outstanding movie requests")
        return 0
    if not indexers:
        print("PRIVATE DISPATCH OK: no supported private indexers are active")
        return 0

    username, password = read_credentials(stack / "secrets/qbittorrent.json")
    qbit = QBittorrentClient("http://127.0.0.1:8888", username, password)
    qbit.login()
    dispatched_tags = existing_request_tags(qbit)
    blocked_tags = blocked_release_tags(qbit)

    now = datetime.now(UTC)
    for request in pending:
        media = request["media"]
        tmdb_id = int(media["tmdbId"])
        movie = movie_by_tmdb.get(tmdb_id, {})
        title = str(movie.get("title") or media.get("title") or tmdb_id)
        request_tag = f"seerr-request-{request['id']}"
        if request_tag in dispatched_tags:
            print(f"ALREADY DISPATCHED: request={request['id']} tmdb={tmdb_id}")
            continue

        releases: list[dict[str, Any]] = []
        for indexer_id in indexers:
            try:
                releases.extend(
                    GRAB.prowlarr_search(
                        prowlarr_url,
                        prowlarr_key,
                        title,
                        indexer_id,
                        "movie",
                    )
                )
            except GRAB.GrabError as error:
                print(
                    f"INDEXER SKIP: request={request['id']} "
                    f"indexer={indexer_id} reason={error}"
                )

        minimum_language = language_floor_for_request(request, policy, now)
        releases = enrich_btarg_candidates(
            releases,
            tmdb_id,
            str(movie.get("imdbId") or "") or None,
            indexers,
            btarg,
        )
        releases = [
            release
            for release in releases
            if release_tag(release, indexers) not in blocked_tags
        ]
        release = select_candidate(
            releases,
            tmdb_id,
            indexers,
            minimum_language,
            int(policy["minimum_resolution"]),
        )
        if release is None:
            print(
                f"NO PRIVATE CANDIDATE: request={request['id']} tmdb={tmdb_id} "
                f"language-floor={minimum_language}"
            )
            continue

        indexer_id = int(release["indexerId"])
        indexer = indexers[indexer_id]
        fingerprint_tag = release_tag(release, indexers)
        tags = f"private,{indexer['tracker']},{request_tag},{fingerprint_tag}"
        actual_language = language_rank(release).name.lower()
        print(
            f"{'DISPATCH' if args.apply else 'WOULD DISPATCH'} "
            f"request={request['id']} tmdb={tmdb_id} indexer={indexer_id} "
            f"language={actual_language} release={fingerprint_tag} "
            f"title={release['title']}"
        )
        if args.apply:
            marker = {
                "latino": "LATINO",
                "castilian": "CASTELLANO",
                "english": "ENGLISH",
            }.get(actual_language)
            display_name = str(release["title"])
            if marker:
                display_name = f"{display_name} [{marker}]"
            GRAB.add_to_qbittorrent(
                qbit,
                release,
                "radarr",
                tags,
                int(indexer["seed_minutes"]),
                False,
                ratio_limit=indexer["ratio_limit"],
                display_name=display_name,
            )
            dispatched_tags.add(request_tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
