from better_bing_image_downloader.utils import resolve_dependencies, gen_valid_dir_name_for_keywords


def test_resolve_dependencies_non_chrome_always_passes():
    assert resolve_dependencies("firefox_headless") is True
    assert resolve_dependencies("firefox") is True
    assert resolve_dependencies("api") is True


def test_resolve_dependencies_default_does_not_crash():
    # default is firefox_headless, should return True without needing chromedriver
    assert resolve_dependencies() is True


def test_gen_valid_dir_name_spaces():
    result = gen_valid_dir_name_for_keywords("golden retriever")
    assert " " not in result
    assert "golden" in result


def test_gen_valid_dir_name_special_chars():
    result = gen_valid_dir_name_for_keywords("cats:dogs")
    assert ":" not in result
