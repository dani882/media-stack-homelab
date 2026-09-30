import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class JDownloaderStackTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_stack_is_independent_and_uses_dedicated_paths(self) -> None:
        compose = self.read("stacks/jdownloader/compose.yaml")
        self.assertIn("name: jdownloader", compose)
        self.assertIn("/volume1/docker/jdownloader/config", compose)
        self.assertIn("/volume1/Family/Downloads/jdownloader", compose)
        self.assertNotIn("network_mode: host", compose)

    def test_unneeded_remote_interfaces_are_disabled(self) -> None:
        compose = self.read("stacks/jdownloader/compose.yaml")
        self.assertIn('VNC_LISTENING_PORT: "-1"', compose)
        self.assertIn('WEB_FILE_MANAGER: "0"', compose)
        self.assertIn('WEB_TERMINAL: "0"', compose)
        self.assertNotIn(":5900", compose)

    def test_image_is_pinned_and_container_is_restartable(self) -> None:
        compose = self.read("stacks/jdownloader/compose.yaml")
        env = self.read("stacks/jdownloader/.env.example")
        self.assertIn("JDOWNLOADER_TAG:-v26.09.1", compose)
        self.assertIn("JDOWNLOADER_TAG=v26.09.1", env)
        self.assertIn("restart: unless-stopped", compose)
        self.assertIn('KEEP_APP_RUNNING: "1"', compose)

    def test_deploy_script_parses(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(ROOT / "scripts/deploy-jdownloader.sh")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
