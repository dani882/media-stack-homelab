from __future__ import annotations

import unittest

from scripts.media.common.latino import (
    approval_sort_key,
    best_latino_release,
    has_latino_format,
    installed_is_latino,
    is_latino_release,
    score_seed_sort_key,
)


class LatinoHelpersTest(unittest.TestCase):
    def test_detects_latino_custom_format(self) -> None:
        payload = {
            "customFormats": [
                {
                    "name": (
                        "[Latino] Spanish Latino + English"
                    )
                }
            ]
        }

        self.assertTrue(
            has_latino_format(payload)
        )
        self.assertTrue(
            installed_is_latino(payload)
        )
        self.assertTrue(
            is_latino_release(payload)
        )

    def test_detects_latino_language(self) -> None:
        release = {
            "languages": [
                {"name": "Spanish (Latino)"}
            ]
        }

        self.assertTrue(
            is_latino_release(release)
        )

    def test_detects_latino_title_marker(self) -> None:
        release = {
            "title": (
                "Example.1080p.WEB-DL."
                "LATINO.ENG"
            )
        }

        self.assertTrue(
            is_latino_release(release)
        )

    def test_does_not_classify_english_as_latino(self) -> None:
        release = {
            "title": "Example.1080p.WEB-DL.ENGLISH",
            "languages": [
                {"name": "English"}
            ],
            "customFormats": [],
        }

        self.assertFalse(
            is_latino_release(release)
        )
        self.assertFalse(
            installed_is_latino(release)
        )

    def test_score_seed_sort_key(self) -> None:
        lower = {
            "customFormatScore": 7000,
            "seeders": 10,
        }
        higher = {
            "customFormatScore": 7000,
            "seeders": 20,
        }

        self.assertGreater(
            score_seed_sort_key(higher),
            score_seed_sort_key(lower),
        )

    def test_approval_sort_key_prefers_usable_release(
        self,
    ) -> None:
        approved = {
            "approved": True,
            "rejected": False,
            "customFormatScore": 7000,
            "seeders": 10,
        }
        rejected = {
            "approved": True,
            "rejected": True,
            "customFormatScore": 7000,
            "seeders": 100,
        }

        self.assertGreater(
            approval_sort_key(approved),
            approval_sort_key(rejected),
        )

    def test_best_latino_release(self) -> None:
        english = {
            "title": "Example.ENGLISH",
            "customFormatScore": 9000,
            "seeders": 1000,
        }
        rejected = {
            "title": "Example.LATINO",
            "approved": True,
            "rejected": True,
            "customFormatScore": 7000,
            "seeders": 100,
        }
        usable = {
            "title": "Example.LATINO",
            "approved": True,
            "rejected": False,
            "customFormatScore": 7000,
            "seeders": 10,
        }

        self.assertIs(
            best_latino_release(
                [english, rejected, usable]
            ),
            usable,
        )


if __name__ == "__main__":
    unittest.main()
