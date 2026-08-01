"""Tests for HTTP/HTTPS proxy support (v3.8.0, issue #44).

- ``Downloader(proxy=...)`` wires a ``urllib.request.ProxyHandler``
  into its opener and threads ``proxy`` through ``search()`` to the
  engine constructors.
- ``Bing`` and ``DuckDuckGo`` accept ``proxy=`` and route their own
  openers (page fetches + image downloads) through it.
- The ``bbid`` CLI and the legacy ``downloader()`` function forward a
  ``--proxy`` / ``proxy=`` value.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from better_bing_image_downloader import Bing, Downloader, DuckDuckGo, downloader
from better_bing_image_downloader.download import main as cli_main
from better_bing_image_downloader.duckduckgo import _build_opener

PROXY = "http://localhost:8080"


def _proxy_handlers(opener: urllib.request.OpenerDirector) -> list[urllib.request.ProxyHandler]:
    """Return the ``ProxyHandler`` instances installed on ``opener``."""
    return [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]


def _proxy_for(opener: urllib.request.OpenerDirector, scheme: str) -> str | None:
    """Return the proxy URL configured for ``scheme`` on ``opener``, if any."""
    for handler in _proxy_handlers(opener):
        proxies = getattr(handler, "proxies", {}) or {}
        if proxies.get(scheme):
            return proxies[scheme]
    return None


# --- Downloader ---


def test_downloader_proxy_opener_has_proxy_handler() -> None:
    """``Downloader(proxy=...)`` routes http and https through the proxy."""
    dl = Downloader(proxy=PROXY)
    assert _proxy_for(dl.opener, "http") == PROXY
    assert _proxy_for(dl.opener, "https") == PROXY


def test_downloader_no_proxy_keeps_default_opener() -> None:
    """``Downloader()`` without a proxy has no custom proxy configured."""
    dl = Downloader()
    assert _proxy_for(dl.opener, "http") != PROXY
    assert _proxy_for(dl.opener, "https") != PROXY


def test_downloader_search_forwards_proxy_to_engine() -> None:
    """The ``proxy`` configured on the Downloader reaches the engine."""
    mock_cls = MagicMock()
    mock_instance = mock_cls.return_value
    mock_instance.download_count = 0
    mock_instance._slots_used = 0
    mock_instance.seen = set()
    mock_instance.manifest = {}
    mock_instance.run = MagicMock()

    with patch.object(
        Downloader,
        "_DEFAULT_REGISTRY",
        {"bing": mock_cls, "duckduckgo": mock_cls},
    ):
        dl = Downloader(proxy=PROXY)
        dl.search("cats", limit=1, output_dir="tmp_dl_proxy")
        kwargs = mock_cls.call_args.kwargs
        assert kwargs.get("proxy") == PROXY


def test_downloader_search_no_proxy_omits_engine_kwarg() -> None:
    """With no proxy configured, engines are constructed without one."""
    mock_cls = MagicMock()
    mock_instance = mock_cls.return_value
    mock_instance.download_count = 0
    mock_instance._slots_used = 0
    mock_instance.seen = set()
    mock_instance.manifest = {}
    mock_instance.run = MagicMock()

    with patch.object(
        Downloader,
        "_DEFAULT_REGISTRY",
        {"bing": mock_cls, "duckduckgo": mock_cls},
    ):
        Downloader().search("cats", limit=1, output_dir="tmp_dl_no_proxy")
        kwargs = mock_cls.call_args.kwargs
        assert "proxy" not in kwargs


# --- Engines ---


def test_bing_accepts_and_forwards_proxy(tmp_path: Path) -> None:
    """``Bing(proxy=...)`` stores it and its opener routes through it."""
    b = Bing("cats", 10, tmp_path, proxy=PROXY)
    assert b.proxy == PROXY
    assert _proxy_for(b.opener, "http") == PROXY
    assert _proxy_for(b.opener, "https") == PROXY


def test_duckduckgo_accepts_and_forwards_proxy(tmp_path: Path) -> None:
    """``DuckDuckGo(proxy=...)`` stores it and its opener routes through it."""
    ddg = DuckDuckGo("cats", 10, str(tmp_path), proxy=PROXY)
    assert ddg.proxy == PROXY
    assert _proxy_for(ddg._opener, "http") == PROXY
    assert _proxy_for(ddg._opener, "https") == PROXY


def test_engines_default_opener_has_no_custom_proxy(tmp_path: Path) -> None:
    """Without a proxy, engine openers keep the default behaviour."""
    b = Bing("cats", 10, tmp_path)
    ddg = DuckDuckGo("cats", 10, str(tmp_path))
    assert _proxy_for(b.opener, "http") != PROXY
    assert _proxy_for(ddg._opener, "http") != PROXY


def test_duckduckgo_build_opener_helper_layers_proxy() -> None:
    """The shared opener helper adds a ProxyHandler only when configured."""
    import http.cookiejar

    jar = http.cookiejar.CookieJar()
    proxied = _build_opener(jar, PROXY)
    assert _proxy_for(proxied, "http") == PROXY
    plain = _build_opener(jar)
    assert _proxy_for(plain, "http") != PROXY


def test_http_get_uses_proxied_opener(tmp_path: Path) -> None:
    """Image downloads go through the engine's proxied opener."""
    b = Bing("cats", 10, tmp_path, proxy=PROXY)
    response = MagicMock()
    response.read.return_value = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    b.opener.open = MagicMock()
    b.opener.open.return_value.__enter__.return_value = response
    body = b._http_get("https://example.com/cat.png")
    assert body == b"\x89PNG\r\n\x1a\n" + b"0" * 64
    b.opener.open.assert_called_once()


# --- Legacy downloader() function and bbid CLI ---


def test_legacy_downloader_forwards_proxy() -> None:
    """``downloader(proxy=...)`` reaches the underlying ``Downloader``."""
    with patch("better_bing_image_downloader.download.Downloader") as mock_dl:
        mock_dl.return_value.search.return_value = MagicMock(
            count=0, images=[], manifest_path=None, _engine=None
        )
        mock_dl.return_value.search.return_value.engine_instance = MagicMock(return_value=None)
        downloader("cats", limit=0, output_dir="tmp_legacy_proxy", proxy=PROXY)
        assert mock_dl.call_args.kwargs.get("proxy") == PROXY


def test_cli_proxy_flag_forwards(monkeypatch) -> None:
    """``bbid --proxy <url>`` parses and forwards the proxy value."""
    captured: dict = {}

    def fake_downloader(*args, **kwargs) -> int:
        captured["proxy"] = kwargs.get("proxy")
        return 0

    monkeypatch.setattr("better_bing_image_downloader.download.downloader", fake_downloader)
    monkeypatch.setattr(sys, "argv", ["bbid", "--proxy", PROXY, "cats", "--limit", "1"])
    cli_main()
    assert captured.get("proxy") == PROXY
