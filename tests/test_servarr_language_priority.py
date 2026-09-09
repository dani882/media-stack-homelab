import importlib
import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path("scripts").resolve()
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

CUSTOM_FORMATS = importlib.import_module("servarr_config.custom_formats")


def quality(quality_id: int, name: str) -> dict:
    return {
        "quality": {"id": quality_id, "name": name},
        "items": [],
        "allowed": True,
    }


class LanguageFirstQualityGroupTests(unittest.TestCase):
    def test_language_scores_do_not_override_hard_rejections(self) -> None:
        latino_total = (
            CUSTOM_FORMATS.SCORES["LATINO"]
            + CUSTOM_FORMATS.SCORES["[Language Guard] Spanish audio"]
        )
        castellano_total = (
            CUSTOM_FORMATS.SCORES["CASTELLANO"]
            + CUSTOM_FORMATS.SCORES["[Language Guard] Spanish audio"]
        )
        self.assertLess(latino_total, 10000)
        self.assertLess(castellano_total, latino_total)
        self.assertEqual(
            CUSTOM_FORMATS.SCORES["[Spanish] Castellano"],
            0,
        )

    def profile(self) -> dict:
        return {
            "cutoff": 7,
            "items": [
                quality(4, "HDTV-720p"),
                quality(6, "Bluray-720p"),
                {
                    "id": 1001,
                    "name": "WEB 720p",
                    "allowed": True,
                    "items": [
                        quality(5, "WEBDL-720p"),
                        quality(14, "WEBRip-720p"),
                    ],
                },
                quality(9, "HDTV-1080p"),
                quality(7, "Bluray-1080p"),
                {
                    "id": 1002,
                    "name": "WEB 1080p",
                    "allowed": True,
                    "items": [
                        quality(3, "WEBDL-1080p"),
                        quality(15, "WEBRip-1080p"),
                    ],
                },
            ]
        }

    def test_groups_all_accepted_hd_qualities(self) -> None:
        profile = self.profile()

        changed = CUSTOM_FORMATS.configure_language_first_quality_group(profile)

        self.assertTrue(changed)
        self.assertEqual(len(profile["items"]), 1)
        group = profile["items"][0]
        self.assertEqual(group["id"], 1002)
        self.assertEqual(
            group["name"],
            "HD 720p-1080p (Language First)",
        )
        self.assertEqual(
            [item["quality"]["name"] for item in group["items"]],
            list(CUSTOM_FORMATS.LANGUAGE_FIRST_QUALITY_ORDER),
        )
        self.assertEqual(profile["cutoff"], 1002)

    def test_reconciliation_is_idempotent(self) -> None:
        profile = self.profile()
        CUSTOM_FORMATS.configure_language_first_quality_group(profile)

        changed = CUSTOM_FORMATS.configure_language_first_quality_group(profile)

        self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
