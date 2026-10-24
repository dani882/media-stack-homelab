#!/usr/bin/env python3
"""Stage completed Lat-Team codec fallbacks as verified H.264 imports."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STACK = Path("/volume1/docker/media-stack")
SCRIPT_ROOT = Path(__file__).resolve().parent
for module_dir in (SCRIPT_ROOT / "media", STACK / "scripts"):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from common.latteam_transcode import (  # noqa: E402
    LatTeamTranscodeError,
    StagedContent,
    stage_completed_content,
)
from common.qbittorrent import (  # noqa: E402
    QBittorrentClient,
    QBittorrentError,
    read_credentials,
)


QBITTORRENT_URL = "http://127.0.0.1:8888"
RADARR_URL = "http://127.0.0.1:7878"
SONARR_URL = "http://127.0.0.1:8989"


class LatTeamWorkerError(RuntimeError):
    pass


def api_key(path: Path) -> str:
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(path).getroot()
        value = root.findtext("ApiKey", "").strip()
    except (OSError, ET.ParseError) as error:
        raise LatTeamWorkerError(f"Unable to read {path}") from error
    if not value:
        raise LatTeamWorkerError(f"API key is missing in {path}")
    return value


def post_json(url: str, payload: dict[str, Any], key: str) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Api-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        response.read()


def tags(torrent: dict[str, Any]) -> set[str]:
    return {
        item.strip()
        for item in str(torrent.get("tags") or "").split(",")
        if item.strip()
    }


def expected_marker(values: set[str]) -> str | None:
    if {"movie-expected-latino", "fallback-language-latino"} & values:
        return "LATINO"
    if {"movie-expected-castilian", "fallback-language-castilian"} & values:
        return "CASTELLANO"
    return None


def eligible(torrent: dict[str, Any]) -> bool:
    values = tags(torrent)
    return bool(
        float(torrent.get("progress", 0) or 0) >= 1
        and {"private", "lat-team", "latteam-transcode-required"} <= values
        and "latteam-transcode-ready" not in values
        and "latteam-transcode-review" not in values
        and "language-mismatch" not in values
        and ({"private-dispatch", "series-fallback"} & values)
    )


def validate_upgrade_provenance(values: set[str]) -> None:
    if "movie-language-upgrade" in values and not any(
        item.startswith("radarr-original-file-") for item in values
    ):
        raise LatTeamWorkerError("Movie upgrade is missing its original file ID")
    if "series-language-upgrade" in values and not any(
        item.startswith("sonarr-original-file-") for item in values
    ):
        raise LatTeamWorkerError("Series upgrade is missing its original file IDs")


def request_import(
    torrent: dict[str, Any], staged: StagedContent, stack: Path
) -> tuple[str, str]:
    values = tags(torrent)
    torrent_hash = str(torrent.get("hash") or "")
    if "private-dispatch" in values:
        post_json(
            f"{RADARR_URL}/api/v3/command",
            {
                "name": "DownloadedMoviesScan",
                "path": staged.container_path,
                "downloadClientId": torrent_hash,
                "importMode": "Auto",
            },
            api_key(stack / "config/radarr/config.xml"),
        )
        return "private-dispatch-import-requested", "Radarr"
    post_json(
        f"{SONARR_URL}/api/v3/command",
        {
            "name": "DownloadedEpisodesScan",
            "path": staged.container_path,
            "downloadClientId": torrent_hash,
            "importMode": "Auto",
        },
        api_key(stack / "config/sonarr/config.xml"),
    )
    return "series-fallback-import-requested", "Sonarr"


def write_status(stack: Path, payload: dict[str, Any]) -> None:
    path = stack / "state/latteam-transcode.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def add_torrent_tags(
    qbit: QBittorrentClient, torrent_hash: str, tag_values: str
) -> None:
    """Refresh the qBittorrent session before tagging after a long conversion."""
    qbit.login()
    qbit.post_form(
        "/api/v2/torrents/addTags",
        {"hashes": torrent_hash, "tags": tag_values},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=STACK)
    parser.add_argument("--torrent")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    username, password = read_credentials(
        args.stack_dir / "secrets/qbittorrent.json"
    )
    qbit = QBittorrentClient(QBITTORRENT_URL, username, password)
    qbit.login()
    torrents = qbit.get_json("/api/v2/torrents/info")
    candidates = [item for item in torrents if eligible(item)]
    if args.torrent:
        needle = args.torrent.casefold()
        candidates = [
            item
            for item in candidates
            if needle in str(item.get("hash") or "").casefold()
            or needle in str(item.get("name") or "").casefold()
        ]
    if not candidates:
        print("LAT-TEAM TRANSCODE OK: no completed fallback requires staging")
        return 0

    torrent = sorted(candidates, key=lambda item: int(item.get("added_on", 0)))[0]
    torrent_hash = str(torrent.get("hash") or "")
    values = tags(torrent)
    marker = expected_marker(values)
    if marker is None:
        raise LatTeamWorkerError("Lat-Team fallback has no proven Spanish language")
    validate_upgrade_provenance(values)
    content_path = str(torrent.get("content_path") or "")
    if not content_path.startswith("/data/Downloads/"):
        raise LatTeamWorkerError("Completed path is outside Downloads")

    print(
        f"{'STAGE' if args.apply else 'WOULD STAGE'} LAT-TEAM H.264: "
        f"name={torrent.get('name')} language={marker.lower()}"
    )
    if not args.apply:
        return 0

    write_status(
        args.stack_dir,
        {
            "checkedAt": datetime.now(UTC).isoformat(),
            "status": "converting",
            "torrent": torrent_hash[:12],
        },
    )
    try:
        staged = stage_completed_content(content_path, torrent_hash, marker)
        import_tag, manager = request_import(torrent, staged, args.stack_dir)
    except (LatTeamTranscodeError, LatTeamWorkerError, OSError) as error:
        retryable = "temperature" in str(error).casefold()
        write_status(
            args.stack_dir,
            {
                "checkedAt": datetime.now(UTC).isoformat(),
                "status": "paused" if retryable else "review",
                "message": str(error),
                "torrent": torrent_hash[:12],
            },
        )
        if not retryable:
            try:
                add_torrent_tags(
                    qbit, torrent_hash, "latteam-transcode-review"
                )
            except QBittorrentError as tag_error:
                print(f"LAT-TEAM TRANSCODE TAG REVIEW: {tag_error}")
        print(f"LAT-TEAM TRANSCODE {'PAUSED' if retryable else 'REVIEW'}: {error}")
        return 0 if retryable else 1

    write_status(
        args.stack_dir,
        {
            "checkedAt": datetime.now(UTC).isoformat(),
            "convertedFiles": staged.converted_files,
            "linkedFiles": staged.linked_files,
            "manager": manager,
            "status": "import-requested",
            "torrent": torrent_hash[:12],
        },
    )
    try:
        add_torrent_tags(
            qbit,
            torrent_hash,
            f"latteam-transcode-ready,{import_tag}",
        )
    except QBittorrentError as error:
        write_status(
            args.stack_dir,
            {
                "checkedAt": datetime.now(UTC).isoformat(),
                "convertedFiles": staged.converted_files,
                "linkedFiles": staged.linked_files,
                "manager": manager,
                "message": f"Import requested; unable to apply qBittorrent tags: {error}",
                "status": "review",
                "torrent": torrent_hash[:12],
            },
        )
        print(f"LAT-TEAM TRANSCODE TAG REVIEW: {error}")
        return 1
    print(
        f"LAT-TEAM H.264 READY: manager={manager} "
        f"converted={staged.converted_files} linked={staged.linked_files}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
