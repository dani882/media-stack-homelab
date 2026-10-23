#!/usr/bin/env python3
"""Move stalled media downloads aside and retry monitored media safely."""

import argparse
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
SCRIPT_ROOT = Path(__file__).resolve().parent
for module_dir in (SCRIPT_ROOT / "media", DEFAULT_STACK_DIR / "scripts"):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from common.arr import ArrClient, ArrError, read_api_key
from common.qbittorrent import QBittorrentClient, QBittorrentError, read_credentials


METADATA_TIMEOUT_HOURS = 24
UNAVAILABLE_TIMEOUT_HOURS = 72
NO_CONNECTION_TIMEOUT_HOURS = 168
PRIVATE_ZERO_PROGRESS_DEFER_HOURS = 12
PUBLIC_INDEXER_PREFIXES = (
    "1337x",
    "eztv",
    "extratorrent",
    "knaben",
    "limetorrents",
    "the pirate bay",
    "torrent downloads",
)


class StalledCleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArrSource:
    name: str
    base_url: str
    config_name: str
    category: str
    include_unknown_key: str


SOURCES = (
    ArrSource(
        "Sonarr",
        "http://127.0.0.1:8989",
        "sonarr",
        "tv",
        "includeUnknownSeriesItems",
    ),
    ArrSource(
        "Radarr",
        "http://127.0.0.1:7878",
        "radarr",
        "radarr",
        "includeUnknownMovieItems",
    ),
)


def age_hours(timestamp: int | float | None, now: float) -> float:
    value = float(timestamp or 0)
    if value <= 0:
        return 0.0
    return max(0.0, (now - value) / 3600)


def public_indexer(indexer: str | None) -> bool:
    normalized = str(indexer or "").strip().casefold()
    return any(normalized.startswith(prefix) for prefix in PUBLIC_INDEXER_PREFIXES)


def explicitly_public(torrent: dict[str, Any], indexer: str | None) -> bool:
    tags = {
        tag.strip().casefold()
        for tag in str(torrent.get("tags", "")).split(",")
        if tag.strip()
    }
    if torrent.get("private") is True or "private" in tags:
        return False
    if torrent.get("private") is False:
        return True
    return public_indexer(indexer)


def explicitly_private(torrent: dict[str, Any]) -> bool:
    tags = {
        tag.strip().casefold()
        for tag in str(torrent.get("tags", "")).split(",")
        if tag.strip()
    }
    return torrent.get("private") is True or "private" in tags


def private_defer_reason(torrent: dict[str, Any], now: float) -> str | None:
    """Return a reason only for untouched private torrents with no swarm.

    Partially downloaded private torrents remain active so this workflow can
    never create a Hit & Run obligation and then silently abandon it.
    """
    if not explicitly_private(torrent):
        return None
    if torrent.get("force_start") is True:
        return None
    if float(torrent.get("progress", 0) or 0) != 0:
        return None
    tags = {
        tag.strip().casefold()
        for tag in str(torrent.get("tags", "")).split(",")
        if tag.strip()
    }
    eligible_states = {"metaDL", "stalledDL", "unknownDL"}
    if "stalled-deferred" in tags:
        eligible_states.add("stoppedDL")
    if str(torrent.get("state") or "") not in eligible_states:
        return None
    if int(torrent.get("num_seeds", 0) or 0) > 0:
        return None
    if float(torrent.get("availability", 0) or 0) > 0:
        return None
    added_hours = age_hours(torrent.get("added_on"), now)
    if added_hours < PRIVATE_ZERO_PROGRESS_DEFER_HOURS:
        return None
    return f"private torrent has no available source after {added_hours:.1f} hours"


def stalled_reason(torrent: dict[str, Any], now: float) -> str | None:
    if float(torrent.get("progress", 0) or 0) >= 1:
        return None
    if torrent.get("force_start") is True:
        return None
    state = str(torrent.get("state") or "")
    added_hours = age_hours(torrent.get("added_on"), now)
    idle_hours = age_hours(torrent.get("last_activity"), now)
    if state == "metaDL" and added_hours >= METADATA_TIMEOUT_HOURS:
        return f"metadata unavailable for {added_hours / 24:.1f} days"
    if state != "stalledDL" or int(torrent.get("num_seeds", 0) or 0) > 0:
        return None
    availability = float(torrent.get("availability", 0) or 0)
    progress = float(torrent.get("progress", 0) or 0)
    if availability <= 0 and added_hours >= UNAVAILABLE_TIMEOUT_HOURS:
        return f"zero swarm availability for {added_hours / 24:.1f} days"
    if (
        0 < progress < 1
        and availability < 1
        and added_hours >= UNAVAILABLE_TIMEOUT_HOURS
    ):
        missing = int(torrent.get("amount_left", 0) or 0)
        return f"swarm is incomplete; {missing} bytes unavailable"
    if idle_hours >= NO_CONNECTION_TIMEOUT_HOURS:
        return f"no useful connection for {idle_hours / 24:.1f} days"
    return None


def queue_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [
            item
            for item in payload.get("records", [])
            if isinstance(item, dict)
        ]
    return []


def grabbed_indexer(client: ArrClient, download_id: str) -> str | None:
    payload = client.get(
        "/history?"
        + urllib.parse.urlencode(
            {"page": 1, "pageSize": 20, "downloadId": download_id}
        )
    )
    for item in queue_rows(payload):
        if item.get("eventType") == "grabbed":
            return str((item.get("data") or {}).get("indexer") or "")
    return None


def monitored_search(
    client: ArrClient,
    source: ArrSource,
    item: dict[str, Any],
) -> bool:
    if source.name == "Radarr":
        media_id = item.get("movieId")
        if not media_id:
            return False
        movie = client.get(f"/movie/{int(media_id)}")
        if not movie.get("monitored") or movie.get("hasFile"):
            return False
        client.request("POST", "/command", {"name": "MoviesSearch", "movieIds": [int(media_id)]})
        return True

    episode_id = item.get("episodeId")
    if not episode_id:
        return False
    episode = client.get(f"/episode/{int(episode_id)}")
    if not episode.get("monitored") or episode.get("hasFile"):
        return False
    client.request(
        "POST",
        "/command",
        {"name": "EpisodeSearch", "episodeIds": [int(episode_id)]},
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-delete", type=int, default=10)
    parser.add_argument("--max-defer", type=int, default=10)
    args = parser.parse_args()
    if args.max_delete < 1 or args.max_defer < 1:
        raise StalledCleanupError("--max-delete and --max-defer must be positive")

    stack = args.stack_dir
    username, password = read_credentials(stack / "secrets/qbittorrent.json")
    qbit = QBittorrentClient("http://127.0.0.1:8888", username, password)
    qbit.login()
    torrents = {
        str(item.get("hash", "")).upper(): item
        for item in qbit.get_json("/api/v2/torrents/info")
    }
    now = time.time()
    candidates: list[tuple[ArrSource, ArrClient, dict[str, Any], dict[str, Any], str]] = []
    private_deferrals: list[
        tuple[ArrSource, ArrClient, dict[str, Any], dict[str, Any], str]
    ] = []

    for source in SOURCES:
        client = ArrClient(
            source.base_url,
            read_api_key(stack / f"config/{source.config_name}/config.xml"),
        )
        queue = client.get(
            "/queue/details?"
            + urllib.parse.urlencode(
                {"page": 1, "pageSize": 500, source.include_unknown_key: "true"}
            )
        )
        for item in queue_rows(queue):
            download_id = str(item.get("downloadId") or "").upper()
            torrent = torrents.get(download_id)
            if torrent is None or torrent.get("category") != source.category:
                continue
            defer_reason = private_defer_reason(torrent, now)
            if defer_reason is not None:
                private_deferrals.append(
                    (source, client, item, torrent, defer_reason)
                )
                continue
            reason = stalled_reason(torrent, now)
            if reason is None:
                continue
            indexer = None
            if torrent.get("private") is not False:
                indexer = grabbed_indexer(client, download_id)
            if not explicitly_public(torrent, indexer):
                print(f"PROTECTED: {item.get('title', '')} (private or unverified origin)")
                continue
            candidates.append((source, client, item, torrent, reason))

    if args.apply and len(candidates) > args.max_delete:
        raise StalledCleanupError(
            f"Refusing to remove {len(candidates)} downloads; "
            f"--max-delete is {args.max_delete}."
        )
    if args.apply and len(private_deferrals) > args.max_defer:
        raise StalledCleanupError(
            f"Refusing to defer {len(private_deferrals)} private downloads; "
            f"--max-defer is {args.max_defer}."
        )

    deferred = 0
    defer_searches = 0
    for source, client, item, torrent, reason in private_deferrals:
        prefix = "DEFERRING" if args.apply else "WOULD DEFER"
        print(
            f"{prefix}: {source.name} {item.get('title', '')}\n"
            f"  hash={str(torrent.get('hash', ''))[:12].upper()} reason={reason}"
        )
        if not args.apply:
            continue
        download_id = str(torrent["hash"])
        qbit.post_form(
            "/api/v2/torrents/addTags",
            {"hashes": download_id, "tags": "stalled-deferred"},
        )
        qbit.post_form("/api/v2/torrents/stop", {"hashes": download_id})
        queue_id = int(item["id"])
        client.delete(
            f"/queue/{queue_id}?"
            + urllib.parse.urlencode(
                {
                    "removeFromClient": "false",
                    "blocklist": "true",
                    "skipRedownload": "false",
                    "changeCategory": "false",
                }
            )
        )
        qbit.post_form(
            "/api/v2/torrents/setCategory",
            {"hashes": download_id, "category": ""},
        )
        deferred += 1
        if monitored_search(client, source, item):
            defer_searches += 1
            print("  retained and stopped; alternate automatic search started")
        else:
            print("  retained and stopped; item is not monitored")

    removed = 0
    searches = 0
    for source, client, item, torrent, reason in candidates:
        prefix = "REMOVING" if args.apply else "WOULD REMOVE"
        print(
            f"{prefix}: {source.name} {item.get('title', '')}\n"
            f"  hash={str(torrent.get('hash', ''))[:12].upper()} reason={reason}"
        )
        if not args.apply:
            continue
        queue_id = int(item["id"])
        client.delete(
            f"/queue/{queue_id}?"
            + urllib.parse.urlencode(
                {
                    "removeFromClient": "true",
                    "blocklist": "true",
                    "skipRedownload": "false",
                    "changeCategory": "false",
                }
            )
        )
        removed += 1
        if monitored_search(client, source, item):
            searches += 1
            print("  blocklisted and new private-only automatic search started")
        else:
            print("  blocklisted; no search because the item is not monitored")

    print(
        f"STALLED DOWNLOAD CLEANUP: publicCandidates={len(candidates)} "
        f"removed={removed} publicSearches={searches} "
        f"privateDeferrals={len(private_deferrals)} deferred={deferred} "
        f"privateSearches={defer_searches}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ArrError, QBittorrentError, StalledCleanupError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
