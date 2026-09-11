import importlib.util
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/audit-language-repairs.py"
SPEC = importlib.util.spec_from_file_location("audit_language_repairs", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class LanguageRepairAuditTest(unittest.TestCase):
    @mock.patch.object(MODULE, "run_helper")
    def test_report_is_always_dry_run_and_combines_both_apps(self, helper: mock.Mock) -> None:
        helper.side_effect = [(0, "Sonarr report"), (0, "Radarr report")]
        report, failures = MODULE.build_report(Path("/stack"))
        self.assertEqual(failures, 0)
        self.assertIn("Sonarr report", report)
        self.assertIn("Radarr report", report)
        for call in helper.call_args_list:
            self.assertIn("--dry-run", call.args[0])


if __name__ == "__main__":
    unittest.main()
