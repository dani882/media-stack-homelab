from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.arr import ArrClient, ArrError, read_api_key
from common.qbittorrent import (
    QBittorrentClient,
    QBittorrentError,
    read_credentials,
)


MINIMUM_SEEDING_MINUTES = 30.0

SAFE_TORRENT_STATES = {
    "stoppedUP",
    "stalledUP",
    "queuedUP",
    "pausedUP",
}

SAFE_WARNING_MARKERS = (
    "Not a Custom Format upgrade",
)

DANGEROUS_WARNING_MARKERS = (
    "Found potentially dangerous file with extension",
)


class CleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class CleanupConfig:
    app_name: str
    base_url: str
    config_file: Path
    category: str
    include_unknown_key: str
    qbittorrent_url: str
    qbittorrent_secret: Path


def queue_warning_messages(
    queue_item: dict[str, Any],
) -> list[str]:
    messages: list[str] = []

    for status_message in queue_item.get(
        "statusMessages",
        [],
    ):
        for message in status_message.get(
            "messages",
            [],
        ):
            messages.append(
                str(message)
            )

    return messages


def has_safe_warning(
    queue_item: dict[str, Any],
) -> bool:
    messages = queue_warning_messages(
        queue_item
    )

    return any(
        marker in message
        for marker in SAFE_WARNING_MARKERS
        for message in messages
    )


def has_dangerous_warning(
    queue_item: dict[str, Any],
) -> bool:
    messages = queue_warning_messages(
        queue_item
    )

    return any(
        marker in message
        for marker in DANGEROUS_WARNING_MARKERS
        for message in messages
    )


def torrent_is_safe_to_remove(
    torrent: dict[str, Any],
    category: str,
    require_seeding: bool = True,
) -> tuple[bool, str]:
    progress = float(
        torrent.get("progress", 0)
        or 0
    )

    amount_left = int(
        torrent.get("amount_left", 0)
        or 0
    )

    force_start = bool(
        torrent.get("force_start", False)
    )

    state = str(
        torrent.get("state", "")
    )

    torrent_category = str(
        torrent.get("category", "")
    )

    seeding_seconds = int(
        torrent.get("seeding_time", 0)
        or 0
    )

    seeding_minutes = (
        seeding_seconds / 60
    )

    seeding_time_limit = int(
        torrent.get("seeding_time_limit", -1)
        or -1
    )

    required_seeding_minutes = (
        MINIMUM_SEEDING_MINUTES
        if require_seeding
        else 0.0
    )

    if seeding_time_limit >= 0:
        required_seeding_minutes = max(
            required_seeding_minutes,
            float(seeding_time_limit),
        )

    if torrent_category != category:
        return False, (
            f"category is {torrent_category!r}, "
            f"not {category!r}"
        )

    if progress < 1:
        return False, "torrent is not complete"

    if amount_left != 0:
        return False, (
            f"amount_left is {amount_left}"
        )

    if force_start:
        return False, "Force Start is enabled"

    if state not in SAFE_TORRENT_STATES:
        return False, (
            f"state {state!r} is not safe"
        )

    if seeding_minutes < required_seeding_minutes:
        return False, (
            f"seeded only {seeding_minutes:.1f} minutes; "
            f"requires {required_seeding_minutes:.1f} minutes"
        )

    return True, "safe"


def run_cleanup(
    config: CleanupConfig,
    dry_run: bool,
) -> int:
    try:
        api_key = read_api_key(
            config.config_file
        )

        username, password = (
            read_credentials(
                config.qbittorrent_secret
            )
        )

        arr = ArrClient(
            config.base_url,
            api_key,
        )

        qbittorrent = QBittorrentClient(
            config.qbittorrent_url,
            username,
            password,
        )

        qbittorrent.login()

        queue = arr.get(
            "/queue?"
            + urllib.parse.urlencode(
                {
                    "page": 1,
                    "pageSize": 500,
                    config.include_unknown_key: "true",
                }
            )
        )

        torrents = qbittorrent.get_json(
            "/api/v2/torrents/info"
        )

    except (
        ArrError,
        QBittorrentError,
    ) as error:
        raise CleanupError(str(error)) from error

    torrents_by_hash = {
        str(
            torrent.get("hash", "")
        ).upper(): torrent
        for torrent in torrents
    }

    candidates = 0
    cleaned = 0

    for item in queue.get(
        "records",
        [],
    ):
        if item.get("status") != "completed":
            continue

        if (
            item.get("trackedDownloadState")
            != "importPending"
        ):
            continue

        if (
            item.get("trackedDownloadStatus")
            != "warning"
        ):
            continue

        dangerous = has_dangerous_warning(item)
        normal_cleanup = has_safe_warning(item)

        if not dangerous and not normal_cleanup:
            continue

        download_id = str(
            item.get("downloadId", "")
        ).upper()

        if not download_id:
            continue

        torrent = torrents_by_hash.get(
            download_id
        )

        if torrent is None:
            print(
                "SKIP: qBittorrent torrent not found:"
            )
            print(
                f"  {item.get('title', '')}"
            )
            continue

        safe, reason = torrent_is_safe_to_remove(
            torrent,
            config.category,
            require_seeding=not dangerous,
        )

        if not safe:
            print(
                f"SKIP: {item.get('title', '')}"
            )
            print(
                f"  reason: {reason}"
            )
            continue

        candidates += 1

        seeding_minutes = (
            int(
                torrent.get(
                    "seeding_time",
                    0,
                )
                or 0
            )
            / 60
        )

        if dangerous:
            prefix = (
                "WOULD REMOVE DANGEROUS"
                if dry_run
                else "REMOVING DANGEROUS"
            )
        else:
            prefix = (
                "WOULD CLEAN"
                if dry_run
                else "CLEANING"
            )

        print()
        print(
            f"{prefix}: "
            f"{item.get('title', '')}"
        )
        print(
            f"  queue ID: {item.get('id')}"
        )
        print(
            f"  torrent: {torrent.get('name', '')}"
        )
        print(
            f"  state: {torrent.get('state', '')}"
        )
        print(
            f"  seeding: {seeding_minutes:.1f} minutes"
        )

        for warning in queue_warning_messages(
            item
        ):
            print(
                f"  warning: {warning}"
            )

        if dry_run:
            continue

        qbittorrent.post_form(
            "/api/v2/torrents/delete",
            {
                "hashes": download_id.lower(),
                "deleteFiles": "true",
            },
        )

        queue_id = int(
            item["id"]
        )

        arr.delete(
            f"/queue/{queue_id}?"
            + urllib.parse.urlencode(
                {
                    "removeFromClient": "false",
                    "blocklist": (
                        "true"
                        if dangerous
                        else "false"
                    ),
                    "skipRedownload": (
                        "false"
                        if dangerous
                        else "true"
                    ),
                }
            )
        )

        cleaned += 1

        print("  cleaned")

    print()
    print("=== Summary ===")
    print(
        f"Safe cleanup candidates: {candidates}"
    )

    if dry_run:
        print(
            "Dry run: nothing was deleted."
        )
    else:
        print(
            f"Downloads cleaned: {cleaned}"
        )

    return 0
