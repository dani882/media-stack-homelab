import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("scripts/configure-bazarr.py")
SPEC = importlib.util.spec_from_file_location("configure_bazarr", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ConfigureBazarrTest(unittest.TestCase):
    def test_read_yaml_scalar_does_not_require_yaml_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            path.write_text("auth:\n  apikey: 'secret-value'\ngeneral:\n  use_radarr: false\n")
            self.assertEqual(
                MODULE.read_yaml_scalar(path, "auth", "apikey"),
                "secret-value",
            )

    def test_merge_managed_profile_preserves_other_profiles(self):
        profiles = [
            {
                "profileId": 1,
                "name": "English",
                "cutoff": 1,
                "items": [],
                "mustContain": [],
                "mustNotContain": [],
                "originalFormat": 0,
                "tag": None,
            }
        ]
        merged, profile_id, changed = MODULE.merge_managed_profile(profiles)
        self.assertEqual(profile_id, 2)
        self.assertTrue(changed)
        self.assertEqual([item["name"] for item in merged], ["English", "Español"])

    def test_merge_managed_profile_is_idempotent(self):
        desired = MODULE.managed_profile(3)
        merged, profile_id, changed = MODULE.merge_managed_profile([desired])
        self.assertEqual(merged, [desired])
        self.assertEqual(profile_id, 3)
        self.assertFalse(changed)
        self.assertEqual(
            desired["items"][0]["audio_exclude"],
            "True",
        )
        self.assertEqual(
            desired["items"][0]["audio_only_include"],
            "False",
        )

    def test_wait_for_sync_requires_complete_inventory(self):
        class Client:
            def __init__(self):
                self.calls = 0

            def request(self, _method, path):
                self.calls += 1
                if path.startswith("movies"):
                    return {"total": 23 if self.calls > 2 else 2}
                return {"total": 29}

        with mock.patch.object(MODULE.time, "sleep"):
            movies, series = MODULE.wait_for_sync(Client(), 23, 29, attempts=3)
        self.assertEqual((movies, series), (23, 29))

    def test_settings_preserve_existing_providers_and_languages(self):
        payload = MODULE.build_settings_payload(
            {"general": {"enabled_providers": ["opensubtitlescom"]}},
            [
                {"code2": "en", "enabled": True},
                {"code2": "es", "enabled": False},
            ],
            [MODULE.managed_profile(1)],
            1,
            "sonarr-secret",
            "radarr-secret",
        )
        self.assertEqual(payload["languages-enabled"], ["en", "es"])
        self.assertIn("opensubtitlescom", payload["settings-general-enabled_providers"])
        for provider in MODULE.MANAGED_PROVIDERS:
            self.assertIn(provider, payload["settings-general-enabled_providers"])
        self.assertEqual(payload["settings-radarr-ip"], "radarr")
        self.assertEqual(payload["settings-sonarr-ip"], "sonarr")

    def test_validation_rejects_empty_integrations(self):
        problems = MODULE.validate_configuration(
            {"general": {}, "radarr": {}, "sonarr": {}},
            [],
            1,
        )
        self.assertIn("general.use_radarr is not enabled", problems)
        self.assertIn("Radarr connection is not configured", problems)
        self.assertTrue(any("providers" in problem for problem in problems))

    def test_missing_search_queues_movies_and_episodes(self):
        client = mock.Mock()
        MODULE.start_missing_subtitle_searches(client)
        self.assertEqual(
            client.request.call_args_list,
            [
                mock.call(
                    "POST",
                    "system/tasks",
                    {"taskid": "wanted_search_missing_subtitles_movies"},
                ),
                mock.call(
                    "POST",
                    "system/tasks",
                    {"taskid": "wanted_search_missing_subtitles_series"},
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
