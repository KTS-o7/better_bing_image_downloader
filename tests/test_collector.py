"""Collector interface: search() wires a session instead of patching (#97)."""

from __future__ import annotations

from better_bing_image_downloader.base import ImageEngine
from better_bing_image_downloader.downloader import Downloader


class _FakeEngine(ImageEngine):
    """Minimal engine that downloads two candidates via the base pipeline."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_collectors = []

    def run(self) -> None:
        for i in (1, 2):
            self.download_image(f"https://img.test/{i}.jpg", self.download_count + 1)

    def _save_image_raising(self, link, file_path) -> str:  # type: ignore[override]
        from pathlib import Path

        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\xff\xd8\xff\xe0fake")
        return "0" * 32


def test_search_sets_collector_not_patches(tmp_path) -> None:
    """search() wires engine.collector; save_image is never monkey-patched."""
    dl = Downloader()
    dl.register("fake", _FakeEngine)
    result = dl.search("cats", limit=2, output_dir=str(tmp_path), engine="fake")
    assert result.count == 2
    assert "save_image" not in result._engine.__dict__
    assert "download_image" not in result._engine.__dict__


def test_collector_reset_after_search(tmp_path) -> None:
    """The engine's collector is cleared when the run finishes."""
    dl = Downloader()
    dl.register("fake", _FakeEngine)
    result = dl.search("cats", limit=2, output_dir=str(tmp_path), engine="fake")
    assert result._engine.collector is None


def test_candidates_counted_through_collector(tmp_path) -> None:
    """Collector-backed runs still report results (not no_results_found)."""
    dl = Downloader()
    dl.register("fake", _FakeEngine)
    result = dl.search("cats", limit=2, output_dir=str(tmp_path), engine="fake")
    assert result.no_results_found is False
    assert result.errors == []
