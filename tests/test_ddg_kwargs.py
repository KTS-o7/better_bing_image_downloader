"""Warn when Bing-only kwargs are passed with engine='duckduckgo' (#78)."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock, patch

from better_bing_image_downloader.downloader import Downloader


def _mock_registry():
    mock_cls = MagicMock()
    mock_instance = mock_cls.return_value
    mock_instance.download_count = 0
    mock_instance._slots_used = 0
    mock_instance.seen = set()
    mock_instance.manifest = {}
    mock_instance.captions = {}
    mock_instance.run = MagicMock()
    return mock_cls


def test_ddg_with_license_warns(tmp_path) -> None:
    """license= with engine=duckduckgo warns (Bing-only, ignored)."""
    mock_cls = _mock_registry()
    with (
        patch.object(Downloader, "_DEFAULT_REGISTRY", {"bing": mock_cls, "duckduckgo": mock_cls}),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        Downloader().search(
            "cats",
            limit=1,
            output_dir=str(tmp_path),
            engine="duckduckgo",
            license="public",
        )
    assert any("license" in str(w.message) for w in caught), [str(w.message) for w in caught]


def test_ddg_defaults_no_warning(tmp_path) -> None:
    """Default kwargs with engine=duckduckgo stay silent."""
    mock_cls = _mock_registry()
    with (
        patch.object(Downloader, "_DEFAULT_REGISTRY", {"bing": mock_cls, "duckduckgo": mock_cls}),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        Downloader().search("cats", limit=1, output_dir=str(tmp_path), engine="duckduckgo")
    bing_only = [w for w in caught if "duckduckgo" in str(w.message).lower()]
    assert bing_only == []


def test_ddg_with_image_filter_warns(tmp_path) -> None:
    """image_filter= with engine=duckduckgo warns."""
    mock_cls = _mock_registry()
    with (
        patch.object(Downloader, "_DEFAULT_REGISTRY", {"bing": mock_cls, "duckduckgo": mock_cls}),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        Downloader().search(
            "cats",
            limit=1,
            output_dir=str(tmp_path),
            engine="duckduckgo",
            image_filter="photo",
        )
    assert any("image_filter" in str(w.message) for w in caught)


def test_bing_with_license_no_warning(tmp_path) -> None:
    """license= with engine=bing stays silent."""
    mock_cls = _mock_registry()
    with (
        patch.object(Downloader, "_DEFAULT_REGISTRY", {"bing": mock_cls, "duckduckgo": mock_cls}),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        Downloader().search(
            "cats",
            limit=1,
            output_dir=str(tmp_path),
            engine="bing",
            license="public",
        )
    bing_only = [w for w in caught if "duckduckgo" in str(w.message).lower()]
    assert bing_only == []
