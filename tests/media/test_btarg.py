import tempfile
import unittest
from pathlib import Path

from scripts.media.common.btarg import (
    BTArgCache,
    BTArgDetail,
    enrich_release,
    parse_btarg_detail,
    torrent_id_from_url,
)


class FakeClient:
    def __init__(self, detail: BTArgDetail) -> None:
        self.value = detail

    def detail(self, url: str) -> BTArgDetail:
        return self.value


class BTArgTest(unittest.TestCase):
    def test_parses_latino_castilian_and_english(self) -> None:
        for text, expected in (
            ("Español latino e inglés", "latino"),
            ("Castellano", "castilian"),
            ("Inglés", "english"),
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    parse_btarg_detail(f"Idioma: {text} Ripper: test").language,
                    expected,
                )

    def test_accepts_only_numeric_btarg_detail_urls(self) -> None:
        self.assertEqual(
            torrent_id_from_url("https://btarg.com.ar/tracker/details.php?id=123"),
            "123",
        )
        with self.assertRaises(Exception):
            torrent_id_from_url("https://example.com/tracker/details.php?id=123")

    def test_cache_expires_unknown_before_verified_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = [1000.0]
            cache = BTArgCache(Path(directory) / "cache.json", now=lambda: current[0])
            unknown = BTArgDetail("unknown", "", None, "", "")
            latino = BTArgDetail("latino", "Latino", "tt1234567", "AVC", "1080p")
            cache.store_detail("1", unknown)
            cache.store_detail("2", latino)
            current[0] += 7 * 60 * 60
            self.assertIsNone(cache.detail("1"))
            self.assertEqual(cache.detail("2"), latino)

    def test_search_backoff_increases_and_can_be_cleared(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = [1000.0]
            cache = BTArgCache(Path(directory) / "cache.json", now=lambda: current[0])
            cache.record_search_miss("series:1")
            self.assertFalse(cache.search_allowed("series:1"))
            current[0] += 6 * 60 * 60
            self.assertTrue(cache.search_allowed("series:1"))
            cache.record_search_miss("series:1")
            current[0] += 6 * 60 * 60
            self.assertFalse(cache.search_allowed("series:1"))
            cache.clear_search("series:1")
            self.assertTrue(cache.search_allowed("series:1"))

    def test_concurrent_cache_writers_merge_detail_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            first = BTArgCache(path)
            second = BTArgCache(path)
            first.store_detail("1", BTArgDetail("latino", "Latino", None, "", ""))
            second.store_detail("2", BTArgDetail("english", "English", None, "", ""))
            merged = BTArgCache(path)
            self.assertEqual(merged.detail("1").language, "latino")
            self.assertEqual(merged.detail("2").language, "english")

    def test_enrichment_marks_verified_latino_for_language_ranking(self) -> None:
        detail = BTArgDetail("latino", "Español latino", "tt1234567", "AVC", "1080p")
        enriched = enrich_release(
            {
                "indexer": "BTArg",
                "infoUrl": "https://btarg.com.ar/tracker/details.php?id=1",
                "customFormats": [],
            },
            FakeClient(detail),
            "tt1234567",
        )
        self.assertEqual(enriched["btargVerifiedLanguage"], "latino")
        self.assertEqual(enriched["customFormats"], [{"name": "LATINO"}])

    def test_identity_mismatch_is_not_downloadable(self) -> None:
        detail = BTArgDetail("latino", "Español latino", "tt7654321", "AVC", "1080p")
        enriched = enrich_release(
            {"indexer": "BTArg", "infoUrl": "https://btarg.com.ar/tracker/details.php?id=1"},
            FakeClient(detail),
            "tt1234567",
        )
        self.assertFalse(enriched["downloadAllowed"])


if __name__ == "__main__":
    unittest.main()
