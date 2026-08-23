"""CLI smoke tests for the ``bbid`` entry point."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
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


# --- v3.5.0 manifest flags (issue #41) ---
#
# These tests run the CLI in-process (monkeypatched ``sys.argv``) with
# ``urllib.request.urlopen`` stubbed, asserting the argparse-to-
# ``downloader()`` wiring for the manifest flags end-to-end without
# touching the network.


class _FakeHttpResponse:
    """Minimal stand-in for an ``urlopen`` response."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers: dict = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _install_fake_bing(monkeypatch, image_count: int = 2) -> None:
    """Stub ``urlopen`` to serve a canned Bing page and JPEG-ish bytes.

    The page is identical on every fetch, so the second page yields no
    new links and ``Bing.run()`` terminates after one page. Image bytes
    start with the JPEG SOI marker so the real ``filetype`` validation
    accepts them.
    """

    def fake_urlopen(request, timeout=None):
        url = getattr(request, "full_url", request)
        if "bing.com/images/async" in url:
            body = "".join(
                f"murl&quot;:&quot;https://img.test/{i}.jpg&quot;"
                for i in range(1, image_count + 1)
            ).encode()
        else:
            body = b"\xff\xd8\xff\xe0" + str(url).encode()
        return _FakeHttpResponse(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)


def _run_cli(monkeypatch, argv: list) -> None:
    monkeypatch.setattr(sys, "argv", ["bbid"] + argv)
    download.main()


def _read_manifest(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_cli_manifest_writes_default_jsonl(monkeypatch, tmp_path) -> None:
    """``bbid --manifest`` writes <output_dir>/<query>/manifest.jsonl."""
    _install_fake_bing(monkeypatch)
    _run_cli(monkeypatch, ["red panda", "--limit", "2", "--manifest", "-d", str(tmp_path)])

    records = _read_manifest(tmp_path / "red panda" / "manifest.jsonl")
    assert len(records) == 2
    for record in records:
        assert record["status"] == "ok"
        assert record["engine"] == "bing"
        assert record["query"] == "red panda"
    # Downloads run in parallel, so records may be appended out of
    # order; the indices themselves are strictly unique per search.
    assert sorted(r["index"] for r in records) == [1, 2]


def test_cli_manifest_path_override(monkeypatch, tmp_path) -> None:
    """``--manifest-path`` redirects the JSONL output."""
    _install_fake_bing(monkeypatch)
    override = tmp_path / "custom" / "out.jsonl"
    _run_cli(
        monkeypatch,
        [
            "red panda",
            "--limit",
            "2",
            "--manifest",
            "--manifest-path",
            str(override),
            "-d",
            str(tmp_path / "imgs"),
        ],
    )

    records = _read_manifest(override)
    assert len(records) == 2


def test_cli_manifest_fields_projection(monkeypatch, tmp_path) -> None:
    """``--manifest-fields url,md5`` writes records with only those keys."""
    _install_fake_bing(monkeypatch)
    _run_cli(
        monkeypatch,
        [
            "red panda",
            "--limit",
            "2",
            "--manifest",
            "--manifest-fields",
            "url,md5",
            "-d",
            str(tmp_path),
        ],
    )

    records = _read_manifest(tmp_path / "red panda" / "manifest.jsonl")
    assert len(records) == 2
    for record in records:
        assert set(record) == {"url", "md5"}


def test_cli_manifest_flush_every_reaches_writer(monkeypatch, tmp_path) -> None:
    """``--manifest-flush-every 5`` is accepted and the run completes."""
    _install_fake_bing(monkeypatch)
    _run_cli(
        monkeypatch,
        [
            "red panda",
            "--limit",
            "2",
            "--manifest",
            "--manifest-flush-every",
            "5",
            "-d",
            str(tmp_path),
        ],
    )

    records = _read_manifest(tmp_path / "red panda" / "manifest.jsonl")
    assert len(records) == 2
