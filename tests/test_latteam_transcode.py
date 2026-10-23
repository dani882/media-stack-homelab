import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


COMMON_PATH = Path("scripts/media/common/latteam_transcode.py")
COMMON_SPEC = importlib.util.spec_from_file_location("latteam_transcode_common", COMMON_PATH)
assert COMMON_SPEC and COMMON_SPEC.loader
COMMON = importlib.util.module_from_spec(COMMON_SPEC)
sys.modules[COMMON_SPEC.name] = COMMON
COMMON_SPEC.loader.exec_module(COMMON)

WORKER_PATH = Path("scripts/dispatch-latteam-transcode.py")
WORKER_SPEC = importlib.util.spec_from_file_location("dispatch_latteam_transcode", WORKER_PATH)
assert WORKER_SPEC and WORKER_SPEC.loader
WORKER = importlib.util.module_from_spec(WORKER_SPEC)
sys.modules[WORKER_SPEC.name] = WORKER
WORKER_SPEC.loader.exec_module(WORKER)


class LatTeamTranscodeTests(unittest.TestCase):
    def test_maps_download_path_without_allowing_other_roots(self) -> None:
        self.assertEqual(
            COMMON.container_to_host("/data/Downloads/movie.mkv"),
            Path("/volume1/Family/Downloads/movie.mkv"),
        )
        with self.assertRaises(COMMON.LatTeamTranscodeError):
            COMMON.container_to_host("/etc/passwd")

    def test_conversion_preserves_streams_and_uses_hardware(self) -> None:
        command = COMMON.conversion_command(
            Path("source.mkv"), Path("destination.partial.mkv"), True
        )
        self.assertIn("h264_rkmpp", command)
        self.assertIn("0:a?", command)
        self.assertEqual(command[command.index("-c:a") + 1], "copy")

    def test_software_fallback_is_available(self) -> None:
        command = COMMON.conversion_command(
            Path("source.mkv"), Path("destination.partial.mkv"), False
        )
        self.assertIn("libx264", command)

    def test_worker_only_accepts_completed_spanish_latteam_fallback(self) -> None:
        torrent = {
            "progress": 1,
            "tags": (
                "private,lat-team,private-dispatch,movie-expected-latino,"
                "latteam-transcode-required"
            ),
        }
        self.assertTrue(WORKER.eligible(torrent))
        torrent["tags"] = str(torrent["tags"]).replace("lat-team", "btarg")
        self.assertFalse(WORKER.eligible(torrent))

    def test_upgrade_requires_original_file_identity(self) -> None:
        with self.assertRaises(WORKER.LatTeamWorkerError):
            WORKER.validate_upgrade_provenance(
                {"movie-language-upgrade", "latteam-transcode-required"}
            )

    def test_movie_import_uses_staged_path(self) -> None:
        torrent = {
            "hash": "abc",
            "tags": "private-dispatch,movie-expected-latino",
        }
        staged = COMMON.StagedContent(
            "/data/Downloads/.transcode/latteam/abc/movie.mkv",
            Path("/volume1/Family/Downloads/.transcode/latteam/abc/movie.mkv"),
            1,
            0,
        )
        with mock.patch.object(WORKER, "api_key", return_value="key"), mock.patch.object(
            WORKER, "post_json"
        ) as post:
            tag, manager = WORKER.request_import(torrent, staged, Path("/stack"))
        self.assertEqual((tag, manager), ("private-dispatch-import-requested", "Radarr"))
        self.assertEqual(post.call_args.args[1]["path"], staged.container_path)


if __name__ == "__main__":
    unittest.main()
