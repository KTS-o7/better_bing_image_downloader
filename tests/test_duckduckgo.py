"""Tests for the DuckDuckGo image search engine.

The DuckDuckGo i.js endpoint requires real network access (Brotli-encoded
JSON, vqd tokens tied to cookies), so most tests mock the HTTP layer.
One optional end-to-end test is gated on the ``BBID_RUN_NETWORK_TESTS``
environment variable; set it to ``1`` to run it.
"""

import gzip
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from better_bing_image_downloader.duckduckgo import DuckDuckGo


class TestDuckDuckGoInit:
    def test_safe_search_validated(self, tmp_path):
        with pytest.raises(ValueError, match="safe_search must be one of"):
            DuckDuckGo("cats", 10, str(tmp_path), safe_search="invalid")

    @pytest.mark.parametrize("value", ["strict", "moderate", "off"])
    def test_valid_safe_search_accepted(self, tmp_path, value):
        b = DuckDuckGo("cats", 10, str(tmp_path), safe_search=value)
        assert b.safe_search == value

    def test_max_workers_clamped(self, tmp_path):
        b = DuckDuckGo("cats", 10, str(tmp_path), max_workers=100)
        assert b.max_workers <= 16
        b = DuckDuckGo("cats", 10, str(tmp_path), max_workers=0)
        assert b.max_workers >= 1

    def test_badsites_default_not_shared(self, tmp_path):
        b1 = DuckDuckGo("cats", 10, str(tmp_path))
        b2 = DuckDuckGo("dogs", 10, str(tmp_path))
        b1.badsites.add("evil.com")
        assert "evil.com" not in b2.badsites

    def test_output_dir_created(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        DuckDuckGo("cats", 10, str(nested))
        assert nested.is_dir()


class TestDuckDuckGoFetchVqd:
    @patch.object(DuckDuckGo, "_get")
    def test_vqd_extracted_from_html(self, mock_get, tmp_path):
        html = b"<html><body>vqd='4-12345678901234567890123456789012345678';</body></html>"
        mock_get.return_value = (html, "")
        b = DuckDuckGo("cats", 10, str(tmp_path))
        vqd = b._fetch_vqd()
        assert vqd == "4-12345678901234567890123456789012345678"

    @patch.object(DuckDuckGo, "_get")
    def test_vqd_gzip_decoded(self, mock_get, tmp_path):
        html = b'vqd="4-99999999999999999999999999999999999999"'
        mock_get.return_value = (gzip.compress(html), "gzip")
        b = DuckDuckGo("cats", 10, str(tmp_path))
        vqd = b._fetch_vqd()
        assert vqd == "4-99999999999999999999999999999999999999"

    @patch.object(DuckDuckGo, "_get")
    def test_missing_vqd_raises(self, mock_get, tmp_path):
        mock_get.return_value = (b"<html>no token here</html>", "")
        b = DuckDuckGo("cats", 10, str(tmp_path))
        with pytest.raises(RuntimeError, match="Could not extract vqd"):
            b._fetch_vqd()


class TestDuckDuckGoFetchPage:
    def _patched_response(self, body, encoding=""):
        """Build a mock HTTP response context manager."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.headers.get.return_value = encoding
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("urllib.request.build_opener")
    def test_extracts_image_urls(self, mock_build_opener, tmp_path):
        payload = {
            "results": [
                {"image": "https://example.com/a.jpg"},
                {"image": "https://example.com/b.png"},
                {"image": "https://example.com/c.webp"},
            ]
        }
        mock_opener = MagicMock()
        mock_opener.open.return_value = self._patched_response(json.dumps(payload).encode())
        mock_build_opener.return_value = mock_opener

        b = DuckDuckGo("cats", 10, str(tmp_path))
        urls = b._fetch_page("vqd-token", 0)
        assert urls == [
            "https://example.com/a.jpg",
            "https://example.com/b.png",
            "https://example.com/c.webp",
        ]

    @patch("urllib.request.build_opener")
    def test_skips_results_without_image(self, mock_build_opener, tmp_path):
        payload = {
            "results": [
                {"image": "https://example.com/a.jpg"},
                {"image": ""},  # empty image
                {"width": 100},  # no image key
            ]
        }
        mock_opener = MagicMock()
        mock_opener.open.return_value = self._patched_response(json.dumps(payload).encode())
        mock_build_opener.return_value = mock_opener

        b = DuckDuckGo("cats", 10, str(tmp_path))
        urls = b._fetch_page("vqd-token", 0)
        assert urls == ["https://example.com/a.jpg"]

    @patch("urllib.request.build_opener")
    def test_invalid_json_raises(self, mock_build_opener, tmp_path):
        mock_opener = MagicMock()
        mock_opener.open.return_value = self._patched_response(b"not json")
        mock_build_opener.return_value = mock_opener

        b = DuckDuckGo("cats", 10, str(tmp_path))
        with pytest.raises(RuntimeError, match="Failed to parse"):
            b._fetch_page("vqd-token", 0)

    @patch("urllib.request.build_opener")
    def test_handles_brotli_response(self, mock_build_opener, tmp_path):
        try:
            import brotli
        except ImportError:
            pytest.skip("brotli not installed")
        payload = {"results": [{"image": "https://example.com/a.jpg"}]}
        encoded = brotli.compress(json.dumps(payload).encode())
        mock_opener = MagicMock()
        mock_opener.open.return_value = self._patched_response(encoded, encoding="br")
        mock_build_opener.return_value = mock_opener

        b = DuckDuckGo("cats", 10, str(tmp_path))
        urls = b._fetch_page("vqd-token", 0)
        assert urls == ["https://example.com/a.jpg"]


class TestDuckDuckGoRun:
    """``run`` should iterate pages, apply badsite/seen filters, and stop."""

    def _mock_download_image(self, b, mock_dl):
        """Wire ``mock_dl`` to behave like a successful download.

        ``download_image`` in the real code updates counters itself, so
        we have to replicate that side effect in the mock or the
        assertions on ``download_count``/``_slots_used`` will fail.
        """

        def fake(link, index):
            with b._count_lock:
                b.download_count += 1
                b._slots_used += 1
            return index

        mock_dl.side_effect = fake

    @patch.object(DuckDuckGo, "_fetch_vqd", return_value="vqd")
    @patch.object(DuckDuckGo, "_fetch_page")
    @patch.object(DuckDuckGo, "download_image")
    def test_run_stops_when_limit_reached(self, mock_dl, mock_page, mock_vqd, tmp_path):
        # 5 unique links per page; limit is 3
        mock_page.return_value = [
            "https://example.com/a.jpg",
            "https://example.com/b.jpg",
            "https://example.com/c.jpg",
            "https://example.com/d.jpg",
            "https://example.com/e.jpg",
        ]
        b = DuckDuckGo("cats", 3, str(tmp_path), verbose=False)
        self._mock_download_image(b, mock_dl)
        b.run()
        # Should have only downloaded 3 (the limit)
        assert b.download_count == 3
        assert b._slots_used == 3

    @patch.object(DuckDuckGo, "_fetch_vqd", return_value="vqd")
    @patch.object(DuckDuckGo, "_fetch_page")
    @patch.object(DuckDuckGo, "download_image")
    def test_run_filters_badsites(self, mock_dl, mock_page, mock_vqd, tmp_path):
        mock_page.return_value = [
            "https://evil.com/a.jpg",
            "https://good.com/b.jpg",
        ]
        b = DuckDuckGo("cats", 5, str(tmp_path), badsites=["evil.com"], verbose=False)
        self._mock_download_image(b, mock_dl)
        b.run()
        # Only the good.com link should have been passed to download_image
        downloaded_links = [call.args[0] for call in mock_dl.call_args_list]
        assert "https://good.com/b.jpg" in downloaded_links
        assert all("evil.com" not in link for link in downloaded_links)

    @patch.object(DuckDuckGo, "_fetch_vqd", return_value="vqd")
    @patch.object(DuckDuckGo, "_fetch_page")
    @patch.object(DuckDuckGo, "download_image")
    def test_run_dedupes_seen_urls(self, mock_dl, mock_page, mock_vqd, tmp_path):
        # Same page returned twice with the same links
        mock_page.return_value = [
            "https://example.com/a.jpg",
            "https://example.com/b.jpg",
        ]
        b = DuckDuckGo("cats", 10, str(tmp_path), verbose=False)
        self._mock_download_image(b, mock_dl)
        b.run()
        # 2 unique links -> 2 download_image calls
        assert mock_dl.call_count == 2

    @patch.object(DuckDuckGo, "_fetch_vqd", return_value="vqd")
    @patch.object(DuckDuckGo, "_fetch_page", return_value=[])
    @patch.object(DuckDuckGo, "download_image")
    def test_run_stops_on_empty_page(self, mock_dl, mock_page, mock_vqd, tmp_path):
        b = DuckDuckGo("cats", 10, str(tmp_path), verbose=False)
        b.run()
        # Only one call to _fetch_page (empty result triggers stop)
        assert mock_page.call_count == 1
        mock_dl.assert_not_called()

    @patch.object(DuckDuckGo, "_fetch_vqd")
    @patch.object(DuckDuckGo, "download_image")
    def test_run_handles_vqd_fetch_failure(self, mock_dl, mock_vqd, tmp_path):
        mock_vqd.side_effect = ConnectionError("nope")
        b = DuckDuckGo("cats", 10, str(tmp_path), verbose=False)
        # Should not raise
        b.run()
        mock_dl.assert_not_called()


@pytest.mark.skipif(
    os.environ.get("BBID_RUN_NETWORK_TESTS") != "1",
    reason="Set BBID_RUN_NETWORK_TESTS=1 to run live network tests",
)
class TestDuckDuckGoEndToEnd:
    def test_real_fetch(self, tmp_path):
        b = DuckDuckGo("red panda", 2, str(tmp_path), timeout=30, verbose=False)
        b.run()
        # At least one file should have been saved
        files = [p for p in tmp_path.iterdir() if p.is_file() and not p.name.startswith(".")]
        assert len(files) >= 1, f"No images downloaded. Files: {list(tmp_path.iterdir())}"
