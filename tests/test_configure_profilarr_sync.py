from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/configure-profilarr-sync.py")

SPEC = importlib.util.spec_from_file_location(
    "configure_profilarr_sync",
    MODULE_PATH,
)

MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ProfilarrSyncHelpersTest(unittest.TestCase):
    def test_load_credentials_reads_username_and_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_file = Path(temp_dir) / "profilarr-admin.txt"
            secret_file.write_text(
                "username=admin\npassword=secret\n",
                encoding="utf-8",
            )

            username, password = MODULE.load_credentials(
                secret_file
            )

        self.assertEqual(username, "admin")
        self.assertEqual(password, "secret")

    def test_validate_config_rejects_empty_instances(self):
        with self.assertRaises(
            MODULE.ProfilarrSyncError
        ):
            MODULE.validate_config(
                {
                    "database": "Dictionarry",
                    "instances": [],
                }
            )

    def test_validate_config_normalizes_profiles(self):
        database, instances = MODULE.validate_config(
            {
                "database": " Dictionarry ",
                "instances": [
                    {
                        "name": " Sonarr Main ",
                        "qualityProfiles": [
                            " 1080p Balanced ",
                        ],
                    }
                ],
            }
        )

        self.assertEqual(database, "Dictionarry")
        self.assertEqual(
            instances,
            [
                {
                    "name": "Sonarr Main",
                    "qualityProfiles": [
                        "1080p Balanced"
                    ],
                }
            ],
        )

    def test_load_config_reads_json_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "pilot-sync.json"
            expected = {
                "database": "Dictionarry",
                "instances": [
                    {
                        "name": "Radarr Movies",
                        "qualityProfiles": [
                            "1080p Balanced"
                        ],
                    }
                ],
            }
            config_path.write_text(
                json.dumps(expected),
                encoding="utf-8",
            )

            result = MODULE.load_config(config_path)

        self.assertEqual(result, expected)

    def test_get_database_id_matches_by_name(self):
        opener = object()

        def fake_get_json(_opener, _url):
            self.assertIs(_opener, opener)
            return [
                {"id": 7, "name": "Other"},
                {"id": 9, "name": "Dictionarry"},
            ]

        original = MODULE.get_json
        MODULE.get_json = fake_get_json
        try:
            result = MODULE.get_database_id(
                opener,
                "http://127.0.0.1:6868",
                "Dictionarry",
            )
        finally:
            MODULE.get_json = original

        self.assertEqual(result, 9)

    def test_wait_for_quality_sync_returns_terminal_status(self):
        opener = object()
        responses = iter(
            [
                {"status": "pending", "count": 1},
                {"status": "in_progress", "count": 1},
                {"status": "success", "count": 1},
            ]
        )

        def fake_get_quality_sync_status(
            _opener,
            _base_url,
            _instance_id,
        ):
            self.assertIs(_opener, opener)
            return next(responses)

        original_status = MODULE.get_quality_sync_status
        original_sleep = MODULE.time.sleep
        MODULE.get_quality_sync_status = (
            fake_get_quality_sync_status
        )
        MODULE.time.sleep = lambda _seconds: None
        try:
            result = MODULE.wait_for_quality_sync(
                opener,
                "http://127.0.0.1:6868",
                1,
                30,
            )
        finally:
            MODULE.get_quality_sync_status = original_status
            MODULE.time.sleep = original_sleep

        self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()
