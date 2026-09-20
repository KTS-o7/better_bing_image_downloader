"""Dedicated tests for results.py value objects (#81)."""

from __future__ import annotations

from pathlib import Path

import pytest

from better_bing_image_downloader.results import ImageResult, Result


def _img(**over) -> ImageResult:
    args = {
        "path": Path("dataset/cats/Image_1.jpg"),
        "source_url": "https://example.com/1.jpg",
        "engine": "bing",
        "query": "cats",
        "image_index": 1,
        "size_bytes": 100,
        "mime_type": "image/jpeg",
    }
    args.update(over)
    return ImageResult(**args)


def test_image_result_defaults_caption_none() -> None:
    assert _img().caption is None


def test_image_result_immutable_and_hashable() -> None:
    img = _img()
    with pytest.raises(AttributeError):
        img.query = "dogs"  # type: ignore[misc]
    assert hash(img) == hash(_img())
    assert len({img, _img()}) == 1


def test_result_defaults() -> None:
    r = Result(query="cats", engine="bing", output_dir=Path("dataset/cats"))
    assert r.images == []
    assert r.skipped == 0
    assert r.errors == []
    assert r.no_results_found is False
    assert r.cancelled is False
    assert r.manifest_path is None
    assert r.count == 0
    assert r.total_bytes == 0
    assert r.engine_instance() is None


def test_result_count_and_total_bytes() -> None:
    r = Result(
        query="cats",
        engine="bing",
        output_dir=Path("dataset/cats"),
        images=[_img(size_bytes=100), _img(image_index=2, size_bytes=50)],
    )
    assert r.count == 2
    assert r.total_bytes == 150


def test_result_repr_flags_and_manifest() -> None:
    r = Result(query="cats", engine="bing", output_dir=Path("d"))
    assert "count=0" in repr(r)
    assert "no manifest" in repr(r)
    r2 = Result(
        query="cats",
        engine="bing",
        output_dir=Path("d"),
        no_results_found=True,
        cancelled=True,
        manifest_path="/tmp/manifest.jsonl",
    )
    text = repr(r2)
    assert "no_results_found" in text and "cancelled" in text
    assert "/tmp/manifest.jsonl" in text


def test_result_copies_input_lists() -> None:
    images = [_img()]
    errors = [("https://x/1.jpg", ValueError("boom"))]
    r = Result(query="c", engine="b", output_dir=Path("d"), images=images, errors=errors)
    images.append(_img(image_index=2))
    assert r.count == 1
