import importlib.util
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


MODULE_PATH = Path("scripts/dispatch-series-fallback.py")
SPEC = importlib.util.spec_from_file_location("dispatch_series_fallback", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SeriesFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = {
            "minimum_resolution": 720,
            "english_fallback_days": 0,
            "public_enabled": True,
            "public_minimum_seeders": 5,
            "public_seed_minutes": 30,
            "max_searches": 12,
        }
        self.episode = {"id": 4512, "seasonNumber": 2, "episodeNumber": 1}

    @staticmethod
    def release(
        title: str,
        indexer: str,
        language: str = "English",
        seeders: int = 10,
        **overrides: object,
    ) -> dict:
        payload = {
            "title": title,
            "indexer": indexer,
            "indexerPriority": 20,
            "seasonNumber": 2,
            "episodeNumbers": [1],
            "approved": True,
            "rejected": False,
            "downloadAllowed": True,
            "protocol": "torrent",
            "downloadUrl": "http://prowlarr:9696/download/opaque",
            "seeders": seeders,
            "customFormatScore": 0,
            "languages": [] if not language else [{"name": language}],
        }
        payload.update(overrides)
        return payload

    def test_language_outranks_private_source(self) -> None:
        private_english = self.release(
            "Example.S02E01.English.1080p.WEB-DL",
            "Milnueve (API) (Prowlarr)",
        )
        public_latino = self.release(
            "Example.S02E01.Spanish.Latino.1080p.WEB-DL",
            "LimeTorrents (Prowlarr)",
            language="Spanish (Latino)",
        )
        selected = MODULE.select_candidate(
            [private_english, public_latino],
            self.episode,
            MODULE.LanguageRank.ENGLISH,
            self.policy,
        )
        self.assertIs(selected, public_latino)

    def test_private_wins_equal_language_tie(self) -> None:
        public = self.release(
            "Example.S02E01.English.1080p.WEB-DL",
            "LimeTorrents (Prowlarr)",
        )
        private = self.release(
            "Example.S02E01.English.1080p.WEB-DL-GROUP",
            "Milnueve (API) (Prowlarr)",
        )
        selected = MODULE.select_candidate(
            [public, private],
            self.episode,
            MODULE.LanguageRank.ENGLISH,
            self.policy,
        )
        self.assertIs(selected, private)

    def test_bare_dual_with_unknown_language_is_rejected(self) -> None:
        candidate = self.release(
            "Example.S02E01.Dual.Audio.1080p.WEB-DL",
            "LimeTorrents (Prowlarr)",
            language="",
        )
        self.assertIsNone(
            MODULE.select_candidate(
                [candidate],
                self.episode,
                MODULE.LanguageRank.ENGLISH,
                self.policy,
            )
        )

    def test_multi_episode_release_is_rejected(self) -> None:
        candidate = self.release(
            "Example.S02E01-E02.English.1080p.WEB-DL",
            "LimeTorrents (Prowlarr)",
            episodeNumbers=[1, 2],
        )
        self.assertIsNone(
            MODULE.select_candidate(
                [candidate],
                self.episode,
                MODULE.LanguageRank.ENGLISH,
                self.policy,
            )
        )

    def test_sonarr_rejection_is_respected(self) -> None:
        candidate = self.release(
            "Example.S02E01.English.1080p.x265",
            "LimeTorrents (Prowlarr)",
            approved=False,
            rejected=True,
        )
        self.assertIsNone(
            MODULE.select_candidate(
                [candidate],
                self.episode,
                MODULE.LanguageRank.ENGLISH,
                self.policy,
            )
        )

    def test_public_minimum_seeders_is_enforced(self) -> None:
        candidate = self.release(
            "Example.S02E01.English.1080p.WEB-DL",
            "LimeTorrents (Prowlarr)",
            seeders=4,
        )
        self.assertIsNone(
            MODULE.select_candidate(
                [candidate],
                self.episode,
                MODULE.LanguageRank.ENGLISH,
                self.policy,
            )
        )

    def test_english_fallback_is_immediate(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=UTC)
        request = {"createdAt": (now - timedelta(minutes=1)).isoformat()}
        self.assertEqual(
            MODULE.language_floor(request, self.policy, now),
            MODULE.LanguageRank.ENGLISH,
        )

    def test_rotation_moves_past_unavailable_episode(self) -> None:
        items = [
            {"id": 1, "seasonNumber": 1, "episodeNumber": 1},
            {"id": 2, "seasonNumber": 1, "episodeNumber": 2},
            {"id": 3, "seasonNumber": 1, "episodeNumber": 3},
        ]
        self.assertEqual(
            [item["id"] for item in MODULE.rotate_after(items, 2)],
            [3, 1, 2],
        )

    def test_inspection_rejections_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            MODULE.save_state(
                path,
                {"56": 4512},
                {"release-series-deadbeef1234"},
                56,
            )
            cursors, rejected, last_request_id = MODULE.load_state(path)
        self.assertEqual(cursors, {"56": 4512})
        self.assertEqual(rejected, {"release-series-deadbeef1234"})
        self.assertEqual(last_request_id, 56)

    def test_requests_rotate_after_last_processed_request(self) -> None:
        requests = [{"id": 14}, {"id": 32}, {"id": 56}]
        self.assertEqual(
            [item["id"] for item in MODULE.rotate_requests(requests, 14)],
            [32, 56, 14],
        )

    def test_missing_filter_excludes_queue_and_active_torrent(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=UTC)
        episodes = [
            {
                "id": 1,
                "seasonNumber": 2,
                "episodeNumber": 1,
                "monitored": True,
                "hasFile": False,
                "episodeFileId": 0,
                "airDateUtc": "2020-01-01T00:00:00Z",
            },
            {
                "id": 2,
                "seasonNumber": 2,
                "episodeNumber": 2,
                "monitored": True,
                "hasFile": False,
                "episodeFileId": 0,
                "airDateUtc": "2020-01-02T00:00:00Z",
            },
            {
                "id": 3,
                "seasonNumber": 2,
                "episodeNumber": 3,
                "monitored": True,
                "hasFile": False,
                "episodeFileId": 0,
                "airDateUtc": "2020-01-03T00:00:00Z",
            },
        ]
        missing = MODULE.missing_episodes(
            episodes,
            {2},
            {1},
            {"sonarr-episode-2"},
            now,
        )
        self.assertEqual([item["id"] for item in missing], [3])


if __name__ == "__main__":
    unittest.main()
