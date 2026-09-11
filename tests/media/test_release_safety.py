import unittest

from common.release_safety import (
    dangerous_release_title,
    dangerous_torrent_paths,
    english_only_torrent_paths,
    unacceptable_source_title,
)


class ReleaseSafetyTests(unittest.TestCase):
    def test_detects_dangerous_title_suffixes(self) -> None:
        for title in (
            "Reacher S04E07 1080p FLUX zipx",
            "Movie.2026.1080p.exe",
            "Movie 2026 installer MSI",
        ):
            with self.subTest(title=title):
                self.assertTrue(dangerous_release_title(title))

    def test_allows_normal_media_title(self) -> None:
        self.assertFalse(
            dangerous_release_title("Reacher S04E07 1080p WEB-DL H.264-FLUX")
        )

    def test_rejects_camera_and_telesync_sources(self) -> None:
        for title in (
            "Movie.2026.1080p.CAM.H264",
            "Movie 2026 HDTS 1080p",
            "Movie.2026.TELESYNC.x264",
        ):
            with self.subTest(title=title):
                self.assertTrue(unacceptable_source_title(title))

    def test_inspects_actual_torrent_members(self) -> None:
        self.assertEqual(
            dangerous_torrent_paths(
                ["Show/S01E01.mkv", "Show/readme.txt", "Show/codec.EXE"]
            ),
            ["Show/codec.EXE"],
        )

    def test_detects_known_english_only_payload_names(self) -> None:
        self.assertEqual(
            english_only_torrent_paths(
                [
                    "Movie/Movie.2026.1080p.WEBRip-[YTS.GG - YTS.BZ].mp4",
                    "Movie/Movie.2026.Castellano.1080p.mkv",
                ]
            ),
            ["Movie/Movie.2026.1080p.WEBRip-[YTS.GG - YTS.BZ].mp4"],
        )
