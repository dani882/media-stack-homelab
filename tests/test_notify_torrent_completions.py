
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/notify-torrent-completions.py"
SPEC = importlib.util.spec_from_file_location("torrent_notifications", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class TorrentNotificationTest(unittest.TestCase):
    def test_reads_legacy_single_recipient_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "telegram.json"
            secret.write_text(
                json.dumps({"botToken": "token", "chatId": 1001}),
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.read_notification_secret(secret),
                ("token", [1001]),
            )

    def test_reads_multiple_recipient_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "telegram.json"
            secret.write_text(
                json.dumps({"botToken": "token", "chatIds": [1001, 1002]}),
                encoding="utf-8",
            )
            self.assertEqual(
                MODULE.read_notification_secret(secret),
                ("token", [1001, 1002]),
            )

    def test_selects_chat_with_exact_registration_code(self) -> None:
        updates = [
            {
                "message": {
                    "text": "/registrar CASA2026",
                    "chat": {"id": 1002, "type": "private"},
                }
            },
            {
                "message": {
                    "text": "/registrar OTROCODIGO",
                    "chat": {"id": 1003, "type": "private"},
                }
            },
        ]
        self.assertEqual(
            MODULE.registration_candidate(updates, [1001], "CASA2026"),
            1002,
        )

    def test_rejects_already_registered_chat(self) -> None:
        updates = [
            {
                "message": {
                    "text": "/registrar CASA2026",
                    "chat": {"id": 1001, "type": "private"},
                }
            }
        ]
        with self.assertRaises(MODULE.NotificationError):
            MODULE.registration_candidate(updates, [1001], "CASA2026")

    def test_detects_completed_transition(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "amount_left": 0,
        }
        self.assertEqual(
            MODULE.newly_completed([torrent], {"ABC": {"progress": 0.5}}),
            [torrent],
        )

    def test_does_not_repeat_existing_completion(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "amount_left": 0,
        }
        self.assertEqual(
            MODULE.newly_completed([torrent], {"ABC": {"progress": 1}}),
            [],
        )

    def test_retries_only_recipient_without_recorded_delivery(self) -> None:
        torrent = {"hash": "abc", "progress": 1, "amount_left": 0}
        first = MODULE.recipient_fingerprint(1001)
        pending = MODULE.pending_notifications(
            [torrent],
            {"ABC": [first]},
            [1001, 1002],
        )
        self.assertEqual(pending, [(torrent, [1002])])

    def test_recipient_fingerprint_does_not_store_chat_id(self) -> None:
        value = MODULE.recipient_fingerprint(123456789)
        self.assertNotIn("123456789", value)
        self.assertEqual(len(value), 16)

    def test_formats_private_completion_message(self) -> None:
        text = MODULE.notification_text(
            {
                "name": "Example Movie",
                "category": "radarr",
                "size": 1024**3,
                "private": True,
            }
        )
        self.assertIn("Descarga completada", text)
        self.assertIn("privado", text)
        self.assertIn("1.0 GiB", text)

    def test_extracts_records_from_paged_response(self) -> None:
        records = [{"downloadId": "ABC"}]
        self.assertEqual(MODULE.records_from_response({"records": records}), records)

    def test_selects_remote_poster_url(self) -> None:
        media = {
            "images": [
                {"coverType": "fanart", "url": "/fanart.jpg"},
                {
                    "coverType": "poster",
                    "url": "/MediaCover/1/poster.jpg",
                    "remoteUrl": "https://example.com/poster.jpg",
                },
            ]
        }
        self.assertEqual(
            MODULE.poster_url(media, "http://127.0.0.1:8989"),
            "https://example.com/poster.jpg",
        )

    def test_does_not_send_arr_api_key_to_remote_poster_host(self) -> None:
        headers = MODULE.poster_request_headers(
            "https://image.example/poster.jpg",
            "private-key",
            "http://127.0.0.1:7878",
        )
        self.assertNotIn("X-Api-Key", headers)

    def test_authenticates_local_poster_fallback(self) -> None:
        headers = MODULE.poster_request_headers(
            "http://127.0.0.1:7878/MediaCover/1/poster.jpg",
            "private-key",
            "http://127.0.0.1:7878",
        )
        self.assertEqual(headers["X-Api-Key"], "private-key")

    def test_returns_none_when_media_has_no_poster(self) -> None:
        self.assertIsNone(
            MODULE.poster_url(
                {"images": [{"coverType": "banner", "url": "/banner.jpg"}]},
                "http://127.0.0.1:8989",
            )
        )


if __name__ == "__main__":
    unittest.main()
