from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/verify-hardlinks.py")

SPEC = importlib.util.spec_from_file_location(
    "verify_hardlinks",
    MODULE_PATH,
)

MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class VerifyHardlinksTest(unittest.TestCase):
    def test_resolve_media_path_prefers_largest_video_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            small = root / "a.mkv"
            large = root / "nested" / "b.mp4"
            large.parent.mkdir()
            small.write_bytes(b"1234")
            large.write_bytes(b"123456789")

            resolved = MODULE.resolve_media_path(root)

        self.assertEqual(resolved.name, "b.mp4")

    def test_verify_pair_accepts_same_inode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            download = root / "download.mkv"
            library = root / "library.mkv"
            download.write_bytes(b"video")
            os.link(download, library)

            MODULE.verify_pair(
                download,
                library,
                2,
            )

    def test_verify_pair_rejects_different_inodes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            download = root / "download.mkv"
            library = root / "library.mkv"
            download.write_bytes(b"video")
            library.write_bytes(b"video")

            with self.assertRaises(
                MODULE.HardlinkVerificationError
            ):
                MODULE.verify_pair(
                    download,
                    library,
                    2,
                )


if __name__ == "__main__":
    unittest.main()
