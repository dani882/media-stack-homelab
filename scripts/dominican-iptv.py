#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import html
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


IPTV_ORG_URL = os.environ.get(
    "IPTV_ORG_URL", "https://iptv-org.github.io/iptv/countries/do.m3u"
)
IPTV_CAT_URL = os.environ.get(
    "IPTV_CAT_URL", "https://iptvcat.com/dominican_republic__6"
)
EPG_URL = os.environ.get(
    "EPG_URL", "https://epgshare01.online/epgshare01/epg_ripper_DO1.xml.gz"
)
PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL", "http://dominican-iptv:8080"
).rstrip("/")
PLAYLIST_URL = os.environ.get(
    "PLAYLIST_URL", "http://dominican-iptv:8080/playlist.m3u"
)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CATALOG_FILE = Path(os.environ.get("CATALOG_FILE", "/app/sources.json"))
CACHE_TTL = int(os.environ.get("CACHE_TTL", "21600"))
RESOLVER_TTL = int(os.environ.get("RESOLVER_TTL", "21600"))
HEALTH_MAX_AGE = int(os.environ.get("HEALTH_MAX_AGE", "86400"))
DEAD_RETENTION = int(os.environ.get("DEAD_RETENTION", "604800"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "30"))
PROBE_TIMEOUT = int(os.environ.get("PROBE_TIMEOUT", "12"))
PROBE_WORKERS = int(os.environ.get("PROBE_WORKERS", "10"))
PROBE_INTERVAL = int(os.environ.get("PROBE_INTERVAL", "21600"))
USER_AGENT = "homelab-dominican-iptv/2.0"

PLAYLIST_CACHE = DATA_DIR / "playlist.m3u"
RESOLVER_CACHE = DATA_DIR / "iptvcat-resolvers.json"
HEALTH_CACHE = DATA_DIR / "health.json"
REFRESH_LOCK = threading.Lock()
RESOLVER_LOCK = threading.Lock()
HEALTH_LOCK = threading.Lock()

CAT_ENTRY_RE = re.compile(
    r'<span class="channel_name".*?title="([^"]+)">.*?</span>.*?'
    r'href="https://list\.iptvcat\.com/my_list/s/([a-f0-9]{32})\.m3u8"',
    re.DOTALL,
)
ORG_ENTRY_RE = re.compile(r"(#EXTINF:[^\r\n]*)\r?\n([^\r\n]+)")
QUALITY_RE = re.compile(r"\s*\(\d{3,4}[pi]\)", re.IGNORECASE)
FLAG_RE = re.compile(r"\s*\[[^]]+\]")
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8", errors="replace")


def normalize_name(name: str) -> str:
    value = html.unescape(name)
    value = QUALITY_RE.sub("", value)
    value = FLAG_RE.sub("", value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-z0-9]+", " ", value.casefold())
    return " ".join(value.split())


def safe_slug(name: str) -> str:
    return normalize_name(name).replace(" ", ".") or "canal"


def metadata_name(metadata: str) -> str:
    return metadata.rsplit(",", 1)[1].strip() if "," in metadata else "Canal"


def metadata_attrs(metadata: str) -> dict[str, str]:
    prefix = metadata.rsplit(",", 1)[0]
    return dict(ATTR_RE.findall(prefix))


def render_metadata(metadata: str, name: str, updates: dict[str, str]) -> str:
    prefix = metadata.rsplit(",", 1)[0] if "," in metadata else "#EXTINF:-1"
    attrs = metadata_attrs(metadata)
    attrs.update({key: value for key, value in updates.items() if value})
    duration = prefix.split(" ", 1)[0]
    rendered = " ".join(
        f'{key}="{str(value).replace(chr(34), chr(39))}"'
        for key, value in attrs.items()
    )
    return f"{duration} {rendered},{name}" if rendered else f"{duration},{name}"


def parse_iptv_org(source: str) -> tuple[list[str], set[str]]:
    entries: list[str] = []
    names: set[str] = set()
    for metadata, url in ORG_ENTRY_RE.findall(source):
        if "," not in metadata or not url.startswith(("http://", "https://")):
            continue
        name = metadata_name(metadata)
        entries.append(f"{metadata}\n{url}")
        names.add(normalize_name(name))
    return entries, names


def discover_cat_pages(first_page: str) -> list[str]:
    page_numbers = {
        int(value)
        for value in re.findall(r"dominican_republic__6/(\d+)", first_page)
    }
    last_page = max(page_numbers, default=1)
    return [IPTV_CAT_URL] + [f"{IPTV_CAT_URL}/{page}" for page in range(2, last_page + 1)]


def parse_iptv_cat(source: str) -> list[tuple[str, str]]:
    return [
        (html.unescape(name).strip(), token)
        for name, token in CAT_ENTRY_RE.findall(source)
    ]


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def stream_key(url: str) -> str:
    token = re.search(r"/iptvcat/([a-f0-9]{32})\.m3u8", url)
    if token:
        return f"iptvcat:{token.group(1)}"
    return "url:" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def load_health() -> dict[str, dict[str, Any]]:
    value = load_json(HEALTH_CACHE, {})
    return value if isinstance(value, dict) else {}


def health_status(url: str, name: str, health: dict[str, dict[str, Any]]) -> str:
    record = health.get(stream_key(url), {})
    checked_at = float(record.get("checked_at", 0) or 0)
    if checked_at and time.time() - checked_at <= HEALTH_MAX_AGE:
        return str(record.get("status", "testing"))
    if "geo-blocked" in name.casefold():
        return "geo-blocked"
    if "not 24/7" in name.casefold():
        return "intermittent"
    return "testing"


def group_for_status(status: str) -> str:
    if status == "stable":
        return "Dominicana - Estables"
    if status == "geo-blocked":
        return "Dominicana - Geobloqueados"
    return "Dominicana - Experimentales"


def decorate_name(name: str, status: str) -> str:
    labels = {
        "silent": "[Sin audio]",
        "intermittent": "[Intermitente]",
        "dead": "[Fuera de servicio]",
        "geo-blocked": "[Geo-blocked]",
        "testing": "[Sin verificar]",
    }
    label = labels.get(status)
    if not label or label.casefold() in name.casefold():
        return name
    return f"{name} {label}"


def should_include(url: str, health: dict[str, dict[str, Any]]) -> bool:
    record = health.get(stream_key(url), {})
    if record.get("status") != "dead":
        return True
    dead_since = float(record.get("dead_since", record.get("last_failure", 0)) or 0)
    return not dead_since or time.time() - dead_since < DEAD_RETENTION


def decorate_entry(metadata: str, url: str, source: str, health: dict[str, dict[str, Any]]) -> str:
    name = metadata_name(metadata)
    status = health_status(url, name, health)
    attrs = metadata_attrs(metadata)
    tvg_id = attrs.get("tvg-id") or f"do.{safe_slug(name)}"
    rendered = render_metadata(
        metadata,
        decorate_name(name, status),
        {
            "tvg-country": "DO",
            "tvg-id": tvg_id,
            "group-title": group_for_status(status),
            "x-source": source,
            "x-health": status,
        },
    )
    return f"{rendered}\n{url}"


def load_catalog() -> list[dict[str, Any]]:
    value = load_json(CATALOG_FILE, {"channels": []})
    channels = value.get("channels", []) if isinstance(value, dict) else []
    return [entry for entry in channels if isinstance(entry, dict)]


def build_playlist() -> tuple[str, int, int]:
    org_entries, _ = parse_iptv_org(fetch_text(IPTV_ORG_URL))
    if not org_entries:
        raise RuntimeError("IPTV-org returned no Dominican Republic channels")

    health = load_health()
    output: list[str] = []
    identities: dict[str, tuple[str, str]] = {}
    for entry in org_entries:
        metadata, url = entry.split("\n", 1)
        name = metadata_name(metadata)
        attrs = metadata_attrs(metadata)
        identities[normalize_name(name)] = (
            attrs.get("tvg-id", f"do.{safe_slug(name)}"),
            attrs.get("tvg-logo", ""),
        )
        if should_include(url, health):
            output.append(decorate_entry(metadata, url, "iptv-org", health))

    first_page = fetch_text(IPTV_CAT_URL)
    cat_entries = parse_iptv_cat(first_page)
    for page_url in discover_cat_pages(first_page)[1:]:
        cat_entries.extend(parse_iptv_cat(fetch_text(page_url)))

    for name, token in cat_entries:
        safe_name = name.replace("\r", " ").replace("\n", " ").replace('"', "'")
        tvg_id, logo = identities.get(
            normalize_name(name), (f"do.{safe_slug(name)}", "")
        )
        metadata = render_metadata(
            "#EXTINF:-1",
            safe_name,
            {"tvg-country": "DO", "tvg-id": tvg_id, "tvg-logo": logo},
        )
        url = f"{PUBLIC_BASE_URL}/iptvcat/{token}.m3u8"
        if should_include(url, health):
            output.append(decorate_entry(metadata, url, "iptvcat", health))

    exit_enabled = os.environ.get("DOMINICAN_EXIT_NODE_ENABLED", "0") == "1"
    official_count = 0
    for item in load_catalog():
        if not item.get("enabled", True):
            continue
        if item.get("requires_dominican_exit") and not exit_enabled:
            continue
        name = str(item.get("name", "")).strip()
        upstream_url = str(item.get("url", "")).strip()
        source_id = str(item.get("id", safe_slug(name))).strip()
        url = (
            f"http://dominican-exit:8081/official/{source_id}.m3u8"
            if item.get("requires_dominican_exit")
            else upstream_url
        )
        if not name or not upstream_url.startswith(("http://", "https://")):
            continue
        metadata = render_metadata(
            "#EXTINF:-1",
            name,
            {
                "tvg-country": "DO",
                "tvg-id": str(item.get("tvg_id", f"do.{safe_slug(name)}")),
                "tvg-logo": str(item.get("logo", "")),
            },
        )
        if should_include(url, health):
            output.insert(0, decorate_entry(metadata, url, "official", health))
            official_count += 1

    playlist = f'#EXTM3U x-tvg-url="{EPG_URL}"\n' + "\n".join(output) + "\n"
    return playlist, len(org_entries), len(cat_entries) + official_count


def cache_is_fresh(path: Path) -> bool:
    try:
        return time.time() - path.stat().st_mtime < CACHE_TTL
    except FileNotFoundError:
        return False


def get_playlist(force: bool = False) -> bytes:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not force and cache_is_fresh(PLAYLIST_CACHE):
        return PLAYLIST_CACHE.read_bytes()
    with REFRESH_LOCK:
        if not force and cache_is_fresh(PLAYLIST_CACHE):
            return PLAYLIST_CACHE.read_bytes()
        try:
            playlist, org_count, extra_count = build_playlist()
            temporary = PLAYLIST_CACHE.with_suffix(".tmp")
            temporary.write_text(playlist, encoding="utf-8")
            temporary.replace(PLAYLIST_CACHE)
            print(
                f"Playlist refreshed: iptv-org={org_count} "
                f"other={extra_count} total={org_count + extra_count}", flush=True
            )
        except Exception as error:
            if not PLAYLIST_CACHE.exists():
                raise
            print(f"Playlist refresh failed; serving last cache: {error}", flush=True)
        return PLAYLIST_CACHE.read_bytes()


def load_resolvers() -> dict[str, Any]:
    value = load_json(RESOLVER_CACHE, {})
    return value if isinstance(value, dict) else {}


def resolve_iptvcat(token: str) -> str:
    with RESOLVER_LOCK:
        resolvers = load_resolvers()
        raw_cached = resolvers.get(token)
        cached = (
            {"url": raw_cached, "resolved_at": 0}
            if isinstance(raw_cached, str)
            else raw_cached if isinstance(raw_cached, dict) else {}
        )
        health = load_health().get(f"iptvcat:{token}", {})
        failing = int(health.get("consecutive_failures", 0) or 0) >= 2
        age = time.time() - float(cached.get("resolved_at", 0) or 0)
        if cached.get("url") and age < RESOLVER_TTL and not failing:
            return str(cached["url"])

        try:
            wrapper_url = f"https://list.iptvcat.com/my_list/s/{token}.m3u8"
            wrapper = fetch_text(wrapper_url)
            candidates = [
                line.strip()
                for line in wrapper.splitlines()
                if line.strip().startswith(("http://", "https://"))
            ]
            if not candidates:
                raise RuntimeError("IPTV Cat returned no playable URL")
            destination = candidates[-1]
            resolvers[token] = {"url": destination, "resolved_at": time.time()}
            write_json(RESOLVER_CACHE, resolvers)
            return destination
        except Exception:
            if cached.get("url"):
                return str(cached["url"])
            raise


def parse_playlist(source: str) -> list[tuple[str, str]]:
    return [
        (metadata_name(metadata), url.strip())
        for metadata, url in ORG_ENTRY_RE.findall(source)
        if url.strip().startswith(("http://", "https://"))
    ]


def probe_stream(name: str, url: str) -> tuple[str, dict[str, Any]]:
    started = time.time()
    command = [
        "ffprobe", "-v", "error", "-rw_timeout", str(PROBE_TIMEOUT * 1_000_000),
        "-show_entries", "stream=codec_name,codec_type,width,height,channels",
        "-of", "json", url,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            timeout=PROBE_TIMEOUT + 4, check=False
        )
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams", [])
        videos = [stream for stream in streams if stream.get("codec_type") == "video"]
        audios = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if result.returncode == 0 and videos:
            return stream_key(url), {
                "name": name, "url": url, "ok": True,
                "video_codec": videos[0].get("codec_name"),
                "audio_codec": audios[0].get("codec_name") if audios else None,
                "width": videos[0].get("width"), "height": videos[0].get("height"),
                "channels": audios[0].get("channels") if audios else 0,
                "latency_seconds": round(time.time() - started, 2),
            }
        error = (result.stderr or "no video stream detected").strip()[-800:]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        error = str(exc)
    return stream_key(url), {
        "name": name, "url": url, "ok": False,
        "error": error, "latency_seconds": round(time.time() - started, 2),
    }


def merge_probe(previous: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    merged = dict(previous)
    merged.update(probe)
    merged["checked_at"] = now
    if probe.get("ok"):
        successes = int(previous.get("consecutive_successes", 0) or 0) + 1
        merged.update({
            "consecutive_successes": successes, "consecutive_failures": 0,
            "last_success": now,
            "status": "silent" if not probe.get("audio_codec") else "stable",
        })
        merged.pop("dead_since", None)
        merged.pop("error", None)
    else:
        failures = int(previous.get("consecutive_failures", 0) or 0) + 1
        error = str(probe.get("error", "")).casefold()
        is_geo = "geo-blocked" in str(probe.get("name", "")).casefold() or (
            "403" in error and "country" in error
        )
        if is_geo:
            status = "geo-blocked"
        elif previous.get("last_success"):
            status = "intermittent"
        elif failures >= 3:
            status = "dead"
        else:
            status = "testing"
        merged.update({
            "consecutive_successes": 0, "consecutive_failures": failures,
            "last_failure": now, "status": status,
        })
        if status == "dead":
            merged.setdefault("dead_since", now)
    return merged


def monitor_once() -> dict[str, dict[str, Any]]:
    playlist = fetch_text(PLAYLIST_URL)
    entries = parse_playlist(playlist)
    previous = load_health()
    current = dict(previous)
    with concurrent.futures.ThreadPoolExecutor(max_workers=PROBE_WORKERS) as executor:
        futures = [executor.submit(probe_stream, name, url) for name, url in entries]
        for future in concurrent.futures.as_completed(futures):
            key, probe = future.result()
            current[key] = merge_probe(previous.get(key, {}), probe)
    with HEALTH_LOCK:
        write_json(HEALTH_CACHE, current)
    get_playlist(force=True)
    counts: dict[str, int] = {}
    for record in current.values():
        status = str(record.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    print(f"IPTV health audit complete: {counts}", flush=True)
    return current


def monitor_forever() -> None:
    while True:
        try:
            monitor_once()
        except Exception as error:
            print(f"IPTV health audit failed: {error}", flush=True)
        time.sleep(PROBE_INTERVAL)


class Handler(BaseHTTPRequestHandler):
    def send_body(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        try:
            if self.path == "/healthz":
                body = json.dumps({"status": "ok", "streams_checked": len(load_health())}).encode()
                self.send_body(HTTPStatus.OK, body, "application/json")
                return
            if self.path == "/status.json":
                self.send_body(
                    HTTPStatus.OK, json.dumps(load_health(), sort_keys=True).encode(),
                    "application/json",
                )
                return
            if self.path == "/playlist.m3u":
                self.send_body(
                    HTTPStatus.OK, get_playlist(), "audio/x-mpegurl; charset=utf-8"
                )
                return
            match = re.fullmatch(r"/iptvcat/([a-f0-9]{32})\.m3u8", self.path)
            if match:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", resolve_iptvcat(match.group(1)))
                self.end_headers()
                return
            self.send_body(HTTPStatus.NOT_FOUND, b"not found\n", "text/plain")
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            message = f"upstream error: {error}\n".encode("utf-8", errors="replace")
            self.send_body(HTTPStatus.BAD_GATEWAY, message, "text/plain")

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"{self.client_address[0]} {format_string % args}", flush=True)


def relay_target(source_id: str) -> dict[str, Any]:
    for item in load_catalog():
        if str(item.get("id", safe_slug(str(item.get("name", ""))))) == source_id:
            return item
    raise RuntimeError("unknown official source")


def encode_relay_url(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def decode_relay_url(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode()


def rewrite_manifest(source_id: str, source_url: str, manifest: str) -> bytes:
    base = source_url.rsplit("/", 1)[0] + "/"

    def proxied(value: str) -> str:
        absolute = urllib.parse.urljoin(base, value)
        return f"/fetch/{source_id}/{encode_relay_url(absolute)}"

    output: list[str] = []
    for line in manifest.splitlines():
        if line and not line.startswith("#"):
            line = proxied(line.strip())
        elif "URI=\"" in line:
            line = re.sub(
                r'URI="([^"]+)"', lambda match: f'URI="{proxied(match.group(1))}"', line
            )
        output.append(line)
    return ("\n".join(output) + "\n").encode()


class RelayHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            official = re.fullmatch(r"/official/([a-z0-9.-]+)\.m3u8", self.path)
            fetched = re.fullmatch(r"/fetch/([a-z0-9.-]+)/([A-Za-z0-9_-]+)", self.path)
            if official:
                source_id = official.group(1)
                item = relay_target(source_id)
                target = str(item["url"])
            elif fetched:
                source_id = fetched.group(1)
                item = relay_target(source_id)
                target = decode_relay_url(fetched.group(2))
                origin_host = urllib.parse.urlparse(str(item["url"])).hostname
                target_host = urllib.parse.urlparse(target).hostname
                if target_host != origin_host:
                    raise RuntimeError("relay target host is not allowed")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

            request = urllib.request.Request(
                target,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": str(item.get("referer", "https://www.antena7.com.do/")),
                    "Origin": str(item.get("origin", "https://www.antena7.com.do")),
                },
            )
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                body = response.read()
                if "mpegurl" in content_type.casefold() or target.endswith(".m3u8"):
                    body = rewrite_manifest(
                        source_id, target, body.decode("utf-8", errors="replace")
                    )
                    content_type = "application/vnd.apple.mpegurl"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
        except Exception as error:
            self.send_error(HTTPStatus.BAD_GATEWAY, str(error))

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"relay {self.client_address[0]} {format_string % args}", flush=True)


def serve() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    print(f"Dominican IPTV source listening on {host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def relay() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8081"))
    print(f"Dominican official-stream relay listening on {host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), RelayHandler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Dominican IPTV source and auditor")
    parser.add_argument(
        "command", choices=("serve", "monitor", "audit", "relay"), nargs="?", default="serve"
    )
    args = parser.parse_args()
    if args.command == "monitor":
        monitor_forever()
    elif args.command == "audit":
        monitor_once()
    elif args.command == "relay":
        relay()
    else:
        serve()


if __name__ == "__main__":
    main()
