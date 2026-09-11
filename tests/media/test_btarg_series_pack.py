import unittest

from scripts.media.btarg_series_pack import (
    EpisodeFileMapping,
    PackValidationError,
    destination_filename,
    map_pack_files,
    parse_btarg_detail,
    parse_season_range,
    validate_torrent_paths,
)


class BTArgSeriesPackTest(unittest.TestCase):
    def test_parses_verified_latino_detail_and_imdb_redirect(self) -> None:
        document = """
        <p>Resolución: 1426 x 1080 (x265) 1920 x 1080 (x264)</p>
        <p>Codec Video: HEVC - AVC</p>
        <p>Codec Audio: AAC - AC-3</p>
        <p>DATOS: Idioma: Español latino e inglés sin subtítulos</p>
        <p>Fecha de Rippeo: 24-7-2021</p>
        <a href="go.php?url=https%3A%2F%2Fwww.imdb.com%2Ftitle%2Ftt0115157%2F">Link</a>
        """

        detail = parse_btarg_detail(document)

        self.assertEqual(detail.language, "latino")
        self.assertEqual(detail.imdb_id, "tt0115157")
        self.assertEqual(detail.video_codec_text, "HEVC - AVC")
        self.assertIn("x265", detail.resolution_text)

    def test_bare_dual_title_is_not_a_language_proof(self) -> None:
        detail = parse_btarg_detail("<p>Idioma: Inglés</p><p>Ripper: example</p>")
        self.assertEqual(detail.language, "unknown")

    def test_parses_multi_season_range(self) -> None:
        self.assertEqual(parse_season_range("Show S01-S04 Dual 1080p"), (1, 4))
        self.assertIsNone(parse_season_range("Show S01 1080p"))

    def test_rejects_executable_or_archive_payload(self) -> None:
        for path in ("Show/S01E01.exe", "Show/S01E01.zipx"):
            with self.subTest(path=path):
                with self.assertRaises(PackValidationError):
                    validate_torrent_paths([path])

    def test_rejects_payload_path_outside_download_root(self) -> None:
        for path in ("../Show/S01E01.mkv", "/Show/S01E01.mkv"):
            with self.subTest(path=path):
                with self.assertRaises(PackValidationError):
                    validate_torrent_paths([path])

    def test_maps_broadcast_files_to_all_segment_episodes(self) -> None:
        paths = [
            "T1/1-1 First Story.mp4",
            "T1/1-2 Fourth Story.mp4",
            "T1/1-3 Seventh Story.mkv",
            "T2/S02E01 - One & Two & Three.mkv",
            "T2/S02E02.Four.and.Five.and.Six.mkv",
        ]
        episodes = [
            {"id": number, "seasonNumber": 1, "episodeNumber": number, "title": title}
            for number, title in enumerate(
                (
                    "First Story",
                    "Second Story",
                    "Third Story",
                    "Fourth Story",
                    "Fifth Story",
                    "Sixth Story",
                    "Seventh Story",
                    "Eighth Story",
                ),
                start=1,
            )
        ] + [
            {
                "id": 100 + number,
                "seasonNumber": 2,
                "episodeNumber": number,
                "title": title,
            }
            for number, title in enumerate(
                ("One", "Two", "Three", "Four", "Five", "Six"), start=1
            )
        ]

        mappings = map_pack_files(paths, episodes)

        self.assertEqual(mappings[0].episode_numbers, (1, 2, 3))
        self.assertEqual(mappings[1].episode_numbers, (4, 5, 6))
        self.assertEqual(mappings[2].episode_numbers, (7, 8))
        self.assertEqual(mappings[3].episode_numbers, (1, 2, 3))
        self.assertEqual(mappings[4].episode_numbers, (4, 5, 6))

    def test_duplicate_first_titles_are_matched_in_pack_order(self) -> None:
        paths = ["T1/1-1 Repeat.mp4", "T1/1-2 Repeat.mp4"]
        episodes = [
            {"id": 1, "seasonNumber": 1, "episodeNumber": 1, "title": "Repeat"},
            {"id": 2, "seasonNumber": 1, "episodeNumber": 2, "title": "Middle"},
            {"id": 3, "seasonNumber": 1, "episodeNumber": 3, "title": "Repeat"},
        ]
        mappings = map_pack_files(paths, episodes)
        self.assertEqual(mappings[0].episode_numbers, (1, 2))
        self.assertEqual(mappings[1].episode_numbers, (3,))

    def test_explicit_groups_map_by_title_when_pack_files_are_out_of_order(self) -> None:
        paths = [
            "T3/S03E01 - One & Two & Three.mkv",
            "T3/S03E02 - Six & Two & Seven.mkv",
            "T3/S03E03 - Four & Five.mkv",
        ]
        episodes = [
            {
                "id": number,
                "seasonNumber": 3,
                "episodeNumber": number,
                "title": title,
            }
            for number, title in enumerate(
                ("One", "Two", "Three", "Four", "Five", "Six", "Seven"),
                start=1,
            )
        ]

        mappings = map_pack_files(paths, episodes)

        self.assertEqual(mappings[0].episode_numbers, (1, 2, 3))
        self.assertEqual(mappings[1].episode_numbers, (6, 7))
        self.assertEqual(mappings[2].episode_numbers, (4, 5))

    def test_small_tracker_title_typo_is_tolerated_in_an_unambiguous_group(self) -> None:
        paths = ["T3/S03E01 - Mind Over Chatter & Quakor Cartoon & Momdark.mkv"]
        episodes = [
            {"id": 4, "seasonNumber": 3, "episodeNumber": 4, "title": "Mind Over Chatter"},
            {"id": 5, "seasonNumber": 3, "episodeNumber": 5, "title": "A Quackor Cartoon"},
            {"id": 6, "seasonNumber": 3, "episodeNumber": 6, "title": "Momdark"},
        ]

        mappings = map_pack_files(paths, episodes)

        self.assertEqual(mappings[0].episode_numbers, (4, 5, 6))

    def test_and_word_matches_ampersand_in_an_explicit_group(self) -> None:
        paths = [
            "T3/S03E01 - Glove at First Sight & A Mom and Dad Cartoon & Smells Like Victory.mkv"
        ]
        episodes = [
            {"id": 27, "seasonNumber": 3, "episodeNumber": 27, "title": "Glove at First Sight"},
            {"id": 28, "seasonNumber": 3, "episodeNumber": 28, "title": "A Mom & Dad Cartoon"},
            {"id": 29, "seasonNumber": 3, "episodeNumber": 29, "title": "Smells Like Victory"},
        ]

        mappings = map_pack_files(paths, episodes)

        self.assertEqual(mappings[0].episode_numbers, (27, 28, 29))

    def test_duplicate_episode_coverage_is_rejected(self) -> None:
        paths = [
            "T3/S03E01 - One & Two.mkv",
            "T3/S03E02 - One & Two & Three.mkv",
        ]
        episodes = [
            {"id": number, "seasonNumber": 3, "episodeNumber": number, "title": title}
            for number, title in enumerate(("One", "Two", "Three"), start=1)
        ]

        with self.assertRaises(PackValidationError):
            map_pack_files(paths, episodes)

    def test_persistent_latino_destination_name(self) -> None:
        mapping = EpisodeFileMapping(
            path="T1/1-1 First.mp4",
            season=1,
            ordinal=1,
            episode_ids=(10, 11, 12),
            episode_numbers=(1, 2, 3),
            first_title="First",
        )
        self.assertEqual(
            destination_filename("Example", mapping, ".mkv"),
            "Example - S01E01-E03 - First [LATINO] WEBDL-1080p.mkv",
        )


if __name__ == "__main__":
    unittest.main()
