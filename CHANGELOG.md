# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
