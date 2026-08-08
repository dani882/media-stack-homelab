from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "scripts/media"

sys.path.insert(
    0,
    str(MEDIA_DIR),
)


from common.cleanup import (  # noqa: E402
    has_dangerous_warning,
    has_safe_warning,
    torrent_is_safe_to_remove,
)


class CleanupHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.completed_torrent = {
            "progress": 1.0,
            "amount_left": 0,
            "force_start": False,
            "state": "stoppedUP",
            "category": "tv",
            "seeding_time": 0,
        }

    def test_detects_dangerous_warning(self) -> None:
        queue_item = {
            "statusMessages": [
                {
                    "messages": [
                        (
                            "Caution: Found potentially dangerous "
                            "file with extension: .scr"
                        )
                    ]
                }
            ]
        }

        self.assertTrue(
            has_dangerous_warning(queue_item)
        )

    def test_normal_warning_is_not_dangerous(self) -> None:
        queue_item = {
            "statusMessages": [
                {
                    "messages": [
                        "Not a Custom Format upgrade"
                    ]
                }
            ]
        }

        self.assertTrue(
            has_safe_warning(queue_item)
        )
        self.assertFalse(
            has_dangerous_warning(queue_item)
        )

    def test_normal_cleanup_requires_seeding(self) -> None:
        safe, reason = torrent_is_safe_to_remove(
            self.completed_torrent,
            "tv",
        )

        self.assertFalse(safe)
        self.assertIn(
            "seeded only",
            reason,
        )

    def test_dangerous_cleanup_skips_seeding_wait(
        self,
    ) -> None:
        safe, reason = torrent_is_safe_to_remove(
            self.completed_torrent,
            "tv",
            require_seeding=False,
        )

        self.assertTrue(safe)
        self.assertEqual(
            reason,
            "safe",
        )

    def test_dangerous_cleanup_still_requires_complete(
        self,
    ) -> None:
        torrent = dict(
            self.completed_torrent
        )
        torrent["progress"] = 0.5
        torrent["amount_left"] = 100

        safe, reason = torrent_is_safe_to_remove(
            torrent,
            "tv",
            require_seeding=False,
        )

        self.assertFalse(safe)
        self.assertEqual(
            reason,
            "torrent is not complete",
        )


if __name__ == "__main__":
    unittest.main()
