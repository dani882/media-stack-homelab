#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


MODULES = (
    ("custom formats and profile scores", "custom_formats.py"),
    ("application settings", "settings.py"),
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Sonarr and Radarr."
    )
    parser.add_argument(
        "--stack-dir",
        default="/volume1/docker/media-stack",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended changes without applying them.",
    )
    return parser.parse_args()


def run_module(
    module_dir: Path,
    label: str,
    filename: str,
    stack_dir: str,
    dry_run: bool,
) -> None:
    module_name = Path(filename).stem

    command = [
        sys.executable,
        "-m",
        f"servarr_config.{module_name}",
        "--stack-dir",
        stack_dir,
    ]

    if dry_run:
        command.append("--dry-run")

    print()
    print(f"Configuring Servarr {label}...")

    result = subprocess.run(
        command,
        cwd=module_dir.parent,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Servarr {label} configuration failed "
            f"with exit code {result.returncode}"
        )


def main() -> int:
    arguments = parse_arguments()
    module_dir = Path(__file__).resolve().parent / "servarr_config"

    try:
        for label, filename in MODULES:
            run_module(
                module_dir=module_dir,
                label=label,
                filename=filename,
                stack_dir=arguments.stack_dir,
                dry_run=arguments.dry_run,
            )
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print()
    print("Servarr configuration completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
