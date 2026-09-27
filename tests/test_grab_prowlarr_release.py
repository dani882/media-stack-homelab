
import importlib.util
import unittest
from pathlib import Path


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

        client = FakeQbit()
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

        safe = FakeQbit("udp://tracker.opentrackr.org:1337/announce")
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
