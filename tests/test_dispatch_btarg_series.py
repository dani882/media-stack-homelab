import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/dispatch-btarg-series.py"
SPEC = importlib.util.spec_from_file_location("dispatch_btarg_series", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DispatchBTArgSeriesTest(unittest.TestCase):
    @mock.patch.object(MODULE.shutil, "disk_usage")
    def test_refuses_pack_without_conversion_reserve(self, disk_usage: mock.Mock) -> None:
        disk_usage.return_value = mock.Mock(free=50 * 1024**3)
        with self.assertRaises(MODULE.DispatchError):
            MODULE.require_dispatch_space(Path("/data"), 30 * 1024**3)

    @mock.patch.object(MODULE.shutil, "disk_usage")
    def test_accepts_pack_with_download_and_conversion_reserve(self, disk_usage: mock.Mock) -> None:
        disk_usage.return_value = mock.Mock(free=100 * 1024**3)
        MODULE.require_dispatch_space(Path("/data"), 30 * 1024**3)

    def test_rejects_explicit_english_only_audio(self) -> None:
        probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "tags": {"language": "eng"}},
            ]
        }
        with self.assertRaises(MODULE.DispatchError):
            MODULE.validate_verified_latino_audio(probe)

    def test_accepts_spanish_audio_metadata(self) -> None:
        probe = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "tags": {"language": "spa"}},
                {"codec_type": "audio", "tags": {"language": "eng"}},
            ]
        }
        MODULE.validate_verified_latino_audio(probe)

    def test_hardware_conversion_preserves_audio_and_uses_rkmpp(self) -> None:
        command = MODULE.conversion_command(
            Path("source.mp4"),
            Path("destination.partial.mkv"),
            True,
        )
        self.assertIn("h264_rkmpp", command)
        self.assertIn("format=nv12", command)
        audio_codec = command.index("-c:a")
        self.assertEqual(command[audio_codec + 1], "copy")

    def test_software_conversion_remains_available_as_fallback(self) -> None:
        command = MODULE.conversion_command(
            Path("source.mp4"),
            Path("destination.partial.mkv"),
            False,
        )
        self.assertIn("libx264", command)
        self.assertNotIn("h264_rkmpp", command)

    def test_transcode_temporary_file_is_outside_library(self) -> None:
        destination = Path("/data/Media/TV Shows/Example/episode.mkv")
        temporary = MODULE.transcode_temporary_path(
            destination,
            Path("/data/Downloads/.transcode/btarg-series"),
        )
        self.assertNotIn("/Media/", str(temporary))
        self.assertTrue(temporary.name.endswith(".partial.mkv"))
        self.assertEqual(
            temporary,
            MODULE.transcode_temporary_path(
                destination,
                Path("/data/Downloads/.transcode/btarg-series"),
            ),
        )

    def test_accepts_matching_conversion_metadata(self) -> None:
        source = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080,
                },
                {"codec_type": "audio", "tags": {"language": "lat"}},
                {"codec_type": "audio", "tags": {"language": "eng"}},
                {"codec_type": "subtitle"},
            ],
            "format": {"duration": "1200.0"},
        }
        converted = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                },
                {"codec_type": "audio", "tags": {"language": "lat"}},
                {"codec_type": "audio", "tags": {"language": "eng"}},
                {"codec_type": "subtitle"},
            ],
            "format": {"duration": "1200.5"},
        }
        MODULE.validate_conversion_probe(source, converted, "episode.mkv")

    def test_ignores_embedded_png_cover_when_selecting_video(self) -> None:
        probe = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 852,
                    "height": 480,
                },
                {
                    "codec_type": "video",
                    "codec_name": "png",
                    "width": 385,
                    "height": 756,
                },
            ]
        }
        self.assertEqual(MODULE.media_codec(probe), "h264")
        self.assertEqual(len(MODULE.primary_video_streams(probe)), 1)

    def test_rejects_truncated_conversion(self) -> None:
        source = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080,
                },
                {"codec_type": "audio", "tags": {"language": "lat"}},
            ],
            "format": {"duration": "1200.0"},
        }
        converted = {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                },
                {"codec_type": "audio", "tags": {"language": "lat"}},
            ],
            "format": {"duration": "600.0"},
        }
        with self.assertRaises(MODULE.DispatchError):
            MODULE.validate_conversion_probe(source, converted, "episode.mkv")

    def test_progress_report_is_secret_free_and_human_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stack = Path(directory)
            payload = MODULE.save_progress_report(
                stack,
                series="Example <Series>",
                status="importando",
                completedFiles=4,
                totalFiles=10,
                completedEpisodes=12,
                totalEpisodes=30,
                current="Temporada 1, E13-E15",
                encoder="Rockchip",
                speed=2.5,
                temperatureC=55.0,
                estimatedSecondsRemaining=3600,
                hardwareFallbacks=0,
                error="",
            )
            report = json.loads(
                (stack / "state/btarg-series-progress.json").read_text(
                    encoding="utf-8"
                )
            )
            page = (stack / "state/btarg-series-progress.html").read_text(
                encoding="utf-8"
            )
            self.assertEqual(report["completedFiles"], 4)
            self.assertEqual(payload["series"], "Example <Series>")
            self.assertIn("40.0%", page)
            self.assertIn("Example &lt;Series&gt;", page)

    def test_reads_highest_valid_temperature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("thermal_zone0", "53000"), ("thermal_zone1", "47")):
                zone = root / name
                zone.mkdir()
                (zone / "temp").write_text(value, encoding="ascii")
            self.assertEqual(MODULE.read_temperature_c(root), 53.0)

    @mock.patch.object(MODULE, "request_json")
    def test_waits_for_sonarr_season_rescan(self, request_json: mock.Mock) -> None:
        request_json.side_effect = [{"id": 42}, {"status": "completed"}]
        MODULE.rescan_series("key", 35)
        self.assertEqual(request_json.call_count, 2)
        self.assertEqual(
            request_json.call_args_list[0].kwargs["payload"],
            {"name": "RescanSeries", "seriesId": 35},
        )


if __name__ == "__main__":
    unittest.main()
