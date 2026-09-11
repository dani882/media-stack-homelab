"""Authenticated BTArg language enrichment with a local, secret-free cache."""

from __future__ import annotations

import html
import http.cookiejar
import fcntl
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


BTARG_BASE_URL = "https://www.btarg.com.ar/"
POSITIVE_TTL_SECONDS = 7 * 24 * 60 * 60
UNKNOWN_TTL_SECONDS = 6 * 60 * 60
BACKOFF_SECONDS = (6 * 60 * 60, 12 * 60 * 60, 24 * 60 * 60)


class BTArgError(RuntimeError):
    pass


@dataclass(frozen=True)
class BTArgDetail:
    language: str
    language_text: str
    imdb_id: str | None
    video_codec_text: str
    resolution_text: str


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def html_to_text(value: str) -> str:
    without_scripts = re.sub(
        r"<(?:script|style)\b.*?</(?:script|style)>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", without_scripts))).strip()


def _field(text: str, label: str, following_labels: Iterable[str]) -> str:
    boundary = "|".join(re.escape(item) for item in following_labels)
    match = re.search(
        rf"\b{re.escape(label)}\s*:\s*(.+?)(?=\s+(?:{boundary})\s*:|$)",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def parse_btarg_detail(document: str) -> BTArgDetail:
    text = html_to_text(document)
    language_text = _field(
        text,
        "Idioma",
        ("Fecha de Rippeo", "Ripper", "Link con Info", "SINOPSIS"),
    )
    folded_language = normalized(language_text)
    if "latino" in folded_language or "latam" in folded_language:
        language = "latino"
    elif "castellano" in folded_language or "espanol" in folded_language:
        language = "castilian"
    elif "ingles" in folded_language or "english" in folded_language:
        language = "english"
    else:
        language = "unknown"

    decoded_document = urllib.parse.unquote(html.unescape(document))
    imdb_match = re.search(r"\btt\d{7,10}\b", decoded_document, re.IGNORECASE)
    codec_text = _field(
        text,
        "Codec Video",
        ("Codec Audio", "Bitrate Video", "Bitrate Audio", "DATOS"),
    )
    resolution_text = _field(
        text,
        "Resolución",
        ("Formato", "Codec Video", "Codec Audio"),
    )
    return BTArgDetail(
        language=language,
        language_text=language_text,
        imdb_id=imdb_match.group(0).lower() if imdb_match else None,
        video_codec_text=codec_text,
        resolution_text=resolution_text,
    )


def torrent_id_from_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "btarg.com.ar",
        "www.btarg.com.ar",
    }:
        raise BTArgError("BTArg detail URL uses an unexpected host")
    if parsed.path != "/tracker/details.php":
        raise BTArgError("BTArg detail URL uses an unexpected path")
    torrent_id = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0]
    if not torrent_id.isdigit():
        raise BTArgError("BTArg detail URL has no numeric torrent ID")
    return torrent_id


class BTArgCache:
    def __init__(self, path: Path, now: Callable[[], float] = time.time) -> None:
        self.path = path
        self.now = now
        self.values = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"details": {}, "searches": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"details": {}, "searches": {}}
        if not isinstance(value, dict):
            return {"details": {}, "searches": {}}
        value.setdefault("details", {})
        value.setdefault("searches", {})
        return value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.path.with_suffix(".lock")
        with lock_path.open("w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            disk = self._load()
            disk["details"].update(self.values["details"])
            disk["searches"].update(self.values["searches"])
            disk["searches"] = {
                key: value for key, value in disk["searches"].items() if value is not None
            }
            self.values = disk
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self.values, sort_keys=True) + "\n", encoding="utf-8"
            )
            temporary.chmod(0o600)
            temporary.replace(self.path)

    def detail(self, torrent_id: str) -> BTArgDetail | None:
        raw = self.values["details"].get(torrent_id)
        if not isinstance(raw, dict):
            return None
        age = self.now() - float(raw.get("checked_at", 0) or 0)
        ttl = POSITIVE_TTL_SECONDS if raw.get("language") != "unknown" else UNKNOWN_TTL_SECONDS
        if age < 0 or age > ttl:
            return None
        try:
            return BTArgDetail(
                language=str(raw["language"]),
                language_text=str(raw.get("language_text", "")),
                imdb_id=str(raw["imdb_id"]) if raw.get("imdb_id") else None,
                video_codec_text=str(raw.get("video_codec_text", "")),
                resolution_text=str(raw.get("resolution_text", "")),
            )
        except KeyError:
            return None

    def store_detail(self, torrent_id: str, detail: BTArgDetail) -> None:
        self.values["details"][torrent_id] = {
            **asdict(detail),
            "checked_at": self.now(),
        }
        self.save()

    def search_allowed(self, key: str) -> bool:
        raw = self.values["searches"].get(key)
        return not isinstance(raw, dict) or self.now() >= float(raw.get("retry_at", 0) or 0)

    def record_search_miss(self, key: str) -> float:
        raw = self.values["searches"].get(key)
        misses = int(raw.get("misses", 0) or 0) + 1 if isinstance(raw, dict) else 1
        delay = BACKOFF_SECONDS[min(misses - 1, len(BACKOFF_SECONDS) - 1)]
        retry_at = self.now() + delay
        self.values["searches"][key] = {"misses": misses, "retry_at": retry_at}
        self.save()
        return retry_at

    def clear_search(self, key: str) -> None:
        if key in self.values["searches"]:
            self.values["searches"][key] = None
            self.save()


class BTArgClient:
    def __init__(self, secret_file: Path, cache: BTArgCache) -> None:
        self.secret_file = secret_file
        self.cache = cache
        self.opener: urllib.request.OpenerDirector | None = None

    def _login(self) -> None:
        try:
            payload = json.loads(self.secret_file.read_text(encoding="utf-8"))["btarg"]
            username = str(payload["username"])
            password = str(payload["password"])
        except (OSError, KeyError, json.JSONDecodeError) as error:
            raise BTArgError(f"Unable to load BTArg credentials: {error}") from error
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
        opener.addheaders = [("User-Agent", "homelab-btarg-language/1.0")]
        login = urllib.parse.urlencode({"username": username, "password": password}).encode()
        try:
            with opener.open(
                urllib.request.Request(
                    urllib.parse.urljoin(BTARG_BASE_URL, "tracker/takelogin.php"),
                    data=login,
                    method="POST",
                ),
                timeout=30,
            ) as response:
                body = response.read().decode("iso-8859-1", errors="replace")
        except (OSError, urllib.error.URLError) as error:
            raise BTArgError(f"BTArg login failed: {error}") from error
        if "logout.php" not in body.casefold():
            raise BTArgError("BTArg login did not produce an authenticated session")
        self.opener = opener

    def detail(self, url: str) -> BTArgDetail:
        torrent_id = torrent_id_from_url(url)
        cached = self.cache.detail(torrent_id)
        if cached is not None:
            return cached
        if self.opener is None:
            self._login()
        assert self.opener is not None
        safe_url = urllib.parse.urljoin(BTARG_BASE_URL, f"tracker/details.php?id={torrent_id}")
        try:
            with self.opener.open(safe_url, timeout=30) as response:
                document = response.read().decode("iso-8859-1", errors="replace")
        except (OSError, urllib.error.URLError) as error:
            raise BTArgError(f"Unable to read BTArg detail: {error}") from error
        detail = parse_btarg_detail(document)
        self.cache.store_detail(torrent_id, detail)
        return detail


def is_btarg_release(release: dict[str, Any]) -> bool:
    return "btarg" in str(release.get("indexer", "")).casefold()


def enrich_release(
    release: dict[str, Any],
    client: BTArgClient,
    expected_imdb: str | None = None,
) -> dict[str, Any]:
    if not is_btarg_release(release):
        return release
    enriched = dict(release)
    info_url = str(release.get("infoUrl", ""))
    if not info_url:
        enriched["downloadAllowed"] = False
        enriched["btargVerification"] = "missing-detail-url"
        return enriched
    detail = client.detail(info_url)
    if expected_imdb and (
        not detail.imdb_id or detail.imdb_id.casefold() != expected_imdb.casefold()
    ):
        enriched["downloadAllowed"] = False
        enriched["btargVerification"] = "identity-mismatch"
        return enriched
    enriched["btargVerifiedLanguage"] = detail.language
    formats = [dict(item) for item in release.get("customFormats", []) if isinstance(item, dict)]
    if detail.language == "latino":
        formats.append({"name": "LATINO"})
    elif detail.language == "castilian":
        formats.append({"name": "CASTELLANO"})
    enriched["customFormats"] = formats
    return enriched


def enrich_releases(
    releases: Iterable[dict[str, Any]],
    client: BTArgClient,
    expected_imdb: str | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for release in releases:
        try:
            enriched.append(enrich_release(release, client, expected_imdb))
        except BTArgError:
            failed = dict(release)
            failed["downloadAllowed"] = False
            failed["btargVerification"] = "detail-unavailable"
            enriched.append(failed)
    return enriched
