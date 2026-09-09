#!/usr/bin/env python3

"""Send one Telegram message for each newly completed qBittorrent download."""


import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCAL_MEDIA_SCRIPT_DIR = Path(__file__).resolve().parent / "media"
DEPLOYED_SCRIPT_DIR = Path("/volume1/docker/media-stack/scripts")
for script_dir in (LOCAL_MEDIA_SCRIPT_DIR, DEPLOYED_SCRIPT_DIR):
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

from common.qbittorrent import (
    QBittorrentClient,
    QBittorrentError,
    read_credentials,
)
from common.arr import ArrClient, ArrError, read_api_key


DEFAULT_STACK_DIR = Path("/volume1/docker/media-stack")
DEFAULT_SECRET_FILE = DEFAULT_STACK_DIR / "secrets/telegram-notifications.json"
DEFAULT_STATE_FILE = DEFAULT_STACK_DIR / "state/torrent-notifications.json"
MAX_NOTIFICATIONS_PER_RUN = 5
ARR_HISTORY_PAGE_SIZE = 250


class NotificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArrSource:
    name: str
    base_url: str
    config_file: Path
    media_kind: str


def read_notification_secret(secret_file: Path) -> tuple[str, int]:
    try:
        values = json.loads(secret_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NotificationError(
            f"Unable to read Telegram notification secret: {error}"
        ) from error

    token = str(values.get("botToken") or "").strip()
    chat_id = values.get("chatId")
    if not token or not isinstance(chat_id, int):
        raise NotificationError(
            "Telegram notification secret requires botToken and numeric chatId."
        )
    return token, chat_id


def load_state(state_file: Path) -> dict[str, Any] | None:
    if not state_file.is_file():
        return None
    try:
        value = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NotificationError(
            f"Unable to read notification state: {error}"
        ) from error
    if not isinstance(value, dict) or not isinstance(value.get("torrents"), dict):
        raise NotificationError("Telegram notification state is invalid.")
    return value


def save_state(state_file: Path, torrents: dict[str, dict[str, Any]]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"torrents": torrents}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(state_file)


def torrent_snapshot(torrent: dict[str, Any]) -> dict[str, Any]:
    return {
        "progress": float(torrent.get("progress", 0) or 0),
        "completion_on": int(torrent.get("completion_on", 0) or 0),
    }


def is_complete(torrent: dict[str, Any]) -> bool:
    return (
        float(torrent.get("progress", 0) or 0) >= 1
        and int(torrent.get("amount_left", 0) or 0) == 0
    )


def newly_completed(
    torrents: list[dict[str, Any]],
    previous: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []
    for torrent in torrents:
        torrent_hash = str(torrent.get("hash") or "").upper()
        if not torrent_hash or not is_complete(torrent):
            continue
        old = previous.get(torrent_hash)
        if old is None or float(old.get("progress", 0) or 0) < 1:
            completed.append(torrent)
    return completed


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TiB"


def notification_text(torrent: dict[str, Any]) -> str:
    private = "privado" if torrent.get("private") is True else "público"
    category = str(torrent.get("category") or "sin categoría")
    return (
        "✅ Descarga completada\n"
        f"{torrent.get('name', 'Sin título')}\n"
        f"Categoría: {category}\n"
        f"Tamaño: {human_size(int(torrent.get('size', 0) or 0))}\n"
        f"Origen: {private}\n"
        "El contenido será importado y analizado por Radarr/Sonarr."
    )


def send_telegram(token: str, chat_id: int, text: str) -> None:
    body = urllib.parse.urlencode(
        {"chat_id": str(chat_id), "text": text}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise NotificationError("Unable to send Telegram notification.") from error
    if not payload.get("ok"):
        raise NotificationError("Telegram rejected the notification.")


def records_from_response(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return [
            item for item in payload["records"]
            if isinstance(item, dict)
        ]
    return []


def matching_arr_record(
    client: ArrClient,
    torrent_hash: str,
) -> dict[str, Any] | None:
    queue = client.get(
        "/queue/details?"
        + urllib.parse.urlencode(
            {
                "includeUnknownSeriesItems": "true",
                "includeUnknownMovieItems": "true",
            }
        )
    )
    for record in records_from_response(queue):
        if str(record.get("downloadId") or "").upper() == torrent_hash:
            return record

    history = client.get(
        "/history?"
        + urllib.parse.urlencode(
            {
                "page": 1,
                "pageSize": ARR_HISTORY_PAGE_SIZE,
                "sortDirection": "descending",
                "downloadId": torrent_hash,
            }
        )
    )
    for record in records_from_response(history):
        if str(record.get("downloadId") or "").upper() == torrent_hash:
            return record
    return None


def media_from_record(
    client: ArrClient,
    record: dict[str, Any],
    media_kind: str,
) -> dict[str, Any] | None:
    embedded = record.get(media_kind)
    if isinstance(embedded, dict) and embedded.get("images"):
        return embedded

    media_id = record.get(f"{media_kind}Id")
    if not isinstance(media_id, int):
        return None
    media = client.get(f"/{media_kind}/{media_id}")
    return media if isinstance(media, dict) else None


def poster_url(media: dict[str, Any], base_url: str) -> str | None:
    images = media.get("images")
    if not isinstance(images, list):
        return None
    poster = next(
        (
            image for image in images
            if isinstance(image, dict) and image.get("coverType") == "poster"
        ),
        None,
    )
    if poster is None:
        return None
    url = str(poster.get("remoteUrl") or poster.get("url") or "").strip()
    if not url:
        return None
    return urllib.parse.urljoin(f"{base_url.rstrip('/')}/", url)


def poster_request_headers(
    url: str,
    api_key: str,
    arr_base_url: str,
) -> dict[str, str]:
    headers = {"User-Agent": "homelab-notifier/1.0"}
    target = urllib.parse.urlsplit(url)
    arr = urllib.parse.urlsplit(arr_base_url)
    if (target.scheme, target.netloc) == (arr.scheme, arr.netloc):
        headers["X-Api-Key"] = api_key
    return headers


def download_poster(
    url: str,
    api_key: str,
    arr_base_url: str,
) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url,
        headers=poster_request_headers(url, api_key, arr_base_url),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            photo = response.read()
            content_type = response.headers.get_content_type()
    except (urllib.error.URLError, OSError) as error:
        raise NotificationError("Unable to download media poster.") from error
    if not photo:
        raise NotificationError("Media poster was empty.")
    if not content_type.startswith("image/"):
        raise NotificationError(
            f"Media poster returned unexpected content type {content_type}."
        )
    return photo, content_type


def find_poster(
    stack_dir: Path,
    torrent: dict[str, Any],
) -> tuple[bytes, str] | None:
    category = str(torrent.get("category") or "").casefold()
    sources = {
        "tv": ArrSource(
            "Sonarr",
            "http://127.0.0.1:8989",
            stack_dir / "config/sonarr/config.xml",
            "series",
        ),
        "radarr": ArrSource(
            "Radarr",
            "http://127.0.0.1:7878",
            stack_dir / "config/radarr/config.xml",
            "movie",
        ),
    }
    source = sources.get(category)
    if source is None:
        return None

    api_key = read_api_key(source.config_file)
    client = ArrClient(source.base_url, api_key)
    torrent_hash = str(torrent.get("hash") or "").upper()
    record = matching_arr_record(client, torrent_hash)
    if record is None:
        return None
    media = media_from_record(client, record, source.media_kind)
    if media is None:
        return None
    url = poster_url(media, source.base_url)
    if url is None:
        return None
    return download_poster(url, api_key, source.base_url)


def send_telegram_photo(
    token: str,
    chat_id: int,
    caption: str,
    photo: bytes,
    content_type: str,
) -> None:
    boundary = f"----homelab-{uuid.uuid4().hex}"
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    parts = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
            f"{chat_id}\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="caption"\r\n\r\n'
            f"{caption}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo"; filename="poster{extension}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8"),
        photo,
        f"\r\n--{boundary}--\r\n".encode("ascii"),
    ]
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise NotificationError("Unable to send Telegram photo.") from error
    if not payload.get("ok"):
        raise NotificationError("Telegram rejected the photo notification.")


def run(
    stack_dir: Path,
    secret_file: Path,
    state_file: Path,
    dry_run: bool,
    test: bool,
) -> int:
    token, chat_id = read_notification_secret(secret_file)
    if test:
        message = "✅ Media NAS conectado. Las notificaciones de descargas están activas."
        if dry_run:
            print(f"WOULD SEND: {message}")
        else:
            send_telegram(token, chat_id, message)
            print("Telegram test notification sent.")
        return 0

    username, password = read_credentials(stack_dir / "secrets/qbittorrent.json")
    qbittorrent = QBittorrentClient("http://127.0.0.1:8888", username, password)
    qbittorrent.login()
    torrents = qbittorrent.get_json("/api/v2/torrents/info?filter=all")
    current = {
        str(torrent.get("hash") or "").upper(): torrent_snapshot(torrent)
        for torrent in torrents
        if torrent.get("hash")
    }
    previous_state = load_state(state_file)
    if previous_state is None:
        save_state(state_file, current)
        print(f"Notification baseline saved for {len(current)} torrents.")
        return 0

    completed = newly_completed(torrents, previous_state["torrents"])
    if len(completed) > MAX_NOTIFICATIONS_PER_RUN:
        raise NotificationError(
            f"Refusing to send {len(completed)} notifications in one run."
        )
    for torrent in completed:
        text = notification_text(torrent)
        if dry_run:
            print(f"WOULD SEND:\n{text}")
        else:
            poster = None
            try:
                poster = find_poster(stack_dir, torrent)
            except (ArrError, NotificationError) as error:
                print(
                    f"Poster unavailable for {torrent.get('name', '')}: {error}",
                    file=sys.stderr,
                )
            if poster is None:
                send_telegram(token, chat_id, text)
            else:
                try:
                    send_telegram_photo(token, chat_id, text, *poster)
                except NotificationError as error:
                    print(
                        f"Photo notification failed; sending text instead: {error}",
                        file=sys.stderr,
                    )
                    send_telegram(token, chat_id, text)
            print(f"Notified completion: {torrent.get('name', '')}")

    if not dry_run:
        save_state(state_file, current)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--secret-file", type=Path, default=DEFAULT_SECRET_FILE)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    return run(args.stack_dir, args.secret_file, args.state_file, args.dry_run, args.test)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (NotificationError, QBittorrentError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
