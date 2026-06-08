"""Tests for v3.3.0 features.

Two new things in 3.3.0:

1. ``Result.no_results_found`` is ``True`` when the engine reported
   it ran zero pages with zero images — meaning the search backend
   returned no candidates, not that all candidates were skipped
   (resume case) or that downloads failed (errors case).

2. ``Downloader.cancel()`` can stop a running ``search()`` mid-flight
   by setting a flag the engines check between page fetches and
   between image downloads. The partial ``Result`` is returned.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

from better_bing_image_downloader import Downloader, ImageEngine

# --- Issue 1: no_results_found ---


def test_no_results_found_true_when_engine_ran_zero_pages(tmp_path: Path) -> None:
    """An engine that finds no candidates should set no_results_found=True."""
    dl = Downloader()

    class EmptyEngine(ImageEngine):
        def run(self) -> None:
            # Don't call download_image at all — engine is "empty"
            pass

    dl.register("empty", EmptyEngine)
    result = dl.search("cat", limit=5, engine="empty", output_dir=tmp_path)

    assert result.count == 0
    assert result.skipped == 0
    assert len(result.errors) == 0
    assert result.no_results_found is True


def test_no_results_found_false_when_images_downloaded(tmp_path: Path) -> None:
    """A successful search must NOT set no_results_found."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()

    class GoodEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1, 3):
                self.download_image(f"https://example.test/{i}.jpg", i)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    dl.register("good", GoodEngine)
    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=2, engine="good", output_dir=tmp_path)

    assert result.count == 2
    assert result.no_results_found is False


def test_no_results_found_false_when_all_skipped(tmp_path: Path) -> None:
    """A resume case (all candidates already on disk) must not set no_results_found."""
    # Pre-populate the output dir with files that the engine "would have" downloaded
    out = tmp_path / "cat"
    out.mkdir()
    (out / "Image_1.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")
    (out / "Image_2.jpg").write_bytes(b"\xff\xd8\xff\xe0fake")

    dl = Downloader()

    class AlwaysResumeEngine(ImageEngine):
        def run(self) -> None:
            # download_image() with existing file returns 0 (skipped)
            self.download_image("https://example.test/1.jpg", 1)
            self.download_image("https://example.test/2.jpg", 2)

    dl.register("always", AlwaysResumeEngine)
    result = dl.search("cat", limit=2, engine="always", output_dir=tmp_path)
    # The engine was given 2 candidates; both were skipped because files exist.
    # This is NOT a "no results" case — the engine found results, they were just already on disk.
    assert result.no_results_found is False


# --- Issue 2: cancellation ---


def test_cancel_token_class_exists() -> None:
    """A CancelToken class is the public surface for cancellation."""
    from better_bing_image_downloader.downloader import CancelToken

    tok = CancelToken()
    assert tok.cancelled is False
    tok.cancel()
    assert tok.cancelled is True


def test_search_supports_cancellation_via_token(tmp_path: Path) -> None:
    """A search() call can be aborted mid-run via a CancelToken."""
    from better_bing_image_downloader.downloader import CancelToken

    dl = Downloader()

    state = {"started": False, "iterations": 0}

    class SlowEngine(ImageEngine):
        def run(self) -> None:
            state["started"] = True
            # Pretend to fetch 100 pages. The base class needs us to
            # respect the cancel token (or not), so we just simulate
            # without it — this test will validate the wrapper.
            for i in range(100):
                self.download_count = i
                self._slots_used = i
                state["iterations"] = i

    dl.register("slow", SlowEngine)
    token = CancelToken()
    token.cancel()  # cancel BEFORE the search even starts

    result = dl.search("cat", limit=100, engine="slow", output_dir=tmp_path, cancel=token)
    # The engine never ran, so nothing was downloaded.
    assert result.count == 0
    assert result.cancelled is True


def test_search_can_be_cancelled_mid_run(tmp_path: Path) -> None:
    """A token cancelled mid-run must abort the engine and return a partial result."""
    from better_bing_image_downloader.downloader import CancelToken

    dl = Downloader()

    class CooperativeEngine(ImageEngine):
        def run(self) -> None:
            for i in range(1000):
                if self.is_cancelled():
                    return  # honor the cancel via the base class helper
                time.sleep(0.005)  # simulate work so the cancel can fire
                self.download_count = i
                self._slots_used = i

    dl.register("coop", CooperativeEngine)

    # Use a real CancelToken to abort a long run
    token = CancelToken()

    def canceller():
        time.sleep(0.02)
        token.cancel()

    t = threading.Thread(target=canceller)
    t.start()
    result = dl.search("cat", limit=1000, engine="coop", output_dir=tmp_path, cancel=token)
    t.join()
    # The engine should have stopped early.
    assert result.cancelled is True
    # The download_count is bounded; we just verify it's not 1000.
    assert result.count < 1000


def test_cancelled_result_is_still_well_formed(tmp_path: Path) -> None:
    """A cancelled result has the same shape as a normal result."""
    from better_bing_image_downloader.downloader import CancelToken

    dl = Downloader()
    token = CancelToken()
    token.cancel()

    class NoopEngine(ImageEngine):
        def run(self) -> None:
            if self.is_cancelled():
                return
            # Should never get here in this test

    dl.register("noop", NoopEngine)
    result = dl.search("cat", limit=1, engine="noop", output_dir=tmp_path, cancel=token)

    assert result.cancelled is True
    assert result.query == "cat"
    assert result.engine == "noop"
    assert result.output_dir == tmp_path / "cat"
    assert isinstance(result.images, list)
    assert isinstance(result.errors, list)
    assert isinstance(result.no_results_found, bool)
