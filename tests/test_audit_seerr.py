from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/audit-seerr.py")

SPEC = importlib.util.spec_from_file_location(
    "audit_seerr",
    MODULE_PATH,
)

MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AuditSeerrTest(unittest.TestCase):
    def test_read_json_loads_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                json.dumps({"main": {"apiKey": "abc"}}),
                encoding="utf-8",
            )

            loaded = MODULE.read_json(path)

        self.assertEqual(loaded["main"]["apiKey"], "abc")

    def test_validate_public_rejects_uninitialized(self) -> None:
        class FakeClient:
            def get(self, _path: str):
                return {
                    "initialized": False,
                    "mediaServerType": 2,
                }

        with self.assertRaises(MODULE.SeerrAuditError):
            MODULE.validate_public(FakeClient())


if __name__ == "__main__":
    unittest.main()
