
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/audit-hardlinks.py")

SPEC = importlib.util.spec_from_file_location(
    "audit_hardlinks",
    MODULE_PATH,
)

MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AuditHardlinksTest(unittest.TestCase):
    def test_recent_media_files_returns_latest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            older = root / "older.mkv"
            newer = root / "newer.mkv"
            older.write_bytes(b"a")
            newer.write_bytes(b"b")
            os.utime(older, (1, 1))
            os.utime(newer, (2, 2))

            result = MODULE.recent_media_files(root, 2)

        self.assertEqual(result[0].name, "newer.mkv")

    def test_matching_download_paths_finds_same_inode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloads = root / "Downloads"
            media = root / "Media"
            downloads.mkdir()
            media.mkdir()
            download = downloads / "file.mkv"
            media_file = media / "file.mkv"
            download.write_bytes(b"video")
            os.link(download, media_file)

            matches = MODULE.matching_download_paths(
                downloads,
                media_file,
            )

        self.assertIn(str(download), matches)

    def test_download_inode_index_matches_hardlinked_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloads = root / "Downloads"
            media = root / "Media"
            downloads.mkdir()
            media.mkdir()
            download = downloads / "episode.mkv"
            library = media / "episode.mkv"
            download.write_bytes(b"video")
            os.link(download, library)

            index = MODULE.download_inode_index(downloads)
            library_stat = library.stat()

        self.assertEqual(
            index[(library_stat.st_dev, library_stat.st_ino)].name,
            "episode.mkv",
        )

    def test_download_inode_index_ignores_non_video_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloads = Path(temp_dir)
            (downloads / "readme.txt").write_text("not media")

            index = MODULE.download_inode_index(downloads)

        self.assertEqual(index, {})


if __name__ == "__main__":
    unittest.main()
