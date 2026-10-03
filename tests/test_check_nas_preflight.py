import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


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
        current = MODULE.PreflightSnapshot(0.5, 2.0, 50.0, 500.0, 60.0)
        self.assertEqual(
            MODULE.evaluate_snapshot(current, 10, 95, 8, 50),
            [],
        )

    def test_busy_or_full_snapshot_is_rejected(self) -> None:
        current = MODULE.PreflightSnapshot(9.0, 75.0, 5.0, 4.0, 97.0)
        problems = MODULE.evaluate_snapshot(current, 10, 95, 8, 50)
        self.assertEqual(len(problems), 5)
        self.assertTrue(any("load" in item for item in problems))
        self.assertTrue(any("I/O wait" in item for item in problems))

    def test_io_wait_uses_cpu_counter_deltas(self) -> None:
        with (
            patch.object(
                MODULE,
                "cpu_counters",
                side_effect=[(1_000, 100), (2_000, 700)],
            ),
            patch.object(MODULE.time, "sleep") as sleep,
        ):
            result = MODULE.io_wait_percent(2.0)

        self.assertEqual(result, 60.0)
        sleep.assert_called_once_with(2.0)

    def test_io_wait_rejects_invalid_sample_duration(self) -> None:
        with self.assertRaises(MODULE.PreflightError):
            MODULE.io_wait_percent(0)


if __name__ == "__main__":
    unittest.main()
