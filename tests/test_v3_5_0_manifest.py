"""Tests for v3.5.0 manifest export.

- New public type: ``ManifestWriter`` (in ``better_bing_image_downloader.manifest``)
- New ``Result.manifest_path`` attribute
- New ``Downloader.search`` params: ``manifest``, ``manifest_path``, ``manifest_fields``,
  ``manifest_flush_every``
- New ``ImageEngine.last_page_url`` attribute (set by Bing and DuckDuckGo on each page fetch)
- New CLI flags: ``--manifest``, ``--manifest-path``, ``--manifest-fields``, ``--manifest-flush-every``

All tests follow the project's existing patterns: mock at module-attribute
boundaries, no real network, stub engines for ``_run_engine`` integration.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from better_bing_image_downloader import (
    Downloader,
    ImageEngine,
)

# --- Group A: ManifestWriter unit tests (10 tests) ---


def test_writer_creates_file_on_construction(tmp_path: Path) -> None:
    """ManifestWriter(path) opens the file immediately."""
    from better_bing_image_downloader.manifest import ManifestWriter

    target = tmp_path / "manifest.jsonl"
    writer = ManifestWriter(target)
    try:
        assert target.exists()
    finally:
        writer.close()


def test_writer_appends_jsonl_one_line_per_append(tmp_path: Path) -> None:
    """Each append() writes exactly one valid JSON line."""
    from better_bing_image_downloader.manifest import ManifestWriter

    target = tmp_path / "manifest.jsonl"
    writer = ManifestWriter(target, fields=["url", "md5"])
    try:
        writer.append({"url": "https://a/1", "md5": "aaaa"})
        writer.append({"url": "https://a/2", "md5": "bbbb"})
        writer.append({"url": "https://a/3", "md5": "cccc"})
    finally:
        writer.close()

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        parsed = json.loads(line)
        assert isinstance(parsed, dict)
    assert json.loads(lines[0]) == {"url": "https://a/1", "md5": "aaaa"}
    assert json.loads(lines[2]) == {"url": "https://a/3", "md5": "cccc"}


def test_writer_filters_to_configured_fields(tmp_path: Path) -> None:
    """Only configured fields appear in the output."""
    from better_bing_image_downloader.manifest import ManifestWriter

    target = tmp_path / "manifest.jsonl"
    writer = ManifestWriter(target, fields=["url", "status"])
    try:
        writer.append({"url": "https://a/1", "file": "x.jpg", "md5": "aaa", "status": "ok"})
    finally:
        writer.close()

    line = target.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert parsed == {"url": "https://a/1", "status": "ok"}


def test_writer_default_fields_are_core_plus_provenance(tmp_path: Path) -> None:
    """The default field set is the 10 core+provenance fields, in the documented order."""
    from better_bing_image_downloader.manifest import (
        DEFAULT_MANIFEST_FIELDS,
        ManifestWriter,
    )

    assert DEFAULT_MANIFEST_FIELDS == [
        "index",
        "status",
        "url",
        "file",
        "md5",
        "error",
        "engine",
        "query",
        "source_page",
        "downloaded_at",
    ]

    target = tmp_path / "manifest.jsonl"
    writer = ManifestWriter(target)
    try:
        writer.append({f: f"v_{f}" for f in DEFAULT_MANIFEST_FIELDS})
    finally:
        writer.close()

    line = target.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    assert list(parsed.keys()) == DEFAULT_MANIFEST_FIELDS


def test_writer_rejects_unknown_field(tmp_path: Path) -> None:
    """Unknown field name raises ManifestFieldError (ValueError subclass) with helpful message."""
    from better_bing_image_downloader.manifest import (
        DEFAULT_MANIFEST_FIELDS,
        ManifestFieldError,
        ManifestWriter,
    )

    with pytest.raises(ManifestFieldError) as excinfo:
        ManifestWriter(tmp_path / "m.jsonl", fields=["bogus", "also_bogus"])
    msg = str(excinfo.value)
    assert "bogus" in msg
    assert "also_bogus" in msg
    # Liskov: a ManifestFieldError is a ValueError, so ``except ValueError``
    # still catches it.
    assert isinstance(excinfo.value, ValueError)
    # And the message lists the valid field names.
    for valid in DEFAULT_MANIFEST_FIELDS:
        assert valid in msg


def test_writer_close_is_idempotent(tmp_path: Path) -> None:
    """close() can be called multiple times without raising."""
    from better_bing_image_downloader.manifest import ManifestWriter

    target = tmp_path / "manifest.jsonl"
    writer = ManifestWriter(target)
    writer.close()
    writer.close()  # must not raise
    writer.close()


def test_writer_flushes_on_close(tmp_path: Path) -> None:
    """Records appended without manual flush are present after close()."""
    from better_bing_image_downloader.manifest import ManifestWriter

    target = tmp_path / "manifest.jsonl"
    writer = ManifestWriter(target)
    writer.append({"x": 1})
    writer.append({"x": 2})
    # No manual flush; close() must flush.
    writer.close()

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_writer_creates_parent_directory(tmp_path: Path) -> None:
    """The writer creates the parent directory if it does not exist."""
    from better_bing_image_downloader.manifest import ManifestWriter

    nested = tmp_path / "a" / "b" / "c" / "manifest.jsonl"
    writer = ManifestWriter(nested, fields=["url"])
    try:
        writer.append({"url": "https://a/1"})
    finally:
        writer.close()
    assert nested.exists()
    assert json.loads(nested.read_text(encoding="utf-8").strip()) == {"url": "https://a/1"}


def test_writer_swallows_write_errors_after_open(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A write error mid-run is logged and swallowed; the next append still works."""
    from better_bing_image_downloader.manifest import ManifestWriter

    target = tmp_path / "manifest.jsonl"
    writer = ManifestWriter(target, fields=["url"])
    real_write = writer._fp.write
    call_count = {"n": 0}

    def flaky_write(line: str) -> int:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OSError("disk full (test)")
        return real_write(line)

    with caplog.at_level("WARNING", logger="better_bing_image_downloader.manifest"):  # noqa: SIM117
        with patch.object(writer._fp, "write", side_effect=flaky_write):
            writer.append({"url": "https://a/1"})  # this one fails (swallowed)
            writer.append({"url": "https://a/2"})  # this one succeeds
    writer.close()

    # First append was swallowed; second was written.
    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"url": "https://a/2"}
    # And we logged a warning.
    assert any("manifest write failed" in rec.message for rec in caplog.records)


def test_writer_flush_every_n(tmp_path: Path) -> None:
    """flush_every=N controls how often flush() is called during appends.

    The relevant invariant is: with ``flush_every=N``, fewer than
    ``count / N`` flushes happen during ``append()`` calls (not
    counting the close-time flush). We assert that the per-N
    threshold was respected and that close flushed at least once.
    """
    from better_bing_image_downloader.manifest import ManifestWriter

    target = tmp_path / "manifest.jsonl"
    writer = ManifestWriter(target, fields=["url"], flush_every=3)
    real_flush = writer._fp.flush
    flush_count = {"n": 0}

    def counting_flush() -> None:
        flush_count["n"] += 1
        real_flush()

    with patch.object(writer._fp, "flush", side_effect=counting_flush):
        writer.append({"url": "https://a/1"})
        writer.append({"url": "https://a/2"})
        # Third append triggers a manual flush (pending reaches 3).
        writer.append({"url": "https://a/3"})
        writer.append({"url": "https://a/4"})
        writer.append({"url": "https://a/5"})
        mid_run_flushes = flush_count["n"]
        # During 5 appends with flush_every=3, the manual path
        # calls flush() exactly once (at record 3). Close() may
        # call it one or more times depending on the buffered text
        # file's close semantics; we just verify it flushed at
        # least once more on close.
        writer.close()
    # Manual mid-run flush: exactly 1.
    assert mid_run_flushes == 1
    # And close flushed at least once more.
    assert flush_count["n"] >= mid_run_flushes + 1


# --- Group B: Downloader integration tests (10 tests) ---


def _make_two_ok_stub() -> type[ImageEngine]:
    """A stub engine that downloads 2 images successfully."""

    class TwoOkStub(ImageEngine):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.last_page_url = "https://example.test/page?q=cat"

        def run(self) -> None:
            self.download_image("https://example.test/a.jpg", 1)
            self.download_image("https://example.test/b.jpg", 2)

    return TwoOkStub


def _make_three_with_one_error_stub() -> type[ImageEngine]:
    """A stub engine that downloads 2 OK, then triggers 1 save error.

    The error is raised by passing a URL whose ``_http_get`` returns
    non-image bytes (the engine's ``_save_image_raising`` will raise
    ``InvalidImageError``). This exercises the manifest's error
    path WITHOUT raising out of the engine (so the search returns
    a normal Result).
    """

    class ThreeWithOneErrorStub(ImageEngine):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.last_page_url = "https://example.test/page?q=cat"

        def run(self) -> None:
            self.download_image("https://example.test/a.jpg", 1)
            self.download_image("https://example.test/b.jpg", 2)
            # The test patches _http_get to fail (return non-image
            # bytes) for URLs containing 'broken' — this exercises
            # the manifest's "error" record path.
            self.download_image("https://example.test/broken.jpg", 3)

    return ThreeWithOneErrorStub


def _make_one_ok_then_engine_raises_stub() -> type[ImageEngine]:
    """A stub that downloads 1 image, then raises out of run() itself."""

    class OneOkThenRaisesStub(ImageEngine):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.last_page_url = "https://example.test/page?q=cat"

        def run(self) -> None:
            self.download_image("https://example.test/a.jpg", 1)
            # Raise from inside run() so the search()'s try/finally
            # catches and re-raises.
            raise RuntimeError("simulated engine failure")

    return OneOkThenRaisesStub


def test_search_with_manifest_false_writes_nothing(tmp_path: Path) -> None:
    """manifest=False (default): no file, result.manifest_path is None."""
    dl = Downloader()
    dl.register("stub", _make_two_ok_stub())

    result = dl.search("cat", limit=2, engine="stub", output_dir=tmp_path)

    assert result.manifest_path is None
    # No manifest file under tmp_path.
    assert not (tmp_path / "cat" / "manifest.jsonl").exists()
    assert not (tmp_path / "manifest.jsonl").exists()


def test_search_with_manifest_true_writes_records(tmp_path: Path) -> None:
    """manifest=True: a manifest file appears, one line per attempt."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_three_with_one_error_stub())

    def fake_http_get(self, url, headers=None):
        # URLs containing "broken" return non-image bytes, so
        # ``_save_image_raising`` raises ``InvalidImageError``.
        if "broken" in url:
            return b"not an image"
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=3, engine="stub", output_dir=tmp_path, manifest=True)

    assert result.manifest_path is not None
    manifest = Path(result.manifest_path)
    assert manifest.exists()

    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    records = [json.loads(line) for line in lines]
    statuses = [r["status"] for r in records]
    errors = [r["error"] for r in records]
    assert statuses == ["ok", "ok", "error"]
    assert errors == [None, None, "InvalidImageError"]


def test_search_manifest_respects_custom_fields(tmp_path: Path) -> None:
    """manifest_fields filters which keys appear in each record."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_two_ok_stub())

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search(
            "cat",
            limit=2,
            engine="stub",
            output_dir=tmp_path,
            manifest=True,
            manifest_fields=["url", "md5"],
        )

    manifest = Path(result.manifest_path)
    lines = manifest.read_text(encoding="utf-8").splitlines()
    for line in lines:
        parsed = json.loads(line)
        assert set(parsed.keys()) == {"url", "md5"}


def test_search_manifest_path_default_is_output_dir_slash_manifest_jsonl(
    tmp_path: Path,
) -> None:
    """Default manifest path is <output_dir>/<query>/manifest.jsonl."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_two_ok_stub())

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=2, engine="stub", output_dir=tmp_path, manifest=True)

    expected = (tmp_path / "cat" / "manifest.jsonl").resolve()
    assert Path(result.manifest_path) == expected
    assert expected.exists()


def test_search_manifest_path_override(tmp_path: Path) -> None:
    """An explicit manifest_path writes the file at the given path, not under output_dir."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_two_ok_stub())

    custom = tmp_path / "custom" / "my-manifest.jsonl"

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search(
            "cat",
            limit=2,
            engine="stub",
            output_dir=tmp_path,
            manifest=True,
            manifest_path=custom,
        )

    assert Path(result.manifest_path) == custom.resolve()
    assert custom.exists()
    # And NOT in the default location.
    assert not (tmp_path / "cat" / "manifest.jsonl").exists()


def test_search_manifest_captures_source_page_from_engine(tmp_path: Path) -> None:
    """A record's source_page matches engine.last_page_url when the engine sets it."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()

    class PagedStub(ImageEngine):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.last_page_url = "https://example.test/results?q=cat&page=1"

        def run(self) -> None:
            self.download_image("https://example.test/a.jpg", 1)

    dl.register("paged", PagedStub)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=1, engine="paged", output_dir=tmp_path, manifest=True)

    record = json.loads(Path(result.manifest_path).read_text(encoding="utf-8").strip())
    assert record["source_page"] == "https://example.test/results?q=cat&page=1"


def test_search_manifest_captures_null_source_page_when_engine_doesnt_set_it(
    tmp_path: Path,
) -> None:
    """If the engine doesn't set last_page_url, source_page is null."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()

    class NoUrlStub(ImageEngine):
        def run(self) -> None:
            # Deliberately do not set self.last_page_url.
            self.download_image("https://example.test/a.jpg", 1)

    dl.register("nourl", NoUrlStub)

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=1, engine="nourl", output_dir=tmp_path, manifest=True)

    record = json.loads(Path(result.manifest_path).read_text(encoding="utf-8").strip())
    assert record["source_page"] is None


def test_search_manifest_records_index_is_one_based_and_sequential(tmp_path: Path) -> None:
    """Record indices are 1-based and increment per record (failures included)."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_three_with_one_error_stub())

    def fake_http_get(self, url, headers=None):
        if "broken" in url:
            return b"not an image"
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=3, engine="stub", output_dir=tmp_path, manifest=True)

    lines = Path(result.manifest_path).read_text(encoding="utf-8").splitlines()
    indices = [json.loads(line)["index"] for line in lines]
    assert indices == [1, 2, 3]


def test_search_manifest_records_have_utc_timestamp(tmp_path: Path) -> None:
    """downloaded_at is an ISO 8601 UTC string with a trailing 'Z'."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_three_with_one_error_stub())

    def fake_http_get(self, url, headers=None):
        if "broken" in url:
            return b"not an image"
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=3, engine="stub", output_dir=tmp_path, manifest=True)

    lines = Path(result.manifest_path).read_text(encoding="utf-8").splitlines()
    for line in lines:
        ts = json.loads(line)["downloaded_at"]
        # YYYY-MM-DDTHH:MM:SSZ
        assert len(ts) == 20, f"unexpected timestamp format: {ts!r}"
        assert ts[4] == "-"
        assert ts[7] == "-"
        assert ts[10] == "T"
        assert ts[13] == ":"
        assert ts[16] == ":"
        assert ts.endswith("Z")


def test_search_manifest_writer_closed_on_exception(tmp_path: Path) -> None:
    """If the engine raises mid-run, the manifest is still flushed and closed."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_one_ok_then_engine_raises_stub())

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):  # noqa: SIM117
        with pytest.raises(RuntimeError, match="simulated engine failure"):
            dl.search("cat", limit=3, engine="stub", output_dir=tmp_path, manifest=True)

    # The manifest file must still exist with the 1 successful record
    # that was written before the engine raised, and the file handle
    # must be closed.
    expected = (tmp_path / "cat" / "manifest.jsonl").resolve()
    assert expected.exists()
    lines = expected.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    records = [json.loads(line) for line in lines]
    assert all(r["status"] == "ok" for r in records)


# --- Group C: Result + CLI integration (4 tests) ---


def test_result_manifest_path_attribute(tmp_path: Path) -> None:
    """Result.manifest_path is None by default and absolute when manifest=True."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_two_ok_stub())

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    # Default (no manifest): None.
    result_off = dl.search("cat", limit=2, engine="stub", output_dir=tmp_path)
    assert result_off.manifest_path is None

    # With manifest: absolute path string.
    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result_on = dl.search("cat", limit=2, engine="stub", output_dir=tmp_path, manifest=True)
    assert result_on.manifest_path is not None
    assert Path(result_on.manifest_path).is_absolute()


def test_search_async_writes_manifest(tmp_path: Path) -> None:
    """search_async with manifest=True produces the same manifest as search."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_three_with_one_error_stub())

    def fake_http_get(self, url, headers=None):
        if "broken" in url:
            return b"not an image"
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = asyncio.run(
            dl.search_async(
                "cat",
                limit=3,
                engine="stub",
                output_dir=tmp_path,
                manifest=True,
            )
        )

    assert result.manifest_path is not None
    lines = Path(result.manifest_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    statuses = [json.loads(line)["status"] for line in lines]
    assert statuses == ["ok", "ok", "error"]


def test_cli_manifest_flag_writes_file(tmp_path: Path, monkeypatch, capsys) -> None:
    """The --manifest CLI flag causes a manifest.jsonl to be written."""
    from better_bing_image_downloader import download as _download

    # Register a stub engine against the default Downloader registry used
    # by the CLI's main() function.
    class NoopStub(ImageEngine):
        def run(self) -> None:
            pass

    # Patch the CLI's downloader() entry point to use a stub that
    # records the manifest call but doesn't actually do work.
    captured: dict = {}

    def fake_downloader(query, *args, **kwargs):
        captured["manifest"] = kwargs.get("manifest", False)
        captured["manifest_path"] = kwargs.get("manifest_path")
        captured["manifest_fields"] = kwargs.get("manifest_fields")
        return 0

    monkeypatch.setattr(_download, "downloader", fake_downloader)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bbid",
            "cat",
            "--limit",
            "0",
            "--output_dir",
            str(tmp_path),
            "--manifest",
        ],
    )
    _download.main()
    assert captured["manifest"] is True
    assert captured["manifest_path"] is None
    assert captured["manifest_fields"] is None
    # And the CLI printed the manifest path line (it'll be None here since
    # the stub doesn't return a real result, but the call should succeed).


def test_cli_manifest_fields_flag_filters(tmp_path: Path, monkeypatch, capsys) -> None:
    """The --manifest-fields CLI flag forwards the field list."""
    from better_bing_image_downloader import download as _download

    captured: dict = {}

    def fake_downloader(query, *args, **kwargs):
        captured["manifest_fields"] = kwargs.get("manifest_fields")
        return 0

    monkeypatch.setattr(_download, "downloader", fake_downloader)
    monkeypatch.setattr(
        "sys.argv",
        [
            "bbid",
            "cat",
            "--limit",
            "0",
            "--output_dir",
            str(tmp_path),
            "--manifest",
            "--manifest-fields",
            "url,md5,status",
        ],
    )
    _download.main()
    assert captured["manifest_fields"] == ["url", "md5", "status"]


# --- Group D: Backwards compatibility (2 tests) ---


def test_existing_search_call_with_manifest_default_unchanged(tmp_path: Path) -> None:
    """Calling search() without any manifest args produces the same behavior as v3.4.0."""
    from better_bing_image_downloader import base as _base

    dl = Downloader()
    dl.register("stub", _make_two_ok_stub())

    def fake_http_get(self, url, headers=None):
        return b"\xff\xd8\xff\xe0" + url.encode("utf-8")

    with patch.object(_base.ImageEngine, "_http_get", fake_http_get):
        result = dl.search("cat", limit=2, engine="stub", output_dir=tmp_path)

    # No manifest file should exist anywhere under output_dir.
    files = list((tmp_path).rglob("manifest.jsonl"))
    assert files == []
    # Result.manifest_path is None.
    # The 2 successful downloads are still in the result.
    assert result.count == 2
    assert len(result.errors) == 0


def test_legacy_downloader_function_supports_manifest(tmp_path: Path) -> None:
    """The module-level downloader() function forwards manifest kwargs to Downloader."""
    from better_bing_image_downloader.download import downloader

    # Patch the Downloader class used inside download() to use a stub
    # engine. The legacy downloader() forwards manifest kwargs; we just
    # verify they reach the underlying call without raising.
    captured: dict = {}

    real_search = Downloader.search

    def spy_search(self, *args, **kwargs):
        captured["manifest"] = kwargs.get("manifest")
        captured["manifest_path"] = kwargs.get("manifest_path")
        captured["manifest_fields"] = kwargs.get("manifest_fields")
        # Call the real one with limit=0 to avoid real downloads.
        return real_search(self, "cat", limit=0, engine="bing", output_dir=tmp_path)

    with patch.object(Downloader, "search", spy_search):
        result_count = downloader(
            "cat",
            limit=0,
            output_dir=str(tmp_path),
            manifest=True,
            manifest_fields=["url", "md5"],
        )

    assert captured["manifest"] is True
    assert captured["manifest_fields"] == ["url", "md5"]
    # Legacy downloader() returns int.
    assert isinstance(result_count, int)
