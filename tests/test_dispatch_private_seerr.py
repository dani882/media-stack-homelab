import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path("scripts/dispatch-private-seerr.py")
SPEC = importlib.util.spec_from_file_location("dispatch_private_seerr", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrivateDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.indexers = {
            11: {
                "tracker": "btarg",
                "priority": 2,
                "minimum_seeders": 1,
            },
            7: {
                "tracker": "milnueve",
                "priority": 4,
                "minimum_seeders": 1,
            },
        }

    @staticmethod
    def release(indexer_id: int, title: str, seeders: int = 3) -> dict:
        return {
            "indexerId": indexer_id,
            "tmdbId": 123,
            "title": title,
            "seeders": seeders,
            "protocol": "torrent",
            "downloadUrl": "http://prowlarr/download/opaque",
        }

    def test_language_outranks_tracker_priority(self) -> None:
        selected = MODULE.select_candidate(
            [
                self.release(11, "Example English 1080p"),
                self.release(7, "Example Castellano 1080p"),
            ],
            123,
            self.indexers,
            "english",
            720,
        )
        self.assertEqual(selected["indexerId"], 7)

    def test_btarg_wins_equal_language_tie(self) -> None:
        selected = MODULE.select_candidate(
            [
                self.release(7, "Example Castellano 1080p"),
                self.release(11, "Example Spanish Castellano 1080p"),
            ],
            123,
            self.indexers,
            "castilian",
            720,
        )
        self.assertEqual(selected["indexerId"], 11)

    def test_dangerous_release_is_never_selected(self) -> None:
        selected = MODULE.select_candidate(
            [self.release(11, "Example Spanish Latino 1080p zipx")],
            123,
            self.indexers,
            "english",
            720,
        )
        self.assertIsNone(selected)

    def test_english_fallback_starts_after_grace_period(self) -> None:
        now = datetime(2026, 9, 11, tzinfo=UTC)
        policy = {
            "minimum_language": "castilian",
            "minimum_resolution": 720,
            "english_fallback_days": 14,
        }
        recent = {"createdAt": (now - timedelta(days=2)).isoformat()}
        old = {"createdAt": (now - timedelta(days=20)).isoformat()}
        self.assertEqual(
            MODULE.language_floor_for_request(recent, policy, now),
            "castilian",
        )
        self.assertEqual(
            MODULE.language_floor_for_request(old, policy, now),
            "english",
        )

    def test_discovers_btarg_by_definition_not_numeric_id(self) -> None:
        policy = next(
            item
            for item in MODULE.PRIVATE_INDEXER_POLICIES
            if item["tracker"] == "btarg"
        )
        self.assertTrue(
            MODULE.matches_policy(
                {"id": 99, "name": "BTArg", "definitionName": "btarg"},
                policy,
            )
        )

    def test_completed_request_is_reopened_when_media_was_deleted(self) -> None:
        self.assertTrue(
            MODULE.eligible_request(
                {
                    "type": "movie",
                    "status": 5,
                    "media": {"tmdbId": 123, "status": 7},
                }
            )
        )
        self.assertFalse(
            MODULE.eligible_request(
                {
                    "type": "movie",
                    "status": 5,
                    "media": {"tmdbId": 123, "status": 5},
                }
            )
        )

    def test_release_tag_uses_btarg_detail_id(self) -> None:
        tag = MODULE.release_tag(
            {
                **self.release(11, "Example 2026 1080p"),
                "infoUrl": "https://www.btarg.com.ar/tracker/details.php?id=129984",
            },
            self.indexers,
        )
        self.assertEqual(tag, "release-btarg-129984")

    def test_language_mismatch_does_not_block_whole_request(self) -> None:
        class FakeQbit:
            @staticmethod
            def get_json(path: str) -> list[dict]:
                return [
                    {
                        "tags": (
                            "private,btarg,seerr-request-3,"
                            "release-btarg-129984,language-mismatch"
                        )
                    }
                ]

        self.assertNotIn("seerr-request-3", MODULE.existing_request_tags(FakeQbit()))
        self.assertEqual(
            MODULE.blocked_release_tags(FakeQbit()),
            {"release-btarg-129984"},
        )

    def test_verified_btarg_detail_supplies_missing_identity_and_language(self) -> None:
        class FakeBTArg:
            @staticmethod
            def detail(url: str) -> SimpleNamespace:
                return SimpleNamespace(
                    language="english",
                    language_text="Inglés",
                    imdb_id="tt1234567",
                    video_codec_text="AVC",
                    resolution_text="1920x1080",
                )

        releases = MODULE.enrich_btarg_candidates(
            [
                {
                    **self.release(11, "Example 2026 1080p"),
                    "tmdbId": 0,
                    "indexer": "BTArg",
                    "infoUrl": "https://www.btarg.com.ar/tracker/details.php?id=123",
                }
            ],
            123,
            "tt1234567",
            self.indexers,
            FakeBTArg(),
        )
        self.assertEqual(releases[0]["tmdbId"], 123)
        self.assertEqual(
            MODULE.language_rank(releases[0]),
            MODULE.GRAB.LanguageRank.ENGLISH,
        )

    def test_btarg_detail_failure_skips_only_that_candidate(self) -> None:
        class FailingBTArg:
            @staticmethod
            def detail(url: str) -> SimpleNamespace:
                raise MODULE.BTArgError("temporary failure")

        releases = MODULE.enrich_btarg_candidates(
            [
                {
                    **self.release(11, "Broken BTArg result 1080p"),
                    "indexer": "BTArg",
                    "infoUrl": "https://www.btarg.com.ar/tracker/details.php?id=123",
                },
                self.release(7, "Working Milnueve Castellano 1080p"),
            ],
            123,
            "tt1234567",
            self.indexers,
            FailingBTArg(),
        )
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["indexerId"], 7)
