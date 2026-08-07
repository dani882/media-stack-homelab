from __future__ import annotations

from typing import Any


LATINO_FORMAT_PREFIX = "[Latino]"

LATINO_FORMAT_PREFIXES = (
    "[Latino] Spanish Latino",
    "[Latino] Spanish Latino + English",
)

LATINO_TITLE_MARKERS = (
    "LATINO",
    "LATAM",
    "SPA ENG",
    "SPA-ENG",
    "SPA.ENG",
    "ESP ENG",
    "ESP-ENG",
    "ESP.ENG",
    "DUAL AUDIO",
    "DUAL-AUDIO",
    "DUAL.AUDIO",
)


def custom_format_names(
    payload: dict[str, Any],
) -> list[str]:
    return [
        item.get("name", "")
        for item in payload.get(
            "customFormats",
            [],
        )
    ]


def has_latino_format(
    payload: dict[str, Any],
) -> bool:
    names = custom_format_names(payload)

    return any(
        any(
            name.startswith(prefix)
            for prefix in LATINO_FORMAT_PREFIXES
        )
        for name in names
    )


def is_latino_release(
    release: dict[str, Any],
) -> bool:
    if any(
        name.startswith(LATINO_FORMAT_PREFIX)
        for name in custom_format_names(release)
    ):
        return True

    languages = {
        item.get("name", "")
        for item in release.get(
            "languages",
            [],
        )
    }

    if "Spanish (Latino)" in languages:
        return True

    title = (
        release.get("title")
        or ""
    ).upper()

    return any(
        marker in title
        for marker in LATINO_TITLE_MARKERS
    )


def installed_is_latino(
    payload: dict[str, Any] | None,
) -> bool:
    if not payload:
        return False

    return any(
        name.startswith(LATINO_FORMAT_PREFIX)
        for name in custom_format_names(payload)
    )


def score_seed_sort_key(
    release: dict[str, Any],
) -> tuple[int, int]:
    return (
        int(
            release.get(
                "customFormatScore",
                0,
            )
            or 0
        ),
        int(
            release.get(
                "seeders",
                0,
            )
            or 0
        ),
    )


def approval_sort_key(
    release: dict[str, Any],
) -> tuple[bool, bool, int, int]:
    return (
        bool(
            release.get(
                "approved",
                False,
            )
        ),
        not bool(
            release.get(
                "rejected",
                False,
            )
        ),
        *score_seed_sort_key(release),
    )


def best_latino_release(
    releases: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = [
        release
        for release in releases
        if is_latino_release(release)
    ]

    candidates.sort(
        key=approval_sort_key,
        reverse=True,
    )

    return (
        candidates[0]
        if candidates
        else None
    )
