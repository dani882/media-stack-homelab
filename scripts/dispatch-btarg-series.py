#!/usr/bin/env python3
"""Automatically dispatch and import verified Latino BTArg multi-season packs."""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any


STACK = Path("/volume1/docker/media-stack")
DATA_ROOT = Path("/volume1/Family")
sys.path.insert(0, str(STACK / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "media"))

from btarg_series_pack import (
    PackValidationError,
    destination_filename,
    map_pack_files,
    parse_season_range,
    validate_torrent_paths,
)
from common.qbittorrent import QBittorrentClient, QBittorrentError, read_credentials
from common.btarg import BTArgCache, BTArgClient, BTArgError


SEERR_URL = "http://127.0.0.1:5055"
SONARR_URL = "http://127.0.0.1:8989"
PROWLARR_URL = "http://127.0.0.1:9696"
QBITTORRENT_URL = "http://127.0.0.1:8888"
BTARG_RATIO_LIMIT = 1.0
MINIMUM_SEEDERS = 1
MAX_BTARG_DOWNLOADS = 6
MINIMUM_FREE_BYTES = 10 * 1024**3
DISPATCH_SPACE_MULTIPLIER = 2.1
_RKMPP_AVAILABLE: bool | None = None


class DispatchError(RuntimeError):
    pass


def read_xml_api_key(path: Path) -> str:
    try:
        value = ET.parse(path).findtext("ApiKey", "").strip()
    except (OSError, ET.ParseError) as error:
        raise DispatchError(f"Unable to read API configuration: {error}") from error
    if not value:
        raise DispatchError(f"API key missing from {path}")
    return value


def request_json(
    base_url: str,
    api_key: str,
    path: str,
    method: str = "GET",
    payload: Any | None = None,
    api_version: int = 3,
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{base_url}/api/v{api_version}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read()
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        raise DispatchError(f"{method} {path} failed: {error}") from error
    return None if not body else json.loads(body)


def seerr_api_key(stack: Path) -> str:
    try:
        payload = json.loads(
            (stack / "config/jellyseerr/settings.json").read_text(encoding="utf-8")
        )
        key = str(payload["main"]["apiKey"]).strip()
    except (OSError, KeyError, json.JSONDecodeError) as error:
        raise DispatchError(f"Unable to read Seerr configuration: {error}") from error
    if not key:
        raise DispatchError("Seerr API key is empty")
    return key


def seerr_requests(stack: Path) -> list[dict[str, Any]]:
    key = seerr_api_key(stack)
    request = urllib.request.Request(
        f"{SEERR_URL}/api/v1/request?take=100&skip=0",
        headers={"X-Api-Key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as error:
        raise DispatchError(f"Unable to read Seerr requests: {error}") from error
    return [
        item
        for item in payload.get("results", [])
        if item.get("type") == "tv"
        and item.get("status") == 2
        and isinstance(item.get("media"), dict)
        and item["media"].get("tvdbId")
    ]


def requested_seasons(request: dict[str, Any]) -> set[int]:
    return {
        int(item["seasonNumber"])
        for item in request.get("seasons", [])
        if int(item.get("seasonNumber", 0)) > 0 and item.get("status") == 2
    }


def tags_for(torrent: dict[str, Any]) -> set[str]:
    return {
        value.strip()
        for value in str(torrent.get("tags", "")).split(",")
        if value.strip()
    }


def download_url_for_qbittorrent(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return value
    port = f":{parsed.port}" if parsed.port else ""
    return urllib.parse.urlunsplit(
        (parsed.scheme, f"prowlarr{port}", parsed.path, parsed.query, parsed.fragment)
    )


def btarg_indexer_id(prowlarr_key: str) -> int:
    indexers = request_json(
        PROWLARR_URL, prowlarr_key, "/indexer", api_version=1
    )
    matches = [item for item in indexers if str(item.get("name", "")).casefold() == "btarg"]
    if len(matches) != 1:
        raise DispatchError(f"Expected one BTArg Prowlarr indexer, found {len(matches)}")
    return int(matches[0]["id"])


def prowlarr_search(
    key: str, title: str, indexer_id: int
) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {"query": title, "indexerIds": indexer_id, "type": "tvsearch"}
    )
    payload = request_json(
        PROWLARR_URL, key, "/search?" + query, api_version=1
    )
    return [item for item in payload if isinstance(item, dict)]


def select_candidate(
    releases: list[dict[str, Any]],
    seasons: set[int],
    imdb_id: str,
    btarg: BTArgClient,
) -> tuple[dict[str, Any], str]:
    accepted: list[tuple[dict[str, Any], str]] = []
    for release in releases:
        season_range = parse_season_range(str(release.get("title", "")))
        if season_range is None:
            continue
        first, last = season_range
        if set(range(first, last + 1)) != seasons:
            continue
        if int(release.get("seeders", 0) or 0) < MINIMUM_SEEDERS:
            continue
        if not re.search(r"\b(?:720|1080|2160)p\b", str(release.get("title", "")), re.I):
            continue
        info_url = str(release.get("infoUrl", ""))
        if not info_url or not release.get("downloadUrl"):
            continue
        detail = btarg.detail(info_url)
        if detail.language != "latino":
            continue
        if not detail.imdb_id or detail.imdb_id.casefold() != imdb_id.casefold():
            continue
        accepted.append((release, detail.language))
    if not accepted:
        raise DispatchError("No identity-verified Latino BTArg multi-season pack was found")
    accepted.sort(
        key=lambda item: (
            -int(item[0].get("seeders", 0) or 0),
            int(item[0].get("size", 0) or 0),
            str(item[0].get("title", "")),
        )
    )
    return accepted[0]


def require_dispatch_space(path: Path, release_size: int) -> None:
    required = max(int(release_size * DISPATCH_SPACE_MULTIPLIER), MINIMUM_FREE_BYTES)
    free = shutil.disk_usage(path).free
    if free < required:
        raise DispatchError(
            f"Insufficient free space: {free // 1024**3} GiB free, "
            f"{required // 1024**3} GiB required"
        )


def wait_for_tagged_torrent(
    qbit: QBittorrentClient,
    required_tags: set[str],
) -> dict[str, Any]:
    for _ in range(20):
        matches = [
            item
            for item in qbit.get_json("/api/v2/torrents/info")
            if required_tags.issubset(tags_for(item))
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise DispatchError("Multiple qBittorrent torrents have the same request tags")
        time.sleep(2)
    raise DispatchError("qBittorrent did not report the BTArg pack after adding it")


def qbit_files(qbit: QBittorrentClient, torrent_hash: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"hash": torrent_hash})
    payload = qbit.get_json("/api/v2/torrents/files?" + query)
    return [item for item in payload if isinstance(item, dict)]


def start_torrent(qbit: QBittorrentClient, torrent_hash: str) -> None:
    try:
        qbit.post_form("/api/v2/torrents/start", {"hashes": torrent_hash})
    except QBittorrentError:
        qbit.post_form("/api/v2/torrents/resume", {"hashes": torrent_hash})


def add_torrent_tag(qbit: QBittorrentClient, torrent_hash: str, tag: str) -> None:
    qbit.post_form(
        "/api/v2/torrents/addTags",
        {"hashes": torrent_hash, "tags": tag},
    )


def add_validated_pack(
    qbit: QBittorrentClient,
    release: dict[str, Any],
    request_id: int,
    series_id: int,
    episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    tags = {
        "private",
        "btarg",
        "btarg-series-pack",
        "latino-verified",
        f"seerr-request-{request_id}",
        f"sonarr-series-{series_id}",
    }
    qbit.post_form(
        "/api/v2/torrents/add",
        {
            "urls": download_url_for_qbittorrent(str(release["downloadUrl"])),
            "category": "tv",
            "tags": ",".join(sorted(tags)),
            "stopped": "true",
            "paused": "true",
        },
    )
    torrent = wait_for_tagged_torrent(qbit, tags)
    torrent_hash = str(torrent["hash"])
    try:
        if torrent.get("private") is not True:
            raise PackValidationError("BTArg torrent is not explicitly private")
        files = qbit_files(qbit, torrent_hash)
        paths = [str(item.get("name", "")) for item in files]
        validate_torrent_paths(paths)
        map_pack_files(paths, episodes)
    except (PackValidationError, DispatchError):
        qbit.post_form(
            "/api/v2/torrents/delete",
            {"hashes": torrent_hash, "deleteFiles": "true"},
        )
        raise
    qbit.post_form(
        "/api/v2/torrents/setShareLimits",
        {
            "hashes": torrent_hash,
            "ratioLimit": BTARG_RATIO_LIMIT,
            "seedingTimeLimit": -2,
            "inactiveSeedingTimeLimit": -2,
            "shareLimitAction": "Default",
        },
    )
    start_torrent(qbit, torrent_hash)
    return torrent


def host_path(container_path: str) -> Path:
    path = PurePosixPath(container_path)
    try:
        relative = path.relative_to("/data")
    except ValueError as error:
        raise DispatchError(f"qBittorrent path is outside /data: {container_path}") from error
    return DATA_ROOT.joinpath(*relative.parts)


def probe_media(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise DispatchError(f"ffprobe failed for {path.name}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DispatchError(f"ffprobe returned invalid data for {path.name}") from error


def media_codec(probe: dict[str, Any]) -> str:
    videos = [
        stream
        for stream in probe.get("streams", [])
        if stream.get("codec_type") == "video"
    ]
    if len(videos) != 1:
        raise DispatchError("Expected exactly one video stream")
    return str(videos[0].get("codec_name", "")).casefold()


def validate_verified_latino_audio(probe: dict[str, Any]) -> None:
    audio = [
        stream
        for stream in probe.get("streams", [])
        if stream.get("codec_type") == "audio"
    ]
    if not audio:
        raise DispatchError("Media file has no audio streams")
    languages = {
        str((stream.get("tags") or {}).get("language", "")).casefold()
        for stream in audio
        if str((stream.get("tags") or {}).get("language", "")).strip()
    }
    spanish = {"es", "esl", "spa", "spanish"}
    if languages & spanish:
        return
    known = languages - {"und", "unknown"}
    if known and known <= {"en", "eng", "english"}:
        raise DispatchError("MediaInfo reports English-only audio")
    # BTArg's authenticated detail is the language proof when old encodes have
    # missing/undefined stream-language tags.


def rkmpp_encoder_available() -> bool:
    global _RKMPP_AVAILABLE
    if _RKMPP_AVAILABLE is not None:
        return _RKMPP_AVAILABLE
    if not Path("/dev/mpp_service").exists() or shutil.which("ffmpeg") is None:
        _RKMPP_AVAILABLE = False
        return False
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=128x128:rate=24",
        "-frames:v",
        "3",
        "-vf",
        "format=nv12",
        "-c:v",
        "h264_rkmpp",
        "-rc_mode",
        "CQP",
        "-qp_init",
        "20",
        "-f",
        "h264",
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        _RKMPP_AVAILABLE = False
    else:
        _RKMPP_AVAILABLE = result.returncode == 0
    return _RKMPP_AVAILABLE


def conversion_command(
    source: Path,
    temporary: Path,
    hardware: bool,
) -> list[str]:
    video_arguments = (
        [
            "-vf",
            "format=nv12",
            "-c:v",
            "h264_rkmpp",
            "-rc_mode",
            "CQP",
            "-qp_init",
            "20",
        ]
        if hardware
        else [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-threads",
            "2",
        ]
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map",
        "0:s?",
        *video_arguments,
        "-c:a",
        "copy",
        "-c:s",
        "copy",
        "-map_metadata",
        "0",
        str(temporary),
    ]


def validate_converted_file(temporary: Path, source_name: str) -> None:
    probe = probe_media(temporary)
    if media_codec(probe) != "h264":
        raise DispatchError(f"Converted file is not H.264: {source_name}")
    validate_verified_latino_audio(probe)


def transcode_to_h264(source: Path, destination: Path) -> None:
    required = max(int(source.stat().st_size * 1.25), 5 * 1024**3)
    free = shutil.disk_usage(destination.parent).free
    if free < required:
        raise DispatchError(
            f"Insufficient free space to convert {source.name}: "
            f"{free // 1024**3} GiB free"
        )
    temporary = destination.with_name(destination.name + ".partial.mkv")
    temporary.unlink(missing_ok=True)
    hardware = rkmpp_encoder_available()
    if hardware:
        print(f"HARDWARE H.264: {source.name}")
    try:
        result = subprocess.run(
            conversion_command(source, temporary, hardware),
            timeout=7200,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None

    conversion_error: DispatchError | None = None
    if result is not None and result.returncode == 0:
        try:
            validate_converted_file(temporary, source.name)
        except DispatchError as error:
            conversion_error = error
    else:
        conversion_error = DispatchError(f"H.264 conversion failed for {source.name}")

    if conversion_error is not None and hardware:
        global _RKMPP_AVAILABLE
        _RKMPP_AVAILABLE = False
        print(f"HARDWARE FALLBACK: {source.name}", file=sys.stderr)
        temporary.unlink(missing_ok=True)
        try:
            result = subprocess.run(
                conversion_command(source, temporary, False),
                timeout=7200,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is None or result.returncode != 0:
            temporary.unlink(missing_ok=True)
            raise DispatchError(f"H.264 conversion failed for {source.name}")
        validate_converted_file(temporary, source.name)
    elif conversion_error is not None:
        temporary.unlink(missing_ok=True)
        raise conversion_error
    source_stat = source.stat()
    os.chown(temporary, source_stat.st_uid, source_stat.st_gid)
    os.chmod(temporary, source_stat.st_mode & 0o777)
    temporary.replace(destination)


def import_completed_pack(
    qbit: QBittorrentClient,
    torrent: dict[str, Any],
    series: dict[str, Any],
    episodes: list[dict[str, Any]],
    sonarr_key: str,
    apply: bool,
) -> None:
    torrent_hash = str(torrent["hash"])
    if "btarg-import-verified" in tags_for(torrent):
        return
    files = qbit_files(qbit, str(torrent["hash"]))
    if any(float(item.get("progress", 0) or 0) < 1 for item in files):
        print(f"WAITING FOR FILES: {torrent.get('name', '')}")
        return
    paths = [str(item.get("name", "")) for item in files]
    mappings = map_pack_files(paths, episodes)
    source_root = host_path(str(torrent.get("save_path", "")))
    series_path = host_path(str(series["path"]))
    episodes_by_id = {int(item["id"]): item for item in episodes}
    changed = 0
    planned = 0
    expected_destinations: dict[int, Path] = {}
    needs_rescan = False
    for mapping in mappings:
        mapped_episodes = [episodes_by_id[item] for item in mapping.episode_ids]
        if any(item.get("hasFile") for item in mapped_episodes):
            print(
                f"KEEP EXISTING: S{mapping.season:02d}"
                f"E{mapping.episode_numbers[0]:02d}-E{mapping.episode_numbers[-1]:02d}"
            )
            continue
        source = source_root / mapping.path
        if not source.is_file():
            raise DispatchError(f"Completed source file is missing: {mapping.path}")
        probe = probe_media(source)
        validate_verified_latino_audio(probe)
        codec = media_codec(probe)
        extension = source.suffix if codec == "h264" else ".mkv"
        destination = (
            series_path
            / f"Season {mapping.season:02d}"
            / destination_filename(str(series["title"]), mapping, extension)
        )
        for episode_id in mapping.episode_ids:
            expected_destinations[episode_id] = destination
        planned += 1
        if destination.exists():
            needs_rescan = True
            continue
        print(f"{'IMPORT' if apply else 'WOULD IMPORT'}: {mapping.path} -> {destination.name}")
        if not apply:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if codec == "h264":
            try:
                os.link(source, destination)
            except OSError as error:
                if error.errno != errno.EXDEV:
                    raise
                raise DispatchError("Source and library are not on the same filesystem") from error
        else:
            transcode_to_h264(source, destination)
        changed += 1
    print(f"PACK IMPORT: planned={planned} changed={changed}")
    if changed or needs_rescan:
        command = request_json(
            SONARR_URL,
            sonarr_key,
            "/command",
            method="POST",
            payload={"name": "RescanSeries", "seriesId": int(series["id"])},
        )
        command_id = int((command or {}).get("id", 0) or 0)
        for _ in range(30):
            if not command_id:
                break
            status = request_json(SONARR_URL, sonarr_key, f"/command/{command_id}")
            if str(status.get("status", "")).casefold() in {"completed", "failed"}:
                break
            time.sleep(2)

    if apply and expected_destinations:
        refreshed = request_json(
            SONARR_URL, sonarr_key, f"/episode?seriesId={series['id']}"
        )
        refreshed_by_id = {int(item["id"]): item for item in refreshed}
        file_cache: dict[int, dict[str, Any]] = {}
        problems: list[str] = []
        for episode_id, destination in expected_destinations.items():
            episode = refreshed_by_id.get(episode_id, {})
            file_id = int(episode.get("episodeFileId", 0) or 0)
            if not episode.get("hasFile") or not file_id:
                problems.append(f"episode {episode_id} is not imported")
                continue
            if file_id not in file_cache:
                file_cache[file_id] = request_json(
                    SONARR_URL, sonarr_key, f"/episodefile/{file_id}"
                )
            relative_path = str(file_cache[file_id].get("relativePath", ""))
            if Path(relative_path).name != destination.name:
                problems.append(f"episode {episode_id} points to an unexpected file")
        if problems:
            add_torrent_tag(qbit, torrent_hash, "btarg-import-review")
            raise DispatchError(
                "Post-import verification failed: " + "; ".join(problems[:3])
            )
        add_torrent_tag(qbit, torrent_hash, "btarg-import-verified")
        print(f"PACK VERIFIED: episodes={len(expected_destinations)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=STACK)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    stack = arguments.stack_dir
    sonarr_key = read_xml_api_key(stack / "config/sonarr/config.xml")
    prowlarr_key = read_xml_api_key(stack / "config/prowlarr/config.xml")
    series_items = request_json(SONARR_URL, sonarr_key, "/series")
    username, password = read_credentials(stack / "secrets/qbittorrent.json")
    qbit = QBittorrentClient(QBITTORRENT_URL, username, password)
    qbit.login()
    torrents = qbit.get_json("/api/v2/torrents/info")

    requests = seerr_requests(stack)
    if not requests:
        print("BTARG SERIES OK: no eligible Seerr TV requests")
        return 0

    cache = BTArgCache(stack / "state/btarg-language-cache.json")
    btarg = BTArgClient(
        stack / "secrets/prowlarr-private-indexers.json",
        cache,
    )
    indexer_id: int | None = None
    started = 0
    for request in requests:
        media = request["media"]
        tvdb_id = int(media["tvdbId"])
        series_matches = [item for item in series_items if int(item.get("tvdbId", 0)) == tvdb_id]
        if len(series_matches) != 1:
            print(f"SKIP request={request['id']}: Sonarr identity is not unique")
            continue
        series = series_matches[0]
        seasons = requested_seasons(request)
        if not seasons or not str(series.get("imdbId", "")).startswith("tt"):
            print(f"SKIP request={request['id']}: missing season or IMDb identity")
            continue
        episodes = request_json(
            SONARR_URL, sonarr_key, f"/episode?seriesId={series['id']}"
        )
        requested_episodes = [
            item for item in episodes if int(item.get("seasonNumber", 0)) in seasons
        ]
        if not requested_episodes:
            continue
        request_tag = f"seerr-request-{request['id']}"
        matches = [item for item in torrents if request_tag in tags_for(item)]
        if len(matches) > 1:
            raise DispatchError(f"Multiple torrents found for Seerr request {request['id']}")
        if matches:
            torrent = matches[0]
            if float(torrent.get("progress", 0) or 0) < 1:
                print(
                    f"DOWNLOADING request={request['id']} progress="
                    f"{float(torrent.get('progress', 0)) * 100:.1f}%"
                )
                continue
            import_completed_pack(
                qbit, torrent, series, episodes, sonarr_key, arguments.apply
            )
            continue
        if all(item.get("hasFile") for item in requested_episodes):
            continue
        if started:
            continue
        active_btarg = sum(
            1
            for item in torrents
            if "btarg" in tags_for(item)
            and float(item.get("progress", 0) or 0) < 1
            and str(item.get("state", "")).casefold() not in {"stoppeddl", "pauseddl"}
        )
        if active_btarg >= MAX_BTARG_DOWNLOADS:
            print("SKIP: BTArg simultaneous-download limit reached")
            continue
        if indexer_id is None:
            indexer_id = btarg_indexer_id(prowlarr_key)
        search_key = f"seerr-tv:{request['id']}:{','.join(map(str, sorted(seasons)))}"
        if not cache.search_allowed(search_key):
            print(f"BACKOFF request={request['id']}: previous BTArg search had no safe pack")
            continue
        releases = prowlarr_search(prowlarr_key, str(series["title"]), indexer_id)
        try:
            release, language = select_candidate(
                releases, seasons, str(series["imdbId"]), btarg
            )
        except DispatchError as error:
            cache.record_search_miss(search_key)
            print(f"NO PACK request={request['id']}: {error}")
            continue
        cache.clear_search(search_key)
        require_dispatch_space(DATA_ROOT, int(release.get("size", 0) or 0))
        print(
            f"{'DISPATCH' if arguments.apply else 'WOULD DISPATCH'} "
            f"request={request['id']} series={series['title']} language={language} "
            f"seeders={release.get('seeders')} title={release.get('title')}"
        )
        if arguments.apply:
            torrent = add_validated_pack(
                qbit,
                release,
                int(request["id"]),
                int(series["id"]),
                episodes,
            )
            print(f"STARTED: hash={str(torrent['hash'])[:12].upper()} ratio=1.0")
            started += 1
    return 0


if __name__ == "__main__":
    try:
        lock_path = STACK / "state/btarg-series.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with lock_path.open("w", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("BTARG SERIES: another worker is already running")
                raise SystemExit(0)
            raise SystemExit(main())
    except (DispatchError, PackValidationError, QBittorrentError, BTArgError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
