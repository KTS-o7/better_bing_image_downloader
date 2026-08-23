"""Tests for v3.9.0 caption capture (image–text pairs).

Bing surfaces a result title in the ``m`` attribute's JSON (``t``
field); DuckDuckGo surfaces ``title`` in its ``i.js`` results. The
caption flows into ``ImageResult.caption`` and the manifest's
``caption`` field.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from better_bing_image_downloader import Downloader, ImageResult
from better_bing_image_downloader.bing import Bing
from better_bing_image_downloader.duckduckgo import DuckDuckGo


def _bing_result_blob(url: str, title: str | None) -> str:
    """Build one Bing result anchor with an HTML-escaped m JSON blob."""
    meta = {"murl": url}
    if title is not None:
        meta["t"] = title
    escaped = json.dumps(meta, separators=(",", ":")).replace('"', "&quot;")
    return f'<a class="iusc" m="{escaped}">'


class TestBingCaptionExtraction:
    def test_extract_captions_parses_titles(self) -> None:
        html = _bing_result_blob("https://img.test/1.jpg", "A red panda") + _bing_result_blob(
            "https://img.test/2.jpg", "Red panda eating bamboo"
        )
        captions = Bing._extract_captions(html)
        assert captions == {
            "https://img.test/1.jpg": "A red panda",
            "https://img.test/2.jpg": "Red panda eating bamboo",
        }

    def test_extract_captions_skips_results_without_title(self) -> None:
        html = _bing_result_blob("https://img.test/1.jpg", None)
        assert Bing._extract_captions(html) == {}

    def test_extract_captions_tolerates_malformed_json(self) -> None:
        html = '<a class="iusc" m="{&quot;murl&quot;:&quot;broken'
        assert Bing._extract_captions(html) == {}

    def test_extract_links_unchanged_by_caption_support(self) -> None:
        html = _bing_result_blob("https://img.test/1.jpg", "A red panda")
        assert Bing._extract_links(html) == ["https://img.test/1.jpg"]


class TestDuckDuckGoCaptionExtraction:
    @patch("urllib.request.build_opener")
    def test_fetch_page_populates_captions(self, mock_build_opener, tmp_path) -> None:
        payload = {
            "results": [
                {"image": "https://example.com/a.jpg", "title": "Cat on a mat"},
                {"image": "https://example.com/b.png"},  # no title
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode()
        mock_resp.headers.get.return_value = ""
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        mock_build_opener.return_value = mock_opener

        d = DuckDuckGo("cats", 10, str(tmp_path))
        urls = d._fetch_page("vqd-token", 0)

        assert urls == ["https://example.com/a.jpg", "https://example.com/b.png"]
        assert d.captions == {"https://example.com/a.jpg": "Cat on a mat"}


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


class TestCaptionEndToEnd:
    def test_caption_reaches_image_result_and_manifest(self, monkeypatch, tmp_path) -> None:
        """A full Bing search (network stubbed) puts captions into both
        ImageResult objects and manifest.jsonl records."""

        def fake_urlopen(request, timeout=None):
            url = getattr(request, "full_url", request)
            if "bing.com/images/async" in url:
                body = (
                    _bing_result_blob("https://img.test/1.jpg", "A red panda")
                    + _bing_result_blob("https://img.test/2.jpg", "Red panda eating bamboo")
                ).encode()
            else:
                body = b"\xff\xd8\xff\xe0" + str(url).encode()
            return _FakeHttpResponse(body)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        seen: list[ImageResult] = []
        dl = Downloader()
        dl.on_image = seen.append
        result = dl.search("red panda", limit=2, output_dir=tmp_path, manifest=True)

        assert result.count == 2
        captions = sorted(img.caption for img in seen)
        assert captions == ["A red panda", "Red panda eating bamboo"]

        assert result.manifest_path is not None
        with open(result.manifest_path, encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
        assert len(records) == 2
        assert sorted(r["caption"] for r in records) == [
            "A red panda",
            "Red panda eating bamboo",
        ]

    def test_caption_is_none_when_engine_provides_none(self, monkeypatch, tmp_path) -> None:
        """Pages without title metadata still work; caption is null."""

        def fake_urlopen(request, timeout=None):
            url = getattr(request, "full_url", request)
            if "bing.com/images/async" in url:
                body = _bing_result_blob("https://img.test/1.jpg", None).encode()
            else:
                body = b"\xff\xd8\xff\xe0" + str(url).encode()
            return _FakeHttpResponse(body)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        result = Downloader().search("red panda", limit=1, output_dir=tmp_path, manifest=True)
        assert result.count == 1
        assert result.images[0].caption is None


class TestImageResultBackwardsCompat:
    def test_image_result_default_caption_is_none(self, tmp_path: Path) -> None:
        """Constructing ImageResult with the pre-3.9.0 7-arg form works."""
        ir = ImageResult(
            path=tmp_path / "Image_1.jpg",
            source_url="https://example.com/a.jpg",
            engine="bing",
            query="cats",
            image_index=1,
            size_bytes=10,
            mime_type="image/jpeg",
        )
        assert ir.caption is None
