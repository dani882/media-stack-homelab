from __future__ import annotations

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
