"""Tests for the optional MCP server (issue #65).

The core ``_run_search`` helper is testable without the ``mcp``
package; the FastMCP wiring test is skipped when ``mcp`` is absent.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from better_bing_image_downloader import mcp_server


def _fake_result(count: int = 3, skipped: int = 1, errors: int = 0) -> MagicMock:
    result = MagicMock()
    result.count = count
    result.output_dir = Path("dataset/cats")
    result.manifest_path = "dataset/cats/manifest.jsonl"
    result.skipped = skipped
    result.errors = [("https://x/bad.jpg", ValueError("boom"))] * errors
    return result


class TestRunSearchHelper:
    def test_summary_dict_shape(self, tmp_path) -> None:
        with patch.object(
            mcp_server.Downloader, "search", return_value=_fake_result()
        ) as mock_search:
            summary = mcp_server._run_search("cats", limit=5, output_dir=str(tmp_path))

        assert summary == {
            "count": 3,
            "output_dir": "dataset/cats",
            "manifest_path": "dataset/cats/manifest.jsonl",
            "skipped": 1,
            "errors": 0,
        }
        # Parameters are forwarded to Downloader.search as kwargs.
        _, kwargs = mock_search.call_args
        assert kwargs["query"] == "cats"
        assert kwargs["limit"] == 5
        assert kwargs["engine"] == "bing"
        assert kwargs["manifest"] is True

    def test_manifest_false_by_request(self, tmp_path) -> None:
        fake = _fake_result()
        fake.manifest_path = None
        with patch.object(mcp_server.Downloader, "search", return_value=fake) as mock_search:
            summary = mcp_server._run_search("cats", manifest=False)
        assert summary["manifest_path"] is None
        assert mock_search.call_args.kwargs["manifest"] is False

    def test_sequential_calls_are_serialized_and_independent(self) -> None:
        """Two calls each construct a fresh Downloader and both succeed."""
        with patch.object(mcp_server, "Downloader") as mock_dl:
            mock_dl.return_value.search.side_effect = [_fake_result(1), _fake_result(2)]
            first = mcp_server._run_search("cats")
            second = mcp_server._run_search("dogs")
        assert first["count"] == 1
        assert second["count"] == 2
        # Fresh Downloader per call (thread-safety contract).
        assert mock_dl.call_count == 2


class TestOptionalDependencyHandling:
    def test_module_importable_without_mcp(self) -> None:
        """Importing mcp_server must not fail when ``mcp`` is absent."""
        with patch.dict(
            sys.modules,
            {"mcp": None, "mcp.server": None, "mcp.server.fastmcp": None},
        ):
            importlib.reload(mcp_server)
            assert mcp_server._HAS_MCP is False
            with pytest.raises(SystemExit):
                mcp_server.main()
        importlib.reload(mcp_server)  # restore real state

    def test_build_server_raises_without_mcp(self) -> None:
        with (
            patch.object(mcp_server, "_HAS_MCP", False),
            pytest.raises(RuntimeError, match="mcp"),
        ):
            mcp_server._build_server()


class TestFastMCPWiring:
    @pytest.fixture(autouse=True)
    def _require_mcp(self):
        pytest.importorskip("mcp", reason="optional [mcp] extra not installed")

    def test_server_builds_and_registers_tool(self) -> None:
        server = mcp_server._build_server()
        assert server.name == "bbid"

    def test_tool_is_registered(self) -> None:
        server = mcp_server._build_server()
        # FastMCP >= 1.x exposes registered tools via the tool manager.
        tools = server._tool_manager.list_tools()
        assert any(t.name == "search_images" for t in tools)
