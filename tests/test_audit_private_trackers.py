
import importlib.util
import tempfile
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
                "seeding_time_limit": 4920,
                "seeding_time": 60,
                "completion_on": 1_000_000,
            },
            {"tracker.retrotoon.world"},
            now=1_000_001,
        )

        self.assertTrue(safe)
        self.assertIn("RetroToon World", message)
        self.assertIn("PENDING", message)

    def test_retrotoon_deadline_alerts_when_remaining_seed_time_will_not_fit(self) -> None:
        complete_at = 1_000_000
        safe, message = MODULE.audit_torrent(
            {
                "hash": "e" * 40,
                "progress": 1,
                "seeding_time_limit": 4920,
                "seeding_time": 60 * 60,
                "completion_on": complete_at,
            },
            {"ann.retrotoon.world"},
            now=complete_at + (9 * 24 * 60 * 60),
        )

        self.assertFalse(safe)
        self.assertIn("AT RISK", message)
        self.assertIn("deadline_remaining", message)

    def test_retrotoon_missing_completion_timestamp_is_at_risk(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "f" * 40,
                "progress": 1,
                "seeding_time_limit": 4920,
                "seeding_time": 60,
                "completion_on": -1,
            },
            {"tracker.retrotoon.world"},
        )

        self.assertFalse(safe)
        self.assertIn("timestamp", message)

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

    def test_torrenthaven_uses_72_hour_policy(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "h" * 40,
                "progress": 1,
                "seeding_time_limit": 4920,
                "seeding_time": 60,
            },
            {"tracker.torrenthaven.org"},
        )

        self.assertTrue(safe)
        self.assertIn("Torrent Haven", message)

    def test_dreadvault_uses_120_hour_policy_plus_margin(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "i" * 40,
                "progress": 1,
                "seeding_time_limit": 7800,
                "seeding_time": 60,
            },
            {"tracker.dreadvault.org"},
        )

        self.assertTrue(safe)
        self.assertIn("DreadVault", message)
        self.assertIn("remaining=7799m", message)

    def test_btarg_uses_one_to_one_ratio_policy(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "j" * 40,
                "progress": 1,
                "ratio_limit": 1.0,
                "ratio": 0.25,
            },
            {"announce.btarg.org"},
        )

        self.assertTrue(safe)
        self.assertIn("BTArg", message)
        self.assertIn("PENDING", message)
        self.assertIn("required=1.00", message)

    def test_btarg_missing_ratio_limit_is_at_risk(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "k" * 40,
                "progress": 1,
                "ratio_limit": -1,
                "ratio": 2.0,
            },
            {"btarg.com.ar"},
        )

        self.assertFalse(safe)
        self.assertIn("no finite", message)

    def test_writes_secret_free_html_and_json_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-trackers.html"
            MODULE.write_dashboard(
                path,
                {
                    "BTArg": {
                        "torrents": 2,
                        "uploaded": 1024**3,
                        "downloaded": 2 * 1024**3,
                        "satisfied": 1,
                        "pending": 1,
                        "downloading": 0,
                        "risk": 0,
                    }
                },
            )
            document = path.read_text(encoding="utf-8")
            payload = (path.with_suffix(".json")).read_text(encoding="utf-8")
            self.assertIn("BTArg", document)
            self.assertIn("1.0 GiB", document)
            self.assertNotIn("announce", document.casefold())
            self.assertIn('"tracker": "BTArg"', payload)


if __name__ == "__main__":
    unittest.main()
