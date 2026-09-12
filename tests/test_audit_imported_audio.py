import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_imported_audio", ROOT / "scripts/audit-imported-audio.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AudioAuditTest(unittest.TestCase):
    def test_rejects_explicit_spanish_marker_with_english_only_audio(self) -> None:
        expected, detected, status = MODULE.audio_status(
            {
                "relativePath": "Movie [LATINO] WEB-DL.mkv",
                "languages": [{"name": "English"}],
                "mediaInfo": {"audioLanguages": "eng"},
            }
        )
        self.assertEqual(expected, "LATINO")
        self.assertEqual(detected, "eng, english")
        self.assertEqual(status, "language-mismatch")

    def test_accepts_spanish_audio(self) -> None:
        self.assertEqual(
            MODULE.audio_status(
                {
                    "relativePath": "Episode [CASTELLANO].mkv",
                    "mediaInfo": {"audioLanguages": "spa/eng"},
                }
            )[2],
            "verified-spanish",
        )

    def test_unknown_marked_audio_requires_review(self) -> None:
        self.assertEqual(
            MODULE.audio_status(
                {"relativePath": "Episode [LATINO].mkv", "mediaInfo": {}}
            )[2],
            "needs-review",
        )

    def test_history_maps_file_identifier_and_path(self) -> None:
        class Client:
            def get(self, _path):
                return {
                    "records": [
                        {
                            "eventType": "downloadFolderImported",
                            "downloadId": "abc123",
                            "episodeFileId": 7,
                            "data": {"importedPath": "/tv/Example.mkv"},
                        }
                    ]
                }

        mapping = MODULE.history_download_ids(Client())
        self.assertEqual(mapping[("episodeFile", "7")], "ABC123")
        self.assertEqual(mapping[("path", "example.mkv")], "ABC123")

    def test_positive_int_accepts_arr_string_identifier(self) -> None:
        self.assertEqual(MODULE.positive_int("17"), 17)
        self.assertIsNone(MODULE.positive_int(""))

    def test_recent_parent_fallback_avoids_full_library_scan(self) -> None:
        class Client:
            calls = []

            def get(self, path):
                self.calls.append(path)
                if path == "/series/4":
                    return {"title": "Example"}
                if path == "/episodefile?seriesId=4":
                    return [{"id": 9, "relativePath": "S01E01 [LATINO].mkv"}]
                raise AssertionError(path)

        client = Client()
        found = MODULE.imported_files(
            client,
            "Sonarr",
            [{"eventType": "downloadFolderImported", "seriesId": "4"}],
            10,
        )
        self.assertEqual(found[0][0], "Example")
        self.assertNotIn("/series", client.calls)

    def test_report_contains_no_torrent_identifier(self) -> None:
        result = MODULE.AudioResult(
            "Sonarr", "Example", "Example.mkv", "2026-09-12", "LATINO", "eng",
            "language-mismatch", True,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            MODULE.write_reports(root, [result])
            payload = (root / "state/imported-audio-audit.json").read_text()
        self.assertIn("language-mismatch", payload)
        self.assertNotIn("abc123", payload)


if __name__ == "__main__":
    unittest.main()
