import re
from pathlib import PurePosixPath
from typing import Iterable


DANGEROUS_EXTENSIONS = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".exe",
        ".jar",
        ".js",
        ".lnk",
        ".msi",
        ".ps1",
        ".scr",
        ".vbs",
        ".zipx",
    }
)

_DANGEROUS_TITLE_RE = re.compile(
    r"(?:^|[\s._-])(?:bat|cmd|com|exe|jar|js|lnk|msi|ps1|scr|vbs|zipx)"
    r"(?:$|[\s._-])",
    re.IGNORECASE,
)

_UNACCEPTABLE_SOURCE_RE = re.compile(
    r"(?:^|[\s._-])(?:cam|hdcam|hdts|telesync|telecine|dvdscr|screener|"
    r"workprint|r5)(?:$|[\s._-])",
    re.IGNORECASE,
)

# YTS/YIFY publishes English-first encodes.  A tracker detail page can be
# mislabeled, so a Spanish claim must not override an unmistakable payload
# name from those sources.
_ENGLISH_ONLY_PAYLOAD_RE = re.compile(
    r"(?:^|[/\s._\-\[\]])(?:yts(?:[. _-]*(?:gg|mx|lt|bz))?|yify)"
    r"(?:$|[/\s._\-\[\]])",
    re.IGNORECASE,
)


def dangerous_release_title(title: str) -> bool:
    """Reject release titles that advertise an executable-like payload."""
    return bool(_DANGEROUS_TITLE_RE.search(title))


def unacceptable_source_title(title: str) -> bool:
    """Reject camera captures and other unsuitable pre-release sources."""
    return bool(_UNACCEPTABLE_SOURCE_RE.search(title))


def dangerous_torrent_paths(paths: Iterable[str]) -> list[str]:
    """Return torrent members whose final extension is unsafe for media."""
    return [
        path
        for path in paths
        if PurePosixPath(path).suffix.casefold() in DANGEROUS_EXTENSIONS
    ]


def english_only_torrent_paths(paths: Iterable[str]) -> list[str]:
    """Return payload names from release groups known to be English-first."""
    return [path for path in paths if _ENGLISH_ONLY_PAYLOAD_RE.search(path)]
