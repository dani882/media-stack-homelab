"""Unit tests for declarative Servarr root-folder reconciliation."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path("scripts").resolve()
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SETTINGS = importlib.import_module("servarr_config.settings")


class FakeClient:
    def __init__(self, folders: list[dict[str, object]]) -> None:
        self.folders = folders
        self.calls: list[tuple[str, str, object | None]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
    ) -> object:
        self.calls.append((method, path, payload))

        if method == "GET":
            return self.folders

        if method == "DELETE":
            return None

        if method == "POST":
            return {"id": 99, "path": payload["path"]}

        raise AssertionError(f"Unexpected request: {method} {path}")


class ConfigureRootFoldersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temporary_directory.name)
        (self.data_path / "root-folders.json").write_text(
            json.dumps([{"path": "/data/Media/Movies"}]),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_removes_obsolete_root_folder(self) -> None:
        client = FakeClient(
            [
                {"id": 1, "path": "/media/Movies"},
                {"id": 3, "path": "/data/Media/Movies"},
            ]
        )

        SETTINGS.configure_root_folders(
            client,
            self.data_path,
            dry_run=False,
        )

        self.assertIn(
            ("DELETE", "/api/v3/rootfolder/1", None),
            client.calls,
        )
        self.assertNotIn(
            ("DELETE", "/api/v3/rootfolder/3", None),
            client.calls,
        )

    def test_dry_run_does_not_remove_obsolete_root_folder(self) -> None:
        client = FakeClient(
            [
                {"id": 1, "path": "/media/Movies"},
                {"id": 3, "path": "/data/Media/Movies"},
            ]
        )

        SETTINGS.configure_root_folders(
            client,
            self.data_path,
            dry_run=True,
        )

        self.assertFalse(
            any(method == "DELETE" for method, _, _ in client.calls)
        )
