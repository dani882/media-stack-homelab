import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_health_dashboard", ROOT / "scripts/build-health-dashboard.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DashboardTest(unittest.TestCase):
    def test_reports_missing_and_fresh_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "private-trackers.json").write_text("{}")
            components = MODULE.report_components(state, time.time())
        self.assertEqual(components[0].status, "ok")
        self.assertEqual(components[1].status, "missing")

    def test_writes_secret_free_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            state.mkdir()
            (state / "imported-audio-audit.json").write_text(
                json.dumps({"counts": {"language-mismatch": 1}})
            )
            json_path, html_path = MODULE.write_dashboard(
                root, [MODULE.Component("Timer", "ok", "active")]
            )
            payload = json.loads(json_path.read_text())
        self.assertEqual(payload["audio_counts"]["language-mismatch"], 1)
        self.assertTrue(html_path.name.endswith(".html"))

    def test_detects_stalled_active_btarg_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "btarg-series-progress.json").write_text(
                json.dumps({"status": "importando", "updatedAt": 1000})
            )
            component, stalled = MODULE.btarg_progress_component(state, 1000 + 3 * 3600)
        self.assertTrue(stalled)
        self.assertEqual(component.status, "failed")

    def test_does_not_claim_to_stop_inactive_btarg_worker(self) -> None:
        completed = mock.Mock(returncode=3)
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
            self.assertFalse(MODULE.stop_stalled_btarg(5))
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
