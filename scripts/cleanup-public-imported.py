#!/usr/bin/env python3

"""Remove imported torrents after their public/private retention requirement."""


import argparse
import importlib.util
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_DATA_ROOT = Path("/volume1/Family")
DEPLOYED_SCRIPT_DIR = DEFAULT_STACK_DIR / "scripts"
LOCAL_MEDIA_SCRIPT_DIR = Path(__file__).resolve().parent / "media"
for script_dir in (LOCAL_MEDIA_SCRIPT_DIR, DEPLOYED_SCRIPT_DIR):
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

from common.arr import ArrClient, ArrError, read_api_key
from common.qbittorrent import (
    QBittorrentClient,
    QBittorrentError,
    read_credentials,
)


PRIVATE_AUDIT_SPEC = importlib.util.spec_from_file_location(
    "private_tracker_audit",
    Path(__file__).resolve().parent / "audit-private-trackers.py",
)
assert PRIVATE_AUDIT_SPEC and PRIVATE_AUDIT_SPEC.loader
PRIVATE_AUDIT = importlib.util.module_from_spec(PRIVATE_AUDIT_SPEC)
sys.modules[PRIVATE_AUDIT_SPEC.name] = PRIVATE_AUDIT
PRIVATE_AUDIT_SPEC.loader.exec_module(PRIVATE_AUDIT)


MINIMUM_SEEDING_MINUTES = 30.0
MINIMUM_AUDIO_VALIDATION_AGE_MINUTES = 15.0
MAX_DELETE_DEFAULT = 10
SAFE_TORRENT_STATES = {
    "stoppedUP",
    "stalledUP",
    "queuedUP",
    "pausedUP",
    "uploading",
}


class PublicCleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArrSource:
    name: str
    base_url: str
    config_file: Path


def is_supported_audio(movie_file: dict[str, Any]) -> bool | None:
    """Return whether Radarr has confirmed a usable audio track.

    ``None`` means Radarr has not yet completed MediaInfo analysis, which is
    deliberately not treated as a rejection.  Spanish includes Latino and
    Castilian; English remains the third-priority fallback.
    """
    languages = movie_file.get("languages")
    media_info = movie_file.get("mediaInfo") or {}
    audio_languages = str(media_info.get("audioLanguages") or "").strip()

    if not languages and not audio_languages:
        return None

    names = {
        str(item.get("name") or "").casefold()
        for item in languages or []
    }
    if any("spanish" in name or "castilian" in name or name == "english" for name in names):
        return True

    codes = {
        code.strip().casefold()
        for code in audio_languages.replace("/", ",").split(",")
        if code.strip()
    }
    if codes & {"spa", "es", "esl", "eng", "en"}:
        return True

    return False


def file_is_ready_for_audio_validation(
    movie_file: dict[str, Any],
    now: datetime,
    minimum_age_minutes: float,
) -> bool:
    raw_date = str(movie_file.get("dateAdded") or "")
    if not raw_date:
        return False
    try:
        added = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        return False
    if added.tzinfo is None:
        added = added.replace(tzinfo=UTC)
    return now - added >= timedelta(minutes=minimum_age_minutes)


def remove_unsupported_radarr_audio(
    client: ArrClient,
    dry_run: bool,
    max_delete: int,
    minimum_age_minutes: float,
) -> int:
    """Remove only library hardlinks that Radarr verified have bad audio.

    Deleting a Radarr movie file removes its library entry, not qBittorrent's
    completed payload.  This keeps private torrents available for their full
    seeding requirement while returning the monitored movie to "missing".
    The regular RSS cycle can then find a better release without falsely
    marking a successfully downloaded private torrent as failed.
    """
    movies = client.get("/movie")
    now = datetime.now(UTC)
    candidates: list[dict[str, Any]] = []

    for movie in movies:
        if not movie.get("hasFile") or not movie.get("monitored"):
            continue
        movie_id = movie.get("id")
        if not isinstance(movie_id, int):
            continue
        files = client.get(f"/moviefile?movieId={movie_id}")
        for movie_file in files:
            if not file_is_ready_for_audio_validation(
                movie_file, now, minimum_age_minutes
            ):
                continue
            if is_supported_audio(movie_file) is not False:
                continue
            candidates.append({"movie": movie, "file": movie_file})

    if len(candidates) > max_delete:
        raise PublicCleanupError(
            f"Refusing to remove {len(candidates)} unsupported-audio files "
            f"in one run; increase --max-delete after reviewing a dry run."
        )

    for candidate in candidates:
        movie = candidate["movie"]
        movie_file = candidate["file"]
        audio = (movie_file.get("mediaInfo") or {}).get("audioLanguages")
        prefix = "WOULD REMOVE" if dry_run else "REMOVING"
        print(
            f"{prefix} UNSUPPORTED AUDIO: {movie.get('title', '')}\n"
            f"  file: {movie_file.get('relativePath', '')}\n"
            f"  audio: {audio or 'unclassified'}"
        )
        if not dry_run:
            client.delete(f"/moviefile/{movie_file['id']}")

    print(f"Unsupported-audio library files: {len(candidates)}")
    return len(candidates)


def history_import_hashes(client: ArrClient) -> set[str]:
    history = client.get(
        "/history?"
        + urllib.parse.urlencode(
            {
                "page": 1,
                "pageSize": 1000,
                "sortDirection": "descending",
            }
        )
    )
    records = history if isinstance(history, list) else history.get("records", [])

    return {
        str(record.get("downloadId", "")).upper()
        for record in records
        if record.get("eventType") == "downloadFolderImported"
        and record.get("downloadId")
    }


def torrent_is_removable(
    torrent: dict[str, Any],
    hosts: set[str] | None = None,
) -> tuple[bool, str]:
    private = torrent.get("private")
    if private not in (False, True):
        return False, "torrent privacy is not explicitly reported"
    if float(torrent.get("progress", 0) or 0) < 1:
        return False, "torrent is not complete"
    if int(torrent.get("amount_left", 0) or 0) != 0:
        return False, "torrent has data remaining"
    if bool(torrent.get("force_start", False)):
        return False, "Force Start is enabled"
    if str(torrent.get("state", "")) not in SAFE_TORRENT_STATES:
        return False, f"state {torrent.get('state')!r} is not eligible"

    seeded_minutes = int(torrent.get("seeding_time", 0) or 0) / 60
    if private is False:
        if seeded_minutes < MINIMUM_SEEDING_MINUTES:
            return False, (
                f"seeded only {seeded_minutes:.1f} minutes; requires "
                f"{MINIMUM_SEEDING_MINUTES:.1f} minutes"
            )
        return True, "safe public retention satisfied"

    if not hosts:
        return False, "private tracker hosts are unavailable"
    policy = PRIVATE_AUDIT.matching_policy(hosts)
    if policy is None:
        return False, "private tracker has no managed retention policy"
    if policy.minimum_ratio is not None:
        ratio_limit = float(torrent.get("ratio_limit", -1) or -1)
        ratio = float(torrent.get("ratio", 0) or 0)
        if ratio_limit <= 0:
            return False, "private torrent has no finite positive ratio limit"
        required_ratio = max(ratio_limit, policy.minimum_ratio)
        if ratio < required_ratio:
            return False, (
                f"ratio is only {ratio:.2f}; requires {required_ratio:.2f}"
            )
        return True, f"safe private retention satisfied ({policy.name})"
    if policy.minimum_seed_minutes is None:
        return False, "private tracker has no usable retention rule"
    limit = int(torrent.get("seeding_time_limit", -1) or -1)
    if limit <= 0:
        return False, "private torrent has no finite positive seeding time limit"
    required_minutes = max(limit, policy.minimum_seed_minutes)
    if seeded_minutes < required_minutes:
        return False, (
            f"seeded only {seeded_minutes:.1f} minutes; requires "
            f"{required_minutes:.1f} minutes"
        )

    return True, f"safe private retention satisfied ({policy.name})"


def private_torrent_has_library_hardlink(
    torrent: dict[str, Any],
    data_root: Path,
) -> tuple[bool, str]:
    """Prove a title-matched private import without trusting Arr history.

    The guarded title matcher creates hardlinks directly and then asks Sonarr
    to rescan. That workflow has no qBittorrent download-id history record.
    A source-to-library hardlink is therefore the durable, non-destructive
    import proof for that narrow case.
    """
    content_path = Path(str(torrent.get("content_path", "")))
    try:
        source = data_root / content_path.relative_to("/data")
    except ValueError:
        return False, f"content path {content_path} is outside /data"
    if not source.is_dir():
        return False, f"source directory is unavailable: {source}"

    source_inodes: set[int] = set()
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_nlink >= 2:
            source_inodes.add(stat.st_ino)
    if not source_inodes:
        return False, "private source has no hardlinked files"

    library = data_root / "Media"
    if not library.is_dir():
        return False, f"library directory is unavailable: {library}"
    for path in library.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_ino in source_inodes:
                return True, f"verified library hardlink: {path}"
        except OSError:
            continue
    return False, "private source hardlinks do not appear in the media library"


def run_cleanup(
    stack_dir: Path,
    dry_run: bool,
    max_delete: int,
    minimum_audio_age_minutes: float = MINIMUM_AUDIO_VALIDATION_AGE_MINUTES,
) -> int:
    sources = (
        ArrSource("Sonarr", "http://127.0.0.1:8989", stack_dir / "config/sonarr/config.xml"),
        ArrSource("Radarr", "http://127.0.0.1:7878", stack_dir / "config/radarr/config.xml"),
    )

    try:
        imported_hashes: set[str] = set()
        for source in sources:
            imported_hashes.update(
                history_import_hashes(
                    ArrClient(source.base_url, read_api_key(source.config_file))
                )
            )

        radarr = ArrClient(
            "http://127.0.0.1:7878",
            read_api_key(stack_dir / "config/radarr/config.xml"),
        )
        remove_unsupported_radarr_audio(
            radarr,
            dry_run,
            max_delete,
            minimum_audio_age_minutes,
        )

        username, password = read_credentials(stack_dir / "secrets/qbittorrent.json")
        qbittorrent = QBittorrentClient("http://127.0.0.1:8888", username, password)
        qbittorrent.login()
        torrents = qbittorrent.get_json("/api/v2/torrents/info")
    except (ArrError, QBittorrentError) as error:
        raise PublicCleanupError(str(error)) from error

    candidates: list[dict[str, Any]] = []
    skipped = 0
    for torrent in torrents:
        torrent_hash = str(torrent.get("hash", "")).upper()
        imported = torrent_hash in imported_hashes
        if not imported and torrent.get("private") is True:
            imported, import_reason = private_torrent_has_library_hardlink(
                torrent,
                DEFAULT_DATA_ROOT,
            )
            if imported:
                print(f"IMPORTED VIA HARDLINK: {torrent.get('name', '')}\n  {import_reason}")
        if not imported:
            continue

        hosts: set[str] | None = None
        if torrent.get("private") is True:
            try:
                hosts = PRIVATE_AUDIT.torrent_hosts(
                    qbittorrent,
                    str(torrent.get("hash", "")),
                )
            except QBittorrentError as error:
                print(
                    f"SKIP: {torrent.get('name', '')}\n"
                    f"  reason: unable to inspect private tracker: {error}"
                )
                skipped += 1
                continue
        safe, reason = torrent_is_removable(torrent, hosts)
        if not safe:
            print(f"SKIP: {torrent.get('name', '')}\n  reason: {reason}")
            skipped += 1
            continue
        candidates.append(torrent)

    if not dry_run and len(candidates) > max_delete:
        raise PublicCleanupError(
            f"Refusing to remove {len(candidates)} torrents in one run; "
            f"increase --max-delete above {max_delete} after reviewing a dry run."
        )

    for torrent in candidates:
        seeded_minutes = int(torrent.get("seeding_time", 0) or 0) / 60
        prefix = "WOULD REMOVE" if dry_run else "REMOVING"
        print(
            f"{prefix}: {torrent.get('name', '')}\n"
            f"  hash: {str(torrent.get('hash', ''))[:12].upper()}\n"
            f"  seeded: {seeded_minutes:.1f} minutes"
        )
        if not dry_run:
            qbittorrent.post_form(
                "/api/v2/torrents/delete",
                {
                    "hashes": str(torrent.get("hash", "")),
                    "deleteFiles": "true",
                },
            )

    print("\n=== Summary ===")
    print(f"Confirmed imported retention candidates: {len(candidates)}")
    print(f"Skipped imported torrents: {skipped}")
    print("Dry run: nothing was deleted." if dry_run else f"Torrents removed: {len(candidates)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Remove imported qBittorrent torrents only after their public or "
            "managed-private seeding requirement has been satisfied."
        )
    )
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-delete", type=int, default=MAX_DELETE_DEFAULT)
    parser.add_argument(
        "--minimum-audio-age-minutes",
        type=float,
        default=MINIMUM_AUDIO_VALIDATION_AGE_MINUTES,
        help="Wait for MediaInfo before rejecting unsupported audio.",
    )
    args = parser.parse_args()
    return run_cleanup(
        args.stack_dir,
        args.dry_run,
        args.max_delete,
        args.minimum_audio_age_minutes,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicCleanupError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
