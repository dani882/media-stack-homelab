#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".m4v",
    ".mov",
    ".ts",
    ".wmv",
}


class HardlinkVerificationError(RuntimeError):
    pass


def resolve_media_path(path: Path) -> Path:
    if not path.exists():
        raise HardlinkVerificationError(
            f"Path not found: {path}"
        )

    if path.is_file():
        return path

    candidates = [
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and candidate.suffix.lower() in VIDEO_EXTENSIONS
    ]

    if not candidates:
        raise HardlinkVerificationError(
            f"No media files found under {path}"
        )

    return max(
        candidates,
        key=lambda candidate: (
            candidate.stat().st_size,
            str(candidate),
        ),
    )


def format_stat(path: Path) -> str:
    stat_result = path.stat()
    return (
        f"inode={stat_result.st_ino} "
        f"links={stat_result.st_nlink} "
        f"size={stat_result.st_size} "
        f"path={path}"
    )


def verify_pair(
    download_path: Path,
    library_path: Path,
    minimum_links: int,
) -> None:
    download_file = resolve_media_path(download_path)
    library_file = resolve_media_path(library_path)

    download_stat = download_file.stat()
    library_stat = library_file.stat()

    print("Download:")
    print(f"  {format_stat(download_file)}")
    print("Library:")
    print(f"  {format_stat(library_file)}")

    if download_stat.st_size != library_stat.st_size:
        raise HardlinkVerificationError(
            "Download and library files have different sizes."
        )

    if download_stat.st_ino != library_stat.st_ino:
        raise HardlinkVerificationError(
            "Download and library files do not share the same inode."
        )

    if (
        download_stat.st_nlink < minimum_links
        or library_stat.st_nlink < minimum_links
    ):
        raise HardlinkVerificationError(
            f"Hardlink count is below {minimum_links}."
        )

    if os.path.samefile(
        download_file,
        library_file,
    ):
        print()
        print(
            "Hardlink verification passed: same inode, same size, "
            f"links >= {minimum_links}."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that a download file and its imported library "
            "file share the same inode."
        )
    )
    parser.add_argument(
        "--download",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--library",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--minimum-links",
        type=int,
        default=2,
    )
    args = parser.parse_args()

    verify_pair(
        args.download,
        args.library,
        args.minimum_links,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HardlinkVerificationError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
