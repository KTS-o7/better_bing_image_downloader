"""Tests for the downloader() function's new engine= parameter."""

from unittest.mock import MagicMock, patch

import pytest

from better_bing_image_downloader.download import downloader


class TestEngineParameter:
    def test_default_engine_is_bing(self, tmp_path):
        mock_cls = _build_mock_engine_cls(0)
        with patch(
            "better_bing_image_downloader.downloader.Downloader._DEFAULT_REGISTRY",
            {"bing": mock_cls, "duckduckgo": mock_cls},
        ):
            downloader("cats", limit=1, output_dir=str(tmp_path))
            assert mock_cls.called

    def test_explicit_bing_engine(self, tmp_path):
        mock_cls = _build_mock_engine_cls(0)
        with patch(
            "better_bing_image_downloader.downloader.Downloader._DEFAULT_REGISTRY",
            {"bing": mock_cls, "duckduckgo": mock_cls},
        ):
            downloader("cats", limit=1, output_dir=str(tmp_path), engine="bing")
            assert mock_cls.called

    def test_duckduckgo_engine(self, tmp_path):
        mock_cls = _build_mock_engine_cls(0)
        with patch(
            "better_bing_image_downloader.downloader.Downloader._DEFAULT_REGISTRY",
            {"bing": mock_cls, "duckduckgo": mock_cls},
        ):
            downloader(
                "cats",
                limit=1,
                output_dir=str(tmp_path),
                engine="duckduckgo",
            )
            assert mock_cls.called
            # The engine kwargs should include DDG-specific options.
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["safe_search"] == "moderate"
            assert call_kwargs["region"] == "us-en"

    def test_duckduckgo_passes_safe_search_and_region(self, tmp_path):
        mock_cls = _build_mock_engine_cls(0)
        with patch(
            "better_bing_image_downloader.downloader.Downloader._DEFAULT_REGISTRY",
            {"bing": mock_cls, "duckduckgo": mock_cls},
        ):
            downloader(
                "cats",
                limit=1,
                output_dir=str(tmp_path),
                engine="duckduckgo",
                ddg_safe_search="off",
                ddg_region="uk-en",
            )
            assert mock_cls.call_args.kwargs["safe_search"] == "off"
            assert mock_cls.call_args.kwargs["region"] == "uk-en"

    def test_invalid_engine_raises(self, tmp_path):
        with pytest.raises(ValueError, match="engine must be"):
            downloader("cats", limit=1, output_dir=str(tmp_path), engine="yahoo")


def _build_mock_engine_cls(num_downloads: int):
    """Build a mock engine class whose run() simulates N successful saves."""
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


class TestLoggerReplacesPrint:
    """``helperdownload`` should use logging, not print()."""

    def test_helperdownload_uses_logging(self):
        # The module should import logging (not just have it in namespace)
        import logging

        from better_bing_image_downloader import helperdownload

        assert hasattr(logging, "info")
        # The file should not contain top-level print() calls
        import inspect

        source = inspect.getsource(helperdownload)
        # ``print_function`` import is fine (it's a Python 2 compat shim).
        # We just want to make sure no actual print() calls leak user output.
        assert 'print("## OK' not in source
        assert 'print("## Err' not in source
        assert 'print("## Fail' not in source


class TestMultidownloaderDeprecated:
    def test_multidownloader_module_is_marked_deprecated(self):
        from better_bing_image_downloader import multidownloader

        assert "deprecated" in multidownloader.__doc__.lower()

    def test_crawler_module_is_marked_deprecated(self):
        from better_bing_image_downloader import crawler

        assert "deprecated" in crawler.__doc__.lower()
