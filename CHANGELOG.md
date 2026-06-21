# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`min_dimension` filter** for `Downloader.search()` / `search_async()`.
  Images smaller than `min_dimension` pixels on either side are
  skipped before being saved — useful for ML training-data
  preparation, where thumbnails are noise. Dimensions are read
  directly from PNG, JPEG, GIF, BMP, and WEBP headers (no new
  dependency); formats we can't parse (e.g. TIFF) are never
  filtered.
- New `BelowMinDimension` exception (subclass of `ImageSaveError`,
  so `except ImageSaveError` still catches it).
- Skips from the new filter are recorded in the manifest as
  `status="skipped"`, `error="BelowMinDimension"`, and counted in
  `Result.skipped` — not `Result.errors` / `on_error`, since a
  too-small image is an intentional filter outcome, not a failure.
- The legacy `downloader()` function and the `bbid` CLI
  (`--min-dimension`) now also accept `min_dimension`, matching
  `Downloader.search()`.
- `Bing` and `DuckDuckGo` accept `min_dimension` directly in their
  constructors; `Downloader.search()` routes it through
  `engine_kwargs` like every other engine option instead of setting
  the attribute on the engine instance after construction.
- 13 new tests in `tests/test_v3_6_0_features.py`.

### Fixed

- The JPEG dimension reader now stops at the Start-of-Scan marker
  instead of walking into entropy-coded scan data.

## [3.5.1] - 2026-06-13

### Fixed

- Re-export `ManifestWriter`, `DEFAULT_MANIFEST_FIELDS`, and
  `ManifestFieldError` at the package top level so
  `from better_bing_image_downloader import ManifestWriter`
  works (these were only importable from the `manifest`
  submodule in 3.5.0). No code changes.

## [3.5.0] - 2026-06-13

### Added

- **JSONL manifest export** via `Downloader.search(manifest=True)`.
  Writes one JSON record per download attempt (success or failure)
  to `<output_dir>/<query>/manifest.jsonl` (or to a custom path).
  Records contain: `index`, `status`, `url`, `file`, `md5`, `error`,
  `engine`, `query`, `source_page`, `downloaded_at`. The writer is
  crash-safe (line-buffered, flushed every record by default) and
  filters records to a configurable `manifest_fields` list.
- **New `ManifestWriter` class** in `better_bing_image_downloader.manifest`,
  reusable independently of `Downloader` for users building custom
  pipelines. Supports context-manager syntax.
- **`Result.manifest_path`** attribute — absolute path to the manifest
  file (or `None` if `manifest=False`).
- **`ImageEngine.last_page_url`** attribute — set by `Bing` and
  `DuckDuckGo` on each page fetch; captured as `source_page` in
  manifest records. Custom engines that don't set it get `None`.
- **4 new `Downloader.search` params**: `manifest`, `manifest_path`,
  `manifest_fields`, `manifest_flush_every`. All default to off (zero
  behavior change for existing users).
- **4 new CLI flags**: `--manifest`, `--manifest-path`,
  `--manifest-fields`, `--manifest-flush-every`.
- **`_save_image_raising()` now returns the MD5** of the saved
  image bytes (typed exceptions still raised on failure). This
  lets the manifest writer record the hash without re-reading
  the file. `save_image()` (the public catching wrapper) is
  unchanged.

### Tests

- 26 new tests in `tests/test_v3_5_0_manifest.py` covering the
  manifest writer (10), `Downloader` integration (10), result
  attribute and CLI (4), and backwards compatibility (2).
- Total: 149 tests passing, 2 network tests skipped by default.

## [3.4.0] - 2026-06-05

### Added

- **Typed `ImageSaveError` subclasses**: `NetworkError`,
  `InvalidImageError`, `DuplicateImageError`, `WriteError`. All
  are subclasses of `ImageSaveError` (so existing
  `except ImageSaveError:` continues to work) but give callers
  a way to distinguish failure reasons without parsing the
  `reason` string. Resolves the 3.2.1 TODO.
- **`on_progress` hook** on `Downloader`:
  `on_progress(percent, downloaded, total, eta_seconds)`. Fires
  after each successful download. `eta_seconds` is `None` until
  the second download (one sample isn't enough to extrapolate).
  Powers progress bars and ETA displays.
- **`Downloader.search_async()`**: async wrapper around
  `search()`. Runs the existing engine in a thread via
  `asyncio.to_thread()`, so it works with the stdlib-only
  urllib-based engines — no new dependencies, no
  `aiohttp`. Returns the same `Result`. Hooks, cancellation
  token, and progress callback all work.
- **`ImageSaveError` and subclasses are now exposed at the top
  level** (`from better_bing_image_downloader import
  NetworkError`, etc.).
- **`_save_image_raising()` method** on `ImageEngine` — the
  new typed-exception variant. `save_image()` is now a thin
  wrapper that catches and returns `False` for backwards
  compatibility. `Downloader.search` uses the raising variant
  directly.

### Changed

- `save_image` is now the catching wrapper. Existing code that
  calls `engine.save_image()` and checks the bool return value
  continues to work unchanged. New code that wants typed
  exceptions should use `engine._save_image_raising()`.
- `Result.errors` entries that come from a `save_image`
  failure are now typed (e.g. `NetworkError` instead of
  generic `ImageSaveError(reason="save_failed")`). Users
  catching `ImageSaveError` are unaffected.

### Tests

- 11 new tests in `tests/test_v3_4_0_features.py`:
  - `ImageSaveError` subclass importability and Liskov
    substitution
  - Network error → `NetworkError` classification
  - Invalid bytes → `InvalidImageError` classification
  - Duplicate MD5 → `DuplicateImageError` classification
  - `on_progress` fires per image with correct percentages
  - ETA is `None` on first call, then extrapolates
  - `on_progress` exception safety
  - `search_async` returns a `Result`
  - `search_async` fires hooks
  - `search_async` honors `CancelToken`
- Total: 123 tests passing, 2 network tests skipped by default.

## [3.3.0] - 2026-06-05

### Added

- **`Result.no_results_found` flag** (bool). True when the search
  backend returned zero candidate URLs. Previously, a query that
  returned nothing was indistinguishable from one where all
  candidates were skipped (resume) or all failed (errors). Now
  callers can check `result.no_results_found` to tell them apart.
- **`CancelToken` class** for mid-run cancellation. Pass
  `cancel=token` to `Downloader.search()`; call `token.cancel()`
  from another thread (or a signal handler) to abort the run.
  Cooperative engines (Bing, DuckDuckGo) check the token between
  page fetches and stop cleanly. The partial `Result` is returned
  with `result.cancelled = True`.
- **`Result.cancelled` flag** (bool). True if a `CancelToken`
  aborted the run. The `images`, `skipped`, and `errors` lists
  reflect whatever was completed up to the cancellation point.
- **`ImageEngine.is_cancelled()` helper** method on the base class.
  Engines that subclass `ImageEngine` should call this in their
  `run()` loop to honor the cancel token.
- **Clamped `Result.skipped`**: if a custom engine subclass
  increments `download_count` without `_slots_used` (or vice
  versa), the subtraction `slots_used - download_count` could
  go negative. We now clamp to 0 so users don't see a
  nonsensical negative count.
- **`CancelToken` exposed at the top level**:
  `from better_bing_image_downloader import CancelToken`.

### Tests

- 7 new tests in `tests/test_v3_3_0_features.py`:
  - `no_results_found` True when engine ran zero pages
  - `no_results_found` False on success
  - `no_results_found` False on all-skipped (resume) case
  - `CancelToken` class basics (cancel, cancelled, reset)
  - `search()` honors a pre-cancelled token
  - `search()` honors a token cancelled mid-run (threaded)
  - Cancelled result is well-formed
- Total: 112 tests passing, 2 network tests skipped by default.

## [3.2.1] - 2026-06-05

### Fixed

- `Downloader.search()` no longer silently drops failed image saves.
  In 3.2.0, when `save_image` returned `False` (network error,
  invalid image body, duplicate, or write failure), the failure was
  logged at `ERROR` level but not surfaced to library users. In
  3.2.1, the `Downloader.search` wrapper now:
  - appends `(url, ImageSaveError(reason="save_failed", url=url))`
    to `Result.errors`
  - invokes the user's `on_error` hook (if set)
  - This matches the behavior of unhandled exceptions in
    `save_image`, which were already surfaced.
- New `ImageSaveError` exception class (in
  `better_bing_image_downloader.ImageSaveError`) is the public
  surface for "save_image returned False". It carries a `reason`
  string and a `url` attribute. For now, `reason` is always
  `"save_failed"`; specific reasons (`"network"`, `"invalid_image"`,
  `"duplicate"`, `"write_failed"`) will be added in 3.3.0 when
  `save_image` is changed to raise typed exceptions.

### Tests

- 6 new tests in `tests/test_v3_2_1_robustness.py`:
  - `on_image` exception safety
  - `on_error` exception safety
  - 5-thread concurrent `search()` corruption check
  - 50-thread concurrent `register()` race check
  - `save_image` returning `False` (invalid + duplicate) calls
    `on_error`
  - Network error in `_http_get` calls `on_error`
- Total: 105 tests passing, 2 network tests skipped by default.

## [3.2.0] - 2026-06-05

### Added

- `Downloader` class — the recommended entry point for library users.
  Owns a session (cookie jar + opener), an engine registry, and
  lifecycle hooks. See the README's "Embedding as a library" section.
- `Result` and `ImageResult` value objects — `Downloader.search()`
  returns a `Result` with the full list of saved images, errors, and
  metadata (`query`, `engine`, `output_dir`, `count`, `total_bytes`,
  `skipped`, `errors`).
- Lifecycle hooks: `on_image`, `on_error`, `on_engine_start`,
  `on_engine_done` — wire progress, logging, or cancellation into
  the download flow.
- Public engine registry: `Downloader.register(name, engine_class)`.
  Plug in custom engines without monkey-patching. Subclassing of
  `ImageEngine` is enforced.
- Shared session across calls — one `Downloader` instance reuses TCP
  connections and DuckDuckGo's `vqd` cookie across many searches
  (the latter is critical: without a stable vqd cookie, DDG's `i.js`
  returns 403).
- `ImageEngine` is now an `ABC` with `@abstractmethod run()`. Custom
  engines get a clear contract enforced by mypy at type-check time.
- 18 new unit tests + 1 live integration test (`tests/test_v3_2_0_*`).
  Total: 99 passing, 1 network test skipped by default.

### Changed

- The module-level `downloader()` function is now a thin wrapper
  around `Downloader().search()`. It still returns `int` for
  backwards compatibility, but the recommended way to get full
  results is `Result` from `Downloader.search()`.
- `ImageEngine.__init__` no longer requires `timeout` as a positional
  argument; default is 60s. Custom engine subclasses can be minimal
  (`class MyEngine(ImageEngine): def run(self): ...`).
- `ImageResult.index` renamed to `ImageResult.image_index` to avoid
  collision with `tuple.index()` in mypy.

## [3.1.1] - 2026-06-05

### Added

- `Bing()` and `DuckDuckGo()` can now be instantiated with just
  `(query, limit, output_dir)` — `adult`, `timeout`, `filter`, `verbose`,
  and engine-specific options all have sensible defaults. This makes the
  library genuinely integrable: `Bing("cat", 10, "/tmp/x")` works
  without keyword arguments.
- `py.typed` marker shipped. Downstream `mypy --strict` users now get the
  type hints we test against (previously all function signatures appeared
  as `Any` to external type-checkers).

### Changed

- `brotli` is now a hard runtime dependency (was an optional `[duckduckgo]`
  extra). DuckDuckGo's CDN returns 403 if the client can't decode Brotli,
  so the "extra" was a footgun: a fresh `pip install` and a `ddg` run
  would silently fail with no clear error.
- `downloader()` signature: only `query` is required; all 12 other
  parameters have defaults. This unblocks the common case of
  `downloader("cats")` in a notebook.

### Removed

- `[duckduckgo]` optional-dependency extra — `brotli` is now always
  installed.

## [3.1.0] - 2026-06-04

### Added

- **DuckDuckGo image search engine** — second search engine, switched via
  `engine="bing" | "duckduckgo"` on `downloader()` or `--engine` on `bbid`
  CLI. No browser required, no API key. Uses DuckDuckGo's `i.js` JSON API
  with Brotli-compressed responses.
- DuckDuckGo-specific options:
  - `ddg_safe_search` — `"strict"`, `"moderate"`, or `"off"` (default
    `"moderate"`)
  - `ddg_region` — region code such as `"us-en"`, `"uk-en"` (default
    `"us-en"`)
  - `--ddg-safe-search` and `--ddg-region` CLI flags
- Optional `[duckduckgo]` extra installs the `brotli` package required to
  decode DuckDuckGo responses.
- New `ImageEngine` base class — Bing and DuckDuckGo share download,
  deduplication, resume, and manifest logic. Less code duplication,
  fewer inconsistencies.
- 31 new tests (atomic write, parallel-future timeout, DuckDuckGo engine,
  engine-dispatch, deprecation markers). Total: 72 tests passing.

### Fixed

- **Atomic file writes in `bing.save_image`** — images are now written to
  a temp file in the target directory and renamed on success, so a
  download interrupted mid-write no longer leaves a corrupt file that
  resume would silently skip.
- **Per-future timeout on parallel downloads** — stalled connections
  can no longer block the whole batch indefinitely (180-second cap,
  matched with `helperdownload`).
- **Exponential backoff on Bing network errors** — was a fixed 2-second
  sleep with no cap; now doubles up to 60 seconds.
- **Bing page loop termination** — if a Bing page returns no new images,
  the run now stops instead of risking an infinite loop.
- **`helperdownload` uses `logging` instead of `print()`** — no more
  stdout pollution when used as a library.

### Deprecated

- Selenium-based `multidownloader` CLI is deprecated and will be removed
  in v4.0.0. The Google path no longer works (Google serves a
  JavaScript-only shell to automated requests); the Bing path is
  superseded by the new `bbid` CLI.
- `import better_bing_image_downloader.crawler` and
  `import better_bing_image_downloader.multidownloader` will emit
  `DeprecationWarning` and the Selenium path is no longer actively
  supported.

## [3.0.1] - 2026-01-15

### Fixed

- Updated Bing headers to advertise gzip/deflate; decompresses
  compressed responses (was returning severely truncated pages).
- Default adult filter changed to `moderate` (Bing's recommended safe
  search).
- New `mkt` parameter (default `en-US`) for region-specific Bing
  results.

## [3.0.0] - 2025-12-20

### Added

- `bbid` CLI command installed automatically via entry point
- Resume support — skips existing files, downloads only what's missing
- `_manifest.json` written per run with filename → source URL mapping
- MD5-based image deduplication
- `pyproject.toml` with proper `install_requires` and
  `python_requires = ">=3.8"`
- Selenium dependencies moved to optional `[google]` extra
- `bbid --version` flag
- Complete test suite (41 tests)

### Fixed

- `input()` and `sys.exit()` removed from library API
- Broken relative imports in `multidownloader.py`
- `urllib.request.urlopen` now passes `timeout` parameter
- Thread-safe `download_count` increment
- Mutable default argument `badsites=[]` replaced with `badsites=None`
- Global `socket.setdefaulttimeout()` side-effect removed
- Atomic file writes in `helperdownload`
- Exponential backoff on download retries
- Stale Google Images Selenium selectors
- `chromedriver_autoinstaller` now lazy-loaded

## [2.0.0] - 2024-06-10

### Added

- Parallel downloading for significantly faster image retrieval
- Improved error handling and recovery
- `max_workers` parameter to control parallel downloads

## [1.1.3] - 2023-08-22

### Fixed

- Issue with invalid image types
- Replaced `imghdr` with `filetype` for more reliable detection

[3.1.0]: https://github.com/KTS-o7/better_bing_image_downloader/compare/v3.0.1...v3.1.0
[3.0.1]: https://github.com/KTS-o7/better_bing_image_downloader/compare/v3.0.0...v3.0.1
[3.0.0]: https://github.com/KTS-o7/better_bing_image_downloader/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/KTS-o7/better_bing_image_downloader/compare/v1.1.3...v2.0.0
[1.1.3]: https://github.com/KTS-o7/better_bing_image_downloader/releases/tag/v1.1.3
