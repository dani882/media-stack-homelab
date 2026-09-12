#!/usr/bin/env python3
"""Verify recently imported Arr audio and block proven language mismatches."""

from __future__ import annotations

import argparse
import datetime
import html
import json
import re
import sys
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_LIMIT = 500
SPANISH_MARKER = re.compile(r"\[(LATINO|CASTELLANO)\]", re.IGNORECASE)
SPANISH_VALUES = {"es", "esl", "spa", "spanish", "castilian", "lat", "latino"}
ENGLISH_VALUES = {"en", "eng", "english"}

LOCAL_MEDIA_SCRIPT_DIR = Path(__file__).resolve().parent / "media"
DEPLOYED_SCRIPT_DIR = DEFAULT_STACK_DIR / "scripts"
for script_dir in (LOCAL_MEDIA_SCRIPT_DIR, DEPLOYED_SCRIPT_DIR):
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

from common.arr import ArrClient, ArrError, read_api_key
from common.qbittorrent import QBittorrentClient, QBittorrentError, read_credentials


class AudioAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioResult:
    source: str
    title: str
    relative_path: str
    date_added: str
    expected: str
    detected: str
    status: str
    torrent_tagged: bool = False


def normalized_audio_values(media_file: dict[str, Any]) -> set[str]:
    values = {
        str(item.get("name") or "").strip().casefold()
        for item in media_file.get("languages") or []
        if isinstance(item, dict) and item.get("name")
    }
    raw = str((media_file.get("mediaInfo") or {}).get("audioLanguages") or "")
    values.update(
        value.strip().casefold()
        for value in re.split(r"[,/;+]", raw)
        if value.strip()
    )
    return values


def audio_status(media_file: dict[str, Any]) -> tuple[str, str, str]:
    path = str(media_file.get("relativePath") or media_file.get("path") or "")
    marker = SPANISH_MARKER.search(path)
    expected = marker.group(1).upper() if marker else "UNMARKED"
    values = normalized_audio_values(media_file)
    has_spanish = any(
        value in SPANISH_VALUES
        or "spanish" in value
        or "castilian" in value
        or "latino" in value
        for value in values
    )
    has_english = bool(values & ENGLISH_VALUES)
    if has_spanish:
        return expected, ", ".join(sorted(values)), "verified-spanish"
    if marker and has_english and values <= ENGLISH_VALUES:
        return expected, ", ".join(sorted(values)), "language-mismatch"
    if marker:
        return expected, ", ".join(sorted(values)) or "unknown", "needs-review"
    if has_english:
        return expected, ", ".join(sorted(values)), "verified-english-fallback"
    return expected, ", ".join(sorted(values)) or "unknown", "unclassified"


def records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return [item for item in payload["records"] if isinstance(item, dict)]
    return []


def positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def import_history(client: ArrClient) -> list[dict[str, Any]]:
    return records(client.get(
        "/history?"
        + urllib.parse.urlencode(
            {"page": 1, "pageSize": 1000, "sortDirection": "descending"}
        )
    ))


def history_download_ids(
    source: ArrClient | list[dict[str, Any]],
) -> dict[tuple[str, str], str]:
    history_records = import_history(source) if hasattr(source, "get") else source
    result: dict[tuple[str, str], str] = {}
    for record in history_records:
        if record.get("eventType") != "downloadFolderImported":
            continue
        download_id = str(record.get("downloadId") or "").upper()
        if not download_id:
            continue
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        for kind in ("episodeFile", "movieFile"):
            identifier = record.get(f"{kind}Id") or data.get(f"{kind}Id")
            if identifier is not None:
                result[(kind, str(identifier))] = download_id
        for field in ("importedPath", "droppedPath"):
            path = str(data.get(field) or "")
            if path:
                result[("path", Path(path).name.casefold())] = download_id
    return result


def imported_files(
    client: ArrClient,
    source: str,
    history_records: list[dict[str, Any]],
    limit: int,
) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    kind = "episodeFile" if source == "Sonarr" else "movieFile"
    media_kind = "series" if source == "Sonarr" else "movie"
    seen: set[int] = set()
    titles: dict[int, str] = {}
    for record in history_records:
        if record.get("eventType") != "downloadFolderImported":
            continue
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        file_id = positive_int(record.get(f"{kind}Id") or data.get(f"{kind}Id"))
        if file_id is None or file_id in seen:
            continue
        try:
            media_file = client.get(f"/{kind.casefold()}/{file_id}")
        except ArrError:
            continue
        if not isinstance(media_file, dict):
            continue
        media = record.get(media_kind)
        title = str(media.get("title") or "") if isinstance(media, dict) else ""
        media_id = positive_int(
            record.get(f"{media_kind}Id") or data.get(f"{media_kind}Id")
        )
        if not title and isinstance(media_id, int):
            if media_id not in titles:
                candidate = client.get(f"/{media_kind}/{media_id}")
                titles[media_id] = str(candidate.get("title") or "") if isinstance(candidate, dict) else ""
            title = titles[media_id]
        seen.add(file_id)
        found.append((title, media_file))
        if len(found) >= limit:
            break

    # Some Arr versions omit the imported file ID from history but retain the
    # parent series/movie ID. Query only those recent parents, never the full
    # library, and deduplicate files already found above.
    recent_media: dict[int, str] = {}
    for record in history_records:
        if record.get("eventType") != "downloadFolderImported":
            continue
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        media_id = positive_int(
            record.get(f"{media_kind}Id") or data.get(f"{media_kind}Id")
        )
        if media_id is None or media_id in recent_media:
            continue
        embedded = record.get(media_kind)
        recent_media[media_id] = (
            str(embedded.get("title") or "") if isinstance(embedded, dict) else ""
        )
    for media_id, title in recent_media.items():
        if len(found) >= limit:
            break
        if not title:
            candidate = client.get(f"/{media_kind}/{media_id}")
            title = str(candidate.get("title") or "") if isinstance(candidate, dict) else ""
        query = (
            f"/episodefile?seriesId={media_id}"
            if source == "Sonarr"
            else f"/moviefile?movieId={media_id}"
        )
        for media_file in client.get(query):
            file_id = positive_int(media_file.get("id"))
            if file_id is None or file_id in seen:
                continue
            seen.add(file_id)
            found.append((title, media_file))
            if len(found) >= limit:
                break
    return found


def download_id_for(
    source: str,
    media_file: dict[str, Any],
    history: dict[tuple[str, str], str],
) -> str | None:
    kind = "episodeFile" if source == "Sonarr" else "movieFile"
    identifier = media_file.get("id")
    if identifier is not None and (kind, str(identifier)) in history:
        return history[(kind, str(identifier))]
    path = str(media_file.get("relativePath") or media_file.get("path") or "")
    return history.get(("path", Path(path).name.casefold()))


def audit_source(
    source: str,
    client: ArrClient,
    limit: int,
    qbittorrent: QBittorrentClient | None,
) -> list[AudioResult]:
    history_records = import_history(client)
    history = history_download_ids(history_records)
    files = imported_files(client, source, history_records, limit)
    files.sort(key=lambda item: str(item[1].get("dateAdded") or ""), reverse=True)
    results: list[AudioResult] = []
    for title, media_file in files[:limit]:
        expected, detected, status = audio_status(media_file)
        tagged = False
        if status == "language-mismatch" and qbittorrent is not None:
            download_id = download_id_for(source, media_file, history)
            if download_id:
                qbittorrent.post_form(
                    "/api/v2/torrents/addTags",
                    {"hashes": download_id, "tags": "language-mismatch"},
                )
                tagged = True
        results.append(
            AudioResult(
                source=source,
                title=title,
                relative_path=str(media_file.get("relativePath") or ""),
                date_added=str(media_file.get("dateAdded") or ""),
                expected=expected,
                detected=detected,
                status=status,
                torrent_tagged=tagged,
            )
        )
    return results


def write_reports(stack_dir: Path, results: list[AudioResult]) -> None:
    state_dir = stack_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    updated = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    payload = {"updated": updated, "counts": counts, "results": [asdict(x) for x in results]}
    json_path = state_dir / "imported-audio-audit.json"
    temporary = json_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(json_path)

    rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.source)}</td>"
        f"<td>{html.escape(item.title)}</td>"
        f"<td>{html.escape(item.expected)}</td>"
        f"<td>{html.escape(item.detected)}</td>"
        f"<td>{html.escape(item.status)}</td>"
        "</tr>"
        for item in results
        if item.status in {"language-mismatch", "needs-review", "unclassified"}
    ) or "<tr><td colspan='5'>No hay conflictos pendientes.</td></tr>"
    document = (
        "<!doctype html><meta charset='utf-8'><title>Auditoría de audio</title>"
        "<style>body{font-family:system-ui;margin:2rem;max-width:1100px}"
        "table{border-collapse:collapse;width:100%}td,th{padding:.5rem;border:1px solid #ccc}"
        "th{text-align:left;background:#eee}</style>"
        f"<h1>Auditoría de audio importado</h1><p>Actualizado: {html.escape(updated)}</p>"
        "<table><thead><tr><th>Servicio</th><th>Título</th><th>Esperado</th>"
        f"<th>Detectado</th><th>Estado</th></tr></thead><tbody>{rows}</tbody></table>"
    )
    html_path = state_dir / "imported-audio-audit.html"
    html_tmp = html_path.with_suffix(".tmp")
    html_tmp.write_text(document, encoding="utf-8")
    html_tmp.replace(html_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--apply", action="store_true", help="Tag proven mismatched torrents.")
    args = parser.parse_args()
    if args.limit < 1:
        raise AudioAuditError("--limit must be positive")
    try:
        sources = (
            ("Sonarr", "http://127.0.0.1:8989", args.stack_dir / "config/sonarr/config.xml"),
            ("Radarr", "http://127.0.0.1:7878", args.stack_dir / "config/radarr/config.xml"),
        )
        qbit: QBittorrentClient | None = None
        if args.apply:
            username, password = read_credentials(args.stack_dir / "secrets/qbittorrent.json")
            qbit = QBittorrentClient("http://127.0.0.1:8888", username, password)
            qbit.login()
        results: list[AudioResult] = []
        for name, url, config in sources:
            results.extend(
                audit_source(name, ArrClient(url, read_api_key(config)), args.limit, qbit)
            )
        write_reports(args.stack_dir, results)
    except (ArrError, QBittorrentError, OSError) as error:
        raise AudioAuditError(str(error)) from error
    mismatches = sum(item.status == "language-mismatch" for item in results)
    review = sum(item.status in {"needs-review", "unclassified"} for item in results)
    print(f"IMPORTED AUDIO AUDIT: files={len(results)} mismatches={mismatches} review={review}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AudioAuditError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
