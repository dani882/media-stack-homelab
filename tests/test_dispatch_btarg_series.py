import importlib.util
import sys
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


if __name__ == "__main__":
    unittest.main()
