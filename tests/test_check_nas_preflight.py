import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_nas_preflight", ROOT / "scripts/check-nas-preflight.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PreflightTest(unittest.TestCase):
    def test_healthy_snapshot_has_no_problems(self) -> None:
        current = MODULE.PreflightSnapshot(0.5, 50.0, 500.0, 60.0)
        self.assertEqual(MODULE.evaluate_snapshot(current, 10, 95, 8), [])

    def test_busy_or_full_snapshot_is_rejected(self) -> None:
        current = MODULE.PreflightSnapshot(9.0, 5.0, 4.0, 97.0)
        problems = MODULE.evaluate_snapshot(current, 10, 95, 8)
        self.assertEqual(len(problems), 4)
        self.assertTrue(any("load" in item for item in problems))


if __name__ == "__main__":
    unittest.main()
