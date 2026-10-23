#!/usr/bin/env python3
"""Dispatch the best safe private release for monitored Radarr movies.

Language is ranked before tracker priority. Missing movies wait for Spanish;
after the configured grace period an English/original private fallback may be
used. Existing files are only replaced by a higher-ranked language. Public
indexers are never queried by this dispatcher.
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
from common.qbittorrent import (
    QBittorrentClient,
    read_credentials,
    torrent_consumes_download_slot,
)


SPEC = importlib.util.spec_from_file_location(
    "private_grab", SCRIPT_ROOT / "grab-prowlarr-release.py"
)
assert SPEC and SPEC.loader
GRAB = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAB)


PRIVATE_INDEXER_POLICIES: tuple[dict[str, Any], ...] = (
    {
        "definition": "lat-team-api",
        "tracker": "lat-team",
        "priority": 1,
        "minimum_seeders": 1,
        "seed_minutes": 4920,
        "ratio_limit": None,
    },
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


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
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


def tag_number(tags: set[str], prefix: str) -> int | None:
    for tag in tags:
        if not tag.startswith(prefix):
            continue
        try:
            value = int(tag[len(prefix) :])
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def expected_movie_language(tags: set[str]) -> Any:
    mapping = {
        "movie-expected-latino": GRAB.LanguageRank.LATINO,
        "movie-expected-castilian": GRAB.LanguageRank.CASTILIAN,
        "movie-expected-english": GRAB.LanguageRank.ENGLISH,
    }
    return next(
        (rank for tag, rank in mapping.items() if tag in tags),
        GRAB.LanguageRank.UNKNOWN,
    )


def request_completed_movie_imports(
    qbit: QBittorrentClient,
    torrents: list[dict[str, Any]],
    radarr_key: str,
    apply: bool,
) -> int:
    requested = 0
    for torrent in torrents:
        tags = torrent_tag_set(torrent)
        if (
            "private-dispatch" not in tags
            or float(torrent.get("progress", 0) or 0) < 1
            or "private-dispatch-import-requested" in tags
            or "private-dispatch-import-verified" in tags
            or "language-mismatch" in tags
        ):
            continue
        content_path = str(torrent.get("content_path") or "")
        if not content_path.startswith("/data/Downloads/"):
            print("MOVIE IMPORT REVIEW: completed path is outside Downloads")
            continue
        movie_id = tag_number(tags, "radarr-movie-")
        print(
            f"{'REQUEST' if apply else 'WOULD REQUEST'} RADARR IMPORT: "
            f"movie={movie_id}"
        )
        if not apply:
            requested += 1
            continue
        post_json(
            "http://127.0.0.1:7878/api/v3/command",
            {
                "name": "DownloadedMoviesScan",
                "path": content_path,
                "downloadClientId": str(torrent["hash"]),
                "importMode": "Auto",
            },
            {"X-Api-Key": radarr_key},
        )
        qbit.post_form(
            "/api/v2/torrents/addTags",
            {
                "hashes": str(torrent["hash"]),
                "tags": "private-dispatch-import-requested",
            },
        )
        torrent["tags"] = (
            f"{torrent.get('tags', '')},private-dispatch-import-requested"
        )
        requested += 1
    return requested


def reconcile_movie_imports(
    qbit: QBittorrentClient,
    torrents: list[dict[str, Any]],
    movies_by_id: dict[int, dict[str, Any]],
    apply: bool,
) -> tuple[int, int]:
    verified = 0
    mismatches = 0
    for torrent in torrents:
        tags = torrent_tag_set(torrent)
        if (
            "private-dispatch" not in tags
            or "private-dispatch-import-verified" in tags
            or "language-mismatch" in tags
            or float(torrent.get("progress", 0) or 0) < 1
        ):
            continue
        movie_id = tag_number(tags, "radarr-movie-")
        movie = movies_by_id.get(movie_id or -1)
        movie_file = movie.get("movieFile") if movie else None
        if not isinstance(movie_file, dict):
            continue
        current_file_id = int(movie_file.get("id", 0) or 0)
        original_file_id = tag_number(tags, "radarr-original-file-")
        if original_file_id and current_file_id == original_file_id:
            print(
                f"MOVIE IMPORT PENDING: movie={movie_id} Radarr still "
                "references the original file"
            )
            continue
        expected = expected_movie_language(tags)
        detected = language_rank(movie_file)
        if detected == GRAB.LanguageRank.UNKNOWN:
            print(f"MOVIE IMPORT REVIEW: movie={movie_id} audio is undefined")
            continue
        minimum = (
            GRAB.LanguageRank.CASTILIAN
            if expected >= GRAB.LanguageRank.CASTILIAN
            else GRAB.LanguageRank.ENGLISH
        )
        result_tag = (
            "private-dispatch-import-verified"
            if detected >= minimum
            else "language-mismatch"
        )
        print(
            f"{'VERIFY' if result_tag.endswith('verified') else 'MISMATCH'} "
            f"MOVIE IMPORT: movie={movie_id} audio={detected.name.lower()}"
        )
        if apply:
            qbit.post_form(
                "/api/v2/torrents/addTags",
                {"hashes": str(torrent["hash"]), "tags": result_tag},
            )
            torrent["tags"] = f"{torrent.get('tags', '')},{result_tag}"
        if result_tag.endswith("verified"):
            verified += 1
        else:
            mismatches += 1
    return verified, mismatches


def existing_request_tags(qbit: QBittorrentClient) -> set[str]:
    torrents = qbit.get_json("/api/v2/torrents/info")
    return {
        tag.strip()
        for torrent in torrents
        if "language-mismatch" not in torrent_tag_set(torrent)
        for tag in str(torrent.get("tags", "")).split(",")
        if tag.strip().startswith("seerr-request-")
    }


def active_dispatch_tags(qbit: QBittorrentClient) -> set[str]:
    return {
        tag
        for torrent in qbit.get_json("/api/v2/torrents/info")
        if "language-mismatch" not in torrent_tag_set(torrent)
        for tag in torrent_tag_set(torrent)
        if tag.startswith(("seerr-request-", "radarr-movie-"))
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
    max_searches = int(automatic.get("maxMovieSearchesPerRun", 8))
    max_active = int(automatic.get("maxActiveDownloads", 2))
    if fallback_days is not None:
        fallback_days = int(fallback_days)
        if fallback_days < 1:
            raise GRAB.GrabError("englishFallbackAfterDays must be positive")
    if (
        minimum_language not in GRAB.LANGUAGE_FLOORS
        or minimum_resolution < 0
        or max_searches < 1
        or max_active < 1
    ):
        raise GRAB.GrabError("Invalid automatic private-grab policy")
    return {
        "minimum_language": minimum_language,
        "minimum_resolution": minimum_resolution,
        "english_fallback_days": fallback_days,
        "max_searches": max_searches,
        "max_active_downloads": max_active,
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
    installed: dict[str, Any] | None = None,
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
        and (
            installed is None
            or language_rank(release) > language_rank(installed)
        )
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: candidate_sort_key(item, indexers))
    return candidates[0]


def monitored_movie_targets(
    movies: list[dict[str, Any]],
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requests_by_tmdb = {
        int(item["media"]["tmdbId"]): item
        for item in requests
        if isinstance(item.get("media"), dict)
        and int(item["media"].get("tmdbId", 0) or 0) > 0
    }
    targets: list[dict[str, Any]] = []
    for movie in movies:
        tmdb_id = int(movie.get("tmdbId", 0) or 0)
        if not movie.get("monitored") or tmdb_id <= 0:
            continue
        movie_file = movie.get("movieFile") if movie.get("hasFile") else None
        if movie_file and language_rank(movie_file) >= GRAB.LanguageRank.CASTILIAN:
            continue
        request = requests_by_tmdb.get(tmdb_id)
        targets.append(
            {
                "movie": movie,
                "request": request,
                "createdAt": (
                    str(request.get("createdAt") or "")
                    if request
                    else str(movie.get("added") or "")
                ),
            }
        )
    return sorted(
        targets,
        key=lambda item: int(item["movie"].get("id", 0) or 0),
    )


def rotate_movie_targets(
    targets: list[dict[str, Any]], last_movie_id: int | None
) -> list[dict[str, Any]]:
    if last_movie_id is None:
        return targets
    for index, target in enumerate(targets):
        if int(target["movie"]["id"]) == last_movie_id:
            return targets[index + 1 :] + targets[: index + 1]
    return targets


def read_last_movie_id(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("lastMovieId")
        return int(value) if value is not None else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def write_last_movie_id(path: Path, movie_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"lastMovieId": movie_id}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def active_private_dispatches(
    torrents: list[dict[str, Any]], now_timestamp: float | None = None
) -> int:
    return sum(
        1
        for torrent in torrents
        if "private-dispatch" in torrent_tag_set(torrent)
        and "language-mismatch" not in torrent_tag_set(torrent)
        and torrent_consumes_download_slot(torrent, now_timestamp)
    )


def add_selected_release(
    qbit: QBittorrentClient,
    release: dict[str, Any],
    indexer: dict[str, Any],
    tags: str,
    display_name: str,
) -> bool:
    try:
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
    except GRAB.TorrentFetchError as error:
        print(
            "MOVIE DELIVERY DEFERRED: "
            f"indexer={release.get('indexerId')} reason={error}"
        )
        return False
    return True


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
    movie_by_id = {
        int(movie["id"]): movie
        for movie in radarr_movies
        if int(movie.get("id", 0) or 0) > 0
    }
    btarg = BTArgClient(
        stack / "secrets/prowlarr-private-indexers.json",
        BTArgCache(stack / "state/btarg-language-cache.json"),
    )
    requests = requests_to_dispatch(stack)
    if args.request_id is not None:
        requests = [item for item in requests if int(item.get("id", -1)) == args.request_id]
    pending = monitored_movie_targets(radarr_movies, requests)
    if args.request_id is not None:
        pending = [item for item in pending if item["request"] is not None]
    if not pending:
        print("PRIVATE DISPATCH OK: no monitored movies need language attention")
        return 0
    if not indexers:
        print("PRIVATE DISPATCH OK: no supported private indexers are active")
        return 0

    username, password = read_credentials(stack / "secrets/qbittorrent.json")
    qbit = QBittorrentClient("http://127.0.0.1:8888", username, password)
    qbit.login()
    torrents = qbit.get_json("/api/v2/torrents/info")
    request_completed_movie_imports(qbit, torrents, radarr_key, args.apply)
    reconcile_movie_imports(qbit, torrents, movie_by_id, args.apply)
    active = active_private_dispatches(torrents)
    if args.apply and active >= int(policy["max_active_downloads"]):
        print(
            "PRIVATE DISPATCH CAP: "
            f"active={active} max={policy['max_active_downloads']}"
        )
        return 0
    dispatched_tags = active_dispatch_tags(qbit)
    blocked_tags = blocked_release_tags(qbit)

    now = datetime.now(UTC)
    state_path = stack / "state/private-dispatch.json"
    last_movie_id = read_last_movie_id(state_path)
    searches = 0
    for target in rotate_movie_targets(pending, last_movie_id):
        movie = target["movie"]
        request = target["request"]
        tmdb_id = int(movie["tmdbId"])
        movie_id = int(movie["id"])
        title = str(movie.get("title") or tmdb_id)
        movie_tag = f"radarr-movie-{movie_id}"
        request_tag = f"seerr-request-{request['id']}" if request else None
        if movie_tag in dispatched_tags or (
            request_tag is not None and request_tag in dispatched_tags
        ):
            print(f"ALREADY DISPATCHED: movie={movie_id} tmdb={tmdb_id}")
            continue

        if searches >= int(policy["max_searches"]):
            break
        searches += 1
        last_movie_id = movie_id

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
                    f"INDEXER SKIP: movie={movie_id} "
                    f"indexer={indexer_id} reason={error}"
                )

        movie_file = movie.get("movieFile") if movie.get("hasFile") else None
        minimum_language = (
            "castilian"
            if movie_file
            else language_floor_for_request(target, policy, now)
        )
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
        while releases:
            release = select_candidate(
                releases,
                tmdb_id,
                indexers,
                minimum_language,
                int(policy["minimum_resolution"]),
                movie_file,
            )
            if release is None:
                break

            indexer_id = int(release["indexerId"])
            indexer = indexers[indexer_id]
            fingerprint_tag = release_tag(release, indexers)
            actual_language = language_rank(release).name.lower()
            tag_values = [
                "private",
                str(indexer["tracker"]),
                "private-dispatch",
                movie_tag,
                fingerprint_tag,
            ]
            if request_tag:
                tag_values.append(request_tag)
            if movie_file:
                tag_values.append("movie-language-upgrade")
                if int(movie_file.get("id", 0) or 0) > 0:
                    tag_values.append(
                        f"radarr-original-file-{int(movie_file['id'])}"
                    )
            tag_values.append(f"movie-expected-{actual_language}")
            tags = ",".join(tag_values)
            print(
                f"{'DISPATCH' if args.apply else 'WOULD DISPATCH'} "
                f"movie={movie_id} tmdb={tmdb_id} indexer={indexer_id} "
                f"language={actual_language} release={fingerprint_tag} "
                f"title={release['title']}"
            )
            if not args.apply:
                break
            marker = {
                "latino": "LATINO",
                "castilian": "CASTELLANO",
                "english": "ENGLISH",
            }.get(actual_language)
            display_name = str(release["title"])
            if marker:
                display_name = f"{display_name} [{marker}]"
            if not add_selected_release(
                qbit,
                release,
                indexer,
                tags,
                display_name,
            ):
                releases = [
                    item
                    for item in releases
                    if int(item.get("indexerId", -1)) != indexer_id
                ]
                continue
            dispatched_tags.add(movie_tag)
            write_last_movie_id(state_path, movie_id)
            return 0
        else:
            release = None
        if release is None:
            print(
                f"NO DELIVERABLE PRIVATE CANDIDATE: movie={movie_id} "
                f"tmdb={tmdb_id} language-floor={minimum_language}"
            )
    if args.apply and last_movie_id is not None:
        write_last_movie_id(state_path, last_movie_id)
    print(f"PRIVATE DISPATCH OK: searched={searches} dispatched=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
