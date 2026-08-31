#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
LEGACY_DOWNLOADS = "/downloads"
LEGACY_MEDIA = "/media"
PREFERRED_MEDIA = "/data"


class BazarrAuditError(RuntimeError):
    pass


def grep_references(
    config_dir: Path,
    needle: str,
) -> list[str]:
    if not config_dir.exists():
        return []

    if shutil.which("rg"):
        result = subprocess.run(
            [
                "rg",
                "--no-heading",
                "--line-number",
                "--fixed-strings",
                needle,
                str(config_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode not in (0, 1):
            raise BazarrAuditError(
                f"rg failed while searching for {needle!r}"
            )

        return [
            line
            for line in result.stdout.splitlines()
            if line.strip()
        ]

    matches: list[str] = []
    for root, _dirs, files in os.walk(config_dir):
        for filename in files:
            path = Path(root) / filename
            try:
                lines = path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                ).splitlines()
            except OSError:
                continue

            for index, line in enumerate(lines, start=1):
                if needle in line:
                    matches.append(
                        f"{path}:{index}:{line}"
                    )

    return matches


def inspect_mount_targets() -> list[str]:
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            "{{range .Mounts}}{{println .Destination}}{{end}}",
            "bazarr",
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
        description=(
            "Audit Bazarr for legacy path assumptions before "
            "removing compatibility mounts."
        )
    )
    parser.add_argument(
        "--stack-dir",
        type=Path,
        default=DEFAULT_STACK_DIR,
    )
    args = parser.parse_args()

    config_dir = args.stack_dir / "config" / "bazarr"

    try:
        mounts = inspect_mount_targets()
    except (
        OSError,
        subprocess.CalledProcessError,
    ) as error:
        raise BazarrAuditError(
            f"Unable to inspect Bazarr mounts: {error}"
        ) from error

    if PREFERRED_MEDIA not in mounts:
        raise BazarrAuditError(
            "Bazarr is missing the /data mount."
        )

    downloads_refs = grep_references(
        config_dir,
        LEGACY_DOWNLOADS,
    )
    media_refs = grep_references(
        config_dir,
        LEGACY_MEDIA,
    )
    data_refs = grep_references(
        config_dir,
        PREFERRED_MEDIA,
    )

    print("Bazarr mount audit:")
    for mount in mounts:
        print(f"  mount: {mount}")

    print()
    print("Bazarr config audit:")
    print(
        f"  /downloads references: {len(downloads_refs)}"
    )
    print(
        f"  /media references: {len(media_refs)}"
    )
    print(
        f"  /data references: {len(data_refs)}"
    )

    if downloads_refs:
        print()
        print(
            "Legacy /downloads references detected:"
        )
        for line in downloads_refs[:20]:
            print(f"  {line}")
        raise BazarrAuditError(
            "Bazarr still references /downloads."
        )

    if media_refs:
        print()
        print(
            "Compatibility /media references still present:"
        )
        for line in media_refs[:20]:
            print(f"  {line}")
        print(
            "Keep the /media compatibility mount until these "
            "references are reviewed or eliminated."
        )
    else:
        print()
        print(
            "No Bazarr /media references found. Compatibility "
            "mount removal may be reviewed separately."
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BazarrAuditError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
