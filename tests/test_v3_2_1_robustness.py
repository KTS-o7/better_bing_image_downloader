"""Tests for v3.2.1 robustness fixes.

Two real issues and two regression-pin tests:

1. ``on_image`` / ``on_error`` exception safety: a buggy user
   hook must not abort the run. (Regression test — already worked
   in 3.2.0 but the audit wasn't sure.)
2. Thread-safe ``Downloader``: concurrent ``search()`` calls and
   concurrent ``register()`` calls must not corrupt state.
   (Regression test.)
3. ``save_image`` returning ``False`` (network failure, invalid
   image, duplicate) was not surfaced via ``on_error`` or
   ``Result.errors`` — silent data loss. This is the real bug
   fixed in 3.2.1.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

from better_bing_image_downloader import Downloader, ImageEngine, ImageResult

# --- Issue 1: on_image exception safety ---


def test_on_image_exception_does_not_crash_search(tmp_path: Path) -> None:
    """A buggy user hook must not abort the run."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1, 3):
                self.download_image(f"https://example.test/{i}.jpg", i)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    dl = Downloader()
    dl.register("fake", FakeEngine)

    call_count = 0

    def bad_hook(img: ImageResult) -> None:
        nonlocal call_count
        call_count += 1
        raise ValueError("user hook blew up")

    dl.on_image = bad_hook

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=2, engine="fake", output_dir=tmp_path)

    # The hook was called for both images despite raising.
    assert call_count == 2
    # The Result should still have both images recorded.
    assert result.count == 2
    # The exception was logged but did not propagate.
    assert all(isinstance(img, ImageResult) for img in result.images)


def test_on_error_exception_does_not_crash_search(tmp_path: Path) -> None:
    """A buggy on_error hook must not abort the run."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1, 3):
                self.download_image(f"https://example.test/{i}.jpg", i)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    dl = Downloader()
    dl.register("fake", FakeEngine)

    def bad_error_hook(url: str, exc: BaseException) -> None:
        raise RuntimeError("user error hook blew up")

    dl.on_error = bad_error_hook

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        # Should not raise even though on_error raises on every call.
        result = dl.search("cat", limit=2, engine="fake", output_dir=tmp_path)

    assert result.count == 2


# --- Issue 2: Thread-safe Downloader ---


def test_downloader_concurrent_search_does_not_corrupt_state(tmp_path: Path) -> None:
    """Multiple threads using one Downloader must not corrupt the result."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1, 3):
                self.download_image(f"https://example.test/{i}.jpg", i)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    dl = Downloader()
    dl.register("fake", FakeEngine)

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        # Run 5 concurrent searches on one Downloader with different
        # output dirs to avoid filename collisions.
        results = []
        errors = []

        def worker(i: int) -> None:
            try:
                r = dl.search(
                    f"q{i}",
                    limit=2,
                    engine="fake",
                    output_dir=tmp_path / f"thread_{i}",
                )
                results.append(r)
            except Exception as exc:
                errors.append((i, exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert errors == [], f"Concurrent search raised: {errors}"
    assert len(results) == 5
    assert all(r.count == 2 for r in results)


def test_downloader_concurrent_register_is_safe() -> None:
    """Concurrent register() calls from many threads must not lose updates."""
    dl = Downloader()

    class E(ImageEngine):
        def run(self) -> None:
            pass

    def worker(i: int) -> None:
        dl.register(f"eng_{i}", E)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    engines = dl.engines()
    # All 50 registrations should be present (plus bing/duckduckgo).
    registered = [name for name in engines if name.startswith("eng_")]
    assert len(registered) == 50, f"Lost registrations: {registered}"


# --- Issue 3: save_image=False surfaces as on_error / Result.errors ---


def test_save_image_returning_false_calls_on_error(tmp_path: Path) -> None:
    """A failed save (network/invalid/duplicate) must call on_error."""
    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            # 1st call succeeds, 2nd call returns invalid bytes (filetype
            # will reject it), 3rd is a duplicate of the 1st.
            self.download_image("https://example.test/1.jpg", 1)
            self.download_image("https://example.test/2.jpg", 2)
            self.download_image("https://example.test/3.jpg", 3)

    bytes_per_url: dict[str, bytes] = {
        "https://example.test/1.jpg": b"\xff\xd8\xff\xe0one",
        "https://example.test/2.jpg": b"not an image at all",
        "https://example.test/3.jpg": b"\xff\xd8\xff\xe0one",  # duplicate of 1
    }

    def fake_http_get(self, url, headers=None):
        return bytes_per_url[url]

    dl = Downloader()
    dl.register("fake", FakeEngine)

    error_calls: list[tuple[str, str]] = []
    dl.on_error = lambda url, exc: error_calls.append((url, type(exc).__name__))

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=3, engine="fake", output_dir=tmp_path)

    # on_error should have fired for the invalid image and the duplicate.
    error_urls = {u for u, _ in error_calls}
    assert "https://example.test/2.jpg" in error_urls
    assert "https://example.test/3.jpg" in error_urls

    # Result.errors should also reflect these failures.
    result_error_urls = {u for u, _ in result.errors}
    assert "https://example.test/2.jpg" in result_error_urls
    assert "https://example.test/3.jpg" in result_error_urls

    # But the valid image still got saved.
    assert result.count == 1


def test_network_error_calls_on_error(tmp_path: Path) -> None:
    """A network failure in _http_get must also surface as on_error.

    The base ``save_image`` catches ``URLError`` and returns ``False``;
    the ``Downloader.search`` wrapper converts that to an
    ``ImageSaveError`` so users see a uniform failure signal.
    """
    import urllib.error

    from better_bing_image_downloader import base as _base

    class FakeEngine(ImageEngine):
        def run(self) -> None:
            self.download_image("https://example.test/1.jpg", 1)

    def fake_http_get(self, url, headers=None):
        raise urllib.error.URLError("network down")

    dl = Downloader()
    dl.register("fake", FakeEngine)

    error_calls: list[tuple[str, str]] = []
    dl.on_error = lambda url, exc: error_calls.append((url, type(exc).__name__))

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=1, engine="fake", output_dir=tmp_path)

    assert len(error_calls) == 1
    assert error_calls[0][0] == "https://example.test/1.jpg"
    # The error type is ImageSaveError (the wrapper's control-flow
    # exception). The underlying URLError is logged inside save_image
    # but not propagated — that's an intentional design choice to
    # keep the save_image contract stable across releases.
    assert error_calls[0][1] == "ImageSaveError"
    assert result.count == 0
    assert len(result.errors) == 1
