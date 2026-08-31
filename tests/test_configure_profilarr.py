from __future__ import annotations

import importlib.util
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("scripts/configure-profilarr.py")

SPEC = importlib.util.spec_from_file_location(
    "configure_profilarr",
    MODULE_PATH,
)

MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(
        self,
        code: int,
        body: str = "",
    ) -> None:
        self.code = code
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self) -> int:
        return self.code

    def read(self) -> bytes:
        return self.body.encode("utf-8")


class ProfilarrHelpersTest(unittest.TestCase):
    def test_detect_public_url_uses_first_ip(self):
        completed = mock.Mock()
        completed.stdout = "10.0.0.123 172.16.0.5\n"

        with mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=completed,
        ):
            result = MODULE.detect_public_url(
                "http://127.0.0.1:6868"
            )

        self.assertEqual(
            result,
            "http://10.0.0.123:6868",
        )

    def test_setup_required_true_on_200(self):
        opener = mock.Mock()
        opener.open.return_value = FakeResponse(200)

        with mock.patch.object(
            MODULE.urllib.request,
            "build_opener",
            return_value=opener,
        ):
            self.assertTrue(
                MODULE.setup_required(
                    "http://127.0.0.1:6868"
                )
            )

    def test_setup_required_false_on_303(self):
        opener = mock.Mock()
        opener.open.side_effect = (
            MODULE.urllib.error.HTTPError(
                "http://127.0.0.1:6868/auth/setup",
                303,
                "See Other",
                {},
                BytesIO(b""),
            )
        )

        with mock.patch.object(
            MODULE.urllib.request,
            "build_opener",
            return_value=opener,
        ):
            self.assertFalse(
                MODULE.setup_required(
                    "http://127.0.0.1:6868"
                )
            )

    def test_hash_password_uses_bcrypt_output(self):
        completed = mock.Mock()
        completed.stdout = (
            "download noise\n"
            "$2b$12$abcdefghijklmnopqrstuuuuuuuuuuuuuuuuuuuuu\n"
        )

        with mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=completed,
        ):
            result = MODULE.hash_password_with_container(
                "profilarr",
                "secret",
            )

        self.assertTrue(result.startswith("$2b$12$"))

    def test_write_credentials_file_sets_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_file = (
                Path(temp_dir) / "profilarr-admin.txt"
            )

            MODULE.write_credentials_file(
                secret_file,
                "admin",
                "password",
                "http://10.0.0.123:6868",
            )

            self.assertIn(
                "username=admin",
                secret_file.read_text(
                    encoding="utf-8"
                ),
            )
            self.assertEqual(
                secret_file.stat().st_mode
                & 0o777,
                0o600,
            )


if __name__ == "__main__":
    unittest.main()
