# v3.5.0: Manifest Export — Design Spec

**Status:** Draft (awaiting user review)
**Date:** 2026-06-13
**Target version:** 3.5.0
**Estimated scope:** 1 new module, 1 new test file, 4 new params on `search()`, 1 new engine attribute, 4 new CLI flags, ~26 new tests.

## 1. Motivation

`better-bing-image-downloader` v3.4.0 produces images on disk and a `Result` object in memory. The `Result` is in-memory only — it doesn't survive a crash, can't be loaded incrementally, and doesn't compose with downstream data tooling (`pandas`, `pyarrow`, `img2dataset`, Hugging Face `datasets`).

The dominant user segment (ML training data preparation) needs a **persistent, line-oriented, append-only record** of what was downloaded, with enough metadata to reconstruct provenance, filter downstream, or feed directly into `img2dataset`.

v3.5.0 adds this primitive: a **JSONL manifest** that is streamed to disk during the run. Everything else (HF `datasets` integration, `min_dimension` filter, `bbid preview`) builds on this primitive in future releases.

## 2. Goals and non-goals

### Goals

- One JSONL line per image, written as the run progresses.
- Crash-safe by default: a partial run leaves a partial but valid manifest.
- Backwards compatible: zero behavior change for users who don't enable the manifest.
- Configurable field set: user picks which of 10 known fields to include.
- Reusable: the `ManifestWriter` class is usable independently of `Downloader`.

### Non-goals (deferred to later releases)

- Hugging Face `datasets` integration (v3.6.0+).
- `min_dimension` / `min_width` / `min_height` filters (v3.6.0+).
- `bbid preview <query>` CLI command (no version set).
- Image dimensions / MIME type in the manifest (would require post-save disk reads; not worth it for v3.5.0).
- Sorting the manifest at end of run (records are written in save order; downstream tools can sort if needed).
- Thread-safe manifest writer (not needed; engines are single-threaded for record-append).

## 3. Architecture

```
Downloader.search(query, ..., manifest=True, manifest_path=..., manifest_fields=...)
       │
       │ if manifest=True:
       │     construct ManifestWriter at manifest_path
       │     store on self._manifest_writer
       ▼
[ existing _run_engine loop ]
       │
       │ after each save_image (success):
       │     if self._manifest_writer: append "ok" record
       │
       │ on exception (failure):
       │     if self._manifest_writer: append "error" record
       │     (and call on_error as today)
       ▼
manifest.jsonl in output_dir (or at manifest_path)
       │
       │ in finally block:
       │     self._manifest_writer.close()
       ▼
Result(manifest_path=...) returned to caller
```

**Key design choices:**

1. **No new base class.** Engines stay unchanged except for one new attribute: `last_page_url` (set on each page fetch in `Bing.run()` and `DuckDuckGo.run()`). Engines are ignorant of the manifest.

2. **Manifest is a hook-driven concern, not an engine concern.** The manifest writer is invoked at the same call sites as `on_image` / `on_error` inside `_run_engine`. No engine-side awareness is required.

3. **`ManifestWriter` lives in a new module** `better_bing_image_downloader/manifest.py`. It is the public primitive. It is reusable independently of `Downloader` for users who want to build their own pipelines.

4. **Stream-as-you-go, buffered.** File is opened in append mode with line buffering. Default flush is every record. A `flush_every=N` knob trades crash-safety for throughput on slow disks.

## 4. Module layout

New file: `better_bing_image_downloader/manifest.py`

```python
"""JSONL manifest writer for image search runs.

A small, append-only writer that streams one JSON object per line
to a file. Used by Downloader.search when manifest=True.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

# Default field set: "core + provenance" (10 fields).
DEFAULT_MANIFEST_FIELDS: list[str] = [
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

_VALID_STATUSES = ("ok", "error", "skipped")


class ManifestFieldError(ValueError):
    """Raised when an unknown field is requested."""


class ManifestWriter:
    """Append-only JSONL writer for search run records.

    Each call to append() writes one line of JSON. Records are
    filtered to the configured fields list before being written.
    The writer is not thread-safe; it is intended for use from
    the single-threaded Downloader.search main loop.
    """

    def __init__(
        self,
        path: str | os.PathLike,
        fields: list[str] | None = None,
        flush_every: int = 1,
    ) -> None:
        if fields is None:
            fields = list(DEFAULT_MANIFEST_FIELDS)
        unknown = [f for f in fields if f not in DEFAULT_MANIFEST_FIELDS]
        if unknown:
            raise ManifestFieldError(
                f"unknown manifest field(s) {unknown!r}; "
                f"valid: {DEFAULT_MANIFEST_FIELDS}"
            )
        if flush_every < 1:
            raise ValueError("flush_every must be >= 1")
        self._fields = fields
        self._flush_every = flush_every
        self._pending = 0
        self._closed = False
        # Ensure parent dir exists (match output_dir semantics in base.py).
        parent = Path(path).expanduser().parent
        parent.mkdir(parents=True, exist_ok=True)
        # Line-buffered append mode. buffering=1 = line buffered.
        self._fp: IO[str] = open(
            Path(path).expanduser(), "a", encoding="utf-8", buffering=1
        )

    @property
    def fields(self) -> list[str]:
        return list(self._fields)

    def append(self, record: dict) -> None:
        """Write one record as a JSON line. Filters to configured fields."""
        if self._closed:
            return
        try:
            filtered = {k: record.get(k) for k in self._fields}
            line = json.dumps(filtered, ensure_ascii=False, separators=(",", ":"))
            self._fp.write(line + "\n")
            self._pending += 1
            if self._pending >= self._flush_every:
                self._fp.flush()
                self._pending = 0
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.warning("manifest write failed: %s", exc)

    def close(self) -> None:
        """Flush and close the file. Idempotent."""
        if self._closed:
            return
        try:
            self._fp.flush()
            self._fp.close()
        except Exception as exc:  # noqa: BLE001 - defensive
            logger.warning("manifest close failed: %s", exc)
        self._closed = True

    def __enter__(self) -> "ManifestWriter":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
```

Modified files:

- `better_bing_image_downloader/base.py`: add `self.last_page_url: str | None = None` to `ImageEngine.__init__`.
- `better_bing_image_downloader/bing.py`: set `self.last_page_url = url` after each page fetch in `run()`.
- `better_bing_image_downloader/duckduckgo.py`: set `self.last_page_url = url` after each page fetch in `run()`.
- `better_bing_image_downloader/downloader.py`:
  - Import `ManifestWriter` and a `_utcnow_iso()` helper.
  - Add 4 new params to `search()`: `manifest`, `manifest_path`, `manifest_fields`, `manifest_flush_every`.
  - Wrap `_run_engine` call in `try/finally` to close the manifest writer.
  - In `_run_engine`, at the success and error call sites, append records to `self._manifest_writer` if set.
  - Set `Result.manifest_path` on the returned result.
- `better_bing_image_downloader/results.py`: add `manifest_path: str | None = None` field to `Result`.
- `better_bing_image_downloader/download.py`: add 4 new CLI flags and pass them through `Downloader.search`. Print `result.manifest_path` after the run if set.
- `better_bing_image_downloader/__init__.py`: re-export `ManifestWriter` and `DEFAULT_MANIFEST_FIELDS` at top level.

New test file: `tests/test_v3_5_0_manifest.py` (26 tests, see section 8).

## 5. Manifest schema

The manifest is **one JSON object per line** in a `manifest.jsonl` file. Each record represents one image (success or failure).

### 5.1 Field set

10 fields. Field values that are `None` are written as JSON `null` (explicit, not omitted).

| Field | Type | Source | Notes |
|---|---|---|---|
| `index` | `int` | `engine.download_count + 1` (1-based) | Increments per-record, including failures |
| `status` | `str` | `"ok"` / `"error"` / `"skipped"` | Enum, see 5.2 |
| `url` | `str` | The image URL we tried to fetch | Always present |
| `file` | `str \| null` | Path relative to `output_dir` (e.g. `"red panda_1.jpg"`) | `null` on failure |
| `md5` | `str \| null` | MD5 of saved bytes | `null` on failure |
| `error` | `str \| null` | Typed exception class name (e.g. `"NetworkError"`) | `null` on success |
| `engine` | `str` | `"bing"` / `"duckduckgo"` / user-registered | Always present |
| `query` | `str` | The search query | Always present |
| `source_page` | `str \| null` | The search-results page URL the image came from | `null` if engine doesn't set `last_page_url` |
| `downloaded_at` | `str` | ISO 8601 UTC timestamp, e.g. `"2026-06-13T15:30:42Z"` | Always present |

### 5.2 Status semantics

- `"ok"` — image saved successfully. `file` and `md5` are set. `error` is `null`.
- `"error"` — fetch or save failed. `file` and `md5` are `null`. `error` is the exception class name.
- `"skipped"` — image was a duplicate (MD5 already existed) or hit a skip filter. `file` and `md5` may be set if a partial write happened. `error` is the exception class name (typically `"DuplicateImageError"`).

### 5.3 `manifest_fields` semantics

- An **allowlist** of any of the 10 field names.
- The writer filters each record to only the configured fields before writing.
- Default (`manifest_fields=None`) is the full 10-field set, in the order listed in 5.1.
- Unknown field names → `ManifestFieldError` (a subclass of `ValueError`) at `ManifestWriter.__init__` time. The error message lists the valid field names.
- The order of fields in the output JSONL matches the order of `manifest_fields` (Python dict insertion order is preserved by `json.dumps`).

### 5.4 Example records

Success (default fields):
```json
{"index": 1, "status": "ok", "url": "https://example.com/red-panda.jpg", "file": "red panda_1.jpg", "md5": "5d41402abc4b2a76b9719d911017c592", "error": null, "engine": "bing", "query": "red panda", "source_page": "https://www.bing.com/images/search?q=red+panda&form=HDRSC2", "downloaded_at": "2026-06-13T15:30:42Z"}
```

Failure:
```json
{"index": 5, "status": "error", "url": "https://example.com/broken.jpg", "file": null, "md5": null, "error": "NetworkError", "engine": "duckduckgo", "query": "red panda", "source_page": "https://duckduckgo.com/?q=red+panda&iax=images&ia=images", "downloaded_at": "2026-06-13T15:31:08Z"}
```

Filtered to `manifest_fields=["url", "md5"]`:
```json
{"url": "https://example.com/red-panda.jpg", "md5": "5d41402abc4b2a76b9719d911017c592"}
```

## 6. Writer semantics

### 6.1 Construction

- `path` is the full file path. Parent directory is created if it doesn't exist (matches the `output_dir` semantics in `base.py`).
- File is opened in **append mode with line buffering** (`open(path, "a", encoding="utf-8", buffering=1)`).
- `flush_every=1` (default): flush after every record. Crash-safe.
- `flush_every=N > 1`: flush every N records. Faster on slow disks, loses up to N-1 records on crash.

### 6.2 `append(record)`

- `record` is a dict with **all 10 fields populated** (or as many as the caller knows).
- The writer **filters** to the configured `fields` list and writes a single JSON line.
- A failed `json.dumps` is logged via `logging` and **swallowed** — manifest writes must never crash a search.
- After `close()` is called, `append()` is a no-op (returns silently).

### 6.3 `close()`

- Flushes pending writes, closes the file handle.
- **Idempotent**: calling `close()` twice is a no-op.
- Called from a `try/finally` in `Downloader.search` so the manifest is always closed even on exception.

### 6.4 Error handling

- **File-open errors** (permission denied, disk full at startup) → `ManifestWriter.__init__` raises. The user explicitly asked for a manifest; fail loudly if we can't create it.
- **Write errors mid-run** → logged, swallowed. The download continues. Matches `on_error` semantics (best-effort observability).
- **`close()` errors** → logged, swallowed. The caller has already gotten their `Result`.

### 6.5 Concurrency

- The writer is **not thread-safe**.
- `Downloader.search` is single-threaded for engine `run()`; engines do their own parallel image downloads, but record-appending happens in the main thread. The base class's parallel `_download_batch` only matters for image bytes, not for the manifest.
- If a user wants a thread-safe manifest writer, they can subclass `ManifestWriter`. Not provided out of the box (YAGNI).

### 6.6 Context manager

`ManifestWriter` supports `with` syntax: `with ManifestWriter(path) as w: w.append(...)`. Useful for users who want to write their own pipelines. `__exit__` calls `close()`.

## 7. `Downloader` integration

### 7.1 New `search()` parameters

```python
def search(
    self,
    query: str,
    limit: int = 100,
    output_dir: str = "dataset",
    engine: str = "bing",
    timeout: float = 60.0,
    filters: str = "",
    force_replace: bool = False,
    verbose: bool = False,
    threads: int | None = None,
    cancel: CancelToken | None = None,
    on_image: Callable | None = None,
    on_error: Callable | None = None,
    on_progress: Callable | None = None,
    # NEW ↓
    manifest: bool = False,
    manifest_path: str | os.PathLike | None = None,
    manifest_fields: list[str] | None = None,
    manifest_flush_every: int = 1,
) -> Result: ...
```

All four are keyword-only-by-convention (existing `search()` is keyword-arg-driven; the legacy `downloader()` only forwards known args).

### 7.2 Behavior

- **`manifest=False` (default):** zero behavior change. The manifest writer is never constructed. No file is created. `result.manifest_path is None`.
- **`manifest=True`:** writer is constructed at the top of `search()`. Path is `manifest_path` if given, else `<output_dir>/manifest.jsonl`. Fields are `manifest_fields` if given, else the default 10. The writer is stored on `self._manifest_writer` and is `None` otherwise.

### 7.3 Record capture

In `_run_engine`, at the same call sites as `on_image` and `on_error`:

Success path (after a successful save):
```python
if self._manifest_writer is not None:
    self._manifest_writer.append({
        "index": engine.download_count + 1,
        "status": "ok",
        "url": link,
        "file": str(Path(file_path).relative_to(output_dir)) if file_path else None,
        "md5": md5_hash,
        "error": None,
        "engine": engine_name,
        "query": query,
        "source_page": getattr(engine, "last_page_url", None),
        "downloaded_at": _utcnow_iso(),
    })
```

Failure path (where `on_error` is called):
```python
if self._manifest_writer is not None:
    self._manifest_writer.append({
        "index": engine.download_count + 1,
        "status": "error",
        "url": link,
        "file": None,
        "md5": None,
        "error": type(exc).__name__,
        "engine": engine_name,
        "query": query,
        "source_page": getattr(engine, "last_page_url", None),
        "downloaded_at": _utcnow_iso(),
    })
```

Note: `engine.download_count + 1` is the **1-based index of the next record**. The engine increments `download_count` *after* a successful save, so on the success path this is the index of the just-saved image; on the failure path it's the index of the failed attempt (the engine's counter didn't advance).

### 7.4 `Result.manifest_path`

`Result` gets one new attribute:

```python
manifest_path: str | None  # absolute path to the manifest file, or None
```

Set by `Downloader.search` after the manifest writer is constructed. `None` if `manifest=False`. Always **absolute** (resolved via `Path(manifest_path).resolve()` so it's useful for downstream tools that don't know the working directory).

### 7.5 `search_async` and legacy `downloader()`

- `Downloader.search_async` is `await asyncio.to_thread(self.search, ...)` — it inherits all new params automatically.
- Legacy `downloader(query, limit, output_dir, ...)` in `download.py` adds 4 new kwargs and forwards them. This is the **only change** to the legacy wrapper.

### 7.6 Engine changes (minimal)

`ImageEngine.__init__` gets one new line:
```python
self.last_page_url: str | None = None
```

`Bing.run()` sets `self.last_page_url = url` after each page fetch. Same for `DuckDuckGo.run()`. The manifest reads it via `getattr(engine, "last_page_url", None)`, so engines that don't set it just get `None` in the manifest — graceful degradation, not a contract violation.

### 7.7 CLI integration

`bbid` in `download.py` gets 4 new flags:

- `--manifest` / `--no-manifest` (default `--no-manifest`)
- `--manifest-path PATH`
- `--manifest-fields f1,f2,f3` (comma-separated)
- `--manifest-flush-every N` (default 1)

After a successful run, if `result.manifest_path` is set, print it: `Wrote manifest to /abs/path/to/manifest.jsonl`. This is a one-line addition to the existing CLI finalization code.

## 8. Testing strategy

New test file: `tests/test_v3_5_0_manifest.py`. **26 new tests** in 4 groups. All tests follow the project's existing patterns: mock at module-attribute boundaries, no real network, stub engines for `_run_engine` integration.

### Group A: `ManifestWriter` unit tests (10 tests)

1. `test_writer_creates_file_on_construction` — `os.path.exists(path)` is `True` after construction.
2. `test_writer_appends_jsonl_one_line_per_append` — 3 appends → 3 lines, each valid JSON.
3. `test_writer_filters_to_configured_fields` — `fields=["a", "c"]` writes only those keys.
4. `test_writer_default_fields_are_core_plus_provenance` — 10 fields in documented order.
5. `test_writer_rejects_unknown_field` — raises `ManifestFieldError` (a `ValueError` subclass) with bad name + valid list. Test also asserts `except ValueError` still catches it (Liskov substitution).
6. `test_writer_close_is_idempotent` — `close()` twice doesn't raise.
7. `test_writer_flushes_on_close` — append without flush, close, read → all records present.
8. `test_writer_creates_parent_directory` — pass a path under nonexistent dir → dir is created.
9. `test_writer_swallows_write_errors_after_open` — mock `write` to raise once, next `append` doesn't propagate.
10. `test_writer_flush_every_n` — `flush_every=3`, 5 appends → exactly 2 flushes (at record 3, on close).

### Group B: `Downloader` integration tests (10 tests)

11. `test_search_with_manifest_false_writes_nothing` — `manifest=False`, no file, `result.manifest_path is None`.
12. `test_search_with_manifest_true_writes_records` — stub downloads 2 + 1 fails → 3 lines, statuses `["ok", "ok", "error"]`, errors `["NetworkError"]`.
13. `test_search_manifest_respects_custom_fields` — `manifest_fields=["url", "md5"]` → each line has 2 keys.
14. `test_search_manifest_path_default_is_output_dir_slash_manifest_jsonl` — default lands at `<output_dir>/manifest.jsonl`.
15. `test_search_manifest_path_override` — `manifest_path="/tmp/foo/whatever.jsonl"` → file there, not in `output_dir`.
16. `test_search_manifest_captures_source_page_from_engine` — stub sets `last_page_url`, record has it.
17. `test_search_manifest_captures_null_source_page_when_engine_doesnt_set_it` — stub doesn't set it, record has `null`.
18. `test_search_manifest_records_index_is_one_based_and_sequential` — 3 records, indices `1, 2, 3`.
19. `test_search_manifest_records_have_utc_timestamp` — `downloaded_at` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`.
20. `test_search_manifest_writer_closed_on_exception` — search raises mid-run, file is still flushed and closed (no "unclosed file" warning; partial content is readable).

### Group C: Result + CLI integration (4 tests)

21. `test_result_manifest_path_attribute` — `None` when off, absolute path when on.
22. `test_search_async_writes_manifest` — `await dl.search_async(..., manifest=True)` produces same manifest.
23. `test_cli_manifest_flag_writes_file` — `bbid --manifest --limit 0` (stub engine) → file exists.
24. `test_cli_manifest_fields_flag_filters` — `--manifest --manifest-fields url,md5` → 2-field lines.

### Group D: Backwards compatibility (2 tests)

25. `test_existing_search_call_with_manifest_default_unchanged` — no manifest args → same behavior as v3.4.0.
26. `test_legacy_downloader_function_supports_manifest` — `downloader()` wrapper passes `manifest` through.

**Total: 26 new tests. Total post-v3.5.0: 149 tests passing, 2 network tests skipped by default.**

### Test patterns reused

- Stub engine: a small `class StubEngine(ImageEngine)` that subclasses `ImageEngine`, implements `run()` to perform a known set of downloads + one failure. Same pattern as `tests/test_v3_2_0_api.py`.
- Mocks at the engine-attribute boundary (e.g., `engine.last_page_url`), not the engine's internal HTTP.
- No real network tests. No `BBID_RUN_NETWORK_TESTS` gate needed — manifest is pure local file I/O.
- The `caplog` fixture (pytest built-in) is used for log-capture tests (Group A #9).

## 9. Migration and risk

### 9.1 Backwards compatibility

- All 4 new params default to off. Existing `Downloader.search()` and `bbid` invocations are unchanged.
- `Result.manifest_path` is a new attribute. Existing code that constructs `Result` directly (only inside the library) gets a default of `None` via the new dataclass field with default.
- `ImageEngine.last_page_url` is a new attribute. Engines that don't set it get `None` in the manifest — not a `KeyError`. Custom engine subclasses that don't subclass `ImageEngine` (i.e., duck-typed) are unaffected.

### 9.2 Risks

- **`last_page_url` is engine-internal state.** If an engine sets it on the **wrong object** (e.g., a per-thread instance) the manifest will get the wrong value. Mitigation: this is the engine author's responsibility; document in `ImageEngine` docstring.
- **Disk I/O on every record** could slow down very fast networks. Mitigation: `manifest_flush_every` knob; default 1 is fine for typical use (10-100 images/min).
- **Manifest file grows unboundedly** during a long run. Mitigation: it's a single file, the OS handles it. If a user runs 1M images they'll have a 1M-line JSONL — that's the user's choice.
- **Cross-platform path handling.** `Path(file_path).relative_to(output_dir)` could fail if `file_path` is not under `output_dir`. Mitigation: the engine constructs `file_path` from `output_dir` plus a filename; this is already the case in `base.py`. We add a defensive try/except that falls back to `os.path.basename(file_path)` if `relative_to` raises.
- **JSON encoding of non-ASCII queries.** The default `ensure_ascii=True` produces escaped unicode; we set `ensure_ascii=False` for readability. Both are valid JSON; downstream tools handle both.

### 9.3 Rollout

- v3.5.0 is a **minor** release (3.x.0 → 3.5.0) — backwards compatible, additive feature.
- No new top-level dependencies. No `brotli` change. No `py.typed` change.
- README: add a "Manifest export" section with a short example.
- CHANGELOG: add an Unreleased entry under a new `[3.5.0]` heading on release.
- AGENTS.md: bump version stamp; update test count.

## 10. Open questions (resolved during brainstorming)

| Question | Decision |
|---|---|
| What's the primary use case? | Generic / keep options open |
| Manifest schema? | User-configurable fields |
| Default field set? | Core + provenance (10 fields) |
| Source page URL source? | Engine attribute `last_page_url` |
| Failed records in manifest? | Include with `status` field |
| Write timing? | Stream-as-you-go, buffered (default flush every record) |
| Other features in this release? | Manifest only |

No remaining open questions at draft time.
