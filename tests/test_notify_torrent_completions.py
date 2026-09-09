
import importlib.util
import sys
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

    def test_selects_local_poster_url(self) -> None:
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
            "http://127.0.0.1:8989/MediaCover/1/poster.jpg",
        )

    def test_returns_none_when_media_has_no_poster(self) -> None:
        self.assertIsNone(
            MODULE.poster_url(
                {"images": [{"coverType": "banner", "url": "/banner.jpg"}]},
                "http://127.0.0.1:8989",
            )
        )


if __name__ == "__main__":
    unittest.main()
