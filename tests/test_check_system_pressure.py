import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_system_pressure", ROOT / "scripts/check-system-pressure.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SystemPressureTest(unittest.TestCase):
    def test_healthy_snapshot_allows_background_work(self) -> None:
        current = MODULE.PressureSnapshot(0.5, 2.0, 1.0, 0.0, 5.0)
        self.assertEqual(MODULE.defer_reasons(current), [])

    def test_incident_snapshot_defers_background_work(self) -> None:
        current = MODULE.PressureSnapshot(9.0, 89.0, 90.0, 93.0, 60.0)
        reasons = MODULE.defer_reasons(current)
        self.assertEqual(len(reasons), 4)
        self.assertTrue(any("disk" in reason for reason in reasons))
        self.assertTrue(any("memory" in reason for reason in reasons))

    def test_writes_secret_free_actionable_state(self) -> None:
        current = MODULE.PressureSnapshot(0.5, 40.0, 1.0, 0.0, 5.0)
        reasons = MODULE.defer_reasons(current)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "system-pressure.json"
            MODULE.write_state(path, current, reasons)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertFalse(payload["deployment_allowed"])
        self.assertEqual(payload["status"], "defer")
        self.assertIn("Do not deploy", payload["recommended_action"])


if __name__ == "__main__":
    unittest.main()
