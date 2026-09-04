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
        self.assertEqual(
            MODULE.torrent_is_removable(self.torrent),
            (True, "safe public retention satisfied"),
        )

    def test_rejects_private_torrent_without_hosts(self) -> None:
        torrent = dict(self.torrent, private=True)
        safe, reason = MODULE.torrent_is_removable(torrent)
        self.assertFalse(safe)
        self.assertIn("hosts are unavailable", reason)

    def test_rejects_unknown_privacy(self) -> None:
        torrent = dict(self.torrent, private=None)
        safe, reason = MODULE.torrent_is_removable(torrent)
        self.assertFalse(safe)
        self.assertIn("privacy is not explicitly", reason)

    def test_rejects_before_retention_window(self) -> None:
        torrent = dict(self.torrent, seeding_time=29 * 60)
        safe, reason = MODULE.torrent_is_removable(torrent)
        self.assertFalse(safe)
        self.assertIn("requires 30.0", reason)

    def test_accepts_known_private_after_tracker_limit(self) -> None:
        torrent = dict(
            self.torrent,
            private=True,
            seeding_time=4320 * 60,
            seeding_time_limit=4320,
        )
        self.assertEqual(
            MODULE.torrent_is_removable(torrent, {"retrotoon.world"}),
            (True, "safe private retention satisfied (RetroToon World)"),
        )

    def test_rejects_private_before_tracker_limit(self) -> None:
        torrent = dict(
            self.torrent,
            private=True,
            seeding_time=4319 * 60,
            seeding_time_limit=4320,
        )
        safe, reason = MODULE.torrent_is_removable(
            torrent,
            {"retrotoon.world"},
        )
        self.assertFalse(safe)
        self.assertIn("requires 4320.0", reason)

    def test_rejects_unknown_private_tracker(self) -> None:
        torrent = dict(
            self.torrent,
            private=True,
            seeding_time=10000 * 60,
            seeding_time_limit=4320,
        )
        safe, reason = MODULE.torrent_is_removable(torrent, {"unknown.example"})
        self.assertFalse(safe)
        self.assertIn("no managed retention policy", reason)


if __name__ == "__main__":
    unittest.main()
