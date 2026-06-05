"""Live integration test for the v3.2.0 embeddable API.

Verifies that ``Downloader().search()`` actually returns a populated
``Result`` with ``ImageResult`` objects when run against the real
DuckDuckGo API. Skipped unless ``BBID_RUN_NETWORK_TESTS=1`` is set.
"""

from __future__ import annotations

import os

import pytest

from better_bing_image_downloader import Downloader, ImageResult, Result


@pytest.mark.skipif(
    os.environ.get("BBID_RUN_NETWORK_TESTS") != "1",
    reason="Set BBID_RUN_NETWORK_TESTS=1 to run live network tests",
)
def test_downloader_search_returns_populated_result(tmp_path) -> None:
    """A real DDG search should return a Result with >=1 ImageResult."""
    dl = Downloader()
    seen: list[ImageResult] = []
    dl.on_image = lambda img: seen.append(img)

    result = dl.search("red panda", limit=2, engine="duckduckgo", output_dir=tmp_path, timeout=30)

    assert isinstance(result, Result)
    assert result.query == "red panda"
    assert result.engine == "duckduckgo"
    assert result.count >= 1
    assert all(isinstance(img, ImageResult) for img in result.images)
    assert len(seen) == result.count
    # The on_image hook should fire with the same engine name
    assert all(img.engine == "duckduckgo" for img in result.images)
    # Files should actually exist on disk
    for img in result.images:
        assert img.path.exists()
        assert img.size_bytes > 0
