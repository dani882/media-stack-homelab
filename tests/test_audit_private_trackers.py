
import importlib.util
import io
import tempfile
import sys
import unittest
from contextlib import redirect_stdout
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
    def test_enforcement_sends_qbittorrent_53_share_limit_mode(self) -> None:
        class FakeClient:
            def __init__(self):
                self.posts = []

            def get_json(self, path):
                if path == "/api/v2/torrents/info":
                    return [
                        {
                            "hash": "p" * 40,
                            "private": True,
                            "progress": 1,
                            "seeding_time_limit": -1,
                            "seeding_time": 0,
                            "uploaded": 0,
                            "downloaded": 1,
                        }
                    ]
                if path.startswith("/api/v2/torrents/trackers?"):
                    return [{"url": "https://announce.lat-team.com/example"}]
                if path.startswith("/api/v2/torrents/files?"):
                    return [{"name": "video.mkv", "priority": 1}]
                raise AssertionError(f"unexpected request: {path}")

            def post_form(self, path, payload):
                self.posts.append((path, payload))

        client = FakeClient()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                MODULE.run_audit(client, enforce_limits=True),
                0,
            )

        self.assertEqual(len(client.posts), 1)
        path, payload = client.posts[0]
        self.assertEqual(path, "/api/v2/torrents/setShareLimits")
        self.assertEqual(payload["shareLimitsMode"], "Default")
        self.assertEqual(payload["shareLimitAction"], "Default")

    def test_lat_team_uses_72_hour_policy_plus_50_hour_margin(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "m" * 40,
                "progress": 1,
                "seeding_time_limit": 7320,
                "seeding_time": 60,
            },
            {"announce.lat-team.com"},
        )

        self.assertTrue(safe)
        self.assertIn("Lat-Team", message)
        self.assertIn("remaining=7319m", message)

    def test_lat_team_partial_selection_is_at_risk(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "n" * 40,
                "progress": 0.5,
                "seeding_time_limit": 7320,
                "seeding_time": 0,
            },
            {"lat-team.com"},
            has_skipped_files=True,
        )

        self.assertFalse(safe)
        self.assertIn("partial torrent selection", message)

    def test_run_audit_inspects_lat_team_file_selection(self) -> None:
        class FakeClient:
            def get_json(self, path):
                if path == "/api/v2/torrents/info":
                    return [
                        {
                            "hash": "o" * 40,
                            "private": True,
                            "progress": 0.5,
                            "seeding_time_limit": 7320,
                            "seeding_time": 0,
                        }
                    ]
                if path.startswith("/api/v2/torrents/trackers?"):
                    return [{"url": "https://announce.lat-team.com/example"}]
                if path.startswith("/api/v2/torrents/files?"):
                    return [
                        {"name": "video.mkv", "priority": 1},
                        {"name": "sample.mkv", "priority": 0},
                    ]
                raise AssertionError(f"unexpected request: {path}")

        with redirect_stdout(io.StringIO()):
            with self.assertRaises(MODULE.PrivateTrackerAuditError):
                MODULE.run_audit(FakeClient())

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

    def test_docspedia_uses_48_hour_policy_plus_margin(self) -> None:
        safe, message = MODULE.audit_torrent(
            {
                "hash": "l" * 40,
                "progress": 1,
                "seeding_time_limit": 3480,
                "seeding_time": 60,
            },
            {"tracker.docspedia.world"},
        )

        self.assertTrue(safe)
        self.assertIn("DocsPedia", message)
        self.assertIn("remaining=3479m", message)

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
