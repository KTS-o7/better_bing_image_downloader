"""Tests for v3.4.0 features.

Three new things in 3.4.0:

1. Typed ``ImageSaveError`` subclasses: ``NetworkError``,
   ``InvalidImageError``, ``DuplicateImageError``, ``WriteError``.
   Resolves the 3.2.1 TODO: callers can now distinguish failure
   reasons without parsing the ``reason`` string.

2. ``on_progress`` hook on ``Downloader``: fires after each
   download with ``(percent, downloaded, total, eta_seconds)``.
   Powers progress bars and ETA displays without forcing users
   to compute them from ``on_image`` timing.

3. ``Downloader.search_async()``: async wrapper around the
   blocking ``search()``. Runs the existing engine in a thread
   via ``asyncio.to_thread()`` so it works with the stdlib-only
   urllib-based engines. Returns the same ``Result``.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import patch

from better_bing_image_downloader import Downloader, ImageEngine
from better_bing_image_downloader.downloader import (
    DuplicateImageError,
    ImageSaveError,
    InvalidImageError,
    NetworkError,
    WriteError,
)

# --- Issue 1: typed ImageSaveError subclasses ---


def test_image_save_error_subclasses_exist() -> None:
    """All four typed subclasses are importable from downloader."""
    for cls in (NetworkError, InvalidImageError, DuplicateImageError, WriteError):
        assert issubclass(cls, ImageSaveError)


def test_network_error_classifies_http_failure(tmp_path: Path) -> None:
    """A network error in _http_get is classified as NetworkError."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            self.download_image("https://example.test/1.jpg", 1)

    def fake_http_get(self, url, headers=None):
        import urllib.error

        raise urllib.error.URLError("network down")

    dl = Downloader()
    dl.register("fake", FakeEngine)

    error_calls = []
    dl.on_error = lambda url, exc: error_calls.append((url, type(exc).__name__))

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=1, engine="fake", output_dir=tmp_path)

    # The error should be classified as NetworkError, not the generic
    # ImageSaveError.
    assert len(error_calls) == 1
    assert error_calls[0][1] == "NetworkError"
    assert any(isinstance(e, NetworkError) for _, e in result.errors)


def test_invalid_image_error_classifies_bad_mime(tmp_path: Path) -> None:
    """Bytes that don't look like an image are classified as InvalidImageError."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            self.download_image("https://example.test/1.jpg", 1)

    def fake_http_get(self, url, headers=None):
        return b"this is not an image at all"

    dl = Downloader()
    dl.register("fake", FakeEngine)

    error_calls = []
    dl.on_error = lambda url, exc: error_calls.append((url, type(exc).__name__))

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=1, engine="fake", output_dir=tmp_path)

    assert len(error_calls) == 1
    assert error_calls[0][1] == "InvalidImageError"
    assert any(isinstance(e, InvalidImageError) for _, e in result.errors)


def test_duplicate_image_error_classifies_same_md5(tmp_path: Path) -> None:
    """Two URLs with the same body are classified as DuplicateImageError."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            self.download_image("https://example.test/1.jpg", 1)
            self.download_image("https://example.test/2.jpg", 2)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0same bytes"

    dl = Downloader()
    dl.register("fake", FakeEngine)

    error_calls = []
    dl.on_error = lambda url, exc: error_calls.append((url, type(exc).__name__))

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=2, engine="fake", output_dir=tmp_path)

    urls_in_errors = {u for u, _ in result.errors}
    assert "https://example.test/2.jpg" in urls_in_errors
    # The second URL must be a DuplicateImageError (same MD5 as first).
    err_by_url = dict(result.errors)
    assert isinstance(err_by_url["https://example.test/2.jpg"], DuplicateImageError)


def test_image_save_error_catch_all_subclass_relationship() -> None:
    """A user can catch ImageSaveError to handle all save failures."""
    # All four subclasses are ImageSaveError.
    assert issubclass(NetworkError, ImageSaveError)
    assert issubclass(InvalidImageError, ImageSaveError)
    assert issubclass(DuplicateImageError, ImageSaveError)
    assert issubclass(WriteError, ImageSaveError)


# --- Issue 2: on_progress hook ---


def test_on_progress_hook_fires_per_image(tmp_path: Path) -> None:
    """on_progress is called after each successful download."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1, 4):
                self.download_image(f"https://example.test/{i}.jpg", i)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    dl = Downloader()
    dl.register("fake", FakeEngine)

    progress_calls = []
    dl.on_progress = lambda pct, done, total, eta: progress_calls.append((pct, done, total, eta))

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        dl.search("cat", limit=3, engine="fake", output_dir=tmp_path)

    # Should have fired 3 times (one per image)
    assert len(progress_calls) == 3
    # First call: 1/3 = 33.33%, no ETA yet
    pct, done, total, eta = progress_calls[0]
    assert done == 1
    assert total == 3
    assert abs(pct - 33.33) < 0.5
    # Last call: 3/3 = 100%
    pct, done, total, eta = progress_calls[-1]
    assert done == 3
    assert pct == 100.0


def test_on_progress_eta_is_none_until_enough_samples(tmp_path: Path) -> None:
    """ETA is None for the first call (no timing data yet)."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1, 3):
                self.download_image(f"https://example.test/{i}.jpg", i)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    dl = Downloader()
    dl.register("fake", FakeEngine)

    progress_calls = []
    dl.on_progress = lambda pct, done, total, eta: progress_calls.append(eta)

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        dl.search("cat", limit=2, engine="fake", output_dir=tmp_path)

    # First call: no ETA. Second call: ETA may be a number (or None if
    # the second download was instantaneous).
    assert progress_calls[0] is None


def test_on_progress_exception_does_not_crash_search(tmp_path: Path) -> None:
    """A buggy progress hook must not abort the run."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1, 3):
                self.download_image(f"https://example.test/{i}.jpg", i)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    dl = Downloader()
    dl.register("fake", FakeEngine)

    def bad_hook(*args) -> None:
        raise ValueError("progress hook blew up")

    dl.on_progress = bad_hook

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        # Should not raise even though the hook raises on every call.
        result = dl.search("cat", limit=2, engine="fake", output_dir=tmp_path)

    assert result.count == 2


# --- Issue 3: async search() ---


def test_search_async_returns_result(tmp_path: Path) -> None:
    """search_async returns a Result just like search()."""
    dl = Downloader()

    class StubEngine(ImageEngine):
        def run(self) -> None:
            pass

    dl.register("stub", StubEngine)
    result = asyncio.run(dl.search_async("cat", limit=0, engine="stub", output_dir=tmp_path))
    assert result.query == "cat"
    assert result.engine == "stub"


def test_search_async_fires_hooks(tmp_path: Path) -> None:
    """Hooks work the same in async search()."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1, 3):
                self.download_image(f"https://example.test/{i}.jpg", i)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    dl = Downloader()
    dl.register("fake", FakeEngine)
    collected = []
    dl.on_image = lambda img: collected.append(img)

    async def go():
        return await dl.search_async("cat", limit=2, engine="fake", output_dir=tmp_path)

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = asyncio.run(go())

    assert result.count == 2
    assert len(collected) == 2


def test_search_async_honors_cancel_token(tmp_path: Path) -> None:
    """CancelToken works the same in async search()."""
    from better_bing_image_downloader.downloader import CancelToken

    dl = Downloader()

    class CooperativeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1000):
                if self.is_cancelled():
                    return
                time.sleep(0.005)
                self.download_count = i
                self._slots_used = i

    dl.register("coop", CooperativeEngine)
    token = CancelToken()

    def cancel():
        time.sleep(0.05)
        token.cancel()

    import threading

    threading.Thread(target=cancel).start()

    async def go():
        return await dl.search_async(
            "cat", limit=1000, engine="coop", output_dir=tmp_path, cancel=token
        )

    result = asyncio.run(go())
    assert result.cancelled is True
    assert result.count < 1000
