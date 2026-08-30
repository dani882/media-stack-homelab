from __future__ import annotations

from typing import Any

try:
    from common.language import (
        LanguageRank,
        approval_sort_key,
        custom_format_names,
        language_rank,
        score_seed_sort_key,
    )
except ModuleNotFoundError:
    from scripts.media.common.language import (
        LanguageRank,
        approval_sort_key,
        custom_format_names,
        language_rank,
        score_seed_sort_key,
    )


LATINO_FORMAT_PREFIX = "[Latino]"

LATINO_FORMAT_PREFIXES = (
    "[Latino] Spanish Latino",
    "[Latino] Spanish Latino + English",
)


def has_latino_format(
    payload: dict[str, Any],
) -> bool:
    return (
        language_rank(payload)
        == LanguageRank.LATINO
    )


def is_latino_release(
    release: dict[str, Any],
) -> bool:
    return (
        language_rank(release)
        == LanguageRank.LATINO
    )


def installed_is_latino(
    payload: dict[str, Any] | None,
) -> bool:
    return (
        language_rank(payload)
        == LanguageRank.LATINO
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
