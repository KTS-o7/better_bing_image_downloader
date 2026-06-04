"""Tests for atomic-write and reliability behavior in the base engine."""

import os
from unittest.mock import MagicMock, patch

from better_bing_image_downloader.bing import Bing


class TestAtomicWrite:
    """``save_image`` must leave no partial files on failure."""

    @patch("better_bing_image_downloader.base.filetype.guess")
    @patch("better_bing_image_downloader.base.urllib.request.urlopen")
    def test_save_image_writes_atomically(self, mock_urlopen, mock_filetype, tmp_path):
        """A successful save produces the target file and no leftover temp file."""
        fake_image = b"\xff\xd8\xff" * 50
        mock_response = MagicMock()
        mock_response.read.return_value = fake_image
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mock_kind = MagicMock()
        mock_kind.mime = "image/jpeg"
        mock_filetype.return_value = mock_kind

        b = Bing("cats", 10, str(tmp_path), "off", 10)
        target = tmp_path / "Image_1.jpg"
        assert b.save_image("https://example.com/img.jpg", target) is True
        assert target.exists()
        # No leftover temp files in the directory
        leftover = [p for p in os.listdir(tmp_path) if p.startswith(".") and p != "." and p != ".."]
        assert leftover == [], f"Leftover temp files: {leftover}"

    @patch("better_bing_image_downloader.base.filetype.guess")
    @patch("better_bing_image_downloader.base.urllib.request.urlopen")
    def test_save_image_no_partial_file_on_write_failure(
        self, mock_urlopen, mock_filetype, tmp_path
    ):
        """If writing the temp file fails, no partial file should be left behind."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        b = Bing("cats", 10, str(tmp_path), "off", 10)
        target = tmp_path / "Image_1.jpg"
        result = b.save_image("https://example.com/img.jpg", target)
        assert result is False
        assert not target.exists()
        # No leftover temp files
        leftover = [p for p in os.listdir(tmp_path) if p.startswith(".")]
        assert leftover == [], f"Leftover temp files: {leftover}"

    @patch("better_bing_image_downloader.base.filetype.guess")
    @patch("better_bing_image_downloader.base.urllib.request.urlopen")
    def test_save_image_no_partial_file_on_invalid_image(
        self, mock_urlopen, mock_filetype, tmp_path
    ):
        """If the response is not an image, no file should be written."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html>not an image</html>"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        mock_filetype.return_value = None  # not an image

        b = Bing("cats", 10, str(tmp_path), "off", 10)
        target = tmp_path / "Image_1.jpg"
        result = b.save_image("https://example.com/page.html", target)
        assert result is False
        assert not target.exists()
        leftover = [p for p in os.listdir(tmp_path) if p.startswith(".")]
        assert leftover == [], f"Leftover temp files: {leftover}"


class TestParallelFutureTimeout:
    """``_download_batch`` must cap how long a single future can block."""

    @patch.object(Bing, "save_image", return_value=True)
    def test_parallel_downloads_complete(self, mock_save, tmp_path):
        """A normal parallel batch should complete and update counters."""
        b = Bing("cats", 10, str(tmp_path), "off", 10, max_workers=4)
        links = [f"https://example.com/img{i}.jpg" for i in range(5)]
        b._download_batch(links, start_index=1)
        assert b.download_count == 5
        assert b._slots_used == 5
