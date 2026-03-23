import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock
from better_bing_image_downloader.download import downloader


def test_downloader_does_not_call_input():
    """downloader() must never call input() — no interactive prompts"""
    tmp = tempfile.mkdtemp()
    with patch('better_bing_image_downloader.download.Bing') as MockBing:
        mock_instance = MagicMock()
        mock_instance.download_count = 5
        mock_instance.seen = {"http://example.com/img.jpg"}
        MockBing.return_value = mock_instance

        with patch('builtins.input', side_effect=AssertionError("input() must not be called!")):
            result = downloader("cats", limit=5, output_dir=tmp)

    assert result == 5


def test_downloader_raises_oserror_not_sysexit_on_bad_dir():
    """downloader must raise OSError, not call sys.exit, on dir creation failure"""
    with patch('better_bing_image_downloader.download.Path') as MockPath:
        mock_path_instance = MagicMock()
        mock_path_instance.__truediv__ = MagicMock(return_value=mock_path_instance)
        mock_path_instance.exists.return_value = False
        mock_path_instance.mkdir.side_effect = PermissionError("no permission")
        MockPath.return_value = mock_path_instance

        with pytest.raises((OSError, PermissionError)):
            downloader("cats", limit=1, output_dir="/root/no_permission_dir_xyz")


def test_downloader_returns_int():
    """downloader() must return the number of downloaded images as int"""
    tmp = tempfile.mkdtemp()
    with patch('better_bing_image_downloader.download.Bing') as MockBing:
        mock_instance = MagicMock()
        mock_instance.download_count = 3
        mock_instance.seen = set()
        MockBing.return_value = mock_instance
        result = downloader("cats", limit=3, output_dir=tmp)
    assert isinstance(result, int)
    assert result == 3


def test_downloader_badsites_default_not_shared():
    """badsites=None default must not produce shared list between calls"""
    tmp = tempfile.mkdtemp()
    with patch('better_bing_image_downloader.download.Bing') as MockBing:
        mock_instance = MagicMock()
        mock_instance.download_count = 0
        mock_instance.seen = set()
        MockBing.return_value = mock_instance
        downloader("cats", limit=1, output_dir=tmp)
        downloader("dogs", limit=1, output_dir=tmp)
        calls = MockBing.call_args_list
        # Both calls should pass a badsites — check they're not the same object
        badsites_1 = calls[0][1].get('badsites')
        badsites_2 = calls[1][1].get('badsites')
        if badsites_1 is not None and badsites_2 is not None:
            assert badsites_1 is not badsites_2


def test_downloader_force_replace_deletes_existing_dir():
    """force_replace=True should delete and recreate the output directory"""
    tmp = tempfile.mkdtemp()
    query_dir = os.path.join(tmp, "cats")
    os.makedirs(query_dir)
    sentinel_file = os.path.join(query_dir, "existing_file.txt")
    with open(sentinel_file, 'w') as f:
        f.write("should be deleted")

    with patch('better_bing_image_downloader.download.Bing') as MockBing:
        mock_instance = MagicMock()
        mock_instance.download_count = 0
        mock_instance.seen = set()
        MockBing.return_value = mock_instance
        downloader("cats", limit=1, output_dir=tmp, force_replace=True)

    assert not os.path.exists(sentinel_file), "force_replace should have deleted existing files"
