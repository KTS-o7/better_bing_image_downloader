import json
from unittest.mock import MagicMock, patch

from better_bing_image_downloader.bing import Bing
from better_bing_image_downloader.download import downloader
from better_bing_image_downloader.downloader import Downloader


class TestResumeSupport:
    def test_skip_existing_file_returns_index(self, tmp_path):
        """If Image_1.jpg already exists, download_image should skip and return 0 (skipped sentinel)"""
        b = Bing("cats", 10, str(tmp_path), "off", 10)
        (tmp_path / "Image_1.jpg").write_bytes(b"fake content")

        with patch.object(b, "save_image") as mock_save:
            result = b.download_image("https://example.com/img.jpg", 1)

        mock_save.assert_not_called()
        assert result == 0  # 0 = skipped (file exists), not None = not an error

    def test_force_replace_does_not_skip_existing(self, tmp_path):
        """With force_replace=True, even existing files should be re-downloaded"""
        b = Bing("cats", 10, str(tmp_path), "off", 10, force_replace=True)
        (tmp_path / "Image_1.jpg").write_bytes(b"old content")

        with patch.object(b, "save_image", return_value=True):
            result = b.download_image("https://example.com/img.jpg", 1)

        assert result == 1

    def test_no_skip_when_force_replace_false_and_no_existing_file(self, tmp_path):
        """When file doesn't exist, download normally"""
        b = Bing("cats", 10, str(tmp_path), "off", 10, force_replace=False)

        with patch.object(b, "save_image", return_value=True):
            result = b.download_image("https://example.com/img.jpg", 1)

        assert result == 1


class TestManifest:
    def test_manifest_written_after_downloader_run(self, tmp_path):
        """downloader() should write _manifest.json after a run"""
        mock_cls = _build_mock_engine_cls(0)
        mock_instance = mock_cls.return_value
        # Pre-populate the engine's manifest so the legacy downloader
        # can write it out to disk on the way through.
        mock_instance.manifest = {"Image_1.jpg": "http://example.com/img.jpg"}

        with patch.object(
            Downloader,
            "_DEFAULT_REGISTRY",
            {"bing": mock_cls, "duckduckgo": mock_cls},
        ):
            downloader("cats", limit=1, output_dir=str(tmp_path))

        manifest_path = tmp_path / "cats" / "_manifest.json"
        assert manifest_path.exists(), "_manifest.json should be created"
        data = json.loads(manifest_path.read_text())
        assert "Image_1.jpg" in data
        assert data["Image_1.jpg"] == "http://example.com/img.jpg"

    def test_manifest_merges_with_existing(self, tmp_path):
        """Successive runs should merge manifests, not overwrite"""
        query_dir = tmp_path / "cats"
        query_dir.mkdir()
        existing_manifest = {"Image_1.jpg": "http://example.com/1.jpg"}
        (query_dir / "_manifest.json").write_text(json.dumps(existing_manifest))

        mock_cls = _build_mock_engine_cls(0)
        mock_instance = mock_cls.return_value
        mock_instance.manifest = {"Image_2.jpg": "http://example.com/2.jpg"}

        with patch.object(
            Downloader,
            "_DEFAULT_REGISTRY",
            {"bing": mock_cls, "duckduckgo": mock_cls},
        ):
            downloader("cats", limit=1, output_dir=str(tmp_path))

        data = json.loads((query_dir / "_manifest.json").read_text())
        assert "Image_1.jpg" in data  # old entry preserved
        assert "Image_2.jpg" in data  # new entry added


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


class TestDeduplication:
    def test_duplicate_md5_not_saved_twice(self, tmp_path):
        """Two save_image calls with the same bytes should only save the first"""
        b = Bing("cats", 10, str(tmp_path), "off", 10)
        fake_image = b"\xff\xd8\xff" * 100

        with patch("better_bing_image_downloader.base.urllib.request.urlopen") as mock_open, patch(
            "better_bing_image_downloader.base.filetype.guess"
        ) as mock_ft:
            mock_response = MagicMock()
            mock_response.read.return_value = fake_image
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_response
            mock_kind = MagicMock()
            mock_kind.mime = "image/jpeg"
            mock_ft.return_value = mock_kind

            r1 = b.save_image("https://example.com/img1.jpg", tmp_path / "img1.jpg")
            r2 = b.save_image("https://example.com/img2.jpg", tmp_path / "img2.jpg")

        assert r1 is True
        assert r2 is False  # duplicate detected

    def test_different_images_both_saved(self, tmp_path):
        """Two save_image calls with different bytes should both be saved"""
        b = Bing("cats", 10, str(tmp_path), "off", 10)

        with patch("better_bing_image_downloader.base.urllib.request.urlopen") as mock_open, patch(
            "better_bing_image_downloader.base.filetype.guess"
        ) as mock_ft:
            mock_kind = MagicMock()
            mock_kind.mime = "image/jpeg"
            mock_ft.return_value = mock_kind

            def make_response(content):
                r = MagicMock()
                r.read.return_value = content
                r.__enter__ = lambda s: s
                r.__exit__ = MagicMock(return_value=False)
                return r

            mock_open.side_effect = [
                make_response(b"\xff\xd8\xff" + b"A" * 100),
                make_response(b"\xff\xd8\xff" + b"B" * 100),
            ]

            r1 = b.save_image("https://example.com/img1.jpg", tmp_path / "img1.jpg")
            r2 = b.save_image("https://example.com/img2.jpg", tmp_path / "img2.jpg")

        assert r1 is True
        assert r2 is True
