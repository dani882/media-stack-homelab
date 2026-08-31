from __future__ import annotations

import importlib.util
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("scripts/check-media-live.py")

SPEC = importlib.util.spec_from_file_location(
    "check_media_live",
    MODULE_PATH,
)

MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, code: int) -> None:
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def getcode(self) -> int:
        return self.code

    def read(self) -> bytes:
        return b""


class CheckMediaLiveTest(unittest.TestCase):
    def test_check_http_target_accepts_redirect(self) -> None:
        target = MODULE.HttpTarget(
            "Profilarr",
            "http://127.0.0.1:6868/auth/login",
        )

        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=MODULE.urllib.error.HTTPError(
                target.url,
                303,
                "See Other",
                {},
                BytesIO(b""),
            ),
        ):
            ok, message = MODULE.check_http_target(
                target,
                5,
            )

        self.assertTrue(ok)
        self.assertEqual(message, "HTTP 303")

    def test_check_http_target_marks_required_unreachable(self) -> None:
        target = MODULE.HttpTarget(
            "Seerr",
            "http://127.0.0.1:5055/api/v1/status",
            expected_statuses=(200,),
        )

        with mock.patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=MODULE.urllib.error.URLError(
                "connection refused"
            ),
        ):
            ok, message = MODULE.check_http_target(
                target,
                5,
            )

        self.assertFalse(ok)
        self.assertIn("unreachable", message)

    def test_service_map_includes_optional_profilarr_only_when_running(
        self,
    ) -> None:
        without = MODULE.service_map(False)
        with_profile = MODULE.service_map(True)

        self.assertFalse(
            any(
                target.name == "Profilarr"
                for target in without
            )
        )
        self.assertTrue(
            any(
                target.name == "Profilarr"
                for target in with_profile
            )
        )

    def test_run_compose_ps_accepts_ndjson_lines(self) -> None:
        completed = mock.Mock()
        completed.stdout = (
            '{"Service":"sonarr","State":"running"}\n'
            '{"Service":"radarr","State":"running"}\n'
        )

        with mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=completed,
        ):
            entries = MODULE.run_compose_ps(
                Path(".")
            )

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["Service"], "sonarr")


if __name__ == "__main__":
    unittest.main()
