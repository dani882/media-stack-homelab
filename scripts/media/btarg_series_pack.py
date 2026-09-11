"""Pure helpers for safely importing verified BTArg multi-season TV packs."""

from __future__ import annotations

import collections
import difflib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

try:
    from .common.btarg import BTArgDetail, parse_btarg_detail
except ImportError:  # Installed as a top-level NAS module.
    from common.btarg import BTArgDetail, parse_btarg_detail


VIDEO_EXTENSIONS = frozenset({".mkv", ".mp4", ".m4v"})
SAFE_AUXILIARY_EXTENSIONS = frozenset(
    {".ass", ".jpg", ".jpeg", ".nfo", ".png", ".srt", ".ssa", ".txt"}
)
BLOCKED_EXTENSIONS = frozenset(
    {
        ".7z",
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".dmg",
        ".exe",
        ".iso",
        ".js",
        ".msi",
        ".ps1",
        ".rar",
        ".scr",
        ".sh",
        ".vbs",
        ".zip",
        ".zipx",
    }
)


class PackValidationError(RuntimeError):
    """Raised when a pack cannot be proven safe and unambiguous."""


@dataclass(frozen=True)
class ParsedPackFile:
    path: str
    season: int
    ordinal: int
    title_fragments: tuple[str, ...]


@dataclass(frozen=True)
class EpisodeFileMapping:
    path: str
    season: int
    ordinal: int
    episode_ids: tuple[int, ...]
    episode_numbers: tuple[int, ...]
    first_title: str


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def parse_season_range(title: str) -> tuple[int, int] | None:
    match = re.search(r"\bS(\d{1,2})\s*-\s*S?(\d{1,2})\b", title, re.IGNORECASE)
    if not match:
        return None
    first, last = (int(match.group(1)), int(match.group(2)))
    if first < 1 or last < first:
        return None
    return first, last


def validate_torrent_paths(paths: Iterable[str]) -> tuple[str, ...]:
    normalized_paths = tuple(str(path) for path in paths)
    if not normalized_paths:
        raise PackValidationError("torrent contains no files")
    video_count = 0
    for path in normalized_paths:
        pure_path = PurePosixPath(path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise PackValidationError("torrent payload path escapes its download root")
        suffix = pure_path.suffix.casefold()
        if suffix in BLOCKED_EXTENSIONS:
            raise PackValidationError(f"blocked payload extension: {suffix}")
        if suffix in VIDEO_EXTENSIONS:
            video_count += 1
            continue
        if suffix not in SAFE_AUXILIARY_EXTENSIONS:
            raise PackValidationError(f"unsupported payload extension: {suffix or '<none>'}")
    if not video_count:
        raise PackValidationError("torrent contains no supported video files")
    return normalized_paths


def parse_pack_file(path: str) -> ParsedPackFile:
    pure_path = PurePosixPath(path)
    folder_match = re.fullmatch(r"T(\d{1,2})", pure_path.parts[0], re.IGNORECASE)
    stem = pure_path.stem
    numeric_match = re.match(r"^(\d{1,2})-(\d{1,3})\s+(.+)$", stem)
    scene_match = re.match(
        r"^S(\d{1,2})E(\d{1,3})[ ._-]+(.+)$",
        stem,
        re.IGNORECASE,
    )
    if numeric_match:
        season = int(numeric_match.group(1))
        ordinal = int(numeric_match.group(2))
        title_text = numeric_match.group(3)
    elif scene_match:
        season = int(scene_match.group(1))
        ordinal = int(scene_match.group(2))
        title_text = scene_match.group(3)
    else:
        raise PackValidationError(f"unrecognized episode filename: {path}")
    if folder_match and int(folder_match.group(1)) != season:
        raise PackValidationError(f"folder/filename season mismatch: {path}")

    title_text = re.sub(r"(?i)\.and\.", " & ", title_text)
    title_text = title_text.replace(".", " ")
    fragments = tuple(
        fragment.strip()
        for fragment in re.split(r"\s+&\s+", title_text)
        if fragment.strip()
    )
    if not fragments:
        raise PackValidationError(f"episode title is missing: {path}")
    return ParsedPackFile(path, season, ordinal, fragments)


def _episode_number(episode: dict[str, Any]) -> int:
    return int(episode["episodeNumber"])


def _titles_match(left: str, right: str) -> bool:
    normalized_left = normalized(left)
    normalized_right = normalized(right)
    if normalized_left == normalized_right:
        return True
    shorter, longer = sorted((normalized_left, normalized_right), key=len)
    if len(shorter) >= 8 and shorter in longer:
        return True
    simplified = []
    for value in (left, right):
        words = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", value).casefold())
        words = [
            word
            for word in words
            if word not in {"a", "an", "and", "the", "cartoon"}
        ]
        simplified.append("".join(words))
    return (
        min(map(len, simplified)) >= 5
        and difflib.SequenceMatcher(None, *simplified).ratio() >= 0.85
    )


def _fill_start_gap(
    starts: list[int | None],
    left_index: int,
    left_start: int,
    right_index: int,
    right_start: int,
) -> None:
    groups = right_index - left_index
    total_episodes = right_start - left_start
    if total_episodes < groups or total_episodes > groups * 3:
        raise PackValidationError(
            "episode-title anchors imply an invalid segment grouping: "
            f"file indexes {left_index}-{right_index}, episode starts "
            f"{left_start}-{right_start}"
        )
    current = left_start
    remaining = total_episodes
    for index in range(left_index, right_index):
        starts[index] = current
        groups_left = right_index - index
        group_size = min(3, remaining - (groups_left - 1))
        current += group_size
        remaining -= group_size


def _contiguous_clusters(numbers: Iterable[int]) -> list[tuple[int, ...]]:
    clusters: list[list[int]] = []
    for number in sorted(set(numbers)):
        if not clusters or number != clusters[-1][-1] + 1:
            clusters.append([number])
        else:
            clusters[-1].append(number)
    return [tuple(cluster) for cluster in clusters]


def _map_explicit_segment_season(
    pack_files: list[ParsedPackFile],
    season_episodes: list[dict[str, Any]],
) -> list[EpisodeFileMapping]:
    """Map packs whose filenames enumerate the contained broadcast segments.

    BTArg has a few legacy packs where the file ordinal is not the broadcast
    order and one filename repeats an old segment title.  The explicit title
    group is therefore stronger evidence than the file ordinal.  An isolated
    stale title is tolerated only when the remaining matches form a unique
    contiguous group of at least two episodes; final coverage validation still
    requires every Sonarr episode exactly once.
    """
    result: list[EpisodeFileMapping] = []
    for item in pack_files:
        matching_numbers = {
            _episode_number(episode)
            for fragment in item.title_fragments
            for episode in season_episodes
            if _titles_match(fragment, str(episode["title"]))
        }
        clusters = _contiguous_clusters(matching_numbers)
        longest = max((len(cluster) for cluster in clusters), default=0)
        candidates = [cluster for cluster in clusters if len(cluster) == longest]
        if longest < 2 or len(candidates) != 1:
            raise PackValidationError(
                f"explicit segment titles are ambiguous for {item.path}"
            )
        numbers = candidates[0]
        assigned = [
            episode
            for episode in season_episodes
            if _episode_number(episode) in numbers
        ]
        result.append(
            EpisodeFileMapping(
                path=item.path,
                season=item.season,
                ordinal=item.ordinal,
                episode_ids=tuple(int(episode["id"]) for episode in assigned),
                episode_numbers=numbers,
                first_title=str(assigned[0]["title"]),
            )
        )
    return result


def map_pack_files(
    paths: Iterable[str],
    episodes: Iterable[dict[str, Any]],
) -> list[EpisodeFileMapping]:
    video_paths = [
        path for path in validate_torrent_paths(paths) if PurePosixPath(path).suffix.casefold() in VIDEO_EXTENSIONS
    ]
    parsed = [parse_pack_file(path) for path in video_paths]
    episode_list = [dict(item) for item in episodes if int(item.get("seasonNumber", 0)) > 0]
    mappings: list[EpisodeFileMapping] = []

    for season in sorted({item.season for item in parsed}):
        pack_files = sorted(
            (item for item in parsed if item.season == season),
            key=lambda item: item.ordinal,
        )
        expected_ordinals = list(range(1, len(pack_files) + 1))
        if [item.ordinal for item in pack_files] != expected_ordinals:
            raise PackValidationError(f"season {season} pack ordinals are not contiguous")

        season_episodes = sorted(
            (item for item in episode_list if int(item["seasonNumber"]) == season),
            key=_episode_number,
        )
        if not season_episodes:
            raise PackValidationError(f"Sonarr has no episodes for season {season}")

        if all(len(item.title_fragments) > 1 for item in pack_files):
            mappings.extend(_map_explicit_segment_season(pack_files, season_episodes))
            continue

        starts: list[int | None] = []
        prior_start = 0
        for item in pack_files:
            fragment_matches = [
                [
                    episode
                    for episode in season_episodes
                    if _episode_number(episode) > prior_start
                    and _titles_match(fragment, str(episode["title"]))
                ]
                for fragment in item.title_fragments
            ]
            if any(not matches for matches in fragment_matches):
                starts.append(None)
                continue
            prior_start = min(
                _episode_number(matches[0]) for matches in fragment_matches
            )
            starts.append(prior_start)

        anchors = [(index, value) for index, value in enumerate(starts) if value is not None]
        if not anchors or anchors[0] != (0, _episode_number(season_episodes[0])):
            raise PackValidationError(f"season {season} pack does not start at episode 1")

        maximum = _episode_number(season_episodes[-1])
        for (left_index, left_start), (right_index, right_start) in zip(
            anchors, anchors[1:]
        ):
            assert left_start is not None and right_start is not None
            _fill_start_gap(starts, left_index, left_start, right_index, right_start)
        last_index, last_start = anchors[-1]
        assert last_start is not None
        _fill_start_gap(
            starts,
            last_index,
            last_start,
            len(starts),
            maximum + 1,
        )

        for index, item in enumerate(pack_files):
            start = starts[index]
            if start is None:
                raise PackValidationError(f"unresolved episode start for {item.path}")
            next_start = starts[index + 1] if index + 1 < len(starts) else maximum + 1
            if next_start is None:
                raise PackValidationError(f"unresolved next episode for {item.path}")
            end = next_start - 1
            assigned = [
                episode
                for episode in season_episodes
                if start <= _episode_number(episode) <= end
            ]
            missing_fragments = [
                fragment
                for fragment in item.title_fragments
                if not any(
                    _titles_match(fragment, str(episode["title"]))
                    for episode in assigned
                )
            ]
            if missing_fragments and len(item.title_fragments) > 1:
                raise PackValidationError(
                    f"listed segment title does not match Sonarr for {item.path}: "
                    + ", ".join(missing_fragments)
                )
            mappings.append(
                EpisodeFileMapping(
                    path=item.path,
                    season=season,
                    ordinal=item.ordinal,
                    episode_ids=tuple(int(episode["id"]) for episode in assigned),
                    episode_numbers=tuple(_episode_number(episode) for episode in assigned),
                    first_title=str(assigned[0]["title"]),
                )
            )

    covered_counts = collections.Counter(
        (mapping.season, number)
        for mapping in mappings
        for number in mapping.episode_numbers
    )
    expected = {
        (int(episode["seasonNumber"]), _episode_number(episode))
        for episode in episode_list
        if int(episode["seasonNumber"]) in {mapping.season for mapping in mappings}
    }
    if set(covered_counts) != expected or any(
        count != 1 for count in covered_counts.values()
    ):
        raise PackValidationError("pack does not cover every Sonarr episode exactly once")
    return sorted(mappings, key=lambda item: (item.season, item.ordinal))


def episode_range_token(numbers: tuple[int, ...]) -> str:
    if not numbers:
        raise PackValidationError("episode mapping is empty")
    first = numbers[0]
    if numbers != tuple(range(first, numbers[-1] + 1)):
        raise PackValidationError("episode mapping is not contiguous")
    return f"E{first:02d}" if len(numbers) == 1 else f"E{first:02d}-E{numbers[-1]:02d}"


def safe_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", value).strip()


def destination_filename(
    series_title: str,
    mapping: EpisodeFileMapping,
    extension: str,
) -> str:
    return (
        f"{safe_filename(series_title)} - S{mapping.season:02d}"
        f"{episode_range_token(mapping.episode_numbers)} - "
        f"{safe_filename(mapping.first_title)} [LATINO] WEBDL-1080p"
        f"{extension.casefold()}"
    )
