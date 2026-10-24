"""Guarded H.264 staging for completed Lat-Team torrents."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FAMILY_ROOT = Path("/volume1/Family")
CONTAINER_DATA_ROOT = Path("/data")
TRANSCODE_ROOT = FAMILY_ROOT / "Downloads/.transcode/latteam"
VIDEO_EXTENSIONS = {".avi", ".m4v", ".mkv", ".mp4", ".ts", ".webm"}
SPANISH_AUDIO = {"es", "esl", "spa", "spanish", "lat", "latino"}
MAX_HARDWARE_TEMPERATURE_C = 85.0
MAX_IMPORT_WIDTH = 1920
MAX_IMPORT_HEIGHT = 1080
H264_VIDEO_FILTER = (
    "scale=w=min(1920\\,iw):h=min(1080\\,ih):"
    "force_original_aspect_ratio=decrease:force_divisible_by=2,format=nv12"
)
_RKMPP_AVAILABLE: bool | None = None


class LatTeamTranscodeError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedContent:
    container_path: str
    host_path: Path
    converted_files: int
    linked_files: int


def container_to_host(path: str) -> Path:
    source = Path(path)
    try:
        relative = source.relative_to(CONTAINER_DATA_ROOT)
    except ValueError as error:
        raise LatTeamTranscodeError("Completed path is outside /data") from error
    return FAMILY_ROOT / relative


def host_to_container(path: Path) -> str:
    try:
        relative = path.relative_to(FAMILY_ROOT)
    except ValueError as error:
        raise LatTeamTranscodeError("Staged path is outside the family root") from error
    return str(CONTAINER_DATA_ROOT / relative)


def probe_media(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LatTeamTranscodeError(f"Unable to inspect {path.name}") from error
    if result.returncode != 0:
        raise LatTeamTranscodeError(f"Unable to inspect {path.name}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise LatTeamTranscodeError(f"Invalid media probe for {path.name}") from error
    if not isinstance(payload, dict):
        raise LatTeamTranscodeError(f"Invalid media probe for {path.name}")
    return payload


def streams(probe: dict[str, Any], stream_type: str) -> list[dict[str, Any]]:
    return [
        item
        for item in probe.get("streams", [])
        if isinstance(item, dict) and item.get("codec_type") == stream_type
    ]


def video_codec(probe: dict[str, Any]) -> str:
    videos = streams(probe, "video")
    if not videos:
        raise LatTeamTranscodeError("Media file has no video stream")
    return str(videos[0].get("codec_name") or "").casefold()


def audio_languages(probe: dict[str, Any]) -> set[str]:
    return {
        str((item.get("tags") or {}).get("language") or "").casefold()
        for item in streams(probe, "audio")
        if str((item.get("tags") or {}).get("language") or "").strip()
    }


def validate_spanish_audio(probe: dict[str, Any]) -> None:
    audio = streams(probe, "audio")
    if not audio:
        raise LatTeamTranscodeError("Media file has no audio streams")
    languages = audio_languages(probe)
    if languages & SPANISH_AUDIO:
        return
    raise LatTeamTranscodeError("MediaInfo does not prove Spanish audio")


def media_duration(probe: dict[str, Any]) -> float | None:
    values = [
        (probe.get("format") or {}).get("duration"),
        *(item.get("duration") for item in streams(probe, "video")),
    ]
    for value in values:
        try:
            duration = float(value)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            return duration
    return None


def read_temperature_c() -> float | None:
    values: list[float] = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            raw = float(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        values.append(raw / 1000 if raw > 1000 else raw)
    return max(values) if values else None


def rkmpp_encoder_available() -> bool:
    global _RKMPP_AVAILABLE
    if _RKMPP_AVAILABLE is not None:
        return _RKMPP_AVAILABLE
    if not Path("/dev/mpp_service").exists() or shutil.which("ffmpeg") is None:
        _RKMPP_AVAILABLE = False
        return False
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=128x128:rate=24",
        "-frames:v",
        "3",
        "-vf",
        "format=nv12",
        "-c:v",
        "h264_rkmpp",
        "-rc_mode",
        "CQP",
        "-qp_init",
        "20",
        "-f",
        "h264",
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        _RKMPP_AVAILABLE = False
    else:
        _RKMPP_AVAILABLE = result.returncode == 0
    return _RKMPP_AVAILABLE


def conversion_command(source: Path, temporary: Path, hardware: bool) -> list[str]:
    video_arguments = (
        [
            "-vf",
            H264_VIDEO_FILTER,
            "-c:v",
            "h264_rkmpp",
            "-rc_mode",
            "CQP",
            "-qp_init",
            "20",
        ]
        if hardware
        else [
            "-vf",
            H264_VIDEO_FILTER,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-threads",
            "2",
        ]
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-map",
        "0:s?",
        *video_arguments,
        "-c:a",
        "copy",
        "-c:s",
        "copy",
        "-map_metadata",
        "0",
        str(temporary),
    ]


def validate_conversion(
    source_probe: dict[str, Any], converted_probe: dict[str, Any], source_name: str
) -> None:
    if video_codec(converted_probe) != "h264":
        raise LatTeamTranscodeError(f"Converted file is not H.264: {source_name}")
    validate_spanish_audio(converted_probe)
    source_video = streams(source_probe, "video")[0]
    converted_video = streams(converted_probe, "video")[0]
    source_width = int(source_video.get("width", 0) or 0)
    source_height = int(source_video.get("height", 0) or 0)
    converted_width = int(converted_video.get("width", 0) or 0)
    converted_height = int(converted_video.get("height", 0) or 0)
    if min(source_width, source_height, converted_width, converted_height) <= 0:
        raise LatTeamTranscodeError(f"Invalid video dimensions: {source_name}")
    if source_width <= MAX_IMPORT_WIDTH and source_height <= MAX_IMPORT_HEIGHT:
        if (source_width, source_height) != (converted_width, converted_height):
            raise LatTeamTranscodeError(
                f"Converted dimensions changed unexpectedly: {source_name}"
            )
    else:
        source_aspect = source_width / source_height
        converted_aspect = converted_width / converted_height
        if (
            converted_width > MAX_IMPORT_WIDTH
            or converted_height > MAX_IMPORT_HEIGHT
            or converted_width > source_width
            or converted_height > source_height
            or abs(source_aspect - converted_aspect) > 0.02
        ):
            raise LatTeamTranscodeError(
                f"Converted dimensions are not an import-safe downscale: {source_name}"
            )
    for stream_type in ("audio", "subtitle"):
        if len(streams(source_probe, stream_type)) != len(
            streams(converted_probe, stream_type)
        ):
            raise LatTeamTranscodeError(
                f"Converted {stream_type} stream count changed: {source_name}"
            )
    if audio_languages(source_probe) != audio_languages(converted_probe):
        raise LatTeamTranscodeError(f"Converted audio languages changed: {source_name}")
    source_duration = media_duration(source_probe)
    converted_duration = media_duration(converted_probe)
    if source_duration is None or converted_duration is None:
        raise LatTeamTranscodeError(f"Unable to verify duration: {source_name}")
    if abs(source_duration - converted_duration) > max(3.0, source_duration * 0.01):
        raise LatTeamTranscodeError(f"Converted duration changed: {source_name}")


def validate_tail(path: Path) -> None:
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-sseof",
                "-10",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-an",
                "-f",
                "null",
                "-",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LatTeamTranscodeError(f"Unable to decode {path.name}") from error
    if result.returncode != 0:
        raise LatTeamTranscodeError(f"Converted file tail is invalid: {path.name}")


def transcode_file(source: Path, destination: Path) -> None:
    source_probe = probe_media(source)
    validate_spanish_audio(source_probe)
    if video_codec(source_probe) not in {"hevc", "h265", "av1"}:
        raise LatTeamTranscodeError(f"Unsupported transcode source: {source.name}")
    required = max(int(source.stat().st_size * 1.25), 5 * 1024**3)
    if shutil.disk_usage(destination.parent).free < required:
        raise LatTeamTranscodeError(f"Insufficient free space: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_name(
        f"{destination.stem}.partial{destination.suffix}"
    )
    temporary.unlink(missing_ok=True)
    hardware = rkmpp_encoder_available()
    temperature = read_temperature_c()
    if hardware and temperature is not None and temperature >= MAX_HARDWARE_TEMPERATURE_C:
        raise LatTeamTranscodeError(
            f"Hardware temperature is {temperature:.1f} C; conversion paused"
        )
    result: subprocess.CompletedProcess[bytes] | None
    try:
        result = subprocess.run(
            conversion_command(source, temporary, hardware), timeout=12 * 60 * 60
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is None or result.returncode != 0:
        if not hardware:
            temporary.unlink(missing_ok=True)
            raise LatTeamTranscodeError(f"H.264 conversion failed: {source.name}")
        temporary.unlink(missing_ok=True)
        try:
            result = subprocess.run(
                conversion_command(source, temporary, False), timeout=12 * 60 * 60
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is None or result.returncode != 0:
            temporary.unlink(missing_ok=True)
            raise LatTeamTranscodeError(f"H.264 conversion failed: {source.name}")
    converted_probe = probe_media(temporary)
    validate_conversion(source_probe, converted_probe, source.name)
    validate_tail(temporary)
    source_stat = source.stat()
    os.chown(temporary, source_stat.st_uid, source_stat.st_gid)
    os.chmod(temporary, source_stat.st_mode & 0o777)
    temporary.replace(destination)


def marked_name(path: Path, marker: str) -> str:
    if f"[{marker}]" in path.stem.upper():
        return path.name
    return f"{path.stem} [{marker}]{path.suffix}"


def converted_name(path: Path, marker: str, downscaled: bool) -> str:
    stem = path.stem
    if downscaled:
        stem = re.sub(
            r"(?<![A-Za-z0-9])(2160p|4k|uhd)(?![A-Za-z0-9])",
            "1080p",
            stem,
            flags=re.IGNORECASE,
        )
        stem = re.sub(
            r"1080p(?:[ ._-]+1080p)+",
            "1080p",
            stem,
            flags=re.IGNORECASE,
        )
    stem = re.sub(
        r"(?<![A-Za-z0-9])(h[ ._-]?265|x265|hevc|av1)(?![A-Za-z0-9])",
        "H.264",
        stem,
        flags=re.IGNORECASE,
    )
    if f"[{marker}]" not in stem.upper():
        stem = f"{stem} [{marker}]"
    return f"{stem}{path.suffix}"


def stage_completed_content(
    content_path: str,
    torrent_hash: str,
    marker: str,
) -> StagedContent:
    source_root = container_to_host(content_path)
    if not source_root.exists():
        raise LatTeamTranscodeError("Completed torrent path does not exist")
    digest = hashlib.sha256(torrent_hash.encode("utf-8")).hexdigest()[:20]
    stage_root = TRANSCODE_ROOT / digest
    video_files = (
        [source_root]
        if source_root.is_file() and source_root.suffix.casefold() in VIDEO_EXTENSIONS
        else sorted(
            item
            for item in source_root.rglob("*")
            if item.is_file() and item.suffix.casefold() in VIDEO_EXTENSIONS
        )
    )
    if not video_files:
        raise LatTeamTranscodeError("Completed torrent has no supported video files")
    converted = 0
    linked = 0
    destinations: list[Path] = []
    for source in video_files:
        relative_parent = Path() if source_root.is_file() else source.parent.relative_to(source_root)
        source_probe = probe_media(source)
        validate_spanish_audio(source_probe)
        codec = video_codec(source_probe)
        source_video = streams(source_probe, "video")[0]
        downscaled = (
            int(source_video.get("width", 0) or 0) > MAX_IMPORT_WIDTH
            or int(source_video.get("height", 0) or 0) > MAX_IMPORT_HEIGHT
        )
        output_name = (
            converted_name(source, marker, downscaled)
            if codec in {"hevc", "h265", "av1"}
            else marked_name(source, marker)
        )
        destination = stage_root / relative_parent / output_name
        legacy_destination = (
            stage_root / relative_parent / marked_name(source, marker)
        )
        if (
            destination != legacy_destination
            and not destination.exists()
            and legacy_destination.exists()
        ):
            staged_probe = probe_media(legacy_destination)
            validate_conversion(source_probe, staged_probe, source.name)
            validate_tail(legacy_destination)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            legacy_destination.replace(destination)
        destinations.append(destination)
        if destination.exists():
            staged_probe = probe_media(destination)
            validate_spanish_audio(staged_probe)
            if video_codec(staged_probe) != "h264":
                raise LatTeamTranscodeError(f"Existing staged file is not H.264: {destination.name}")
            staged_video = streams(staged_probe, "video")[0]
            staged_width = int(staged_video.get("width", 0) or 0)
            staged_height = int(staged_video.get("height", 0) or 0)
            if staged_width <= MAX_IMPORT_WIDTH and staged_height <= MAX_IMPORT_HEIGHT:
                linked += int(codec == "h264")
                converted += int(codec != "h264")
                continue
            if codec not in {"hevc", "h265", "av1"}:
                raise LatTeamTranscodeError(
                    f"Existing staged file exceeds the managed profile: {destination.name}"
                )
            destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if codec == "h264":
            os.link(source, destination)
            linked += 1
        elif codec in {"hevc", "h265", "av1"}:
            transcode_file(source, destination)
            converted += 1
        else:
            raise LatTeamTranscodeError(
                f"Unsupported Lat-Team video codec {codec or 'unknown'}"
            )
    scan_root = destinations[0] if source_root.is_file() else stage_root
    return StagedContent(
        container_path=host_to_container(scan_root),
        host_path=scan_root,
        converted_files=converted,
        linked_files=linked,
    )
