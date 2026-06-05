"""Tests for v3.1.1 integrability improvements.

- Bing() and DuckDuckGo() can be instantiated with just (query, limit, output_dir)
  using sensible defaults.
- downloader() can be called with no required arguments beyond query.
- py.typed marker is shipped.
- brotli is a hard dep (installable via base install).
"""

from __future__ import annotations

import importlib
from pathlib import Path

from better_bing_image_downloader import Bing, DuckDuckGo, downloader


def test_bing_instantiable_with_only_required_args(tmp_path: Path) -> None:
    """Bing() should work with just (query, limit, output_dir) — no surprises."""
    b = Bing("red panda", 5, tmp_path)
    assert b.query == "red panda"
    assert b.limit == 5
    assert b.adult == "moderate"
    assert b.timeout == 60
    assert b.verbose is True
    assert b.filter == ""
    assert b.mkt == "en-US"


def test_duckduckgo_instantiable_with_only_required_args(tmp_path: Path) -> None:
    """DuckDuckGo() should work with just (query, limit, output_dir)."""
    d = DuckDuckGo("red panda", 5, tmp_path)
    assert d.query == "red panda"
    assert d.limit == 5
    assert d.timeout == 30
    assert d.safe_search == "moderate"
    assert d.region == "us-en"


def test_downloader_callable_with_minimal_args(tmp_path: Path) -> None:
    """downloader() should accept just (query) for a sensible default run."""
    # Note: we don't actually trigger a network call here; we just check
    # the function signature is callable. network gating is elsewhere.
    import inspect

    sig = inspect.signature(downloader)
    required = [
        p.name
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    # `query` is the only required positional. `limit` has a default.
    assert required == ["query"], f"Expected only `query` required, got {required}"


def test_bing_verbose_can_be_disabled_by_default(tmp_path: Path) -> None:
    """verbose=True is the noisy default; downstream users can silence it."""
    b = Bing("x", 1, tmp_path, verbose=False)
    assert b.verbose is False


def test_duckduckgo_verbose_can_be_disabled_by_default(tmp_path: Path) -> None:
    d = DuckDuckGo("x", 1, tmp_path, verbose=False)
    assert d.verbose is False


def test_py_typed_marker_shipped() -> None:
    """The package must ship py.typed so mypy users get types downstream."""
    pkg_root = Path(importlib.import_module("better_bing_image_downloader").__file__).parent
    assert (pkg_root / "py.typed").is_file(), "py.typed marker missing"


def test_brotli_importable_on_fresh_install() -> None:
    """brotli is a hard dep in 3.1.1; no extra install step."""
    import brotli  # noqa: F401


def test_bing_adult_default_is_moderate(tmp_path: Path) -> None:
    """The default adult filter is 'moderate' (safe default)."""
    b = Bing("x", 1, tmp_path)
    assert b.adult == "moderate"


def test_bing_explicit_adult_off_works(tmp_path: Path) -> None:
    """Users can still opt out of the adult filter explicitly."""
    b = Bing("x", 1, tmp_path, adult="off")
    assert b.adult == "off"


def test_duckduckgo_safe_search_strict_works(tmp_path: Path) -> None:
    d = DuckDuckGo("x", 1, tmp_path, safe_search="strict")
    assert d.safe_search == "strict"
