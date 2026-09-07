
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


if __name__ == "__main__":
    unittest.main()
