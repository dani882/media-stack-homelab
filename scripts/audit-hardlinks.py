#!/usr/bin/env python3


import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_DOWNLOADS = Path("/volume1/Family/Downloads")
DEFAULT_MEDIA = Path("/volume1/Family/Media")
DEFAULT_LIMIT = 500
DEFAULT_MAX_REPORT = 10
VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".m4v",
    ".mov",
    ".ts",
    ".wmv",
}


class HardlinkAuditError(RuntimeError):
    pass


def recent_media_files(
    media_root: Path,
    limit: int,
) -> list[Path]:
    candidates = [
        path
        for path in media_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    candidates.sort(
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[:limit]


def matching_download_paths(
    downloads_root: Path,
    media_file: Path,
) -> list[str]:
    result = subprocess.run(
        [
            "find",
            str(downloads_root),
            "-xdev",
            "-samefile",
            str(media_file),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def download_inode_index(downloads_root: Path) -> dict[tuple[int, int], Path]:
    """Index video payloads once instead of scanning Downloads per media file."""
    index: dict[tuple[int, int], Path] = {}
    for path in downloads_root.rglob("*"):
        try:
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            stat_result = path.stat()
        except OSError:
            continue
        index.setdefault((stat_result.st_dev, stat_result.st_ino), path)
    return index


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit recent media files for real hardlink counterparts."
    )
    parser.add_argument(
        "--downloads-root",
        type=Path,
        default=DEFAULT_DOWNLOADS,
    )
    parser.add_argument(
        "--media-root",
        type=Path,
        default=DEFAULT_MEDIA,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
    )
    parser.add_argument(
        "--require-matches",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--max-report",
        type=int,
        default=DEFAULT_MAX_REPORT,
        help="Maximum number of matching file pairs to print.",
    )
    args = parser.parse_args()

    if args.limit < 1 or args.require_matches < 0 or args.max_report < 0:
        raise HardlinkAuditError(
            "--limit must be positive; match and report limits "
            "must be non-negative."
        )

    files = recent_media_files(
        args.media_root,
        args.limit,
    )

    if not files:
        raise HardlinkAuditError(
            "No media files found to audit."
        )

    found = 0
    scanned = 0
    download_index = download_inode_index(args.downloads_root)

    for media_file in files:
        scanned += 1
        stat_result = media_file.stat()
        if stat_result.st_nlink < 2:
            continue

        download_match = download_index.get(
            (stat_result.st_dev, stat_result.st_ino)
        )
        if download_match is None:
            continue

        found += 1
        if found <= args.max_report:
            print(
                "HARDLINK MATCH:"
                f" inode={stat_result.st_ino}"
                f" links={stat_result.st_nlink}"
            )
            print(f"  media: {media_file}")
            print(f"  download: {download_match}")

    print()
    print(f"Scanned recent media files: {scanned}")
    print(f"Indexed download video files: {len(download_index)}")
    print(f"Hardlink-backed matches found: {found}")

    if found < args.require_matches:
        raise HardlinkAuditError(
            f"Found only {found} hardlink-backed matches; "
            f"expected at least {args.require_matches}."
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HardlinkAuditError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
