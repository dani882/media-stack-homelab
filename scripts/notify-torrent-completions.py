#!/usr/bin/env python3

"""Send one Telegram message for each newly completed qBittorrent download."""


import argparse
import hashlib
import json
import mimetypes
import re
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
REGISTRATION_CODE_PATTERN = re.compile(r"[A-Za-z0-9_-]{6,64}")


class NotificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArrSource:
    name: str
    base_url: str
    config_file: Path
    media_kind: str


def read_notification_secret(secret_file: Path) -> tuple[str, list[int]]:
    try:
        values = json.loads(secret_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NotificationError(
            f"Unable to read Telegram notification secret: {error}"
        ) from error

    token = str(values.get("botToken") or "").strip()
    configured_chat_ids = values.get("chatIds")
    if configured_chat_ids is None:
        configured_chat_ids = [values.get("chatId")]
    if not isinstance(configured_chat_ids, list):
        configured_chat_ids = []
    chat_ids = list(
        dict.fromkeys(
            chat_id
            for chat_id in configured_chat_ids
            if type(chat_id) is int
        )
    )
    if not token or not chat_ids:
        raise NotificationError(
            "Telegram notification secret requires botToken and at least one "
            "numeric chatId or chatIds entry."
        )
    return token, chat_ids


def telegram_updates(token: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/getUpdates?limit=100&timeout=0",
        headers={"User-Agent": "homelab-notifier/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise NotificationError("Unable to read Telegram updates.") from error
    if not payload.get("ok") or not isinstance(payload.get("result"), list):
        raise NotificationError("Telegram rejected the update lookup.")
    return [
        update for update in payload["result"]
        if isinstance(update, dict)
    ]


def registration_candidate(
    updates: list[dict[str, Any]],
    existing_chat_ids: list[int],
    registration_code: str,
) -> int:
    expected_text = f"/registrar {registration_code}"
    existing = set(existing_chat_ids)
    candidates: set[int] = set()
    for update in updates:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if (
            chat.get("type") == "private"
            and type(chat_id) is int
            and chat_id not in existing
            and str(message.get("text") or "").strip() == expected_text
        ):
            candidates.add(chat_id)
    if len(candidates) != 1:
        raise NotificationError(
            "Expected exactly one new private chat with the registration code; "
            f"found {len(candidates)}."
        )
    return next(iter(candidates))


def register_telegram_chat(
    secret_file: Path,
    registration_code: str,
    dry_run: bool,
) -> int:
    if REGISTRATION_CODE_PATTERN.fullmatch(registration_code) is None:
        raise NotificationError(
            "Registration code must contain 6-64 letters, numbers, underscores, "
            "or hyphens."
        )
    token, chat_ids = read_notification_secret(secret_file)
    chat_id = registration_candidate(
        telegram_updates(token),
        chat_ids,
        registration_code,
    )
    if dry_run:
        print(f"WOULD REGISTER RECIPIENT {len(chat_ids) + 1}")
        return len(chat_ids) + 1

    try:
        values = json.loads(secret_file.read_text(encoding="utf-8"))
        values["chatIds"] = [*chat_ids, chat_id]
        temporary = secret_file.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(values, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(secret_file)
    except (OSError, json.JSONDecodeError) as error:
        raise NotificationError(
            "Unable to update Telegram notification recipients."
        ) from error
    print(f"Telegram recipient {len(chat_ids) + 1} registered.")
    return len(chat_ids) + 1


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


def recipient_fingerprint(chat_id: int) -> str:
    return hashlib.sha256(str(chat_id).encode("ascii")).hexdigest()[:16]


def save_state(
    state_file: Path,
    torrents: dict[str, dict[str, Any]],
    notified: dict[str, list[str]] | None = None,
    recipients: list[str] | None = None,
) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = state_file.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "torrents": torrents,
                "notified": notified or {},
                "recipients": recipients or [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(state_file)


def torrent_snapshot(torrent: dict[str, Any]) -> dict[str, Any]:
    return {
        "progress": float(torrent.get("progress", 0) or 0),
        "completion_on": int(torrent.get("completion_on", 0) or 0),
        "notification_ready": notification_ready(torrent),
    }


def is_complete(torrent: dict[str, Any]) -> bool:
    return (
        float(torrent.get("progress", 0) or 0) >= 1
        and int(torrent.get("amount_left", 0) or 0) == 0
    )


def notification_ready(torrent: dict[str, Any]) -> bool:
    if not is_complete(torrent):
        return False
    tags = {
        tag.strip()
        for tag in str(torrent.get("tags") or "").split(",")
        if tag.strip()
    }
    return "btarg-series-pack" not in tags or "btarg-import-verified" in tags


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


def pending_notifications(
    torrents: list[dict[str, Any]],
    notified: dict[str, list[str]],
    chat_ids: list[int],
) -> list[tuple[dict[str, Any], list[int]]]:
    pending: list[tuple[dict[str, Any], list[int]]] = []
    for torrent in torrents:
        if not notification_ready(torrent):
            continue
        torrent_hash = str(torrent.get("hash") or "").upper()
        delivered = set(notified.get(torrent_hash, []))
        missing = [
            chat_id
            for chat_id in chat_ids
            if recipient_fingerprint(chat_id) not in delivered
        ]
        if torrent_hash and missing:
            pending.append((torrent, missing))
    return pending


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
    tags = {
        tag.strip()
        for tag in str(torrent.get("tags") or "").split(",")
        if tag.strip()
    }
    if "btarg-series-pack" in tags and "btarg-import-verified" in tags:
        return (
            "✅ Contenido disponible\n"
            f"{torrent.get('name', 'Sin título')}\n"
            f"Categoría: {category}\n"
            f"Tamaño: {human_size(int(torrent.get('size', 0) or 0))}\n"
            f"Origen: {private}\n"
            "La serie ya fue importada y verificada por Sonarr."
        )
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


def tagged_media_id(
    torrent: dict[str, Any],
    media_kind: str,
) -> int | None:
    prefixes = {
        "series": "sonarr-series-",
        "movie": "radarr-movie-",
    }
    prefix = prefixes.get(media_kind)
    if prefix is None:
        return None
    for tag in str(torrent.get("tags") or "").split(","):
        match = re.fullmatch(rf"{re.escape(prefix)}([1-9][0-9]*)", tag.strip())
        if match is not None:
            return int(match.group(1))
    return None


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
    media = (
        media_from_record(client, record, source.media_kind)
        if record is not None
        else None
    )
    if media is None:
        media_id = tagged_media_id(torrent, source.media_kind)
        if media_id is not None:
            candidate = client.get(f"/{source.media_kind}/{media_id}")
            media = candidate if isinstance(candidate, dict) else None
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


def send_download_notification(
    token: str,
    chat_id: int,
    text: str,
    poster: tuple[bytes, str] | None,
) -> None:
    if poster is None:
        send_telegram(token, chat_id, text)
        return
    try:
        send_telegram_photo(token, chat_id, text, *poster)
    except NotificationError as error:
        print(
            f"Photo notification failed; sending text instead: {error}",
            file=sys.stderr,
        )
        send_telegram(token, chat_id, text)


def run(
    stack_dir: Path,
    secret_file: Path,
    state_file: Path,
    dry_run: bool,
    test: bool,
) -> int:
    token, chat_ids = read_notification_secret(secret_file)
    if test:
        message = "✅ Media NAS conectado. Las notificaciones de descargas están activas."
        if dry_run:
            print(f"WOULD SEND TO {len(chat_ids)} RECIPIENTS: {message}")
        else:
            for chat_id in chat_ids:
                send_telegram(token, chat_id, message)
            print(f"Telegram test notification sent to {len(chat_ids)} recipients.")
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
    current_recipients = [recipient_fingerprint(chat_id) for chat_id in chat_ids]
    if previous_state is None:
        baseline = {
            torrent_hash: current_recipients
            for torrent_hash, snapshot in current.items()
            if snapshot.get("notification_ready") is True
        }
        save_state(state_file, current, baseline, current_recipients)
        print(f"Notification baseline saved for {len(current)} torrents.")
        return 0

    raw_notified = previous_state.get("notified")
    if isinstance(raw_notified, dict):
        notified = {
            str(torrent_hash): [str(value) for value in values]
            for torrent_hash, values in raw_notified.items()
            if isinstance(values, list)
        }
    else:
        # Migrate the original state format without repeating old messages.
        notified = {
            torrent_hash: [recipient_fingerprint(chat_id) for chat_id in chat_ids]
            for torrent_hash, snapshot in previous_state["torrents"].items()
            if float(snapshot.get("progress", 0) or 0) >= 1
        }
    known_recipients = {
        str(value) for value in previous_state.get("recipients", current_recipients)
    }
    new_recipients = set(current_recipients) - known_recipients
    if new_recipients:
        for torrent_hash, snapshot in current.items():
            if snapshot.get("notification_ready") is True:
                notified.setdefault(torrent_hash, []).extend(sorted(new_recipients))
    completed_now = newly_completed(torrents, previous_state["torrents"])
    for torrent in completed_now:
        notified.setdefault(str(torrent.get("hash") or "").upper(), [])
    pending = pending_notifications(torrents, notified, chat_ids)
    if len(pending) > MAX_NOTIFICATIONS_PER_RUN:
        print(
            f"Deferring {len(pending) - MAX_NOTIFICATIONS_PER_RUN} completion "
            "notification(s) to the next run."
        )
        pending = pending[:MAX_NOTIFICATIONS_PER_RUN]
    delivery_failures = 0
    for torrent, pending_chat_ids in pending:
        text = notification_text(torrent)
        if dry_run:
            print(f"WOULD SEND TO {len(pending_chat_ids)} RECIPIENTS:\n{text}")
        else:
            poster = None
            try:
                poster = find_poster(stack_dir, torrent)
            except (ArrError, NotificationError) as error:
                print(
                    f"Poster unavailable for {torrent.get('name', '')}: {error}",
                    file=sys.stderr,
                )
            delivered = 0
            torrent_hash = str(torrent.get("hash") or "").upper()
            for recipient_number, chat_id in enumerate(pending_chat_ids, 1):
                try:
                    send_download_notification(token, chat_id, text, poster)
                except NotificationError as error:
                    print(
                        f"Recipient {recipient_number} notification failed: {error}",
                        file=sys.stderr,
                    )
                    delivery_failures += 1
                    continue
                delivered += 1
                notified.setdefault(torrent_hash, []).append(
                    recipient_fingerprint(chat_id)
                )
            print(
                f"Notified completion to {delivered}/{len(pending_chat_ids)} recipients: "
                f"{torrent.get('name', '')}"
            )

    if not dry_run:
        active_hashes = set(current)
        save_state(
            state_file,
            current,
            {
                torrent_hash: sorted(set(values))
                for torrent_hash, values in notified.items()
                if torrent_hash in active_hashes
            },
            current_recipients,
        )
    if delivery_failures:
        raise NotificationError(
            f"Failed to notify {delivery_failures} recipient deliveries."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    parser.add_argument("--secret-file", type=Path, default=DEFAULT_SECRET_FILE)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test", action="store_true")
    parser.add_argument(
        "--register-chat",
        metavar="CODE",
        help="Register the one private chat that sent /registrar CODE.",
    )
    args = parser.parse_args()
    if args.register_chat:
        register_telegram_chat(
            args.secret_file,
            args.register_chat,
            args.dry_run,
        )
        if not args.test:
            return 0
    return run(args.stack_dir, args.secret_file, args.state_file, args.dry_run, args.test)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (NotificationError, QBittorrentError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
