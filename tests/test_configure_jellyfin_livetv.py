from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("scripts/configure-jellyfin-livetv.py")
SPEC = importlib.util.spec_from_file_location(
    "configure_jellyfin_livetv",
    MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class JellyfinLiveTvConfigurationTest(unittest.TestCase):
    def test_update_tree_is_idempotent_and_preserves_other_tuners(self):
        root = ET.fromstring(
            """
            <LiveTvOptions>
              <TunerHosts>
                <TunerHostInfo>
                  <Id>other</Id>
                  <Url>http://other/tuner.m3u</Url>
                  <Type>m3u</Type>
                </TunerHostInfo>
              </TunerHosts>
              <ListingProviders />
            </LiveTvOptions>
            """
        )

        MODULE.update_tree(root)
        first = ET.tostring(root)
        MODULE.update_tree(root)

        self.assertEqual(first, ET.tostring(root))
        self.assertEqual(len(root.findall("./TunerHosts/TunerHostInfo")), 2)
        self.assertEqual(
            root.findtext("./TunerHosts/TunerHostInfo[2]/Url"),
            MODULE.DEFAULT_M3U_URL,
        )
        self.assertEqual(
            root.findtext("./ListingProviders/ListingsProviderInfo/Path"),
            MODULE.DEFAULT_EPG_URL,
        )

    def test_written_new_configuration_is_valid_xml(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "livetv.xml"
            MODULE.write_configuration(
                path,
                MODULE.DEFAULT_M3U_URL,
                MODULE.DEFAULT_EPG_URL,
            )

            parsed = ET.parse(path)
            self.assertEqual(parsed.getroot().tag, "LiveTvOptions")
            self.assertFalse(
                MODULE.configuration_changed(
                    path,
                    MODULE.DEFAULT_M3U_URL,
                    MODULE.DEFAULT_EPG_URL,
                )
            )

    def test_reads_existing_seerr_jellyfin_api_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(
                json.dumps({"jellyfin": {"apiKey": "local-key"}}),
                encoding="utf-8",
            )
            self.assertEqual(MODULE.read_jellyfin_api_key(path), "local-key")

    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE, "jellyfin_request")
    def test_refresh_guide_starts_task_and_waits_for_idle(
        self,
        request,
        _sleep,
    ):
        request.side_effect = [
            [{"Key": "RefreshGuide", "Id": "task-id", "State": "Idle"}],
            None,
            [{"Key": "RefreshGuide", "Id": "task-id", "State": "Idle"}],
        ]

        MODULE.refresh_guide("http://jellyfin", "secret", timeout=5)

        self.assertEqual(request.call_count, 3)
        self.assertEqual(
            request.call_args_list[1].args,
            (
                "http://jellyfin",
                "secret",
                "POST",
                "/ScheduledTasks/Running/task-id",
            ),
        )


if __name__ == "__main__":
    unittest.main()
