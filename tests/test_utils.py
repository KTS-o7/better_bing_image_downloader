from unittest.mock import patch

from better_bing_image_downloader.utils import (
    gen_valid_dir_name_for_keywords,
    resolve_dependencies,
)


def test_resolve_dependencies_non_chrome_always_passes():
    assert resolve_dependencies("firefox_headless") is True
    assert resolve_dependencies("firefox") is True
    assert resolve_dependencies("api") is True


def test_resolve_dependencies_default_chrome_calls_installer():
    """Default driver is chrome_headless; must invoke chromedriver_autoinstaller"""
    import sys
    from unittest.mock import MagicMock

    fake_installer = MagicMock()
    fake_installer.install.return_value = "/path/to/chromedriver"
    with patch.dict(sys.modules, {"chromedriver_autoinstaller": fake_installer}):
        result = resolve_dependencies()  # no args → default "chrome_headless"
    fake_installer.install.assert_called_once()
    assert result is True


def test_resolve_dependencies_chrome_calls_installer():
    import sys
    from unittest.mock import MagicMock

    fake_installer = MagicMock()
    fake_installer.install.return_value = "/path/to/driver"
    with patch.dict(sys.modules, {"chromedriver_autoinstaller": fake_installer}):
        result = resolve_dependencies("chrome_headless")
    # Should return True when installer returns a path
    assert result is True


def test_gen_valid_dir_name_spaces():
    result = gen_valid_dir_name_for_keywords("golden retriever")
    assert " " not in result
    assert "golden" in result


def test_gen_valid_dir_name_special_chars():
    result = gen_valid_dir_name_for_keywords("cats:dogs")
    assert ":" not in result
    assert result == "cats-dogs"  # colon maps to dash per the implementation
