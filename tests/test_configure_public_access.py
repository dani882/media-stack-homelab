import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path("scripts/configure-public-access.py")
SPEC = importlib.util.spec_from_file_location("configure_public_access", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        key = (method, path)
        if key not in self.responses:
            raise AssertionError(f"Unexpected request: {key}")
        response = self.responses[key]
        return response(payload) if callable(response) else response


class PublicAccessEnvironmentTests(unittest.TestCase):
    def test_prepare_adds_domain_without_changing_other_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stack = root / "stack"
            stack.mkdir()
            media_env = stack / ".env"
            media_env.write_text("SECRET=value\nTZ=America/Toronto\n", encoding="utf-8")
            duckdns = root / "duckdns.env"
            duckdns.write_text(
                "DUCKDNS_DOMAINS=example-home\n"
                "DUCKDNS_TOKEN=00000000-0000-0000-0000-000000000000\n",
                encoding="utf-8",
            )

            MODULE.prepare_environment(stack, duckdns)

            values = MODULE.read_key_value_file(media_env)
            self.assertEqual(values["SECRET"], "value")
            self.assertEqual(values["PUBLIC_MEDIA_DOMAIN"], "example-home")

    def test_invalid_domain_is_rejected(self):
        with self.assertRaises(MODULE.PublicAccessError):
            MODULE.validate_domain("bad domain")

    def test_media_urls_use_separate_subdomains(self):
        jellyfin, seerr = MODULE.media_urls("example-home")
        self.assertEqual(jellyfin, "https://jellyfin.example-home.duckdns.org")
        self.assertEqual(seerr, "https://seerr.example-home.duckdns.org")


class PublicAccessConfigurationTests(unittest.TestCase):
    def test_jellyfin_preserves_settings_and_adds_proxy_subnet(self):
        current = {
            "KnownProxies": [],
            "EnableRemoteAccess": False,
            "EnableUPnP": True,
            "PublicHttpPort": 8096,
            "PublicHttpsPort": 8920,
            "BaseUrl": "",
        }
        client = FakeClient(
            {
                ("GET", "/System/Configuration/network"): current,
                ("POST", "/System/Configuration/network"): None,
            }
        )

        changed = MODULE.configure_jellyfin(client, "172.20.0.0/16", True)

        self.assertTrue(changed)
        payload = client.calls[1][2]
        self.assertEqual(payload["KnownProxies"], ["172.20.0.0/16"])
        self.assertTrue(payload["EnableRemoteAccess"])
        self.assertFalse(payload["EnableUPnP"])
        self.assertEqual(payload["BaseUrl"], "")

    def test_seerr_sets_proxy_and_public_urls(self):
        client = FakeClient(
            {
                ("GET", "/api/v1/settings/network"): {
                    "trustProxy": False,
                    "csrfProtection": False,
                },
                ("POST", "/api/v1/settings/network"): {},
                ("GET", "/api/v1/settings/main"): {
                    "applicationUrl": "",
                    "locale": "es",
                },
                ("POST", "/api/v1/settings/main"): {},
                ("GET", "/api/v1/settings/jellyfin"): {
                    "externalHostname": "http://nas.local:8899",
                },
                ("POST", "/api/v1/settings/jellyfin"): {},
            }
        )

        changed = MODULE.configure_seerr(
            client,
            "https://jellyfin.example-home.duckdns.org",
            "https://seerr.example-home.duckdns.org",
            True,
        )

        self.assertTrue(changed)
        self.assertEqual(client.calls[1][2], {"trustProxy": True})
        self.assertEqual(
            client.calls[3][2],
            {"applicationUrl": "https://seerr.example-home.duckdns.org"},
        )
        self.assertEqual(
            client.calls[5][2],
            {"externalHostname": "https://jellyfin.example-home.duckdns.org"},
        )


if __name__ == "__main__":
    unittest.main()
