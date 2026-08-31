import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/configure-prowlarr.py")

SPEC = importlib.util.spec_from_file_location(
    "configure_prowlarr",
    MODULE_PATH,
)

MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PrivateIndexerLoaderTest(unittest.TestCase):
    def test_missing_secret_returns_empty(self) -> None:
        result = MODULE.load_private_indexers(
            Path("/tmp/does-not-exist-prowlarr-secret.json")
        )

        self.assertEqual(result, [])

    def test_empty_secret_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-indexers.json"
            path.write_text("{}\n")

            result = MODULE.load_private_indexers(path)

        self.assertEqual(result, [])

    def test_loads_lat_team_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-indexers.json"

            path.write_text(
                json.dumps(
                    {
                        "lat-team-api": {
                            "apikey": "test-only",
                        }
                    }
                )
            )

            result = MODULE.load_private_indexers(path)

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["definition"],
            "lat-team-api",
        )
        self.assertEqual(
            result[0]["priority"],
            5,
        )
        self.assertEqual(
            result[0]["minimum_seeders"],
            5,
        )
        self.assertEqual(
            result[0]["fields"]["apikey"],
            "test-only",
        )

    def test_loads_btarg_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-indexers.json"

            path.write_text(
                json.dumps(
                    {
                        "btarg": {
                            "username": "test-user",
                            "password": "test-password",
                        }
                    }
                )
            )

            result = MODULE.load_private_indexers(path)

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["definition"],
            "btarg",
        )
        self.assertEqual(
            result[0]["fields"]["username"],
            "test-user",
        )
        self.assertEqual(
            result[0]["fields"]["password"],
            "test-password",
        )

    def test_loads_retrotoon_with_protected_seed_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-indexers.json"

            path.write_text(
                json.dumps(
                    {
                        "retrotoon-torznab": {
                            "apiKey": "test-only",
                        }
                    }
                )
            )

            result = MODULE.load_private_indexers(path)

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["definition"],
            "Torznab",
        )
        self.assertEqual(
            result[0]["instance_name"],
            "RetroToon World",
        )
        self.assertEqual(
            result[0]["fields"]["apiPath"],
            "/torznab.php",
        )
        self.assertEqual(
            result[0]["fields"]["torrentBaseSettings.seedTime"],
            4320,
        )

    def test_generic_torznab_identity_uses_instance_name(self) -> None:
        payload = {
            "definitionName": "Torznab",
            "name": "RetroToon World",
        }

        self.assertEqual(
            MODULE.indexer_identity(payload),
            "retrotoon world",
        )

    def test_configures_retrotoon_from_generic_torznab_schema(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.requests: list[tuple[str, str, dict]] = []

            def request(
                self,
                method: str,
                path: str,
                payload: dict | None = None,
            ) -> dict:
                self.requests.append(
                    (method, path, payload or {})
                )
                return {}

            def test_indexer(self, payload: dict) -> None:
                self.requests.append(
                    ("TEST", "/indexer/test", payload)
                )

        schema = {
            "name": "Generic Torznab",
            "fields": [
                {"name": "baseUrl"},
                {"name": "apiPath"},
                {"name": "apiKey"},
                {
                    "name": (
                        "torrentBaseSettings.appMinimumSeeders"
                    )
                },
                {"name": "torrentBaseSettings.seedTime"},
                {
                    "name": (
                        "torrentBaseSettings.packSeedTime"
                    )
                },
            ],
        }
        desired = {
            **MODULE.PRIVATE_INDEXERS["retrotoon-torznab"],
            "fields": {
                **MODULE.PRIVATE_INDEXERS[
                    "retrotoon-torznab"
                ]["fields"],
                "apiKey": "test-only",
            },
        }
        client = FakeClient()

        MODULE.configure_indexer(
            client,
            {"torznab": schema},
            {},
            desired,
            dry_run=True,
        )

        method, path, payload = client.requests[-1]
        self.assertEqual((method, path), ("TEST", "/indexer/test"))
        self.assertEqual(payload["name"], "RetroToon World")
        self.assertEqual(
            MODULE.field_map(payload)["apiPath"]["value"],
            "/torznab.php",
        )

    def test_masked_api_key_does_not_cause_drift(self) -> None:
        desired = {
            "enabled": True,
            "priority": 8,
            "minimum_seeders": 1,
            "fields": {"apiKey": "test-only"},
        }
        payload = {
            "enable": True,
            "priority": 8,
            "fields": [
                {
                    "name": (
                        "torrentBaseSettings.appMinimumSeeders"
                    ),
                    "value": 1,
                },
                {"name": "apiKey", "value": "********"},
            ],
        }

        self.assertTrue(
            MODULE.managed_indexer_matches(payload, desired)
        )

    def test_unknown_definition_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-indexers.json"

            path.write_text(
                json.dumps(
                    {
                        "unknown-tracker": {
                            "apikey": "test-only",
                        }
                    }
                )
            )

            result = MODULE.load_private_indexers(path)

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
