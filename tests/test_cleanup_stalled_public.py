import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/cleanup-stalled-public.py")
SPEC = importlib.util.spec_from_file_location("cleanup_stalled_public", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StalledPublicCleanupTests(unittest.TestCase):
    NOW = 2_000_000_000.0

    def torrent(self, **overrides: object) -> dict:
        payload = {
            "progress": 0.0,
            "force_start": False,
            "state": "stalledDL",
            "added_on": self.NOW - 4 * 86400,
            "last_activity": self.NOW - 4 * 86400,
            "availability": 0.0,
            "num_seeds": 0,
            "private": False,
            "tags": "",
        }
        payload.update(overrides)
        return payload

    def test_zero_availability_public_torrent_expires(self) -> None:
        self.assertIn(
            "zero swarm availability",
            MODULE.stalled_reason(self.torrent(), self.NOW),
        )

    def test_incomplete_swarm_expires_even_after_recent_tracker_activity(self) -> None:
        torrent = self.torrent(
            progress=0.998,
            availability=0.998,
            amount_left=4_071_424,
            last_activity=self.NOW - 3600,
        )
        self.assertIn("swarm is incomplete", MODULE.stalled_reason(torrent, self.NOW))

    def test_metadata_magnet_expires_after_one_day(self) -> None:
        torrent = self.torrent(
            state="metaDL",
            added_on=self.NOW - 25 * 3600,
        )
        self.assertIn("metadata unavailable", MODULE.stalled_reason(torrent, self.NOW))

    def test_private_torrent_is_never_explicitly_public(self) -> None:
        self.assertFalse(
            MODULE.explicitly_public(
                self.torrent(private=True, tags="private,btarg"),
                "1337x (Prowlarr)",
            )
        )

    def test_unknown_magnet_requires_public_history(self) -> None:
        torrent = self.torrent(private=None)
        self.assertFalse(MODULE.explicitly_public(torrent, None))
        self.assertTrue(
            MODULE.explicitly_public(torrent, "The Pirate Bay (Prowlarr)")
        )

    def test_active_seed_prevents_cleanup(self) -> None:
        self.assertIsNone(
            MODULE.stalled_reason(self.torrent(num_seeds=1), self.NOW)
        )
