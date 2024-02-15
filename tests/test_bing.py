import unittest
from unittest.mock import patch
from better_bing_image_downloader.bing import Bing

class TestBing(unittest.TestCase):
    def setUp(self):
        self.query = 'cat'
        self.limit = 10
        self.output_dir = '/path/to/output'
        self.adult = 'Moderate'
        self.timeout = 10
        self.filter = ''
        self.verbose = True

    def test_get_filter(self):
        bing = Bing(self.query, self.limit, self.output_dir, self.adult, self.timeout, self.filter, self.verbose)
        self.assertEqual(bing.get_filter('Size:Small'), 'filterui:imagesize-small')

    @patch('better_bing_image_downloader.bing.urllib.request')
    def test_save_image(self, mock_urllib_request):
        bing = Bing(self.query, self.limit, self.output_dir, self.adult, self.timeout, self.filter, self.verbose)
        link = 'https://example.com/image.jpg'
        file_path = '/path/to/save/image.jpg'
        bing.save_image(link, file_path)
        mock_urllib_request.urlretrieve.assert_called_once_with(link, file_path)

    @patch('better_bing_image_downloader.bing.urllib.request')
    def test_download_image(self, mock_urllib_request):
        bing = Bing(self.query, self.limit, self.output_dir, self.adult, self.timeout, self.filter, self.verbose)
        link = 'https://example.com/image.jpg'
        bing.download_image(link)
        mock_urllib_request.urlretrieve.assert_called_once_with(link, '/path/to/output/image.jpg')

    @patch('better_bing_image_downloader.bing.urllib.request')
    def test_run(self, mock_urllib_request):
        bing = Bing(self.query, self.limit, self.output_dir, self.adult, self.timeout, self.filter, self.verbose)
        bing.run()
        self.assertEqual(bing.page_counter, 1)
        self.assertEqual(bing.download_count, 10)

if __name__ == '__main__':
    unittest.main()
