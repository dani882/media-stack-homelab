import importlib.util
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock


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
            "max_active_downloads": 3,
            "minimum_free_space_gib": 50,
            "stalled_after_hours": 12,
            "max_stalled_removals": 2,
            "season_packs_enabled": True,
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

    def test_lat_team_is_first_private_source(self) -> None:
        source = MODULE.source_policy(
            self.release(
                "Example.S02E01.SPANiSH.1080p.WEB-DL",
                "Lat-Team (API) (Prowlarr)",
                language="Spanish",
            ),
            self.policy,
        )
        self.assertIsNotNone(source)
        self.assertEqual(source.name, "lat-team")
        self.assertEqual(source.priority, 1)
        self.assertEqual(source.seed_minutes, 4920)

    def test_direct_latteam_season_pack_gets_missing_sonarr_scope(self) -> None:
        normalized = MODULE.normalize_direct_latteam_release(
            {
                "title": (
                    "The Last of Us 2023 S01 1080p AMZN WEB-DL "
                    "DD+ 5.1 H.264-LatTeam SPANiSH"
                ),
                "indexer": "Lat-Team (API)",
                "tvdbId": 392256,
                "downloadAllowed": None,
            },
            392256,
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["seasonNumber"], 1)
        self.assertTrue(normalized["fullSeason"])
        self.assertEqual(normalized["episodeNumbers"], [])
        self.assertTrue(normalized["approved"])
        self.assertTrue(normalized["downloadAllowed"])

    def test_direct_latteam_episode_gets_exact_episode_scope(self) -> None:
        normalized = MODULE.normalize_direct_latteam_release(
            {
                "title": "Example S02E03 Spanish Latino 1080p WEB-DL",
                "indexer": "Lat-Team (API)",
                "tvdbId": 451098,
            },
            451098,
        )
        self.assertIsNotNone(normalized)
        assert normalized is not None
        self.assertEqual(normalized["seasonNumber"], 2)
        self.assertEqual(normalized["episodeNumbers"], [3])
        self.assertFalse(normalized["fullSeason"])

    def test_direct_latteam_release_requires_exact_tvdb_identity(self) -> None:
        self.assertIsNone(
            MODULE.normalize_direct_latteam_release(
                {
                    "title": "Example S01 Spanish Latino 1080p WEB-DL",
                    "indexer": "Lat-Team (API)",
                    "tvdbId": 123,
                },
                999,
            )
        )

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

    def test_exact_missing_season_pack_is_accepted(self) -> None:
        candidate = self.release(
            "Example.S02.English.1080p.WEB-DL",
            "LimeTorrents (Prowlarr)",
            episodeNumbers=[1, 2, 3],
        )
        self.assertIs(
            MODULE.select_candidate(
                [candidate],
                self.episode,
                MODULE.LanguageRank.ENGLISH,
                self.policy,
                {1, 2, 3},
            ),
            candidate,
        )
        self.assertIsNone(
            MODULE.select_candidate(
                [candidate],
                self.episode,
                MODULE.LanguageRank.ENGLISH,
                self.policy,
                {1, 2},
            )
        )

    def test_pack_members_must_exactly_cover_missing_episodes(self) -> None:
        MODULE.validate_pack_members(
            [
                "Season 2/Example.S02E01.mkv",
                "Season 2/Example.S02E02.mkv",
            ],
            2,
            {1, 2},
        )
        with self.assertRaises(MODULE.GRAB.GrabError):
            MODULE.validate_pack_members(
                ["Season 2/Example.S02E01.mkv"],
                2,
                {1, 2},
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

    def test_empty_safe_candidate_search_is_retried_once(self) -> None:
        fetch = mock.Mock(side_effect=[[], [{"title": "safe"}]])
        with mock.patch.object(MODULE.time, "sleep") as sleep:
            candidates = MODULE.candidates_with_retry(
                fetch,
                lambda releases: releases,
                "series=Example season=S01",
            )
        self.assertEqual(candidates, [{"title": "safe"}])
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(2)

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

    def test_complete_english_season_is_upgradeable(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=UTC)
        episodes = [
            {
                "id": number,
                "seasonNumber": 1,
                "episodeNumber": number,
                "monitored": True,
                "hasFile": True,
                "episodeFileId": 100 + number,
                "airDateUtc": "2026-01-01T00:00:00Z",
            }
            for number in (1, 2)
        ]
        files = {
            101: {"languages": [{"name": "English"}]},
            102: {"languages": [{"name": "English"}]},
        }
        upgrades = MODULE.upgradeable_seasons(
            episodes,
            {1},
            files,
            set(),
            set(),
            now,
        )
        self.assertEqual(
            [item["id"] for item in upgrades[1]],
            [1, 2],
        )

    def test_partial_season_targets_missing_and_english_only_episodes(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=UTC)
        episodes = [
            {
                "id": 1,
                "seasonNumber": 1,
                "episodeNumber": 1,
                "monitored": True,
                "hasFile": True,
                "episodeFileId": 101,
                "airDateUtc": "2026-01-01T00:00:00Z",
            },
            {
                "id": 2,
                "seasonNumber": 1,
                "episodeNumber": 2,
                "monitored": True,
                "hasFile": True,
                "episodeFileId": 102,
                "airDateUtc": "2026-01-02T00:00:00Z",
            },
            {
                "id": 3,
                "seasonNumber": 1,
                "episodeNumber": 3,
                "monitored": True,
                "hasFile": False,
                "episodeFileId": 0,
                "airDateUtc": "2026-01-03T00:00:00Z",
            },
        ]
        files = {
            101: {"languages": [{"name": "English"}]},
            102: {"languages": [{"name": "Spanish"}]},
        }
        upgrades = MODULE.upgradeable_seasons(
            episodes, {1}, files, set(), set(), now
        )
        self.assertEqual([item["id"] for item in upgrades[1]], [1, 3])

    def test_monitored_series_without_seerr_request_is_targeted(self) -> None:
        targets = MODULE.monitored_series_targets(
            [
                {
                    "id": 7,
                    "tvdbId": 451098,
                    "monitored": True,
                    "added": "2026-01-01T00:00:00Z",
                    "seasons": [
                        {"seasonNumber": 0, "monitored": True},
                        {"seasonNumber": 1, "monitored": True},
                        {"seasonNumber": 2, "monitored": False},
                    ],
                }
            ],
            [],
        )
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["id"], -7)
        self.assertEqual(MODULE.requested_seasons(targets[0]), {1})
        self.assertEqual(
            MODULE.target_tags(targets[0], {"id": 7}),
            ["monitored-series-7"],
        )

    def test_season_with_latino_file_is_not_replaced(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=UTC)
        episodes = [
            {
                "id": 1,
                "seasonNumber": 1,
                "episodeNumber": 1,
                "monitored": True,
                "hasFile": True,
                "episodeFileId": 101,
                "airDateUtc": "2026-01-01T00:00:00Z",
            }
        ]
        files = {
            101: {"customFormats": [{"name": "LATINO"}]},
        }
        self.assertEqual(
            MODULE.upgradeable_seasons(
                episodes,
                {1},
                files,
                set(),
                set(),
                now,
            ),
            {},
        )

    def test_english_episode_is_an_individual_upgrade_target(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=UTC)
        episode = {
            "id": 1,
            "seasonNumber": 1,
            "episodeNumber": 1,
            "monitored": True,
            "hasFile": True,
            "episodeFileId": 101,
            "airDateUtc": "2026-01-01T00:00:00Z",
        }
        files = {101: {"languages": [{"name": "English"}]}}
        self.assertEqual(
            MODULE.upgradeable_episodes(
                [episode], {1}, files, set(), set(), now
            ),
            [episode],
        )

    def test_spanish_episode_is_not_an_individual_upgrade_target(self) -> None:
        now = datetime(2026, 9, 27, tzinfo=UTC)
        episode = {
            "id": 1,
            "seasonNumber": 1,
            "episodeNumber": 1,
            "monitored": True,
            "hasFile": True,
            "episodeFileId": 101,
            "airDateUtc": "2026-01-01T00:00:00Z",
        }
        files = {101: {"mediaInfo": {"audioLanguages": "spa/eng"}}}
        self.assertEqual(
            MODULE.upgradeable_episodes(
                [episode], {1}, files, set(), set(), now
            ),
            [],
        )

    def test_individual_upgrade_requires_better_private_spanish(self) -> None:
        installed = {"languages": [{"name": "English"}]}
        private_castilian = self.release(
            "Example.S02E01.SPANiSH.1080p.WEB-DL",
            "Milnueve (API) (Prowlarr)",
            language="Spanish",
            approved=False,
            rejected=True,
            rejections=[
                "Existing file on disk is of equal or higher preference: v2"
            ],
        )
        public_latino = self.release(
            "Example.S02E01.Spanish.Latino.1080p.WEB-DL",
            "LimeTorrents (Prowlarr)",
            language="Spanish (Latino)",
        )
        private_english = self.release(
            "Example.S02E01.English.1080p.WEB-DL",
            "Lat-Team (API) (Prowlarr)",
        )
        self.assertEqual(
            MODULE.language_upgrade_candidates(
                [public_latino, private_english, private_castilian],
                self.episode,
                installed,
                self.policy,
            ),
            [private_castilian],
        )

    def test_individual_upgrade_rejects_non_overridable_sonarr_reason(self) -> None:
        candidate = self.release(
            "Example.S02E01.SPANiSH.1080p.x265",
            "Lat-Team (API) (Prowlarr)",
            language="Spanish (Latino)",
            approved=False,
            rejected=True,
            rejections=["x265 is not wanted in profile"],
        )
        self.assertEqual(
            MODULE.language_upgrade_candidates(
                [candidate],
                self.episode,
                {"languages": [{"name": "English"}]},
                self.policy,
            ),
            [],
        )

    def test_individual_upgrade_requires_sonarr_approval_state(self) -> None:
        candidate = self.release(
            "Example.S02E01.SPANiSH.1080p.WEB-DL",
            "Lat-Team (API) (Prowlarr)",
            language="Spanish (Latino)",
            approved=False,
            rejected=False,
        )
        self.assertEqual(
            MODULE.language_upgrade_candidates(
                [candidate],
                self.episode,
                {"languages": [{"name": "English"}]},
                self.policy,
            ),
            [],
        )

    def test_only_approved_private_latino_season_pack_is_selected(self) -> None:
        good = self.release(
            "Carrie.2026.S01.1080p.H264.SPANiSH",
            "Lat-Team (API) (Prowlarr)",
            language="Spanish",
            seasonNumber=1,
            episodeNumbers=[],
            fullSeason=True,
        )
        rejected_h265 = self.release(
            "Carrie.2026.S01.1080p.H265.SPANiSH",
            "Lat-Team (API) (Prowlarr)",
            language="Spanish",
            seasonNumber=1,
            episodeNumbers=[],
            fullSeason=True,
            approved=False,
            rejected=True,
        )
        public = self.release(
            "Carrie.2026.S01.1080p.H264.Spanish.Latino",
            "Public (Prowlarr)",
            language="Spanish (Latino)",
            seasonNumber=1,
            episodeNumbers=[],
            fullSeason=True,
        )
        self.assertEqual(
            MODULE.latino_season_pack_candidates(
                [rejected_h265, public, good],
                1,
                self.policy,
            ),
            [good],
        )

    def test_equal_revision_rejection_does_not_hide_missing_pack_episodes(self) -> None:
        release = self.release(
            "Ranma.1.2.2024.S01.1080p.H264.SPANiSH",
            "Lat-Team (API) (Prowlarr)",
            language="Spanish",
            seasonNumber=1,
            episodeNumbers=[],
            fullSeason=True,
            approved=False,
            rejected=True,
        )
        release["rejections"] = [
            "Existing file on disk is of equal or higher preference: v2"
        ]
        self.assertEqual(
            MODULE.latino_season_pack_candidates([release], 1, self.policy),
            [release],
        )

    def test_audio_rank_uses_imported_media_metadata(self) -> None:
        self.assertEqual(
            MODULE.detected_audio_rank(
                {"mediaInfo": {"audioLanguages": "spa/eng"}}
            ),
            MODULE.LanguageRank.CASTILIAN,
        )
        self.assertEqual(
            MODULE.detected_audio_rank(
                {"mediaInfo": {"audioLanguages": "eng"}}
            ),
            MODULE.LanguageRank.ENGLISH,
        )

    def test_completed_import_is_verified_from_sonarr_audio(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "tags": (
                "series-fallback,sonarr-episode-4512,"
                "fallback-language-latino"
            ),
        }
        qbit = mock.Mock()

        def fake_get(_base: str, path: str, _key: str) -> dict:
            if path == "/api/v3/episode/4512":
                return {"hasFile": True, "episodeFileId": 88}
            if path == "/api/v3/episodefile/88":
                return {"mediaInfo": {"audioLanguages": "spa/eng"}}
            raise AssertionError(path)

        with mock.patch.object(MODULE, "get_json", side_effect=fake_get):
            self.assertEqual(
                MODULE.reconcile_imports(qbit, [torrent], "key", True),
                (1, 0),
            )
        qbit.post_form.assert_called_once_with(
            "/api/v2/torrents/addTags",
            {"hashes": "abc", "tags": "series-fallback-import-verified"},
        )

    def test_completed_direct_pack_requests_sonarr_scan_once(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "content_path": "/data/Downloads/complete/tv/Example S01",
            "tags": "series-fallback,sonarr-episode-1,sonarr-episode-2",
        }
        qbit = mock.Mock()
        with mock.patch.object(MODULE, "post_json", return_value={"id": 3}) as post:
            self.assertEqual(
                MODULE.request_completed_imports(qbit, [torrent], "key", True),
                1,
            )
        self.assertEqual(post.call_args.args[3]["name"], "DownloadedEpisodesScan")
        self.assertEqual(
            post.call_args.args[3]["path"],
            "/data/Downloads/complete/tv/Example S01",
        )
        self.assertIn("series-fallback-import-requested", torrent["tags"])

    def test_completed_pack_outside_downloads_is_not_scanned(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "content_path": "/data/Media/TV Shows/Example",
            "tags": "series-fallback,sonarr-episode-1",
        }
        qbit = mock.Mock()
        with mock.patch.object(MODULE, "post_json") as post:
            self.assertEqual(
                MODULE.request_completed_imports(qbit, [torrent], "key", True),
                0,
            )
        post.assert_not_called()
        qbit.post_form.assert_not_called()

    def test_english_only_import_is_marked_as_language_mismatch(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "tags": (
                "series-fallback,sonarr-episode-4512,"
                "fallback-language-castilian"
            ),
        }
        qbit = mock.Mock()

        def fake_get(_base: str, path: str, _key: str) -> dict:
            if path == "/api/v3/episode/4512":
                return {"hasFile": True, "episodeFileId": 88}
            return {"mediaInfo": {"audioLanguages": "eng"}}

        with mock.patch.object(MODULE, "get_json", side_effect=fake_get):
            self.assertEqual(
                MODULE.reconcile_imports(qbit, [torrent], "key", True),
                (0, 1),
            )
        self.assertIn("language-mismatch", torrent["tags"])

    def test_upgrade_waits_until_sonarr_replaces_original_file(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 1,
            "tags": (
                "series-fallback,series-language-upgrade,"
                "sonarr-episode-4512,sonarr-original-file-88,"
                "fallback-language-latino"
            ),
        }
        qbit = mock.Mock()

        def fake_get(_base: str, path: str, _key: str) -> dict:
            if path == "/api/v3/episode/4512":
                return {"hasFile": True, "episodeFileId": 88}
            if path == "/api/v3/episodefile/88":
                return {"mediaInfo": {"audioLanguages": "eng"}}
            raise AssertionError(path)

        with mock.patch.object(MODULE, "get_json", side_effect=fake_get):
            self.assertEqual(
                MODULE.reconcile_imports(qbit, [torrent], "key", True),
                (0, 0),
            )
        qbit.post_form.assert_not_called()

    def test_incomplete_torrent_is_not_import_verified(self) -> None:
        torrent = {
            "hash": "abc",
            "progress": 0.99,
            "tags": "series-fallback,sonarr-episode-4512",
        }
        qbit = mock.Mock()
        with mock.patch.object(MODULE, "get_json") as get_json:
            self.assertEqual(
                MODULE.reconcile_imports(qbit, [torrent], "key", True),
                (0, 0),
            )
        get_json.assert_not_called()
        qbit.post_form.assert_not_called()

    def test_manually_stopped_download_does_not_consume_active_cap(self) -> None:
        active = MODULE.active_fallback_torrents(
            [
                {
                    "tags": "private,series-fallback",
                    "state": "stoppedDL",
                },
                {
                    "tags": "private,series-fallback",
                    "state": "downloading",
                },
            ]
        )
        self.assertEqual(len(active), 1)

    def test_only_old_stalled_public_fallback_is_removable(self) -> None:
        now = 1_000_000
        old = now - 13 * 3600
        torrents = [
            {
                "tags": "public,series-fallback",
                "state": "stalledDL",
                "progress": 0.1,
                "dlspeed": 0,
                "added_on": old,
            },
            {
                "tags": "private,series-fallback",
                "state": "stalledDL",
                "progress": 0,
                "dlspeed": 0,
                "added_on": old,
            },
        ]
        self.assertEqual(
            MODULE.stalled_public_torrents(torrents, now, 12),
            [torrents[0]],
        )

    def test_unsafe_public_payload_is_removed_and_blocked(self) -> None:
        torrent = {
            "hash": "abc",
            "tags": "public,series-fallback,release-series-danger",
        }
        qbit = mock.Mock()
        qbit.get_json.return_value = [
            {"name": "Example.S01E01.1080p.WEB-DL.exe"}
        ]
        rejected: set[str] = set()

        self.assertEqual(
            MODULE.remove_unsafe_public(
                qbit,
                [torrent],
                rejected,
                True,
            ),
            1,
        )
        self.assertEqual(rejected, {"release-series-danger"})
        qbit.post_form.assert_called_once_with(
            "/api/v2/torrents/delete",
            {"hashes": "abc", "deleteFiles": "true"},
        )

    def test_unsafe_private_payload_is_never_deleted_by_public_cleanup(self) -> None:
        torrent = {
            "hash": "abc",
            "tags": "private,series-fallback,release-series-private",
        }
        qbit = mock.Mock()
        self.assertEqual(
            MODULE.remove_unsafe_public(
                qbit,
                [torrent],
                set(),
                True,
            ),
            0,
        )
        qbit.get_json.assert_not_called()
        qbit.post_form.assert_not_called()

    def test_free_space_reserves_candidate_and_safety_floor(self) -> None:
        usage = mock.Mock(free=100 * 1024**3)
        with mock.patch.object(MODULE.shutil, "disk_usage", return_value=usage):
            self.assertTrue(
                MODULE.free_space_allows(Path("/downloads"), 40 * 1024**3, 50)
            )
            self.assertFalse(
                MODULE.free_space_allows(Path("/downloads"), 60 * 1024**3, 50)
            )


if __name__ == "__main__":
    unittest.main()
