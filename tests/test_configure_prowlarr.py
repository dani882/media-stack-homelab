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
