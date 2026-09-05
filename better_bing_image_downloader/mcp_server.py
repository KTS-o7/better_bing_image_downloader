"""MCP server exposing image search to LLM agents (issue #65).

LLM agents (Claude Code/Desktop, LangGraph, ...) call tools over the
Model Context Protocol. This module wraps :class:`Downloader.search` in
a single MCP tool, ``search_images``, served over stdio by the
``bbid-mcp`` console script.

The ``mcp`` package is an **optional** dependency (install with
``pip install "better-bing-image-downloader[mcp]"``). This module is
importable without it: the import is guarded the same way
``duckduckgo.py`` guards ``brotli``, and the entry point fails with a
helpful message only when the server is actually started.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .downloader import Downloader

# ``FastMCP`` is provided by the optional ``mcp`` package (1.x — see
# ``[project.optional-dependencies] mcp``). Decoupling the runtime symbol
# from the import lets mypy see ``FastMCP`` as ``Any`` regardless of which
# branch ran, and dodges ``[unused-ignore]`` lint errors when ``mcp`` is
# installed in a dev/CI environment.
FastMCP: Any

try:
    from mcp.server.fastmcp import FastMCP as _fastmcp_real

    FastMCP = _fastmcp_real

    _HAS_MCP = True
except ImportError:  # pragma: no cover
    _HAS_MCP = False

__all__ = ["main"]

logger = logging.getLogger(__name__)

_MCP_MISSING_MSG = (
    "The 'mcp' package is required to run the bbid MCP server. "
    'Install it with `pip install "better-bing-image-downloader[mcp]"`.'
)

# Serializes searches across MCP tool calls. ``Downloader`` instances
# are not safe to share across threads when ``manifest=True`` (the
# underlying ``ManifestWriter`` is single-threaded), so each call also
# constructs a fresh ``Downloader()`` — the lock additionally prevents
# two concurrent searches from racing on the same ``output_dir``.
_SEARCH_LOCK = threading.Lock()


def _run_search(
    query: str,
    limit: int = 10,
    engine: str = "bing",
    output_dir: str = "dataset",
    manifest: bool = True,
) -> dict:
    """Run one image search and return a JSON-serializable summary dict.

    This is the core of the MCP ``search_images`` tool, kept free of any
    ``mcp`` imports so it can be tested (and reused) without the
    optional dependency installed.

    Returns
    -------
    dict
        ``{"count": int, "output_dir": str, "manifest_path": str | None,
        "skipped": int, "errors": int}``.
    """
    with _SEARCH_LOCK:
        result = Downloader().search(
            query=query,
            limit=limit,
            engine=engine,
            output_dir=output_dir,
            manifest=manifest,
        )
    summary = {
        "count": result.count,
        "output_dir": str(result.output_dir),
        "manifest_path": result.manifest_path,
        "skipped": result.skipped,
        "errors": len(result.errors),
    }
    logger.info(
        "MCP search_images: query=%r engine=%r count=%d skipped=%d errors=%d",
        query,
        engine,
        summary["count"],
        summary["skipped"],
        summary["errors"],
    )
    return summary


def _build_server() -> FastMCP:
    """Create the FastMCP server and register the ``search_images`` tool.

    Raises
    ------
    RuntimeError
        If the optional ``mcp`` package is not installed.
    """
    if not _HAS_MCP:
        raise RuntimeError(_MCP_MISSING_MSG)
    server = FastMCP("bbid")

    @server.tool()
    def search_images(
        query: str,
        limit: int = 10,
        engine: str = "bing",
        output_dir: str = "dataset",
        manifest: bool = True,
    ) -> dict:
        """Search Bing or DuckDuckGo for images and download them to disk.

        Args:
            query: Search term (e.g. "red panda").
            limit: Maximum number of images to download.
            engine: Search engine to use: "bing" or "duckduckgo".
            output_dir: Base output directory; images land in
                ``<output_dir>/<query>/``.
            manifest: Write a JSONL ``manifest.jsonl` recording every
                attempted download (success or failure).

        Returns:
            A summary dict with keys ``count``, ``output_dir``,
            ``manifest_path``, ``skipped`` and ``errors``.
        """
        return _run_search(
            query=query,
            limit=limit,
            engine=engine,
            output_dir=output_dir,
            manifest=manifest,
        )

    return server


def main() -> None:
    """Console-script entry point for ``bbid-mcp``: serve MCP over stdio."""
    if not _HAS_MCP:
        raise SystemExit(_MCP_MISSING_MSG)
    _build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
