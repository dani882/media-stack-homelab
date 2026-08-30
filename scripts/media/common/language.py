from __future__ import annotations

import re
from enum import IntEnum
from typing import Any


class LanguageRank(IntEnum):
    UNKNOWN = 0
    ENGLISH = 1
    CASTILIAN = 2
    LATINO = 3


LATINO_FORMAT_PREFIXES = (
    "[Latino] Spanish Latino",
    "[Latino] Spanish Latino + English",
)

CASTILIAN_FORMAT_PREFIXES = (
    "[Spanish] Castellano",
    "[Spanish] Castellano + English",
)

TOKEN_START = r"(?<![A-Z0-9])"
TOKEN_END = r"(?![A-Z0-9])"
SEPARATOR = r"[ ._-]?"

LATINO_TITLE_PATTERN = re.compile(
    TOKEN_START
    + r"(?:"
    + r"LATINO|LATAM|ES"
    + SEPARATOR
    + r"419|SPA"
    + SEPARATOR
    + r"LAT|ESP"
    + SEPARATOR
    + r"LAT|SPANISH"
    + SEPARATOR
    + r"LAT(?:INO)?|AUDIO"
    + SEPARATOR
    + r"LAT(?:INO)?|YERISAN710|USERHEVC|URBIN4HD|DAV1NCI|"
    + r"DUAL[ ._-]*(?:AUDIO[ ._-]*)?"
    + r"(?:SPA[ ._-]*ENG|ENG[ ._-]*SPA|"
    + r"ESP[ ._-]*ENG|ENG[ ._-]*ESP)"
    + r")"
    + TOKEN_END,
    re.IGNORECASE,
)

CASTILIAN_TITLE_PATTERN = re.compile(
    TOKEN_START
    + r"(?:SPANISH|CASTELLANO|CASTILIAN|"
    + r"ESP(?:AÑOL|ANOL)?|SPA)"
    + TOKEN_END,
    re.IGNORECASE,
)

ENGLISH_TITLE_PATTERN = re.compile(
    TOKEN_START
    + r"(?:ENGLISH|ENG)"
    + TOKEN_END,
    re.IGNORECASE,
)

OVERRIDABLE_REJECTION_PREFIXES = (
    "Existing file on disk is of equal or higher preference",
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


def _has_prefix(
    payload: dict[str, Any],
    prefixes: tuple[str, ...],
) -> bool:
    return any(
        any(
            name.startswith(prefix)
            for prefix in prefixes
        )
        for name in custom_format_names(payload)
    )


def language_rank(
    payload: dict[str, Any] | None,
) -> LanguageRank:
    if not payload:
        return LanguageRank.UNKNOWN

    if _has_prefix(
        payload,
        LATINO_FORMAT_PREFIXES,
    ):
        return LanguageRank.LATINO

    if _has_prefix(
        payload,
        CASTILIAN_FORMAT_PREFIXES,
    ):
        return LanguageRank.CASTILIAN

    title = str(
        payload.get("title")
        or payload.get("relativePath")
        or ""
    )

    # A specific Latino title marker is more informative than
    # generic "Spanish" metadata returned by Servarr/indexers.
    if LATINO_TITLE_PATTERN.search(title):
        return LanguageRank.LATINO

    languages = {
        item.get("name", "")
        for item in payload.get(
            "languages",
            [],
        )
    }

    if "Spanish (Latino)" in languages:
        return LanguageRank.LATINO

    if (
        "Spanish" in languages
        or "Spanish (Spain)" in languages
        or "Castilian" in languages
    ):
        return LanguageRank.CASTILIAN

    if "English" in languages:
        return LanguageRank.ENGLISH

    if CASTILIAN_TITLE_PATTERN.search(title):
        return LanguageRank.CASTILIAN

    if ENGLISH_TITLE_PATTERN.search(title):
        return LanguageRank.ENGLISH

    return LanguageRank.UNKNOWN


def language_name(
    payload: dict[str, Any] | None,
) -> str:
    return language_rank(payload).name.lower()


def is_language_upgrade(
    installed: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> bool:
    candidate_rank = language_rank(candidate)

    if candidate_rank < LanguageRank.CASTILIAN:
        return False

    return (
        candidate_rank
        > language_rank(installed)
    )


def rejection_reasons(
    release: dict[str, Any],
) -> list[str]:
    return [
        str(reason)
        for reason in release.get(
            "rejections",
            [],
        )
        if str(reason).strip()
    ]


def rejection_is_overridable(
    reason: str,
) -> bool:
    return any(
        reason.startswith(prefix)
        for prefix in OVERRIDABLE_REJECTION_PREFIXES
    )


def release_is_safe_language_upgrade(
    installed: dict[str, Any] | None,
    release: dict[str, Any],
) -> bool:
    if not is_language_upgrade(
        installed,
        release,
    ):
        return False

    if not bool(
        release.get(
            "downloadAllowed",
            True,
        )
    ):
        return False

    rejected = bool(
        release.get(
            "rejected",
            False,
        )
    )

    if not rejected:
        return True

    reasons = rejection_reasons(
        release
    )

    if not reasons:
        return False

    return all(
        rejection_is_overridable(reason)
        for reason in reasons
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


def language_upgrade_sort_key(
    release: dict[str, Any],
) -> tuple[int, int, int]:
    return (
        int(language_rank(release)),
        *score_seed_sort_key(release),
    )


def best_language_upgrade(
    installed: dict[str, Any] | None,
    releases: list[dict[str, Any]],
) -> dict[str, Any] | None:
    candidates = [
        release
        for release in releases
        if release_is_safe_language_upgrade(
            installed,
            release,
        )
    ]

    candidates.sort(
        key=language_upgrade_sort_key,
        reverse=True,
    )

    return (
        candidates[0]
        if candidates
        else None
    )
