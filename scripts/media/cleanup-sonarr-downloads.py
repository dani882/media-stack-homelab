#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common.cleanup import (
    CleanupConfig,
    CleanupError,
    run_cleanup,
)


DEFAULT_STACK_DIR = Path(
    "/volume1/docker/media-stack"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clean completed Sonarr downloads that can no longer "
            "be imported because they are not Custom Format upgrades."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )
    parser.add_argument(
        "--max-delete",
        type=int,
        default=10,
        help=(
            "Maximum number of downloads to remove in one "
            "destructive run."
        ),
    )

    parser.add_argument(
        "--sonarr-url",
        default="http://127.0.0.1:8989",
    )

    parser.add_argument(
        "--stack-dir",
        type=Path,
        default=DEFAULT_STACK_DIR,
    )

    args = parser.parse_args()

    config = CleanupConfig(
        app_name="Sonarr",
        base_url=args.sonarr_url,
        config_file=(
            args.stack_dir
            / "config/sonarr/config.xml"
        ),
        category="tv",
        include_unknown_key=(
            "includeUnknownSeriesItems"
        ),
        qbittorrent_url=(
            "http://127.0.0.1:8888"
        ),
        qbittorrent_secret=(
            args.stack_dir
            / "secrets/qbittorrent.json"
        ),
    )

    return run_cleanup(
        config,
        args.dry_run,
        max_delete=args.max_delete,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CleanupError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        raise SystemExit(1)
