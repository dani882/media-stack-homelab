#!/usr/bin/env python3

"""Audit that a Seerr request is represented safely in Sonarr or Radarr.

The audit is read-only.  It follows the media identity stored by Seerr rather
than relying on a title string, and confirms that the matching Arr item uses a
/data/Media library path.  Pair it with ``make audit-hardlinks`` to validate
the qBittorrent-to-library storage layer.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
SEERR_URL = "http://127.0.0.1:5055"
ARR_URLS = {"tv": "http://127.0.0.1:8989", "movie": "http://127.0.0.1:7878"}


class RequestFlowAuditError(RuntimeError):
    pass


def get_json(url: str, api_key: str, path: str) -> Any:
    request = urllib.request.Request(
        f"{url.rstrip('/')}{path}", headers={"X-Api-Key": api_key}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError) as error:
        raise RequestFlowAuditError(f"GET {path} failed: {error}") from error


def read_seerr_api_key(stack_dir: Path) -> str:
    try:
        payload = json.loads(
            (stack_dir / "config/jellyseerr/settings.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as error:
        raise RequestFlowAuditError(f"Unable to read Seerr settings: {error}") from error

    api_key = str(payload.get("main", {}).get("apiKey", "")).strip()
    if not api_key:
        raise RequestFlowAuditError("Seerr API key was not found.")
    return api_key


def read_arr_api_key(stack_dir: Path, service: str) -> str:
    config_file = stack_dir / "config" / service / "config.xml"
    try:
        api_key = element_tree.parse(config_file).findtext("ApiKey", "").strip()
    except (OSError, element_tree.ParseError) as error:
        raise RequestFlowAuditError(f"Unable to read {service} API key: {error}") from error
    if not api_key:
        raise RequestFlowAuditError(f"{service} API key was not found.")
    return api_key


def request_by_id(stack_dir: Path, request_id: int) -> dict[str, Any]:
    payload = get_json(SEERR_URL, read_seerr_api_key(stack_dir), f"/api/v1/request/{request_id}")
    if not isinstance(payload, dict):
        raise RequestFlowAuditError("Unexpected Seerr request payload.")
    return payload


def audit_tv(stack_dir: Path, request: dict[str, Any]) -> None:
    media = request.get("media")
    if not isinstance(media, dict):
        raise RequestFlowAuditError("Seerr TV request has no media identity.")
    tvdb_id = media.get("tvdbId")
    if not tvdb_id:
        raise RequestFlowAuditError("Seerr TV request has no TVDB ID.")

    series = get_json(
        ARR_URLS["tv"], read_arr_api_key(stack_dir, "sonarr"), "/api/v3/series"
    )
    match = next((item for item in series if item.get("tvdbId") == tvdb_id), None)
    if match is None:
        raise RequestFlowAuditError("No matching Sonarr series was found.")
    path = str(match.get("path", ""))
    episodes = get_json(
        ARR_URLS["tv"],
        read_arr_api_key(stack_dir, "sonarr"),
        "/api/v3/episode?" + urllib.parse.urlencode({"seriesId": match["id"]}),
    )
    with_file = sum(1 for episode in episodes if episode.get("hasFile"))
    print(f"ARR: Sonarr seriesId={match['id']} path={path}")
    print(f"LIBRARY: episodes_with_file={with_file}/{len(episodes)}")
    if not path.startswith("/data/Media/"):
        raise RequestFlowAuditError("Sonarr series does not use a /data/Media path.")


def audit_movie(stack_dir: Path, request: dict[str, Any]) -> None:
    media = request.get("media")
    if not isinstance(media, dict):
        raise RequestFlowAuditError("Seerr movie request has no media identity.")
    tmdb_id = media.get("tmdbId")
    if not tmdb_id:
        raise RequestFlowAuditError("Seerr movie request has no TMDB ID.")

    movies = get_json(
        ARR_URLS["movie"], read_arr_api_key(stack_dir, "radarr"), "/api/v3/movie"
    )
    match = next((item for item in movies if item.get("tmdbId") == tmdb_id), None)
    if match is None:
        raise RequestFlowAuditError("No matching Radarr movie was found.")
    path = str(match.get("path", ""))
    print(f"ARR: Radarr movieId={match['id']} path={path}")
    print(f"LIBRARY: has_file={bool(match.get('hasFile'))}")
    if not path.startswith("/data/Media/"):
        raise RequestFlowAuditError("Radarr movie does not use a /data/Media path.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", required=True, type=int)
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    args = parser.parse_args()

    request = request_by_id(args.stack_dir, args.request_id)
    media_type = str(request.get("type", ""))
    media = request.get("media", {})
    title = str(media.get("title", "unknown")) if isinstance(media, dict) else "unknown"
    print(f"SEERR: request={args.request_id} type={media_type} status={request.get('status')} title={title}")

    if media_type == "tv":
        audit_tv(args.stack_dir, request)
    elif media_type == "movie":
        audit_movie(args.stack_dir, request)
    else:
        raise RequestFlowAuditError(f"Unsupported Seerr request type: {media_type!r}")

    print("SEERR REQUEST FLOW OK: request is managed under /data/Media")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RequestFlowAuditError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
