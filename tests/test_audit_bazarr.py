from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/audit-bazarr.py")

SPEC = importlib.util.spec_from_file_location(
    "audit_bazarr",
    MODULE_PATH,
)

MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BazarrAuditTest(unittest.TestCase):
    def test_grep_references_finds_matching_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample = root / "config.ini"
            sample.write_text(
                "root=/data/Media\nlegacy=/media\n",
                encoding="utf-8",
            )

            matches = MODULE.grep_references(
                root,
                "/media",
            )

        self.assertEqual(len(matches), 1)
        self.assertIn("legacy=/media", matches[0])

    def test_grep_references_returns_empty_for_missing_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "missing"
            matches = MODULE.grep_references(
                root,
                "/downloads",
            )

        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
