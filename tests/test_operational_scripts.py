import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OperationalScriptsTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_critical_shell_scripts_parse(self) -> None:
        scripts = [
            ROOT / "scripts/deploy.sh",
            ROOT / "scripts/backup.sh",
            ROOT / "scripts/restore.sh",
            ROOT / "scripts/monitor-media-stack.sh",
            ROOT / "scripts/deploy-reliability.sh",
        ]
        result = subprocess.run(
            ["bash", "-n", *map(str, scripts)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deploy_reapplies_language_policy_after_recyclarr(self) -> None:
        script = self.read("scripts/deploy.sh")
        sonarr_sync = script.index("sync sonarr --instance series")
        radarr_sync = script.index("sync radarr --instance movies")
        reapply = script.index("Reapplying language and safety scores")
        post_policy = script.index("Applying post-Recyclarr Radarr Latino policy")
        self.assertLess(sonarr_sync, radarr_sync)
        self.assertLess(radarr_sync, reapply)
        self.assertLess(reapply, post_policy)

    def test_deploy_docker_steps_have_deadlines_and_preflight(self) -> None:
        script = self.read("scripts/deploy.sh")
        self.assertIn("check-nas-preflight.py", script)
        self.assertIn("sudo timeout -k 30s", script)
        for operation in ("pull --ignore-buildable", "build dominican-iptv", "up -d", "restart prowlarr"):
            self.assertIn(operation, script)

    def test_backup_stops_only_previously_running_services(self) -> None:
        script = self.read("scripts/backup.sh")
        self.assertIn('docker compose stop "${RUNNING_SERVICES[@]}"', script)
        self.assertIn('docker compose start "${RUNNING_SERVICES[@]}"', script)

    def test_restore_has_automatic_rollback_and_checksum_validation(self) -> None:
        script = self.read("scripts/restore.sh")
        self.assertIn("rollback_restore", script)
        self.assertIn("sha256sum", script)
        self.assertIn("trap on_exit EXIT INT TERM", script)

    def test_restore_requires_a_pre_restore_backup(self) -> None:
        script = self.read("scripts/restore.sh")
        self.assertIn("Creating pre-restore safety backup", script)
        self.assertIn('BACKUP_SCRIPT="${STACK_DIR}/backup.sh"', script)


if __name__ == "__main__":
    unittest.main()
