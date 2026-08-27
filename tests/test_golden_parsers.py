"""Golden-file parser tests (issue #66).

Recorded representative responses from both engines pin the parser
contract: if someone refactors ``_extract_links`` / ``_extract_captions``
(Bing) or the ``i.js`` parsing (DuckDuckGo) and breaks extraction,
these tests fail without needing the network.

If the *live* endpoints change their layout instead, the weekly canary
workflow (``.github/workflows/canary.yml``) catches it and these
fixtures should be regenerated to match the new reality.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from better_bing_image_downloader.bing import Bing
from better_bing_image_downloader.duckduckgo import DuckDuckGo

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_URLS = [
    "https://example.test/images/red-panda-1.jpg",
    "https://example.test/images/red-panda-2.png",
    "https://example.test/images/red-panda-3.webp",
]

EXPECTED_CAPTIONS = {
    "https://example.test/images/red-panda-1.jpg": "Red panda climbing a tree",
    "https://example.test/images/red-panda-2.png": "Red panda eating bamboo",
    # result 3 deliberately has no title
}


class TestBingGoldenPage:
    html = (FIXTURES / "bing_page.html").read_text(encoding="utf-8")

    def test_extract_links_matches_golden_page(self) -> None:
        assert Bing._extract_links(self.html) == EXPECTED_URLS

    def test_extract_captions_matches_golden_page(self) -> None:
        assert Bing._extract_captions(self.html) == EXPECTED_CAPTIONS


class TestDuckDuckGoGoldenPage:
    @patch("urllib.request.build_opener")
    def test_fetch_page_matches_golden_fixture(self, mock_build_opener, tmp_path) -> None:
        body = (FIXTURES / "ddg_page.json").read_bytes()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.headers.get.return_value = ""
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        mock_build_opener.return_value = mock_opener

        d = DuckDuckGo("red panda", 10, str(tmp_path))
        urls = d._fetch_page("vqd-token", 0)

        assert urls == EXPECTED_URLS
        assert d.captions == EXPECTED_CAPTIONS


class TestGoldenFixturesAligned:
    """Both fixtures describe the same three results — drift between
    them would make the per-engine assertions incomparable."""

    def test_fixtures_describe_same_urls(self) -> None:
        bing_urls = Bing._extract_links((FIXTURES / "bing_page.html").read_text(encoding="utf-8"))
        ddg = json.loads((FIXTURES / "ddg_page.json").read_text(encoding="utf-8"))
        ddg_urls = [r["image"] for r in ddg["results"]]
        assert bing_urls == ddg_urls


class _FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers: dict = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *exc) -> bool:
        return False


class TestEndpointDriftWarning:
    """A page that fetches fine but parses to zero links must emit a
    distinctive 'layout may have changed' warning (issue #66)."""

    def test_bing_warns_when_page_yields_no_links(self, monkeypatch, tmp_path, caplog) -> None:
        import logging
        import urllib.request

        monkeypatch.setattr(
            urllib.request,
            "urlopen",
            lambda request, timeout=None: _FakeHttpResponse(b"<html>unexpected layout</html>"),
        )
        engine = Bing("cats", 1, str(tmp_path))
        with caplog.at_level(logging.WARNING):
            engine.run()
        assert any("layout may have changed" in r.message for r in caplog.records)

    def test_duckduckgo_warns_when_page_yields_no_links(self, tmp_path, caplog) -> None:
        import logging

        with (
            patch.object(DuckDuckGo, "_fetch_vqd", return_value="vqd"),
            patch.object(DuckDuckGo, "_fetch_page", return_value=[]),
            patch.object(DuckDuckGo, "download_image"),
        ):
            engine = DuckDuckGo("cats", 10, str(tmp_path), verbose=False)
            with caplog.at_level(logging.WARNING):
                engine.run()
        assert any("layout may have changed" in r.message for r in caplog.records), [
            r.message for r in caplog.records
        ]
