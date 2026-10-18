import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
UPDATER = ROOT / "stacks/duckdns/update-duckdns.sh"


class DuckDnsUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.config = self.directory / "duckdns.env"
        self.args_file = self.directory / "curl-args"
        self.stdin_file = self.directory / "curl-stdin"
        self.fake_curl = self.directory / "curl"
        self.fake_curl.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                printf '%s\\n' "$@" > "$DUCKDNS_TEST_ARGS"
                cat > "$DUCKDNS_TEST_STDIN"
                printf 'OK'
                """
            ),
            encoding="utf-8",
        )
        self.fake_curl.chmod(0o755)

    def tearDown(self):
        self.temporary.cleanup()

    def run_updater(self):
        environment = os.environ.copy()
        environment.update(
            {
                "DUCKDNS_CONFIG_FILE": str(self.config),
                "DUCKDNS_CURL_BIN": str(self.fake_curl),
                "DUCKDNS_TEST_ARGS": str(self.args_file),
                "DUCKDNS_TEST_STDIN": str(self.stdin_file),
            }
        )
        return subprocess.run(
            [str(UPDATER)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_valid_config_keeps_token_out_of_process_arguments(self):
        token = "00000000-0000-0000-0000-000000000000"
        self.config.write_text(
            f"DUCKDNS_DOMAINS=example-home\nDUCKDNS_TOKEN={token}\n",
            encoding="utf-8",
        )

        result = self.run_updater()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "DuckDNS update OK.\n")
        self.assertNotIn(token, self.args_file.read_text(encoding="utf-8"))
        self.assertIn(token, self.stdin_file.read_text(encoding="utf-8"))

    def test_invalid_domain_fails_before_contacting_duckdns(self):
        self.config.write_text(
            "DUCKDNS_DOMAINS=bad domain\n"
            "DUCKDNS_TOKEN=00000000-0000-0000-0000-000000000000\n",
            encoding="utf-8",
        )

        result = self.run_updater()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.args_file.exists())
        self.assertNotIn("00000000", result.stderr)

    def test_config_is_data_not_shell_code(self):
        marker = self.directory / "should-not-exist"
        self.config.write_text(
            "DUCKDNS_DOMAINS=example-home\n"
            f"DUCKDNS_TOKEN=$(touch {marker})\n",
            encoding="utf-8",
        )

        result = self.run_updater()

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertFalse(self.args_file.exists())


if __name__ == "__main__":
    unittest.main()
