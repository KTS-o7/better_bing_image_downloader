"""CLI smoke tests for the ``bbid`` entry point."""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

import pytest

from better_bing_image_downloader import download


def _installed_version() -> str | None:
    try:
        return pkg_version("better-bing-image-downloader")
    except PackageNotFoundError:
        return None


def test_version_flag_via_argv(monkeypatch, capsys) -> None:
    """``bbid --version`` exits 0 and prints the installed version."""
    monkeypatch.setattr(sys, "argv", ["bbid", "--version"])
    with pytest.raises(SystemExit) as exc_info:
        download.main()
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("bbid ")
    installed = _installed_version()
    if installed is not None:
        assert installed in out
    else:
        # Running from source without an install: 'unknown' is expected.
        assert "unknown" in out


def test_version_flag_via_subprocess() -> None:
    """The same flag works when the CLI runs as a separate process."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from better_bing_image_downloader.download import main; main()",
            "--version",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    installed = _installed_version()
    if installed is not None:
        assert installed in result.stdout
    else:
        assert "unknown" in result.stdout
