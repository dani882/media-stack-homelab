from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path("scripts/dominican-iptv.py")
SPEC = importlib.util.spec_from_file_location("dominican_iptv", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DominicanIptvTest(unittest.TestCase):
    def test_normalize_name_ignores_quality_flags_and_accents(self):
        self.assertEqual(
            MODULE.normalize_name("Color Visión (720p) [Not 24/7]"),
            "color vision",
        )

    def test_parse_iptv_org_keeps_metadata_and_names(self):
        source = (
            '#EXTM3U\n#EXTINF:-1 tvg-country="DO",Águila TV (1080p)\n'
            "https://example.test/aguila.m3u8\n"
        )
        entries, names = MODULE.parse_iptv_org(source)
        self.assertEqual(len(entries), 1)
        self.assertIn("aguila tv", names)
        self.assertIn("https://example.test/aguila.m3u8", entries[0])

    def test_parse_iptv_cat_extracts_name_and_token(self):
        token = "a" * 32
        source = (
            '<span class="channel_name" data-content="details" '
            'title="Canal 6 (720p)">Canal 6</span>'
            f'<a href="https://list.iptvcat.com/my_list/s/{token}.m3u8">'
        )
        self.assertEqual(
            MODULE.parse_iptv_cat(source),
            [("Canal 6 (720p)", token)],
        )

    @mock.patch.object(MODULE, "fetch_text")
    def test_build_playlist_keeps_duplicate_sources_as_fallbacks(self, fetch_text):
        existing_token = "a" * 32
        new_token = "b" * 32
        org = (
            '#EXTM3U\n#EXTINF:-1 tvg-country="DO",Canal Uno (720p)\n'
            "https://example.test/uno.m3u8\n"
        )
        cat = (
            '<span class="channel_name" title="Canal Uno (1080p)">Canal Uno</span>'
            f'<a href="https://list.iptvcat.com/my_list/s/{existing_token}.m3u8">'
            '<span class="channel_name" title="Canal Dos (720p)">Canal Dos</span>'
            f'<a href="https://list.iptvcat.com/my_list/s/{new_token}.m3u8">'
        )
        fetch_text.side_effect = [org, cat]

        playlist, org_count, cat_count = MODULE.build_playlist()

        self.assertEqual((org_count, cat_count), (1, 2))
        self.assertIn("Canal Uno (720p)", playlist)
        self.assertIn(existing_token, playlist)
        self.assertIn("Canal Dos (720p)", playlist)
        self.assertIn(new_token, playlist)

    def test_merge_probe_classifies_audio_and_transient_failures(self):
        silent = MODULE.merge_probe(
            {}, {"ok": True, "name": "Canal", "url": "https://x", "audio_codec": None}
        )
        self.assertEqual(silent["status"], "silent")

        intermittent = MODULE.merge_probe(
            {"last_success": 1, "consecutive_successes": 1},
            {"ok": False, "name": "Canal", "url": "https://x", "error": "timeout"},
        )
        self.assertEqual(intermittent["status"], "intermittent")

    def test_resolver_cache_expires(self):
        token = "c" * 32
        with mock.patch.object(MODULE, "load_resolvers") as load_resolvers, mock.patch.object(
            MODULE, "load_health", return_value={}
        ), mock.patch.object(MODULE, "fetch_text", return_value="https://new.test/live.m3u8\n"), mock.patch.object(
            MODULE, "write_json"
        ) as write_json:
            load_resolvers.return_value = {
                token: {"url": "https://old.test/live.m3u8", "resolved_at": 0}
            }
            self.assertEqual(
                MODULE.resolve_iptvcat(token), "https://new.test/live.m3u8"
            )
            write_json.assert_called_once()

    def test_manifest_rewrite_keeps_media_inside_relay(self):
        manifest = (
            "#EXTM3U\n"
            "#EXT-X-KEY:METHOD=AES-128,URI=\"keys/live.key\"\n"
            "variant/index.m3u8\n"
        )
        rewritten = MODULE.rewrite_manifest(
            "antena7", "https://cdn.example/live/master.m3u8", manifest
        ).decode()
        self.assertNotIn("variant/index.m3u8\n", rewritten)
        self.assertIn("/fetch/antena7/", rewritten)
        self.assertNotIn('URI="keys/live.key"', rewritten)

    def test_official_geo_source_waits_for_exit_node(self):
        org = '#EXTM3U\n#EXTINF:-1,Canal Uno\nhttps://example.test/uno.m3u8\n'
        catalog = [{
            "id": "antena7", "name": "Antena 7",
            "url": "https://cdn.example/master.m3u8",
            "requires_dominican_exit": True,
        }]
        with mock.patch.object(MODULE, "fetch_text", side_effect=[org, ""]), mock.patch.object(
            MODULE, "load_catalog", return_value=catalog
        ), mock.patch.dict(MODULE.os.environ, {"DOMINICAN_EXIT_NODE_ENABLED": "0"}):
            playlist, _, extra = MODULE.build_playlist()
        self.assertNotIn("dominican-exit", playlist)
        self.assertEqual(extra, 0)


if __name__ == "__main__":
    unittest.main()
