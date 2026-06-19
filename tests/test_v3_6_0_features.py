"""Tests for v3.6.0's ``min_dimension`` filter.

One new thing in 3.6.0: ``Downloader.search(min_dimension=N)`` skips
any downloaded image smaller than ``N`` pixels on either side, so ML
training-data pipelines don't have to filter thumbnails out of the
manifest themselves.

- New typed exception: ``BelowMinDimension`` (a subclass of
  ``ImageSaveError``, so ``except ImageSaveError`` still catches it).
- New ``Downloader.search`` / ``search_async`` parameter:
  ``min_dimension``.
- Skips are recorded in the manifest as ``status="skipped"``,
  ``error="BelowMinDimension"``, and counted in ``Result.skipped``
  (NOT ``Result.errors`` — a too-small image is an intentional filter
  outcome, not a failure).
- Images in formats we can't measure (e.g. TIFF) are never filtered.

All tests follow the project's existing patterns: mock
``ImageEngine._http_get`` at the module-attribute boundary, no real
network, stub engines registered against a ``Downloader`` instance.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from unittest.mock import patch

from better_bing_image_downloader import BelowMinDimension, Downloader, ImageEngine, ImageSaveError

# --- Byte builders for synthetic images (header-only; no real pixel data) ---


def _make_png(width: int, height: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"
    return sig + chunk


def _make_gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 4


def _make_bmp(width: int, height: int) -> bytes:
    header = b"BM" + b"\x00" * 8 + b"\x00\x00\x00\x00"
    dib = struct.pack("<IiiHH", 40, width, height, 1, 24) + b"\x00" * 20
    return header + dib


def _make_jpeg(width: int, height: int) -> bytes:
    soi = b"\xff\xd8"
    app0 = (
        b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00\x01\x01\x00"
        + struct.pack(">HH", 1, 1)
        + b"\x00\x00"
    )
    sof0_payload = (
        struct.pack(">BHHB", 8, height, width, 3)
        + b"\x01\x11\x00"
        + b"\x02\x11\x01"
        + b"\x03\x11\x01"
    )
    sof0 = b"\xff\xc0" + struct.pack(">H", len(sof0_payload) + 2) + sof0_payload
    return soi + app0 + sof0 + b"\xff\xd9"


def _make_webp_vp8x(width: int, height: int) -> bytes:
    payload = (
        b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    )
    chunk = b"VP8X" + struct.pack("<I", len(payload)) + payload
    riff_payload = b"WEBP" + chunk
    return b"RIFF" + struct.pack("<I", len(riff_payload)) + riff_payload


def _make_tiff() -> bytes:
    # Recognized as image/tiff by ``filetype``, but our dimension
    # reader doesn't parse TIFF's IFD structure, so this always
    # yields ``None`` from ``_read_image_dimensions``.
    return b"II*\x00" + b"\x00" * 20


# --- Group A: BelowMinDimension exception (1 test) ---


def test_below_min_dimension_is_image_save_error_subclass() -> None:
    """BelowMinDimension is an ImageSaveError (Liskov substitution)."""
    assert issubclass(BelowMinDimension, ImageSaveError)
    exc = BelowMinDimension(url="https://x/a.jpg", width=10, height=10, min_dimension=50)
    assert isinstance(exc, ImageSaveError)
    assert exc.width == 10
    assert exc.height == 10
    assert exc.min_dimension == 50


# --- Group B: _read_image_dimensions unit tests (6 tests) ---


def test_read_image_dimensions_png() -> None:
    from better_bing_image_downloader.base import _read_image_dimensions

    assert _read_image_dimensions(_make_png(800, 600)) == (800, 600)


def test_read_image_dimensions_gif() -> None:
    from better_bing_image_downloader.base import _read_image_dimensions

    assert _read_image_dimensions(_make_gif(320, 240)) == (320, 240)


def test_read_image_dimensions_bmp() -> None:
    from better_bing_image_downloader.base import _read_image_dimensions

    assert _read_image_dimensions(_make_bmp(640, 480)) == (640, 480)


def test_read_image_dimensions_jpeg() -> None:
    from better_bing_image_downloader.base import _read_image_dimensions

    assert _read_image_dimensions(_make_jpeg(800, 600)) == (800, 600)


def test_read_image_dimensions_webp() -> None:
    from better_bing_image_downloader.base import _read_image_dimensions

    assert _read_image_dimensions(_make_webp_vp8x(800, 600)) == (800, 600)


def test_read_image_dimensions_unknown_or_malformed_returns_none() -> None:
    from better_bing_image_downloader.base import _read_image_dimensions

    assert _read_image_dimensions(_make_tiff()) is None
    assert _read_image_dimensions(b"not an image at all") is None
    assert _read_image_dimensions(b"") is None


# --- Group C: Downloader.search(min_dimension=...) integration (6 tests) ---


def _make_dimension_stub() -> type[ImageEngine]:
    """A stub engine that downloads two URLs: 'small' and 'large'."""

    class DimensionStub(ImageEngine):
        def run(self) -> None:
            self.download_image("https://example.test/small.png", 1)
            self.download_image("https://example.test/large.png", 2)

    return DimensionStub


def test_search_min_dimension_none_is_noop(tmp_path: Path) -> None:
    """Without min_dimension, both a tiny and a large image are saved."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_dimension_stub())

    def fake_http_get(self, url, headers=None):
        if "small" in url:
            return _make_png(10, 10)
        return _make_png(800, 600)

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=2, engine="stub", output_dir=tmp_path)

    assert result.count == 2
    assert result.skipped == 0
    assert result.errors == []


def test_search_min_dimension_skips_small_image(tmp_path: Path) -> None:
    """An image below min_dimension is skipped, not saved, not an error."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_dimension_stub())

    error_calls = []
    dl.on_error = lambda url, exc: error_calls.append((url, exc))

    def fake_http_get(self, url, headers=None):
        if "small" in url:
            return _make_png(10, 10)
        return _make_png(800, 600)

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=2, engine="stub", output_dir=tmp_path, min_dimension=200)

    assert result.count == 1
    assert result.images[0].source_url == "https://example.test/large.png"
    assert result.skipped == 1
    # A min_dimension skip is NOT an error: no Result.errors entry, no
    # on_error call.
    assert result.errors == []
    assert error_calls == []


def test_search_min_dimension_threshold_is_strict_less_than(tmp_path: Path) -> None:
    """An image exactly at min_dimension passes; one pixel under is skipped."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()

    class ExactStub(ImageEngine):
        def run(self) -> None:
            self.download_image("https://example.test/exact.png", 1)
            self.download_image("https://example.test/under.png", 2)

    dl.register("stub", ExactStub)

    def fake_http_get(self, url, headers=None):
        if "exact" in url:
            return _make_png(200, 200)
        return _make_png(199, 200)

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=2, engine="stub", output_dir=tmp_path, min_dimension=200)

    assert result.count == 1
    assert result.images[0].source_url == "https://example.test/exact.png"
    assert result.skipped == 1


def test_search_min_dimension_unmeasurable_format_not_filtered(tmp_path: Path) -> None:
    """A format we can't read dimensions for (TIFF) is never filtered."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()

    class TiffStub(ImageEngine):
        def run(self) -> None:
            self.download_image("https://example.test/a.tiff", 1)

    dl.register("stub", TiffStub)

    def fake_http_get(self, url, headers=None):
        return _make_tiff()

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        # A huge threshold would reject any real image this small,
        # but since we can't measure TIFF, it must still be saved.
        result = dl.search(
            "cat", limit=1, engine="stub", output_dir=tmp_path, min_dimension=999_999
        )

    assert result.count == 1
    assert result.skipped == 0


def test_search_min_dimension_manifest_records_skip(tmp_path: Path) -> None:
    """manifest=True records the skip as status='skipped', error='BelowMinDimension'."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_dimension_stub())

    def fake_http_get(self, url, headers=None):
        if "small" in url:
            return _make_png(10, 10)
        return _make_png(800, 600)

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search(
            "cat",
            limit=2,
            engine="stub",
            output_dir=tmp_path,
            min_dimension=200,
            manifest=True,
        )

    lines = Path(result.manifest_path).read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert len(records) == 2
    statuses = {r["url"]: r["status"] for r in records}
    errors = {r["url"]: r["error"] for r in records}
    assert statuses["https://example.test/small.png"] == "skipped"
    assert errors["https://example.test/small.png"] == "BelowMinDimension"
    assert statuses["https://example.test/large.png"] == "ok"
    assert errors["https://example.test/large.png"] is None


def test_search_async_honors_min_dimension(tmp_path: Path) -> None:
    """search_async forwards min_dimension the same way search() does."""
    import asyncio

    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_dimension_stub())

    def fake_http_get(self, url, headers=None):
        if "small" in url:
            return _make_png(10, 10)
        return _make_png(800, 600)

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = asyncio.run(
            dl.search_async("cat", limit=2, engine="stub", output_dir=tmp_path, min_dimension=200)
        )

    assert result.count == 1
    assert result.skipped == 1
