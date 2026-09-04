from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("scripts/configure-dispatcharr.py")
SPEC = importlib.util.spec_from_file_location(
    "configure_dispatcharr",
    MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DispatcharrConfigurationTest(unittest.TestCase):
    def test_generate_password_has_expected_length(self):
        password = MODULE.generate_password()
        self.assertEqual(len(password), 32)
        self.assertNotIn("\n", password)

    def test_credentials_are_created_once_and_hardened(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "secrets" / "dispatcharr-admin.txt"
            first = MODULE.read_or_create_credentials(
                path,
                "admin",
                "http://nas:9191",
            )
            second = MODULE.read_or_create_credentials(
                path,
                "admin",
                "http://nas:9191",
            )

            self.assertEqual(first, second)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn("username=admin", path.read_text(encoding="utf-8"))

    @mock.patch.object(MODULE, "run_manage_code", return_value="ok")
    def test_playlist_configuration_embedded_code_compiles(self, run_manage_code):
        MODULE.configure_playlist(
            "dispatcharr",
            "Republica Dominicana (combinada)",
            "http://dominican-iptv:8080/playlist.m3u",
        )
        embedded_code = run_manage_code.call_args.args[1]
        compile(embedded_code, "<dispatcharr-config>", "exec")


if __name__ == "__main__":
    unittest.main()
