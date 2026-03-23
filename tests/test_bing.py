import unittest
import tempfile
import threading
from unittest.mock import patch, MagicMock
from pathlib import Path
from better_bing_image_downloader.bing import Bing


class TestBingInit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_badsites_default_not_shared_between_instances(self):
        """badsites=None default must not be shared between instances"""
        b1 = Bing("cats", 10, self.tmp, "off", 10)
        b2 = Bing("dogs", 10, self.tmp, "off", 10)
        b1.badsites.add("evil.com")
        self.assertNotIn("evil.com", b2.badsites)

    def test_max_workers_clamped_upper(self):
        b = Bing("cats", 10, self.tmp, "off", 10, max_workers=100)
        self.assertLessEqual(b.max_workers, 16)

    def test_max_workers_clamped_lower(self):
        b = Bing("cats", 10, self.tmp, "off", 10, max_workers=0)
        self.assertGreaterEqual(b.max_workers, 1)

    def test_output_dir_created(self):
        import os
        b = Bing("cats", 10, self.tmp, "off", 10)
        self.assertTrue(os.path.isdir(self.tmp))


class TestBingGetFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_photo_filter(self):
        b = Bing("cats", 10, self.tmp, "off", 10)
        self.assertEqual(b.get_filter("photo"), "+filterui:photo-photo")

    def test_clipart_filter(self):
        b = Bing("cats", 10, self.tmp, "off", 10)
        self.assertEqual(b.get_filter("clipart"), "+filterui:photo-clipart")

    def test_gif_filter(self):
        b = Bing("cats", 10, self.tmp, "off", 10)
        self.assertEqual(b.get_filter("gif"), "+filterui:photo-animatedgif")
        self.assertEqual(b.get_filter("animatedgif"), "+filterui:photo-animatedgif")

    def test_line_filter(self):
        b = Bing("cats", 10, self.tmp, "off", 10)
        self.assertEqual(b.get_filter("line"), "+filterui:photo-linedrawing")
        self.assertEqual(b.get_filter("linedrawing"), "+filterui:photo-linedrawing")

    def test_transparent_filter(self):
        b = Bing("cats", 10, self.tmp, "off", 10)
        self.assertEqual(b.get_filter("transparent"), "+filterui:photo-transparent")

    def test_unknown_filter_returns_empty(self):
        b = Bing("cats", 10, self.tmp, "off", 10)
        self.assertEqual(b.get_filter("Size:Small"), "")
        self.assertEqual(b.get_filter(""), "")


class TestBingSaveImage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    @patch('better_bing_image_downloader.bing.urllib.request.urlopen')
    @patch('better_bing_image_downloader.bing.filetype.guess')
    def test_save_image_success_returns_true(self, mock_filetype, mock_urlopen):
        fake_image = b'\xff\xd8\xff' * 10
        mock_response = MagicMock()
        mock_response.read.return_value = fake_image
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mock_kind = MagicMock()
        mock_kind.mime = 'image/jpeg'
        mock_filetype.return_value = mock_kind

        b = Bing("cats", 10, self.tmp, "off", 10)
        file_path = Path(self.tmp) / "test.jpg"
        result = b.save_image("https://example.com/image.jpg", file_path)
        self.assertTrue(result)

    @patch('better_bing_image_downloader.bing.urllib.request.urlopen')
    @patch('better_bing_image_downloader.bing.filetype.guess')
    def test_save_image_rejects_non_image_returns_false(self, mock_filetype, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b'not an image'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response
        mock_filetype.return_value = None

        b = Bing("cats", 10, self.tmp, "off", 10)
        file_path = Path(self.tmp) / "test.jpg"
        result = b.save_image("https://example.com/file.html", file_path)
        self.assertFalse(result)

    @patch('better_bing_image_downloader.bing.urllib.request.urlopen')
    def test_save_image_network_error_returns_false(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        b = Bing("cats", 10, self.tmp, "off", 10)
        result = b.save_image("https://example.com/img.jpg", Path(self.tmp) / "img.jpg")
        self.assertFalse(result)


class TestBingDownloadImage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    @patch.object(Bing, 'save_image', return_value=True)
    def test_download_image_returns_index_on_success(self, mock_save):
        b = Bing("cats", 10, self.tmp, "off", 10)
        result = b.download_image("https://example.com/img.jpg", 5)
        self.assertEqual(result, 5)

    @patch.object(Bing, 'save_image', return_value=False)
    def test_download_image_returns_none_on_failure(self, mock_save):
        b = Bing("cats", 10, self.tmp, "off", 10)
        result = b.download_image("https://example.com/img.jpg", 5)
        self.assertIsNone(result)

    def test_download_image_signature_has_index_param(self):
        import inspect
        b = Bing("cats", 10, self.tmp, "off", 10)
        sig = inspect.signature(b.download_image)
        self.assertIn("index", sig.parameters)


class TestBingCountLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_count_lock_exists(self):
        b = Bing("cats", 10, self.tmp, "off", 10)
        self.assertTrue(hasattr(b, '_count_lock'))
        self.assertIsInstance(b._count_lock, type(threading.Lock()))


if __name__ == '__main__':
    unittest.main()
