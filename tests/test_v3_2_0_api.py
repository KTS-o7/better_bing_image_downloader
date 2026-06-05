"""Tests for v3.2.0 embeddable API.

- New public types: ``Downloader``, ``Result``, ``ImageResult``
- Engine registry: ``Downloader.register(name, cls)``
- Hooks: ``on_image``, ``on_error``, ``on_engine_start``, ``on_engine_done``
- Session reuse: a single ``Downloader`` shares cookies across calls
- Backwards compat: ``downloader(...)`` and the per-engine classes still work
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from better_bing_image_downloader import (
    Bing,
    Downloader,
    DuckDuckGo,
    ImageEngine,
    ImageResult,
    Result,
    downloader,
)

# --- Public API surface ---


def test_downloader_is_importable() -> None:
    assert callable(Downloader)


def test_result_and_image_result_are_importable() -> None:
    assert ImageResult is not None
    assert Result is not None


def test_image_result_is_a_dataclass_like_namedtuple() -> None:
    """ImageResult is a value object: equality, fields, repr."""
    a = ImageResult(
        path=Path("/tmp/x.jpg"),
        source_url="https://example.com/x.jpg",
        engine="bing",
        query="cat",
        image_index=1,
        size_bytes=1024,
        mime_type="image/jpeg",
    )
    b = ImageResult(
        path=Path("/tmp/x.jpg"),
        source_url="https://example.com/x.jpg",
        engine="bing",
        query="cat",
        image_index=1,
        size_bytes=1024,
        mime_type="image/jpeg",
    )
    assert a == b
    assert a.path == Path("/tmp/x.jpg")
    assert a.size_bytes == 1024
    assert repr(a).startswith("ImageResult(")


def test_result_aggregates_images_and_metadata() -> None:
    img1 = ImageResult(
        path=Path("/tmp/1.jpg"),
        source_url="https://a/1.jpg",
        engine="bing",
        query="cat",
        image_index=1,
        size_bytes=100,
        mime_type="image/jpeg",
    )
    img2 = ImageResult(
        path=Path("/tmp/2.jpg"),
        source_url="https://a/2.jpg",
        engine="bing",
        query="cat",
        image_index=2,
        size_bytes=200,
        mime_type="image/jpeg",
    )
    r = Result(
        query="cat",
        engine="bing",
        output_dir=Path("/tmp"),
        images=[img1, img2],
        skipped=0,
        errors=[],
    )
    assert r.query == "cat"
    assert r.engine == "bing"
    assert len(r.images) == 2
    assert r.total_bytes == 300
    assert r.count == 2


# --- Downloader construction ---


def test_downloader_zero_arg_construction() -> None:
    """Downloader() takes no required arguments; everything has a default."""
    dl = Downloader()
    assert dl is not None


def test_downloader_with_session_dir() -> None:
    dl = Downloader(cache_dir=Path(tempfile.gettempdir()) / "bbid_test_cache")
    assert dl.cache_dir is not None


# --- Engine registry ---


def test_downloader_registers_default_engines() -> None:
    """Bing and DuckDuckGo are registered by default."""
    dl = Downloader()
    engines = dl.engines()
    assert "bing" in engines
    assert "duckduckgo" in engines


def test_downloader_register_custom_engine() -> None:
    """Users can plug in their own engine subclass."""
    dl = Downloader()

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            pass

    dl.register("fake", FakeEngine)
    assert "fake" in dl.engines()
    # Buildable through the public API
    inst = dl.build_engine(engine_name="fake", query="x", limit=1, output_dir=Path("/tmp"))
    assert isinstance(inst, FakeEngine)


def test_downloader_build_engine_unknown_raises() -> None:
    dl = Downloader()
    with pytest.raises(ValueError):
        dl.build_engine(engine_name="doesnt-exist", query="x", limit=1, output_dir=Path("/tmp"))


# --- Hooks ---


def test_downloader_hooks_default_to_noop() -> None:
    """Downloader can be constructed without specifying any hooks."""
    dl = Downloader()
    assert dl.on_image is None or callable(dl.on_image)
    assert dl.on_error is None or callable(dl.on_error)


def test_downloader_accepts_callable_hooks() -> None:
    calls: list[ImageResult] = []

    def my_hook(img: ImageResult) -> None:
        calls.append(img)

    dl = Downloader(on_image=my_hook)
    assert dl.on_image is my_hook


# --- Session reuse ---


def test_downloader_has_a_shared_cookie_jar() -> None:
    """A single Downloader shares cookies across engine calls (DDG needs this)."""
    import http.cookiejar

    dl = Downloader()
    assert isinstance(dl.cookie_jar, http.cookiejar.CookieJar)


def test_downloader_has_a_shared_opener() -> None:
    """A single Downloader uses a connection-pooled OpenerDirector."""
    import urllib.request

    dl = Downloader()
    assert isinstance(dl.opener, urllib.request.OpenerDirector)


# --- search() entry point ---


def test_downloader_search_returns_result(tmp_path: Path) -> None:
    """search() should return a Result even when no images download."""
    dl = Downloader()

    # We don't want to hit the network in a unit test; we just check the
    # return type and that it doesn't raise on construction.
    # Use a registry that returns a fake engine with run() as no-op.
    class StubEngine(ImageEngine):
        def run(self) -> None:
            pass

    dl.register("stub", StubEngine)
    result = dl.search("cat", limit=0, engine="stub", output_dir=tmp_path)
    assert isinstance(result, Result)
    assert result.query == "cat"
    assert result.engine == "stub"
    assert result.count == 0


def test_downloader_search_collects_images_via_hook(tmp_path: Path) -> None:
    """on_image hook fires for each download; the result.images list fills up."""
    from unittest.mock import patch

    from better_bing_image_downloader import base as _base

    dl = Downloader()

    # Use a fake engine that goes through the real download_image()
    # pipeline, but with _http_get stubbed to return valid JPEG bytes
    # without touching the network.
    class FakeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1, 3):
                self.download_image(f"https://example.test/{i}.jpg", i)

    def fake_http_get(self, url, headers=None):
        # Return bytes unique per URL so MD5 dedup doesn't collapse them.
        # First two bytes (\xff\xd8) are a valid JPEG SOI marker so
        # filetype.guess() returns image/jpeg.
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    dl.register("fake", FakeEngine)
    collected: list[ImageResult] = []
    dl.on_image = lambda img: collected.append(img)

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=2, engine="fake", output_dir=tmp_path)

    assert result.count == 2
    assert len(collected) == 2
    assert all(isinstance(c, ImageResult) for c in collected)
    assert collected[0].engine == "fake"


# --- Backwards compatibility ---


def test_legacy_downloader_function_still_works(tmp_path: Path) -> None:
    """The module-level downloader() function is preserved (delegates to Downloader)."""
    import inspect

    sig = inspect.signature(downloader)
    # query is the only required parameter
    required = [
        p.name
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    assert required == ["query"]


def test_legacy_bing_class_still_works(tmp_path: Path) -> None:
    b = Bing("cat", 1, tmp_path)
    assert b.query == "cat"
    assert b.adult == "moderate"


def test_legacy_duckduckgo_class_still_works(tmp_path: Path) -> None:
    d = DuckDuckGo("cat", 1, tmp_path)
    assert d.query == "cat"
    assert d.safe_search == "moderate"
