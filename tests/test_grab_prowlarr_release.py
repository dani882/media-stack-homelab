
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("scripts/grab-prowlarr-release.py")
SPEC = importlib.util.spec_from_file_location("grab_prowlarr_release", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def release(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Las Supernenas (1992)",
        "indexerId": 8,
        "protocol": "torrent",
        "tvdbId": 76200,
        "seeders": 4,
        "downloadUrl": "http://prowlarr/download/opaque",
    }
    payload.update(overrides)
    return payload


class SelectReleaseTests(unittest.TestCase):
    def test_prowlarr_empty_search_is_retried_once(self) -> None:
        empty = mock.MagicMock()
        empty.__enter__.return_value.read.return_value = b"[]"
        result = mock.MagicMock()
        result.__enter__.return_value.read.return_value = json.dumps(
            [{"title": "Example Spanish Latino 1080p"}]
        ).encode("utf-8")
        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=[empty, result],
        ) as urlopen, mock.patch.object(MODULE.time, "sleep"):
            releases = MODULE.prowlarr_search(
                "http://prowlarr:9696",
                "secret",
                "Example",
                12,
                "movie",
            )
        self.assertEqual(len(releases), 1)
        self.assertEqual(urlopen.call_count, 2)

    def test_selects_exact_valid_release(self) -> None:
        selected = MODULE.select_release(
            [release(), release(title="Something Else")],
            "Las Supernenas (1992)",
            8,
            76200,
            "tv",
            1,
        )
        self.assertEqual(selected["indexerId"], 8)

    def test_rejects_unexpected_tvdb_id(self) -> None:
        with self.assertRaises(MODULE.GrabError):
            MODULE.select_release(
                [release(tvdbId=999)],
                "Las Supernenas (1992)",
                8,
                76200,
                "tv",
                1,
            )

    def test_rejects_non_exact_title(self) -> None:
        with self.assertRaises(MODULE.GrabError):
            MODULE.select_release(
                [release(title="Las Supernenas extended")],
                "Las Supernenas (1992)",
                8,
                76200,
                "tv",
                1,
            )

    def test_rewrites_loopback_download_url_for_docker(self) -> None:
        rewritten = MODULE.download_url_for_qbittorrent(
            "http://127.0.0.1:9696/api/v1/download?id=opaque"
        )
        self.assertEqual(
            rewritten,
            "http://prowlarr:9696/api/v1/download?id=opaque",
        )

    def test_fetch_torrent_payload_rejects_html_login_page(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"<html>login</html>"
        response.__enter__.return_value.headers = {"Content-Type": "text/html"}
        with mock.patch.object(MODULE.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(MODULE.GrabError, "returned HTML"):
                MODULE.fetch_torrent_payload("http://prowlarr/download/opaque")

    def test_fetch_torrent_payload_accepts_bencoded_torrent(self) -> None:
        payload = b"d8:announce20:https://tracker.teste"
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = payload
        response.__enter__.return_value.headers = {
            "Content-Type": "application/x-bittorrent"
        }
        with mock.patch.object(MODULE.urllib.request, "urlopen", return_value=response):
            self.assertEqual(
                MODULE.fetch_torrent_payload("http://prowlarr/download/opaque"),
                payload,
            )

    def test_latteam_release_falls_back_to_direct_api_delivery(self) -> None:
        payload = b"d8:announce20:https://tracker.teste"
        selected = release(
            indexer="Lat-Team",
            size=1234,
        )
        with (
            mock.patch.object(MODULE, "ensure_latteam_account_healthy"),
            mock.patch.object(
                MODULE,
                "fetch_torrent_payload",
                side_effect=MODULE.TorrentFetchError("Prowlarr unavailable"),
            ),
            mock.patch.object(
                MODULE,
                "fetch_latteam_torrent_payload",
                return_value=payload,
            ) as direct,
        ):
            self.assertEqual(
                MODULE.fetch_torrent_payload_for_release(selected),
                payload,
            )
        direct.assert_called_once_with(selected)

    def test_non_latteam_release_does_not_use_direct_api_delivery(self) -> None:
        selected = release(indexer="Milnueve")
        with (
            mock.patch.object(
                MODULE,
                "fetch_torrent_payload",
                side_effect=MODULE.TorrentFetchError("Prowlarr unavailable"),
            ),
            mock.patch.object(MODULE, "fetch_latteam_torrent_payload") as direct,
        ):
            with self.assertRaises(MODULE.TorrentFetchError):
                MODULE.fetch_torrent_payload_for_release(selected)
        direct.assert_not_called()

    def test_latteam_account_guard_rejects_ratio_below_minimum(self) -> None:
        with (
            mock.patch.object(MODULE, "read_latteam_api_key", return_value="test"),
            mock.patch.object(
                MODULE,
                "latteam_api_json",
                return_value={"ratio": "0.22"},
            ),
        ):
            with self.assertRaisesRegex(
                MODULE.TrackerAccountGuardError,
                "below 0.25",
            ):
                MODULE.ensure_latteam_account_healthy(Path("/secret"))

    def test_latteam_account_guard_accepts_minimum_ratio(self) -> None:
        with (
            mock.patch.object(MODULE, "read_latteam_api_key", return_value="test"),
            mock.patch.object(
                MODULE,
                "latteam_api_json",
                return_value={"ratio": "0.25"},
            ),
        ):
            self.assertEqual(
                MODULE.ensure_latteam_account_healthy(Path("/secret")),
                "test",
            )

    def test_latteam_title_normalization_only_removes_trailing_marker(self) -> None:
        self.assertEqual(
            MODULE.normalized_latteam_title("Example S01 SPANiSH"),
            "Example S01",
        )
        self.assertEqual(
            MODULE.normalized_latteam_title("SPANiSH Example S01"),
            "SPANiSH Example S01",
        )
    def test_selects_exact_movie_with_matching_tmdb_id(self) -> None:
        selected = MODULE.select_release(
            [
                release(
                    title="Madagascar 2005 1080p NF WEB-DL H.264-TORRENTAVENUE",
                    indexerId=9,
                    tmdbId=953,
                )
            ],
            "Madagascar 2005 1080p NF WEB-DL H.264-TORRENTAVENUE",
            9,
            953,
            "movie",
            1,
        )

        self.assertEqual(selected["tmdbId"], 953)

    def test_rejects_movie_with_unexpected_tmdb_id(self) -> None:
        with self.assertRaises(MODULE.GrabError):
            MODULE.select_release(
                [release(indexerId=9, tmdbId=999)],
                "Las Supernenas (1992)",
                9,
                953,
                "movie",
                1,
            )

    def test_private_policy_rejects_english_when_spanish_is_required(self) -> None:
        with self.assertRaises(MODULE.GrabError):
            MODULE.select_release(
                [release(title="Example.English.1080p", tvdbId=76200)],
                "Example.English.1080p",
                8,
                76200,
                "tv",
                1,
                "castilian",
                720,
            )

    def test_private_policy_accepts_latino_720p_or_better(self) -> None:
        selected = MODULE.select_release(
            [release(title="Example.Spanish.Latino.1080p", tvdbId=76200)],
            "Example.Spanish.Latino.1080p",
            8,
            76200,
            "tv",
            1,
            "castilian",
            720,
        )
        self.assertEqual(selected["tvdbId"], 76200)

    def test_private_policy_rejects_dangerous_title_before_grab(self) -> None:
        with self.assertRaises(MODULE.GrabError):
            MODULE.select_release(
                [release(title="Example.Spanish.Latino.1080p.zipx")],
                "Example.Spanish.Latino.1080p.zipx",
                8,
                76200,
                "tv",
                1,
                "castilian",
                720,
            )

    def test_private_policy_rejects_camera_source_before_grab(self) -> None:
        with self.assertRaises(MODULE.GrabError):
            MODULE.select_release(
                [release(title="Example.English.1080p.CAM.x264")],
                "Example.English.1080p.CAM.x264",
                8,
                76200,
                "tv",
                1,
                "english",
                720,
            )

    def test_guarded_public_torrent_is_inspected_before_start(self) -> None:
        class FakeQbit:
            def __init__(self) -> None:
                self.info_calls = 0
                self.posts: list[tuple[str, dict]] = []

            def get_json(self, path: str) -> list[dict]:
                if path == "/api/v2/torrents/info":
                    self.info_calls += 1
                    if self.info_calls == 1:
                        return []
                    return [
                        {
                            "hash": "abcdef1234567890",
                            "tags": "public,series-fallback,sonarr-episode-9",
                            "private": 0,
                            "save_path": "/data/Downloads/complete/tv",
                        }
                    ]
                if path.startswith("/api/v2/torrents/files?"):
                    return [{"name": "Example.S01E01.1080p.mkv"}]
                raise AssertionError(path)

            def post_form(self, path: str, form: dict) -> None:
                self.posts.append((path, form))

            def post_multipart(
                self, path: str, form: dict, filename: str, payload: bytes
            ) -> None:
                self.posts.append((path, form))

        client = FakeQbit()
        with mock.patch.object(MODULE, "fetch_torrent_payload", return_value=b"torrent"):
            MODULE.add_to_qbittorrent(
                client,
                release(title="Example.S01E01.English.1080p.WEB-DL"),
                "tv",
                "public,series-fallback,sonarr-episode-9",
                30,
                False,
                require_private=False,
                policy_label="PUBLIC FALLBACK POLICY",
            )
        self.assertIn(
            "/api/v2/torrents/start",
            [path for path, _form in client.posts],
        )
        share_limits = next(
            form
            for path, form in client.posts
            if path == "/api/v2/torrents/setShareLimits"
        )
        self.assertEqual(share_limits["shareLimitsMode"], "Default")

    def test_public_source_private_flag_requires_non_private_tracker(self) -> None:
        class FakeQbit:
            def __init__(self, tracker: str) -> None:
                self.tracker = tracker
                self.info_calls = 0
                self.posts: list[tuple[str, dict]] = []

            def get_json(self, path: str) -> list[dict]:
                if path == "/api/v2/torrents/info":
                    self.info_calls += 1
                    if self.info_calls == 1:
                        return []
                    return [
                        {
                            "hash": "abcdef1234567890",
                            "tags": "public,series-fallback,sonarr-episode-9",
                            "private": True,
                            "save_path": "/data/Downloads/complete/tv",
                        }
                    ]
                if path.startswith("/api/v2/torrents/trackers?"):
                    return [{"url": self.tracker}]
                if path.startswith("/api/v2/torrents/files?"):
                    return [{"name": "Example.S01E01.1080p.mkv"}]
                raise AssertionError(path)

            def post_form(self, path: str, form: dict) -> None:
                self.posts.append((path, form))

            def post_multipart(
                self, path: str, form: dict, filename: str, payload: bytes
            ) -> None:
                self.posts.append((path, form))

        safe = FakeQbit("udp://tracker.opentrackr.org:1337/announce")
        with mock.patch.object(MODULE, "fetch_torrent_payload", return_value=b"torrent"):
            MODULE.add_to_qbittorrent(
                safe,
                release(title="Example.S01E01.English.1080p.WEB-DL"),
                "tv",
                "public,series-fallback,sonarr-episode-9",
                30,
                False,
                require_private=False,
                allow_public_private_flag=True,
            )
        self.assertIn(
            "/api/v2/torrents/start",
            [path for path, _form in safe.posts],
        )

        private = FakeQbit("https://announce.btarg.org/announce")
        with mock.patch.object(MODULE, "fetch_torrent_payload", return_value=b"torrent"):
            with self.assertRaises(MODULE.GrabError):
                MODULE.add_to_qbittorrent(
                    private,
                    release(title="Example.S01E01.English.1080p.WEB-DL"),
                    "tv",
                    "public,series-fallback,sonarr-episode-9",
                    30,
                    False,
                    require_private=False,
                    allow_public_private_flag=True,
                )
        self.assertNotIn(
            "/api/v2/torrents/start",
            [path for path, _form in private.posts],
        )
