"""Tests for :mod:`better_bing_image_downloader.export` (issue #64)."""

from __future__ import annotations

import sys

import pytest

from better_bing_image_downloader import download, export_manifest
from better_bing_image_downloader.manifest import ManifestWriter

_RECORDS = [
    {
        "index": 1,
        "status": "ok",
        "url": "https://img.test/1.jpg",
        "file": "red panda_1.jpg",
        "md5": "aaa",
        "error": None,
        "engine": "bing",
        "query": "red panda",
        "source_page": "https://bing.com/images/async?q=red+panda",
        "downloaded_at": "2026-08-24T10:00:00Z",
        "caption": "a red panda",
    },
    {
        "index": 2,
        "status": "error",
        "url": "https://img.test/2.jpg",
        "file": None,
        "md5": None,
        "error": "NetworkError",
        "engine": "bing",
        "query": "red panda",
        "source_page": "https://bing.com/images/async?q=red+panda",
        "downloaded_at": "2026-08-24T10:00:01Z",
        "caption": None,
    },
    {
        "index": 3,
        "status": "skipped",
        "url": "https://img.test/3.jpg",
        "file": None,
        "md5": None,
        "error": "BelowMinDimension",
        "engine": "bing",
        "query": "red panda",
        "source_page": "https://bing.com/images/async?q=red+panda",
        "downloaded_at": "2026-08-24T10:00:02Z",
        "caption": "tiny red panda",
    },
]


def _write_manifest(path, records=None) -> None:
    with ManifestWriter(path) as w:
        for record in records or _RECORDS:
            w.append(record)


def test_url_list_exports_only_ok_records(tmp_path) -> None:
    """url-list contains one URL per line, ok records only."""
    manifest = tmp_path / "manifest.jsonl"
    dest = tmp_path / "urls.txt"
    _write_manifest(manifest)

    count = export_manifest(manifest, "url-list", dest)

    assert count == 1
    assert dest.read_text(encoding="utf-8") == "https://img.test/1.jpg\n"


def test_url_list_skips_blank_and_malformed_lines(tmp_path, caplog) -> None:
    """Blank lines are skipped; malformed JSON warns and is skipped."""
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        "\n"
        '{"status": "ok", "url": "https://img.test/a.jpg"}\n'
        "not json at all\n"
        '{"status": "ok", "url": "https://img.test/b.jpg"}\n',
        encoding="utf-8",
    )
    dest = tmp_path / "urls.txt"

    with caplog.at_level("WARNING", logger="better_bing_image_downloader.export"):
        count = export_manifest(manifest, "url-list", dest)

    assert count == 2
    assert dest.read_text(encoding="utf-8").splitlines() == [
        "https://img.test/a.jpg",
        "https://img.test/b.jpg",
    ]
    assert any("malformed manifest line" in r.message for r in caplog.records)


def test_parquet_exports_all_statuses(tmp_path) -> None:
    """Parquet export includes ok/error/skipped records and round-trips fields."""
    pq = pytest.importorskip("pyarrow.parquet")
    manifest = tmp_path / "manifest.jsonl"
    dest = tmp_path / "out" / "manifest.parquet"
    _write_manifest(manifest)

    count = export_manifest(manifest, "parquet", dest)

    assert count == 3
    table = pq.read_table(dest)
    assert table.num_rows == 3
    rows = table.to_pylist()
    assert rows[0]["url"] == "https://img.test/1.jpg"
    assert rows[1]["status"] == "error"
    assert rows[2]["caption"] == "tiny red panda"


def test_unknown_format_raises_value_error(tmp_path) -> None:
    """An unknown format raises ValueError listing the valid formats."""
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest)

    with pytest.raises(ValueError, match="url-list"):
        export_manifest(manifest, "csv", tmp_path / "out.csv")


def test_cli_export_url_list(monkeypatch, tmp_path) -> None:
    """``bbid export --format url-list`` writes the dest file in-process."""
    manifest = tmp_path / "manifest.jsonl"
    dest = tmp_path / "urls.txt"
    _write_manifest(manifest)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "bbid",
            "export",
            "--format",
            "url-list",
            "--manifest",
            str(manifest),
            "--dest",
            str(dest),
        ],
    )

    download.main()

    assert dest.read_text(encoding="utf-8") == "https://img.test/1.jpg\n"


def test_cli_export_does_not_break_query_invocation(monkeypatch) -> None:
    """Pin the ``bbid export`` intercept in :func:`download.main`.

    The first positional token ``export`` is routed to
    :func:`_export_main` before the search-query parser runs, so
    ``bbid export`` (no flags) hits the export parser and exits with
    argparse's ``usage`` error (exit code 2). ``bbid "query"`` is
    unchanged — the intercept only fires on the exact first token.
    """
    monkeypatch.setattr(sys, "argv", ["bbid", "export"])
    with pytest.raises(SystemExit) as exc_info:
        download.main()
    assert exc_info.value.code == 2
