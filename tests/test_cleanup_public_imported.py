from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/cleanup-public-imported.py"
SPEC = importlib.util.spec_from_file_location("cleanup_public_imported", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PublicCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.torrent = {
            "private": False,
            "progress": 1.0,
            "amount_left": 0,
            "force_start": False,
            "state": "stalledUP",
            "seeding_time": 30 * 60,
        }

    def test_accepts_public_import_after_thirty_minutes(self) -> None:
        self.assertEqual(MODULE.public_torrent_is_removable(self.torrent), (True, "safe"))

    def test_rejects_private_torrent(self) -> None:
        torrent = dict(self.torrent, private=True)
        safe, reason = MODULE.public_torrent_is_removable(torrent)
        self.assertFalse(safe)
        self.assertIn("explicitly public", reason)

    def test_rejects_unknown_privacy(self) -> None:
        torrent = dict(self.torrent, private=None)
        safe, reason = MODULE.public_torrent_is_removable(torrent)
        self.assertFalse(safe)
        self.assertIn("explicitly public", reason)

    def test_rejects_before_retention_window(self) -> None:
        torrent = dict(self.torrent, seeding_time=29 * 60)
        safe, reason = MODULE.public_torrent_is_removable(torrent)
        self.assertFalse(safe)
        self.assertIn("requires 30.0", reason)


if __name__ == "__main__":
    unittest.main()
