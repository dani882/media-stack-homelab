#!/usr/bin/env python3
"""Safely hardlink completed DocsPedia learning content into libraries."""

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any


STACK = Path("/volume1/docker/media-stack")
DATA_ROOT = Path("/volume1/Family")
DEPLOYED_SCRIPT_DIR = STACK / "scripts"
LOCAL_MEDIA_SCRIPT_DIR = Path(__file__).resolve().parent / "media"
for module_dir in (LOCAL_MEDIA_SCRIPT_DIR, DEPLOYED_SCRIPT_DIR):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from common.qbittorrent import QBittorrentClient, read_credentials


DOCSPEDIA_HOST = "docspedia.world"
LEARNING_CATEGORY = "learning"
MINIMUM_SEED_MINUTES = 3480
QBITTORRENT_SECRET = Path("secrets/qbittorrent.json")
VIDEO_EXTENSIONS = {
    ".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg",
    ".mpg", ".mts", ".ts", ".webm",
}
VIDEO_AUX_EXTENSIONS = {
    ".aac", ".ass", ".flac", ".m4a", ".mp3", ".ogg", ".opus",
    ".srt", ".ssa", ".vtt", ".wav",
}
DOCUMENT_EXTENSIONS = {
    ".azw", ".azw3", ".cb7", ".cbr", ".cbt", ".cbz", ".djvu",
    ".epub", ".fb2", ".mobi", ".pdf",
}
DANGEROUS_EXTENSIONS = {
    ".apk", ".app", ".bat", ".cmd", ".com", ".deb", ".dmg",
    ".exe", ".hta", ".jar", ".lnk", ".msi", ".pkg", ".ps1",
    ".reg", ".rpm", ".scr", ".sh", ".vbs",
}


class LearningImportError(RuntimeError):
    pass


def safe_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:180] or "DocsPedia course"


def safe_relative_path(value: str) -> Path:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts:
        raise LearningImportError("unsafe absolute or empty torrent path")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise LearningImportError("unsafe torrent path traversal")
    return Path(*candidate.parts)


def classify_file(path: Path) -> str | None:
    extension = path.suffix.casefold()
    if extension in DANGEROUS_EXTENSIONS:
        return "dangerous"
    if extension in VIDEO_EXTENSIONS or extension in VIDEO_AUX_EXTENSIONS:
        return "video"
    if extension in DOCUMENT_EXTENSIONS:
        return "document"
    return None


def tracker_hosts(client: QBittorrentClient, torrent_hash: str) -> set[str]:
    payload = client.get_json(
        "/api/v2/torrents/trackers?"
        + urllib.parse.urlencode({"hash": torrent_hash})
    )
    hosts: set[str] = set()
    for tracker in payload:
        host = urllib.parse.urlsplit(str(tracker.get("url") or "")).hostname
        if host:
            hosts.add(host.casefold().rstrip("."))
    return hosts


def is_docspedia(hosts: set[str]) -> bool:
    return any(
        host == DOCSPEDIA_HOST or host.endswith(f".{DOCSPEDIA_HOST}")
        for host in hosts
    )


def mapped_data_path(path: str, data_root: Path) -> Path:
    container_path = PurePosixPath(path)
    try:
        relative = container_path.relative_to("/data")
    except ValueError as error:
        raise LearningImportError("torrent save path is outside /data") from error
    return data_root.joinpath(*relative.parts)


def link_file(source: Path, destination: Path, dry_run: bool) -> bool:
    if source.is_symlink() or not source.is_file():
        raise LearningImportError("source is not a regular file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        source_stat = source.stat()
        destination_stat = destination.stat()
        if (
            source_stat.st_dev == destination_stat.st_dev
            and source_stat.st_ino == destination_stat.st_ino
        ):
            return False
        raise LearningImportError("destination already exists with other content")
    if dry_run:
        return True
    try:
        os.link(source, destination)
    except OSError as error:
        raise LearningImportError(f"hardlink failed: {error.strerror}") from error
    return True


def import_files(
    *,
    name: str,
    files: list[dict[str, Any]],
    save_path: Path,
    videos_root: Path,
    documents_root: Path,
    dry_run: bool,
) -> tuple[int, int]:
    course = safe_component(name)
    planned: list[tuple[Path, Path, str]] = []
    for item in files:
        relative = safe_relative_path(str(item.get("name") or ""))
        kind = classify_file(relative)
        if kind == "dangerous":
            raise LearningImportError("payload contains an executable-like file")
        if kind is None:
            continue
        source = save_path / relative
        root = videos_root if kind == "video" else documents_root
        planned.append((source, root / course / relative, kind))

    if not planned:
        raise LearningImportError("payload contains no supported learning files")

    video_count = 0
    document_count = 0
    for source, destination, kind in planned:
        link_file(source, destination, dry_run)
        if kind == "video":
            video_count += 1
        else:
            document_count += 1
    return video_count, document_count


def add_tags(client: QBittorrentClient, torrent_hash: str, tags: list[str]) -> None:
    client.post_form(
        "/api/v2/torrents/addTags",
        {"hashes": torrent_hash, "tags": ",".join(tags)},
    )


def refresh_jellyfin(stack: Path) -> None:
    settings_path = stack / "config/jellyseerr/settings.json"
    if not settings_path.is_file():
        return
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    api_key = str(settings.get("jellyfin", {}).get("apiKey", "")).strip()
    if not api_key:
        return
    request = urllib.request.Request(
        "http://127.0.0.1:8899/Library/Refresh",
        headers={"X-Emby-Token": api_key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def run(stack: Path, data_root: Path, dry_run: bool, max_torrents: int) -> int:
    username, password = read_credentials(stack / QBITTORRENT_SECRET)
    client = QBittorrentClient("http://127.0.0.1:8888", username, password)
    client.login()
    videos_root = data_root / "Media/Learning/Videos"
    documents_root = data_root / "Media/Learning/Documents"
    if not dry_run:
        videos_root.mkdir(parents=True, exist_ok=True)
        documents_root.mkdir(parents=True, exist_ok=True)

    handled = 0
    imported_videos = False
    torrents = client.get_json("/api/v2/torrents/info")
    for torrent in torrents:
        torrent_hash = str(torrent.get("hash") or "")
        if not torrent_hash or not is_docspedia(tracker_hosts(client, torrent_hash)):
            continue
        handled += 1
        if handled > max_torrents:
            raise LearningImportError("DocsPedia torrent limit exceeded")

        if not dry_run:
            client.post_form(
                "/api/v2/torrents/setCategory",
                {"hashes": torrent_hash, "category": LEARNING_CATEGORY},
            )
            add_tags(client, torrent_hash, ["private", "docspedia", "learning"])
            if int(torrent.get("seeding_time_limit", -1) or -1) < MINIMUM_SEED_MINUTES:
                client.post_form(
                    "/api/v2/torrents/setShareLimits",
                    {
                        "hashes": torrent_hash,
                        "ratioLimit": -2,
                        "seedingTimeLimit": MINIMUM_SEED_MINUTES,
                        "inactiveSeedingTimeLimit": -2,
                        "shareLimitAction": "Default",
                    },
                )

        if float(torrent.get("progress", 0) or 0) < 1:
            print(f"LEARNING DOWNLOAD PENDING: {safe_component(str(torrent.get('name') or ''))}")
            continue
        tags = {tag.strip() for tag in str(torrent.get("tags") or "").split(",")}
        if "learning-import-verified" in tags:
            continue
        try:
            save_path = mapped_data_path(str(torrent.get("save_path") or ""), data_root)
            files = client.get_json(
                "/api/v2/torrents/files?"
                + urllib.parse.urlencode({"hash": torrent_hash})
            )
            videos, documents = import_files(
                name=str(torrent.get("name") or "DocsPedia course"),
                files=files,
                save_path=save_path,
                videos_root=videos_root,
                documents_root=documents_root,
                dry_run=dry_run,
            )
        except LearningImportError as error:
            if not dry_run:
                add_tags(client, torrent_hash, ["learning-import-review"])
            print(
                f"LEARNING IMPORT REVIEW: {safe_component(str(torrent.get('name') or ''))}: {error}"
            )
            continue

        if not dry_run:
            add_tags(client, torrent_hash, ["learning-import-verified"])
        imported_videos = imported_videos or videos > 0
        prefix = "WOULD IMPORT" if dry_run else "IMPORTED"
        print(
            f"{prefix} LEARNING: {safe_component(str(torrent.get('name') or ''))} "
            f"videos={videos} documents={documents}"
        )

    if imported_videos and not dry_run:
        refresh_jellyfin(stack)
    print(f"DOCSPEDIA LEARNING OK: torrents={handled}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=STACK)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-torrents", type=int, default=100)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(run(args.stack_dir, args.data_root, args.dry_run, args.max_torrents))
