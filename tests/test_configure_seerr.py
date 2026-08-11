from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path


MODULE_PATH = Path("scripts/configure-seerr.py")

SPEC = importlib.util.spec_from_file_location(
    "configure_seerr",
    MODULE_PATH,
)

MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeClient:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))

        key = (method, path)

        if key not in self.responses:
            raise AssertionError(
                f"Unexpected request: {method} {path}"
            )

        response = self.responses[key]

        if callable(response):
            return response(payload)

        return response


class SeerrLookupTest(unittest.TestCase):
    def test_find_profile(self):
        probe = {
            "profiles": [
                {"id": 1, "name": "Any"},
                {"id": 7, "name": "Latino 1080p"},
            ]
        }

        result = MODULE.find_profile(
            probe,
            "Latino 1080p",
        )

        self.assertEqual(result["id"], 7)

    def test_find_profile_error_lists_available(self):
        probe = {
            "profiles": [
                {"id": 1, "name": "Any"},
                {"id": 2, "name": "HD-1080p"},
            ]
        }

        with self.assertRaises(MODULE.SeerrError) as context:
            MODULE.find_profile(
                probe,
                "Latino 1080p",
            )

        message = str(context.exception)

        self.assertIn("Latino 1080p", message)
        self.assertIn("Any", message)
        self.assertIn("HD-1080p", message)

    def test_find_root_folder(self):
        probe = {
            "rootFolders": [
                {"id": 1, "path": "/media/TV Shows"},
                {"id": 2, "path": "/media/Movies"},
            ]
        }

        result = MODULE.find_root_folder(
            probe,
            "/media/Movies",
        )

        self.assertEqual(result["id"], 2)

    def test_find_root_folder_error_lists_available(self):
        probe = {
            "rootFolders": [
                {"id": 1, "path": "/media/Movies"},
            ]
        }

        with self.assertRaises(MODULE.SeerrError) as context:
            MODULE.find_root_folder(
                probe,
                "/media/Kids Movies",
            )

        message = str(context.exception)

        self.assertIn("/media/Kids Movies", message)
        self.assertIn("/media/Movies", message)


class SeerrBuilderTest(unittest.TestCase):
    def test_build_sonarr_settings(self):
        probe = {
            "profiles": [
                {
                    "id": 7,
                    "name": "Latino 1080p",
                }
            ],
            "rootFolders": [
                {
                    "id": 1,
                    "path": "/media/TV Shows",
                }
            ],
        }

        result = MODULE.build_sonarr_settings(
            "sonarr-key",
            probe,
        )

        self.assertEqual(result["name"], "Sonarr Main")
        self.assertEqual(result["hostname"], "sonarr")
        self.assertEqual(result["activeProfileId"], 7)
        self.assertEqual(
            result["activeProfileName"],
            "Latino 1080p",
        )
        self.assertEqual(
            result["activeDirectory"],
            "/media/TV Shows",
        )
        self.assertTrue(result["enableSeasonFolders"])
        self.assertTrue(result["isDefault"])
        self.assertTrue(result["syncEnabled"])
        self.assertFalse(result["preventSearch"])

    def test_build_radarr_movies_settings(self):
        probe = {
            "profiles": [
                {
                    "id": 7,
                    "name": "Latino 1080p",
                }
            ],
            "rootFolders": [
                {
                    "id": 1,
                    "path": "/media/Movies",
                }
            ],
        }

        result = MODULE.build_radarr_settings(
            "radarr-key",
            probe,
            {
                "name": "Radarr Movies",
                "directory": "/media/Movies",
                "isDefault": True,
            },
        )

        self.assertEqual(
            result["name"],
            "Radarr Movies",
        )
        self.assertEqual(
            result["activeDirectory"],
            "/media/Movies",
        )
        self.assertTrue(result["isDefault"])
        self.assertEqual(
            result["minimumAvailability"],
            "released",
        )

    def test_build_radarr_kids_settings(self):
        probe = {
            "profiles": [
                {
                    "id": 7,
                    "name": "Latino 1080p",
                }
            ],
            "rootFolders": [
                {
                    "id": 2,
                    "path": "/media/Kids Movies",
                }
            ],
        }

        result = MODULE.build_radarr_settings(
            "radarr-key",
            probe,
            {
                "name": "Radarr Kids Movies",
                "directory": "/media/Kids Movies",
                "isDefault": False,
            },
        )

        self.assertEqual(
            result["name"],
            "Radarr Kids Movies",
        )
        self.assertEqual(
            result["activeDirectory"],
            "/media/Kids Movies",
        )
        self.assertFalse(result["isDefault"])


class SeerrServiceReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.desired = {
            "name": "Sonarr Main",
            "hostname": "sonarr",
            "port": 8989,
            "apiKey": "secret",
            "useSsl": False,
            "baseUrl": "",
            "activeProfileId": 7,
            "activeProfileName": "Latino 1080p",
            "activeDirectory": "/media/TV Shows",
            "is4k": False,
            "isDefault": True,
            "syncEnabled": True,
            "preventSearch": False,
            "enableSeasonFolders": True,
        }

    def test_managed_service_matches(self):
        current = dict(self.desired)
        current["id"] = 12

        self.assertTrue(
            MODULE.managed_service_matches(
                current,
                self.desired,
            )
        )

    def test_managed_service_detects_change(self):
        current = dict(self.desired)
        current["activeDirectory"] = "/wrong"

        self.assertFalse(
            MODULE.managed_service_matches(
                current,
                self.desired,
            )
        )

    def test_reconcile_creates_missing_service(self):
        client = FakeClient(
            {
                ("GET", "/settings/sonarr"): [],
                ("POST", "/settings/sonarr"): {
                    "id": 12,
                },
            }
        )

        MODULE.reconcile_service(
            client,
            "sonarr",
            self.desired,
            False,
        )

        self.assertEqual(
            client.calls[1],
            (
                "POST",
                "/settings/sonarr",
                self.desired,
            ),
        )

    def test_reconcile_dry_run_does_not_create(self):
        client = FakeClient(
            {
                ("GET", "/settings/sonarr"): [],
            }
        )

        MODULE.reconcile_service(
            client,
            "sonarr",
            self.desired,
            True,
        )

        self.assertEqual(len(client.calls), 1)

    def test_reconcile_noop_when_correct(self):
        current = dict(self.desired)
        current["id"] = 12

        client = FakeClient(
            {
                ("GET", "/settings/sonarr"): [
                    current
                ],
            }
        )

        MODULE.reconcile_service(
            client,
            "sonarr",
            self.desired,
            False,
        )

        self.assertEqual(len(client.calls), 1)

    def test_reconcile_updates_changed_service(self):
        current = dict(self.desired)
        current["id"] = 12
        current["activeDirectory"] = "/wrong"

        client = FakeClient(
            {
                ("GET", "/settings/sonarr"): [
                    current
                ],
                ("PUT", "/settings/sonarr/12"): {
                    "id": 12,
                },
            }
        )

        MODULE.reconcile_service(
            client,
            "sonarr",
            self.desired,
            False,
        )

        self.assertEqual(
            client.calls[1],
            (
                "PUT",
                "/settings/sonarr/12",
                self.desired,
            ),
        )

    def test_reconcile_dry_run_does_not_update(self):
        current = dict(self.desired)
        current["id"] = 12
        current["activeDirectory"] = "/wrong"

        client = FakeClient(
            {
                ("GET", "/settings/sonarr"): [
                    current
                ],
            }
        )

        MODULE.reconcile_service(
            client,
            "sonarr",
            self.desired,
            True,
        )

        self.assertEqual(len(client.calls), 1)


class SeerrJellyfinLibrariesTest(unittest.TestCase):
    def setUp(self):
        self.disabled = [
            {
                "id": "kids-id",
                "name": "Kids",
                "enabled": False,
            },
            {
                "id": "movies-id",
                "name": "Movies",
                "enabled": False,
            },
            {
                "id": "series-id",
                "name": "Series",
                "enabled": False,
            },
        ]

        self.enabled = [
            {
                **item,
                "enabled": True,
            }
            for item in self.disabled
        ]

    def test_libraries_already_enabled(self):
        client = FakeClient(
            {
                (
                    "GET",
                    "/settings/jellyfin/library?sync=true",
                ): self.enabled,
            }
        )

        MODULE.configure_jellyfin_libraries(
            client,
            False,
        )

        self.assertEqual(len(client.calls), 1)

    def test_libraries_dry_run_does_not_modify(self):
        client = FakeClient(
            {
                (
                    "GET",
                    "/settings/jellyfin/library?sync=true",
                ): self.disabled,
            }
        )

        MODULE.configure_jellyfin_libraries(
            client,
            True,
        )

        self.assertEqual(len(client.calls), 1)

    def test_missing_library_raises(self):
        client = FakeClient(
            {
                (
                    "GET",
                    "/settings/jellyfin/library?sync=true",
                ): self.disabled[:2],
            }
        )

        with self.assertRaises(MODULE.SeerrError):
            MODULE.configure_jellyfin_libraries(
                client,
                False,
            )

    def test_library_enable_persists(self):
        update_path = (
            "/settings/jellyfin/library?"
            "sync=true&enable=movies-id,kids-id,series-id"
        )

        client = FakeClient(
            {
                (
                    "GET",
                    "/settings/jellyfin/library?sync=true",
                ): self.disabled,
                ("GET", update_path): self.enabled,
                (
                    "GET",
                    "/settings/jellyfin/library",
                ): self.enabled,
            }
        )

        MODULE.configure_jellyfin_libraries(
            client,
            False,
        )

        self.assertEqual(len(client.calls), 3)

    def test_library_enable_not_persisted_warns(self):
        update_path = (
            "/settings/jellyfin/library?"
            "sync=true&enable=movies-id,kids-id,series-id"
        )

        client = FakeClient(
            {
                (
                    "GET",
                    "/settings/jellyfin/library?sync=true",
                ): self.disabled,
                ("GET", update_path): self.enabled,
                (
                    "GET",
                    "/settings/jellyfin/library",
                ): self.disabled,
            }
        )

        output = io.StringIO()

        with redirect_stdout(output):
            MODULE.configure_jellyfin_libraries(
                client,
                False,
            )

        self.assertIn(
            "did not persist",
            output.getvalue(),
        )
        self.assertIn(
            "Persisted: none",
            output.getvalue(),
        )


class SeerrInitializationTest(unittest.TestCase):
    def test_already_initialized(self):
        client = FakeClient()

        MODULE.initialize_seerr(
            client,
            {"initialized": True},
            False,
        )

        self.assertEqual(client.calls, [])

    def test_initialize_dry_run(self):
        client = FakeClient()

        MODULE.initialize_seerr(
            client,
            {"initialized": False},
            True,
        )

        self.assertEqual(client.calls, [])

    def test_initialize_success(self):
        client = FakeClient(
            {
                (
                    "POST",
                    "/settings/initialize",
                ): {
                    "initialized": True,
                }
            }
        )

        MODULE.initialize_seerr(
            client,
            {"initialized": False},
            False,
        )

        self.assertEqual(len(client.calls), 1)

    def test_initialize_failure_raises(self):
        client = FakeClient(
            {
                (
                    "POST",
                    "/settings/initialize",
                ): {
                    "initialized": False,
                }
            }
        )

        with self.assertRaises(MODULE.SeerrError):
            MODULE.initialize_seerr(
                client,
                {"initialized": False},
                False,
            )


if __name__ == "__main__":
    unittest.main()
