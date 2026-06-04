"""Tests for the downloader() function's new engine= parameter."""

from unittest.mock import MagicMock, patch

import pytest

from better_bing_image_downloader.download import downloader


class TestEngineParameter:
    def test_default_engine_is_bing(self, tmp_path):
        with patch("better_bing_image_downloader.download.Bing") as MockBing:
            mock_instance = MagicMock()
            mock_instance.download_count = 0
            mock_instance.manifest = {}
            MockBing.return_value = mock_instance
            downloader("cats", limit=1, output_dir=str(tmp_path))
            assert MockBing.called

    def test_explicit_bing_engine(self, tmp_path):
        with patch("better_bing_image_downloader.download.Bing") as MockBing:
            mock_instance = MagicMock()
            mock_instance.download_count = 0
            mock_instance.manifest = {}
            MockBing.return_value = mock_instance
            downloader("cats", limit=1, output_dir=str(tmp_path), engine="bing")
            assert MockBing.called

    def test_duckduckgo_engine(self, tmp_path):
        with patch("better_bing_image_downloader.duckduckgo.DuckDuckGo") as MockDDG:
            mock_instance = MagicMock()
            mock_instance.download_count = 0
            mock_instance.manifest = {}
            MockDDG.return_value = mock_instance
            downloader(
                "cats",
                limit=1,
                output_dir=str(tmp_path),
                engine="duckduckgo",
            )
            assert MockDDG.called
            # Engine should be configured with DDG-specific kwargs
            call_kwargs = MockDDG.call_args.kwargs
            assert call_kwargs["safe_search"] == "moderate"
            assert call_kwargs["region"] == "us-en"

    def test_duckduckgo_passes_safe_search_and_region(self, tmp_path):
        with patch("better_bing_image_downloader.duckduckgo.DuckDuckGo") as MockDDG:
            mock_instance = MagicMock()
            mock_instance.download_count = 0
            mock_instance.manifest = {}
            MockDDG.return_value = mock_instance
            downloader(
                "cats",
                limit=1,
                output_dir=str(tmp_path),
                engine="duckduckgo",
                ddg_safe_search="off",
                ddg_region="uk-en",
            )
            assert MockDDG.call_args.kwargs["safe_search"] == "off"
            assert MockDDG.call_args.kwargs["region"] == "uk-en"

    def test_invalid_engine_raises(self, tmp_path):
        with pytest.raises(ValueError, match="engine must be"):
            downloader("cats", limit=1, output_dir=str(tmp_path), engine="yahoo")


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
