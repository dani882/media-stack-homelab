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
            "Clean completed Radarr downloads that can no longer "
            "be imported because they are not Custom Format upgrades."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    parser.add_argument(
        "--radarr-url",
        default="http://127.0.0.1:7878",
    )

    parser.add_argument(
        "--stack-dir",
        type=Path,
        default=DEFAULT_STACK_DIR,
    )

    args = parser.parse_args()

    config = CleanupConfig(
        app_name="Radarr",
        base_url=args.radarr_url,
        config_file=(
            args.stack_dir
            / "config/radarr/config.xml"
        ),
        category="radarr",
        include_unknown_key=(
            "includeUnknownMovieItems"
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
