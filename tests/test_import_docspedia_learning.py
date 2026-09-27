import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/import-docspedia-learning.py")
SPEC = importlib.util.spec_from_file_location("import_docspedia_learning", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DocsPediaLearningImportTest(unittest.TestCase):
    def test_uses_existing_qbittorrent_secret(self) -> None:
        self.assertEqual(
            MODULE.QBITTORRENT_SECRET,
            Path("secrets/qbittorrent.json"),
        )

    def test_matches_docspedia_subdomain_only(self) -> None:
        self.assertTrue(MODULE.is_docspedia({"tracker.docspedia.world"}))
        self.assertFalse(MODULE.is_docspedia({"fake-docspedia.world.example"}))

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaises(MODULE.LearningImportError):
            MODULE.safe_relative_path("../escape.pdf")

    def test_rejects_executable_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(MODULE.LearningImportError, "executable"):
                MODULE.import_files(
                    name="Unsafe Course",
                    files=[{"name": "course/setup.exe"}],
                    save_path=root,
                    videos_root=root / "videos",
                    documents_root=root / "documents",
                    dry_run=False,
                )

    def test_hardlinks_video_and_document_without_copying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "downloads"
            (save / "course").mkdir(parents=True)
            video = save / "course/lesson.mp4"
            document = save / "course/guide.pdf"
            ignored = save / "course/notes.txt"
            for path in (video, document, ignored):
                path.write_bytes(path.name.encode())

            counts = MODULE.import_files(
                name="Python / Basics",
                files=[
                    {"name": "course/lesson.mp4"},
                    {"name": "course/guide.pdf"},
                    {"name": "course/notes.txt"},
                ],
                save_path=save,
                videos_root=root / "videos",
                documents_root=root / "documents",
                dry_run=False,
            )

            imported_video = root / "videos/Python Basics/course/lesson.mp4"
            imported_document = root / "documents/Python Basics/course/guide.pdf"
            self.assertEqual(counts, (1, 1))
            self.assertEqual(video.stat().st_ino, imported_video.stat().st_ino)
            self.assertEqual(document.stat().st_ino, imported_document.stat().st_ino)
            self.assertFalse((root / "documents/Python Basics/course/notes.txt").exists())


if __name__ == "__main__":
    unittest.main()
