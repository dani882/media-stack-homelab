import importlib.util
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


MODULE_PATH = Path("scripts/dispatch-private-seerr.py")
SPEC = importlib.util.spec_from_file_location("dispatch_private_seerr", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrivateDispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.indexers = {
            12: {
                "tracker": "lat-team",
                "priority": 1,
                "minimum_seeders": 1,
            },
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

    def test_lat_team_wins_equal_language_tie(self) -> None:
        selected = MODULE.select_candidate(
            [
                self.release(11, "Example Spanish Latino 1080p"),
                self.release(12, "Example Spanish Latino 1080p"),
            ],
            123,
            self.indexers,
            "latino",
            720,
        )
        self.assertEqual(selected["indexerId"], 12)

    def test_h264_beats_latteam_hevc_for_equal_language(self) -> None:
        selected = MODULE.select_candidate(
            [
                self.release(12, "Example Spanish Latino 2160p H.265-LatTeam"),
                self.release(11, "Example Spanish Latino 1080p H.264-GROUP"),
            ],
            123,
            self.indexers,
            "latino",
            720,
        )
        self.assertEqual(selected["indexerId"], 11)

    def test_latteam_hevc_is_a_last_resort_candidate(self) -> None:
        selected = MODULE.select_candidate(
            [self.release(12, "Example Spanish Latino 2160p HEVC-LatTeam")],
            123,
            self.indexers,
            "latino",
            720,
        )
        self.assertIsNotNone(selected)

    def test_other_tracker_hevc_remains_rejected(self) -> None:
        selected = MODULE.select_candidate(
            [self.release(11, "Example Spanish Latino 1080p x265-GROUP")],
            123,
            self.indexers,
            "latino",
            720,
        )
        self.assertIsNone(selected)

    def test_existing_movie_requires_real_language_upgrade(self) -> None:
        selected = MODULE.select_candidate(
            [self.release(12, "Example English 1080p")],
            123,
            self.indexers,
            "english",
            720,
            {"languages": [{"name": "English"}]},
        )
        self.assertIsNone(selected)

    def test_existing_english_movie_accepts_castilian_upgrade(self) -> None:
        selected = MODULE.select_candidate(
            [self.release(7, "Example Castellano 1080p")],
            123,
            self.indexers,
            "castilian",
            720,
            {"languages": [{"name": "English"}]},
        )
        self.assertIsNotNone(selected)

    def test_all_monitored_non_latino_movies_are_targets(self) -> None:
        movies = [
            {
                "id": 1,
                "tmdbId": 101,
                "monitored": True,
                "hasFile": True,
                "movieFile": {"languages": [{"name": "English"}]},
            },
            {
                "id": 2,
                "tmdbId": 102,
                "monitored": True,
                "hasFile": True,
                "movieFile": {"customFormats": [{"name": "LATINO"}]},
            },
            {
                "id": 5,
                "tmdbId": 105,
                "monitored": True,
                "hasFile": True,
                "movieFile": {"mediaInfo": {"audioLanguages": "spa/eng"}},
            },
            {"id": 3, "tmdbId": 103, "monitored": True, "hasFile": False},
            {"id": 4, "tmdbId": 104, "monitored": False, "hasFile": False},
        ]
        targets = MODULE.monitored_movie_targets(movies, [])
        self.assertEqual([item["movie"]["id"] for item in targets], [1, 3])

    def test_movie_rotation_continues_after_last_checked_item(self) -> None:
        targets = [
            {"movie": {"id": 1}},
            {"movie": {"id": 2}},
            {"movie": {"id": 3}},
        ]
        rotated = MODULE.rotate_movie_targets(targets, 2)
        self.assertEqual([item["movie"]["id"] for item in rotated], [3, 1, 2])

    def test_active_private_dispatch_cap_ignores_completed_items(self) -> None:
        self.assertEqual(
            MODULE.active_private_dispatches(
                [
                    {"tags": "private-dispatch", "progress": 0.5},
                    {"tags": "private-dispatch", "progress": 1},
                    {
                        "tags": "private-dispatch,language-mismatch",
                        "progress": 0.2,
                    },
                ]
            ),
            1,
        )

    def test_active_private_dispatch_cap_ignores_inactive_and_queued_items(self) -> None:
        now = 1_000_000.0
        self.assertEqual(
            MODULE.active_private_dispatches(
                [
                    {
                        "tags": "private-dispatch",
                        "progress": 0,
                        "state": "stalledDL",
                        "dlspeed": 0,
                        "added_on": now - 61,
                        "last_activity": now - 61,
                    },
                    {
                        "tags": "private-dispatch",
                        "progress": 0,
                        "state": "queuedDL",
                    },
                    {
                        "tags": "private-dispatch",
                        "progress": 0.2,
                        "state": "downloading",
                        "dlspeed": 4096,
                    },
                ],
                now,
            ),
            1,
        )

    def test_torrent_fetch_failure_is_deferred_without_crashing(self) -> None:
        qbit = mock.Mock()
        release = {"indexerId": 12}
        indexer = {"seed_minutes": 4920, "ratio_limit": None}
        with mock.patch.object(
            MODULE.GRAB,
            "add_to_qbittorrent",
            side_effect=MODULE.GRAB.TorrentFetchError("tracker unavailable"),
        ):
            self.assertFalse(
                MODULE.add_selected_release(
                    qbit,
                    release,
                    indexer,
                    "private,lat-team",
                    "Example [LATINO]",
                )
            )

    def test_movie_upgrade_waits_for_radarr_to_replace_original_file(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "tags": (
                "private-dispatch,movie-language-upgrade,radarr-movie-7,"
                "radarr-original-file-88,movie-expected-latino,"
                "private-dispatch-import-requested"
            ),
        }
        qbit = mock.Mock()
        movies = {
            7: {
                "movieFile": {
                    "id": 88,
                    "mediaInfo": {"audioLanguages": "eng"},
                }
            }
        }
        self.assertEqual(
            MODULE.reconcile_movie_imports(qbit, [torrent], movies, True),
            (0, 0),
        )
        qbit.post_form.assert_not_called()

    def test_completed_direct_movie_requests_radarr_scan_once(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "content_path": "/data/Downloads/complete/radarr/Example",
            "tags": "private-dispatch,radarr-movie-7",
        }
        qbit = mock.Mock()
        with mock.patch.object(MODULE, "post_json", return_value={"id": 4}) as post:
            self.assertEqual(
                MODULE.request_completed_movie_imports(qbit, [torrent], "key", True),
                1,
            )
        self.assertEqual(post.call_args.args[1]["name"], "DownloadedMoviesScan")
        self.assertEqual(
            post.call_args.args[1]["path"],
            "/data/Downloads/complete/radarr/Example",
        )
        self.assertIn("private-dispatch-import-requested", torrent["tags"])

    def test_movie_upgrade_is_verified_after_new_spanish_file_import(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "tags": (
                "private-dispatch,movie-language-upgrade,radarr-movie-7,"
                "radarr-original-file-88,movie-expected-latino,"
                "private-dispatch-import-requested"
            ),
        }
        qbit = mock.Mock()
        movies = {
            7: {
                "movieFile": {
                    "id": 99,
                    "mediaInfo": {"audioLanguages": "spa/eng"},
                }
            }
        }
        self.assertEqual(
            MODULE.reconcile_movie_imports(qbit, [torrent], movies, True),
            (1, 0),
        )
        qbit.post_form.assert_called_once_with(
            "/api/v2/torrents/addTags",
            {"hashes": "abc", "tags": "private-dispatch-import-verified"},
        )

    def test_movie_upgrade_without_original_file_id_is_never_verified(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "tags": (
                "private-dispatch,movie-language-upgrade,radarr-movie-7,"
                "movie-expected-latino,private-dispatch-import-requested"
            ),
        }
        qbit = mock.Mock()
        movies = {
            7: {
                "movieFile": {
                    "id": 99,
                    "mediaInfo": {"audioLanguages": "spa/eng"},
                }
            }
        }
        self.assertEqual(
            MODULE.reconcile_movie_imports(qbit, [torrent], movies, True),
            (0, 0),
        )
        qbit.post_form.assert_not_called()

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

    def test_lat_team_policy_is_priority_one(self) -> None:
        policy = next(
            item
            for item in MODULE.PRIVATE_INDEXER_POLICIES
            if item["tracker"] == "lat-team"
        )
        self.assertEqual(policy["priority"], 1)
        self.assertTrue(
            MODULE.matches_policy(
                {
                    "id": 12,
                    "name": "Lat-Team (API)",
                    "definitionName": "lat-team-api",
                },
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
