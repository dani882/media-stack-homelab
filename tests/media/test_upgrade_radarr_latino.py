import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock


SCRIPT = (
    Path(__file__).parents[2]
    / "scripts/media/upgrade-radarr-latino.py"
)
SPEC = importlib.util.spec_from_file_location(
    "upgrade_radarr_latino",
    SCRIPT,
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class QueuedMovieIdsTests(unittest.TestCase):
    def test_extracts_known_movie_ids(self) -> None:
        client = Mock()
        client.get.return_value = {
            "records": [
                {"movieId": 8},
                {"movieId": None},
                {"title": "unknown"},
                {"movieId": "11"},
            ]
        }

        self.assertEqual(
            MODULE.queued_movie_ids(client),
            {8, 11},
        )
        requested_path = client.get.call_args.args[0]
        self.assertIn("/queue?", requested_path)
        self.assertIn("pageSize=1000", requested_path)

    def test_identifies_exact_qbittorrent_duplicate(self) -> None:
        error = MODULE.UpgradeError(
            "POST /release failed: qBittorrent "
            "409:Conflict /api/v2/torrents/add"
        )
        self.assertTrue(
            MODULE.is_qbittorrent_duplicate(error)
        )

    def test_does_not_hide_other_conflicts(self) -> None:
        error = MODULE.UpgradeError(
            "POST /release failed: 409:Conflict"
        )
        self.assertFalse(
            MODULE.is_qbittorrent_duplicate(error)
        )


if __name__ == "__main__":
    unittest.main()
