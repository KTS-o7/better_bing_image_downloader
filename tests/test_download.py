import os
import tempfile
from unittest.mock import MagicMock, patch

from better_bing_image_downloader.download import downloader
from better_bing_image_downloader.downloader import Downloader


def _mock_bing_factory():
    """Helper: patch the Bing class in the Downloader registry."""
    mock_instance = MagicMock()
    mock_instance.download_count = 0
    mock_instance._slots_used = 0
    mock_instance.seen = set()
    mock_instance.manifest = {}
    mock_instance.run = MagicMock()  # don't actually run anything
    return patch.object(
        Downloader,
        "_DEFAULT_REGISTRY",
        {
            "bing": MagicMock(return_value=mock_instance),
            "duckduckgo": MagicMock(return_value=mock_instance),
        },
    )


def _build_mock_engine_cls(num_downloads: int):
    """Build a mock engine class whose run() simulates N successful saves.

    The Downloader wires save_image hooks; for the legacy downloader()
    tests we just need the run() method to populate download_count /
    _slots_used. The Result.count comes from a separate list, but
    because we're not asserting on Result in these tests (we only
    assert the legacy int return), this is fine.
    """
    mock_cls = MagicMock()
    mock_instance = mock_cls.return_value
    mock_instance.download_count = 0
    mock_instance._slots_used = 0
    mock_instance.seen = set()
    mock_instance.manifest = {}

    def fake_run() -> None:
        for i in range(1, num_downloads + 1):
            mock_instance.download_count = i
            mock_instance._slots_used = i

    mock_instance.run = MagicMock(side_effect=fake_run)
    return mock_cls


def test_downloader_does_not_call_input():
    """downloader() must never call input() — no interactive prompts"""
    tmp = tempfile.mkdtemp()
    mock_cls = _build_mock_engine_cls(5)
    with patch.object(
        Downloader,
        "_DEFAULT_REGISTRY",
        {"bing": mock_cls, "duckduckgo": mock_cls},
    ), patch("builtins.input", side_effect=AssertionError("input() must not be called!")):
        result = downloader("cats", limit=5, output_dir=tmp)

    assert result == 5


def test_downloader_returns_int():
    """downloader() must return the number of downloaded images as int"""
    tmp = tempfile.mkdtemp()
    mock_cls = _build_mock_engine_cls(3)
    with patch.object(
        Downloader,
        "_DEFAULT_REGISTRY",
        {"bing": mock_cls, "duckduckgo": mock_cls},
    ):
        result = downloader("cats", limit=3, output_dir=tmp)
    assert isinstance(result, int)
    assert result == 3


def test_downloader_badsites_default_not_shared():
    """badsites=None default must not produce shared list between calls"""
    tmp = tempfile.mkdtemp()
    mock_cls = _build_mock_engine_cls(0)
    with patch.object(
        Downloader,
        "_DEFAULT_REGISTRY",
        {"bing": mock_cls, "duckduckgo": mock_cls},
    ):
        downloader("cats", limit=1, output_dir=tmp)
        downloader("dogs", limit=1, output_dir=tmp)
        calls = mock_cls.call_args_list
        assert len(calls) == 2
        # Both calls should pass a badsites list — check they're not the same object
        badsites_1 = calls[0][1].get("badsites")
        badsites_2 = calls[1][1].get("badsites")
        if badsites_1 is not None and badsites_2 is not None:
            assert badsites_1 is not badsites_2


def test_downloader_force_replace_deletes_existing_dir():
    """force_replace=True should delete and recreate the output directory"""
    tmp = tempfile.mkdtemp()
    query_dir = os.path.join(tmp, "cats")
    os.makedirs(query_dir)
    sentinel_file = os.path.join(query_dir, "existing_file.txt")
    with open(sentinel_file, "w") as f:
        f.write("should be deleted")

    mock_cls = _build_mock_engine_cls(0)
    with patch.object(
        Downloader,
        "_DEFAULT_REGISTRY",
        {"bing": mock_cls, "duckduckgo": mock_cls},
    ):
        downloader("cats", limit=1, output_dir=tmp, force_replace=True)

    assert not os.path.exists(sentinel_file), "force_replace should have deleted existing files"


def test_downloader_old_filter_param_works_with_deprecation_warning():
    """Old 'filter=' kwarg should still work but emit DeprecationWarning"""
    import warnings

    tmp = tempfile.mkdtemp()
    mock_cls = _build_mock_engine_cls(0)
    with patch.object(
        Downloader,
        "_DEFAULT_REGISTRY",
        {"bing": mock_cls, "duckduckgo": mock_cls},
    ):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            downloader("cats", limit=1, output_dir=tmp, filter="photo")
        assert any(issubclass(x.category, DeprecationWarning) for x in w)
        assert any("image_filter" in str(x.message) for x in w)
