from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/media"))

MODULE_PATH = ROOT / "scripts/audit-private-trackers.py"
SPEC = importlib.util.spec_from_file_location(
    "audit_private_trackers",
    MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrivateTrackerAuditTest(unittest.TestCase):
    def test_matches_known_tracker_subdomain(self) -> None:
        policy = MODULE.matching_policy({"tracker.milnueve.cc"})

        self.assertIsNotNone(policy)
        assert policy is not None
        self.assertEqual(policy.name, "Milnueve")

    def test_retrotoon_pending_torrent_is_protected(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "a" * 40,
                "progress": 1,
                "seeding_time_limit": 4320,
                "seeding_time": 60,
            },
            {"tracker.retrotoon.world"},
        )

        self.assertTrue(safe)
        self.assertIn("RetroToon World", message)
        self.assertIn("PENDING", message)

    def test_missing_seed_limit_is_at_risk(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "b" * 40,
                "progress": 1,
                "seeding_time_limit": -1,
                "seeding_time": 0,
            },
            {"tracker.milnueve.cc"},
        )

        self.assertFalse(safe)
        self.assertIn("no finite", message)

    def test_short_seed_limit_is_at_risk(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "c" * 40,
                "progress": 1,
                "seeding_time_limit": 60,
                "seeding_time": 0,
            },
            {"tracker.retrotoon.world"},
        )

        self.assertFalse(safe)
        self.assertIn("below policy", message)

    def test_unknown_private_tracker_is_at_risk(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "d" * 40,
                "progress": 1,
                "seeding_time_limit": 9999,
                "seeding_time": 9999,
            },
            {"tracker.example.invalid"},
        )

        self.assertFalse(safe)
        self.assertIn("UNRECOGNIZED", message)


if __name__ == "__main__":
    unittest.main()
