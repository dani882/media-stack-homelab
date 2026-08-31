#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_DOWNLOADS = Path("/volume1/Family/Downloads")
DEFAULT_MEDIA = Path("/volume1/Family/Media")
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
        default=20,
    )
    parser.add_argument(
        "--require-matches",
        type=int,
        default=1,
    )
    args = parser.parse_args()

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

    for media_file in files:
        scanned += 1
        stat_result = media_file.stat()
        if stat_result.st_nlink < 2:
            continue

        matches = matching_download_paths(
            args.downloads_root,
            media_file,
        )
        download_matches = [
            path
            for path in matches
            if path.startswith(str(args.downloads_root))
        ]

        if not download_matches:
            continue

        found += 1
        print(
            "HARDLINK MATCH:"
            f" inode={stat_result.st_ino}"
            f" links={stat_result.st_nlink}"
        )
        print(f"  media: {media_file}")
        print(f"  download: {download_matches[0]}")

    print()
    print(f"Scanned recent media files: {scanned}")
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
