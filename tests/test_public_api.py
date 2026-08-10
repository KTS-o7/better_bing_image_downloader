"""Regression tests for the top-level public API surface.

Guards against the v3.5.0 -> v3.5.1 bug class, where a new public
symbol (``ManifestWriter``) was added to a submodule's exports and to
``downloader.py:__all__`` but not to the package's top-level
``__init__.py``, making ``from better_bing_image_downloader import
ManifestWriter`` fail at release time.

These tests fail loudly if any future name added to ``__all__`` is
missing from ``__init__.py``, or if the top-level export resolves to a
*different* object than the submodule one.
"""

from __future__ import annotations

import importlib

import pytest

import better_bing_image_downloader as pkg

# Every symbol in the package ``__all__`` and the submodule it is
# defined in. Kept in sync with ``better_bing_image_downloader/__init__.py``.
_SUBMODULE_OF = {
    "BelowMinDimension": "base",
    "Bing": "bing",
    "CancelToken": "downloader",
    "DEFAULT_MANIFEST_FIELDS": "manifest",
    "Downloader": "downloader",
    "DuplicateImageError": "base",
    "DuckDuckGo": "duckduckgo",
    "ImageEngine": "base",
    "ImageResult": "results",
    "ImageSaveError": "base",
    "InvalidImageError": "base",
    "ManifestFieldError": "manifest",
    "ManifestWriter": "manifest",
    "NetworkError": "base",
    "Result": "results",
    "WriteError": "base",
    "downloader": "download",
}


@pytest.mark.parametrize("name", sorted(set(pkg.__all__)))
def test_every_all_name_is_importable_from_top_level(name: str) -> None:
    """``from better_bing_image_downloader import <name>`` must work."""
    namespace: dict = {}
    exec(f"from better_bing_image_downloader import {name}", namespace)  # noqa: S102
    assert namespace[name] is getattr(pkg, name)


@pytest.mark.parametrize("name", sorted(set(pkg.__all__)))
def test_top_level_export_is_same_object_as_submodule(name: str) -> None:
    """Top-level re-exports must resolve to the submodule's object.

    Catches the "imported into __init__ but as a different object"
    variant of the re-export bug.
    """
    submodule = importlib.import_module(f"better_bing_image_downloader.{_SUBMODULE_OF[name]}")
    assert getattr(pkg, name) is getattr(submodule, name)
