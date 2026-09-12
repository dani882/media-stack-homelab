import http.client
import unittest
from unittest.mock import patch

from scripts.media.common.arr import ArrClient, ArrError


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"ok": true}'


class ArrClientRetryTests(unittest.TestCase):
    def test_get_retries_one_timeout(self) -> None:
        client = ArrClient("http://arr", "secret")
        with patch(
            "urllib.request.urlopen",
            side_effect=[TimeoutError(), FakeResponse()],
        ) as urlopen:
            self.assertEqual(client.get("/release"), {"ok": True})
        self.assertEqual(urlopen.call_count, 2)

    def test_post_does_not_retry_timeout(self) -> None:
        client = ArrClient("http://arr", "secret")
        with patch(
            "urllib.request.urlopen",
            side_effect=TimeoutError(),
        ) as urlopen:
            with self.assertRaises(ArrError):
                client.request("POST", "/release", {"id": 1})
        self.assertEqual(urlopen.call_count, 1)

    @patch("scripts.media.common.arr.time.sleep", return_value=None)
    def test_get_retries_remote_disconnect(self, _sleep) -> None:
        client = ArrClient("http://arr", "secret")
        with patch(
            "urllib.request.urlopen",
            side_effect=[http.client.RemoteDisconnected(), FakeResponse()],
        ) as urlopen:
            self.assertEqual(client.get("/release"), {"ok": True})
        self.assertEqual(urlopen.call_count, 2)

    @patch("scripts.media.common.arr.time.sleep", return_value=None)
    def test_remote_disconnect_becomes_arr_error(self, _sleep) -> None:
        client = ArrClient("http://arr", "secret")
        with patch(
            "urllib.request.urlopen",
            side_effect=http.client.RemoteDisconnected(),
        ):
            with self.assertRaises(ArrError):
                client.get("/release")


if __name__ == "__main__":
    unittest.main()
