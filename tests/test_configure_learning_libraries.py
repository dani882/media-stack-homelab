import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path("scripts/configure-learning-libraries.py")
SPEC = importlib.util.spec_from_file_location("configure_learning_libraries", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FakeClient:
    def __init__(self, libraries):
        self.libraries = libraries
        self.requests = []

    def request(self, method, path, query=None):
        self.requests.append((method, path, query))
        if method == "GET":
            return self.libraries
        return None


class LearningLibraryTest(unittest.TestCase):
    def test_existing_courses_library_is_idempotent(self) -> None:
        client = FakeClient(
            [{
                "Name": "Cursos",
                "CollectionType": "homevideos",
                "Locations": ["/data/Learning/Videos"],
            }]
        )
        self.assertFalse(MODULE.ensure_courses_library(client, False))
        self.assertEqual(len(client.requests), 1)

    def test_creates_courses_library_with_dedicated_type(self) -> None:
        client = FakeClient([])
        self.assertTrue(MODULE.ensure_courses_library(client, False))
        method, path, query = client.requests[-1]
        self.assertEqual((method, path), ("POST", "/Library/VirtualFolders"))
        self.assertEqual(query["collectionType"], "homevideos")
        self.assertEqual(query["paths"], ["/data/Learning/Videos"])

    def test_refuses_to_repurpose_existing_library(self) -> None:
        client = FakeClient(
            [{
                "Name": "Cursos",
                "CollectionType": "movies",
                "Locations": ["/data/Movies"],
            }]
        )
        with self.assertRaises(MODULE.LearningLibraryError):
            MODULE.ensure_courses_library(client, False)


if __name__ == "__main__":
    unittest.main()
