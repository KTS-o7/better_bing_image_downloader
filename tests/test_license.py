"""License filter tests (issue #63). TDD RED first."""

from better_bing_image_downloader.bing import Bing


def test_license_mapping(tmp_path):
    b = Bing("cats", 10, str(tmp_path), license="public")
    assert b.get_license_filter() == "+filterui:license-L1"
    b2 = Bing("cats", 10, str(tmp_path), license="modify_commercially")
    assert b2.get_license_filter() == "+filterui:license-L2_L3"
    b3 = Bing("cats", 10, str(tmp_path), license="any")
    assert b3.get_license_filter() == ""


def test_qft_combines_filter_and_license(tmp_path):
    b = Bing("cats", 10, str(tmp_path), filter="photo", license="modify_commercially")
    url = b._build_page_url(0)
    assert "+filterui:photo-photo" in url
    assert "+filterui:license-L2_L3" in url
    assert url.count("&qft=") == 1


def test_qft_empty_by_default(tmp_path):
    b = Bing("cats", 10, str(tmp_path))
    assert b._build_page_url(0).endswith("&qft=")


def test_invalid_license_raises(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        Bing("cats", 10, str(tmp_path), license="bogus")


def test_license_aliases_and_raw(tmp_path):
    b = Bing("cats", 10, str(tmp_path), license="publicdomain")
    assert b.get_license_filter() == "+filterui:license-L1"
    b2 = Bing("cats", 10, str(tmp_path), license="share_commercially")
    assert b2.get_license_filter() == "+filterui:license-L2_L3_L4"
    b3 = Bing("cats", 10, str(tmp_path), license="license-L2_L3")
    assert b3.get_license_filter() == "+filterui:license-L2_L3"


def test_search_forwards_license(tmp_path):
    from better_bing_image_downloader import Downloader

    dl = Downloader()
    eng = dl.build_engine("bing", "cats", 5, tmp_path, license="public")
    assert eng.license == "public"
