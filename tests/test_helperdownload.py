import socket
import os
from unittest.mock import patch, MagicMock
from better_bing_image_downloader import helperdownload


def test_download_images_does_not_mutate_global_socket_timeout(tmp_path):
    """download_images must not call socket.setdefaulttimeout"""
    original_timeout = socket.getdefaulttimeout()
    with patch('better_bing_image_downloader.helperdownload.requests.get') as mock_get:
        mock_resp = MagicMock()
        mock_resp.content = b'\x00' * 100
        mock_get.return_value = mock_resp
        with patch('better_bing_image_downloader.helperdownload.filetype.guess', return_value=None):
            helperdownload.download_images(
                ["http://example.com/img.jpg"],
                dst_dir=str(tmp_path),
                timeout=5
            )
    after_timeout = socket.getdefaulttimeout()
    assert after_timeout == original_timeout, \
        f"socket.setdefaulttimeout was called! Before: {original_timeout}, After: {after_timeout}"


def test_valid_extensions_includes_gif():
    assert "gif" in helperdownload.VALID_IMAGE_EXTENSIONS


def test_valid_extensions_includes_tiff():
    assert "tiff" in helperdownload.VALID_IMAGE_EXTENSIONS


def test_valid_extensions_includes_ico():
    assert "ico" in helperdownload.VALID_IMAGE_EXTENSIONS


def test_default_concurrency_is_reasonable():
    """Default concurrency should be <= 10 to avoid rate limiting"""
    import inspect
    sig = inspect.signature(helperdownload.download_images)
    default_concurrency = sig.parameters['concurrency'].default
    assert default_concurrency <= 10, f"concurrency default {default_concurrency} is too high"


def test_invalid_image_leaves_no_orphaned_file(tmp_path):
    """After rejecting an invalid image, no temp files should remain"""
    with patch('better_bing_image_downloader.helperdownload.requests.get') as mock_get:
        mock_resp = MagicMock()
        mock_resp.content = b'not an image'
        mock_get.return_value = mock_resp
        with patch('better_bing_image_downloader.helperdownload.filetype.guess', return_value=None):
            helperdownload.download_image(
                "http://example.com/notanimage.txt",
                str(tmp_path),
                "test_img",
                timeout=5
            )
    # No files should remain in the directory
    remaining_files = os.listdir(str(tmp_path))
    assert remaining_files == [], f"Orphaned files found: {remaining_files}"
