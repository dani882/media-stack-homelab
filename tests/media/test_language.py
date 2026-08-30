from __future__ import annotations

import unittest

from scripts.media.common.language import (
    LanguageRank,
    best_language_upgrade,
    language_rank,
    release_is_safe_language_upgrade,
)


class LanguageUpgradeTest(unittest.TestCase):
    def test_language_ranking(self) -> None:
        english = {
            "languages": [{"name": "English"}],
        }
        castilian = {
            "languages": [{"name": "Spanish"}],
        }
        latino = {
            "languages": [{"name": "Spanish (Latino)"}],
        }

        self.assertEqual(
            language_rank(english),
            LanguageRank.ENGLISH,
        )
        self.assertEqual(
            language_rank(castilian),
            LanguageRank.CASTILIAN,
        )
        self.assertEqual(
            language_rank(latino),
            LanguageRank.LATINO,
        )

    def test_title_markers_are_token_aware(self) -> None:
        self.assertEqual(
            language_rank({"title": "Example.SPACEMAN.1080p"}),
            LanguageRank.UNKNOWN,
        )
        self.assertEqual(
            language_rank({"title": "Example.ESPN.1080p"}),
            LanguageRank.UNKNOWN,
        )
        self.assertEqual(
            language_rank({"title": "Example.SPA.1080p"}),
            LanguageRank.CASTILIAN,
        )

    def test_explicit_latino_title_beats_spanish_metadata(self) -> None:
        release = {
            "title": "Example.SPANISH.LATINO.1080p",
            "languages": [{"name": "Spanish"}],
        }

        self.assertEqual(
            language_rank(release),
            LanguageRank.LATINO,
        )

    def test_dual_spanish_english_title_is_latino(self) -> None:
        release = {
            "title": "Example.DUAL.SPA.ENG.1080p",
        }

        self.assertEqual(
            language_rank(release),
            LanguageRank.LATINO,
        )

    def test_english_does_not_upgrade_unknown(self) -> None:
        candidate = {
            "languages": [{"name": "English"}],
            "downloadAllowed": True,
            "rejected": False,
        }

        self.assertFalse(
            release_is_safe_language_upgrade(
                None,
                candidate,
            )
        )

    def test_castilian_upgrades_unknown(self) -> None:
        candidate = {
            "languages": [{"name": "Spanish"}],
            "downloadAllowed": True,
            "rejected": False,
        }

        self.assertTrue(
            release_is_safe_language_upgrade(
                None,
                candidate,
            )
        )

    def test_castilian_upgrades_english(self) -> None:
        installed = {
            "languages": [{"name": "English"}],
        }

        candidate = {
            "languages": [{"name": "Spanish"}],
            "downloadAllowed": True,
            "rejected": False,
        }

        self.assertTrue(
            release_is_safe_language_upgrade(
                installed,
                candidate,
            )
        )

    def test_latino_upgrades_castilian(self) -> None:
        installed = {
            "languages": [{"name": "Spanish"}],
        }

        candidate = {
            "languages": [{"name": "Spanish (Latino)"}],
            "downloadAllowed": True,
            "rejected": False,
        }

        self.assertTrue(
            release_is_safe_language_upgrade(
                installed,
                candidate,
            )
        )

    def test_castilian_does_not_replace_latino(self) -> None:
        installed = {
            "languages": [{"name": "Spanish (Latino)"}],
        }

        candidate = {
            "languages": [{"name": "Spanish"}],
            "downloadAllowed": True,
            "rejected": False,
        }

        self.assertFalse(
            release_is_safe_language_upgrade(
                installed,
                candidate,
            )
        )

    def test_quality_rejection_can_be_overridden(self) -> None:
        installed = {
            "languages": [{"name": "English"}],
        }

        candidate = {
            "languages": [{"name": "Spanish"}],
            "downloadAllowed": True,
            "rejected": True,
            "rejections": [
                (
                    "Existing file on disk is of equal or "
                    "higher preference: WEBDL-1080p v1"
                ),
            ],
        }

        self.assertTrue(
            release_is_safe_language_upgrade(
                installed,
                candidate,
            )
        )

    def test_other_rejection_is_not_overridden(self) -> None:
        installed = {
            "languages": [{"name": "English"}],
        }

        candidate = {
            "languages": [{"name": "Spanish"}],
            "downloadAllowed": True,
            "rejected": True,
            "rejections": [
                "Release is blocklisted",
            ],
        }

        self.assertFalse(
            release_is_safe_language_upgrade(
                installed,
                candidate,
            )
        )

    def test_language_rank_beats_score(self) -> None:
        installed = {
            "languages": [{"name": "English"}],
        }

        castilian = {
            "title": "Example Spanish",
            "languages": [{"name": "Spanish"}],
            "customFormatScore": 5000,
            "seeders": 100,
            "downloadAllowed": True,
            "rejected": False,
        }

        latino = {
            "title": "Example Latino",
            "languages": [{"name": "Spanish (Latino)"}],
            "customFormatScore": 100,
            "seeders": 1,
            "downloadAllowed": True,
            "rejected": False,
        }

        self.assertIs(
            best_language_upgrade(
                installed,
                [castilian, latino],
            ),
            latino,
        )


if __name__ == "__main__":
    unittest.main()
