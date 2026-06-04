# Better Bing Image Downloader

A fast, reliable Python library and CLI tool for bulk downloading images from Bing or DuckDuckGo.

[![GitHub top language](https://img.shields.io/github/languages/top/KTS-o7/better_bing_image_downloader)](https://github.com/KTS-o7/better_bing_image_downloader)
[![GitHub](https://img.shields.io/github/license/KTS-o7/better_bing_image_downloader)](https://github.com/KTS-o7/better_bing_image_downloader/blob/main/LICENSE)
[![PyPI version](https://badge.fury.io/py/better-bing-image-downloader.svg)](https://pypi.org/project/better-bing-image-downloader/)
[![Hits](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2FKTS-o7%2Fbetter_bing_image_downloader&count_bg=%2379C83D&title_bg=%23555555&icon=&icon_color=%23E7E7E7&title=hits&edge_flat=false)](https://hits.seeyoufarm.com)

## Features

- **Two search engines, one API** — Bing (default) or DuckDuckGo, switched via a single `engine=` parameter
- **No browser required** — both engines use plain HTTP/JSON (no Selenium, no headless Chrome)
- **Parallel downloading** with configurable worker threads (atomic writes, no partial files)
- **Resume support** — re-running skips already-downloaded files and fills the gap
- **Download manifest** — `_manifest.json` written per run mapping filenames to source URLs
- **Image deduplication** — MD5 hash check prevents saving the same image twice from different URLs
- **Image type validation** — `filetype` library rejects non-image responses
- **Filtering** by image type (photo, clipart, line drawing, animated gif, transparent) on Bing
- **Adult content filter** control
- **Bad sites exclusion** list
- **`bbid` CLI command** installed automatically with the package
- **Exponential backoff** on network errors with per-page retry
- Requires Python 3.8+

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Search Engines](#search-engines)
- [Python API](#python-api)
- [CLI — bbid](#cli--bbid)
- [Parameters](#parameters)
- [Examples](#examples)
- [Multidownloader (Deprecated)](#multidownloader-deprecated)
- [Changelog](#changelog)
- [Disclaimer](#disclaimer)
- [License](#license)

## Installation

```bash
pip install better-bing-image-downloader
```

For **DuckDuckGo** engine support (installs the `brotli` package for response decoding):

```bash
pip install "better-bing-image-downloader[duckduckgo]"
```

If you want both engines in one install:

```bash
pip install "better-bing-image-downloader[duckduckgo,google]"
```

The Bing engine works out of the box with no extra dependencies. The DuckDuckGo engine requires `brotli` (used to decode DuckDuckGo's Brotli-compressed responses).

### From source

```bash
git clone https://github.com/KTS-o7/better_bing_image_downloader
cd better_bing_image_downloader
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[duckduckgo,dev]"
```

## Quick Start

```python
from better_bing_image_downloader import downloader

# Bing (default)
downloader("golden retriever", limit=50)
# → downloads to ./dataset/golden retriever/
# → writes ./dataset/golden retriever/_manifest.json

# DuckDuckGo
downloader("golden retriever", limit=50, engine="duckduckgo")
```

```bash
# Bing (default)
bbid "golden retriever" --limit 50

# DuckDuckGo
bbid "golden retriever" --limit 50 --engine duckduckgo
```

## Search Engines

### Bing (default)

- Direct API access via `https://www.bing.com/images/async`
- Supports image-type filtering: `photo`, `clipart`, `line`/`linedrawing`, `gif`/`animatedgif`, `transparent`
- Supports market codes (`mkt`) for region-specific results
- No additional dependencies

### DuckDuckGo (new in 3.1.0)

- Direct API access via `https://duckduckgo.com/i.js` (Brotli-compressed JSON)
- No API key, no rate-limit token beyond a short-lived `vqd` cookie
- Supports safe-search modes: `strict`, `moderate` (default), `off`
- Supports region codes (e.g. `us-en`, `uk-en`)
- Requires the `brotli` Python package: `pip install "better-bing-image-downloader[duckduckgo]"`

DuckDuckGo is a great fallback when Bing is rate-limiting or blocking your IP, and vice versa.

## Python API

```python
from better_bing_image_downloader import downloader

count = downloader(
    query="cute puppies",
    limit=100,
    output_dir="my_images",
    engine="bing",                # "bing" (default) or "duckduckgo"
    adult_filter_off=True,        # Bing only
    force_replace=False,          # False = resume (skip existing files)
    timeout=60,
    image_filter="photo",         # Bing only: "line", "photo", "clipart", "gif", "transparent"
    verbose=True,
    badsites=["stock.adobe.com", "shutterstock.com"],
    name="Puppy",
    max_workers=8,
    mkt="en-US",                  # Bing only: market code
    ddg_safe_search="moderate",   # DuckDuckGo only: "strict", "moderate", "off"
    ddg_region="us-en",           # DuckDuckGo only: region code
)
print(f"Downloaded {count} images")
```

The return value is the number of **newly downloaded** images (not counting files that were already on disk from a previous run).

### Resume behaviour

By default (`force_replace=False`), re-running the same query skips already-downloaded files and downloads only what's missing:

```python
# First run: downloads 100 images
downloader("cats", limit=100, output_dir="dataset")

# Second run: all 100 exist — downloads nothing, returns 0
downloader("cats", limit=100, output_dir="dataset")

# Third run with higher limit: skips 100 existing, downloads 50 new ones
downloader("cats", limit=150, output_dir="dataset")

# DuckDuckGo works the same way
downloader("cats", limit=150, output_dir="dataset", engine="duckduckgo")
```

### Download manifest

After every run, `_manifest.json` is written to the output directory:

```json
{
  "Image_1.jpg": "https://example.com/photo1.jpg",
  "Image_2.png": "https://example.com/photo2.png"
}
```

Successive runs merge into the existing manifest.

### Backward compatibility

The old `filter=` keyword argument still works but emits a `DeprecationWarning`. Use `image_filter=` going forward:

```python
# Deprecated (still works):
downloader("cats", filter="photo")

# Correct:
downloader("cats", image_filter="photo")
```

## CLI — bbid

The `bbid` command is installed automatically with the package:

```bash
bbid --help
bbid --version

# Basic Bing download
bbid "mountain landscape" --limit 100

# DuckDuckGo
bbid "mountain landscape" --limit 100 --engine duckduckgo

# DuckDuckGo with safe search off and UK region
bbid "mountain landscape" --limit 100 --engine duckduckgo \
    --ddg-safe-search off --ddg-region uk-en

# With options
bbid "logo design" \
  --engine bing \
  --limit 50 \
  --filter transparent \
  --workers 8 \
  --output_dir logos \
  --verbose

# Exclude sites
bbid "puppies" --limit 200 --bad-sites stock.adobe.com shutterstock.com
```

### CLI options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `query` | | (required) | Search term |
| `--engine` | `-e` | `bing` | Search engine: `bing` or `duckduckgo` |
| `--limit` | `-l` | 100 | Maximum images to download |
| `--output_dir` | `-d` | `dataset` | Output directory |
| `--adult_filter_off` | `-a` | False | Disable adult content filter (Bing only) |
| `--force_replace` | `-F` | False | Delete and recreate output dir |
| `--timeout` | `-t` | 60 | Connection timeout (seconds) |
| `--filter` | `-f` | `""` | Image type filter (Bing only) |
| `--verbose` | `-v` | False | Detailed output |
| `--bad-sites` | `-b` | `[]` | Sites to exclude |
| `--name` | `-n` | `Image` | Base filename prefix |
| `--workers` | `-w` | 4 | Parallel download threads |
| `--mkt` | `-m` | `en-US` | Bing market code (Bing only) |
| `--ddg-safe-search` | | `moderate` | DuckDuckGo safe-search: `strict`, `moderate`, `off` |
| `--ddg-region` | | `us-en` | DuckDuckGo region code |
| `--version` | | | Show version and exit |

## Parameters

### `downloader()` API parameters

| Parameter | Type | Default | Applies to | Description |
|-----------|------|---------|------------|-------------|
| `query` | str | (required) | both | Search term |
| `limit` | int | 100 | both | Maximum images to download |
| `output_dir` | str | `'dataset'` | both | Root output directory |
| `engine` | str | `'bing'` | both | Search engine: `'bing'` or `'duckduckgo'` |
| `adult_filter_off` | bool | False | Bing | Disable adult content filter |
| `force_replace` | bool | False | both | Delete existing dir before download |
| `timeout` | int | 60 | both | Connection timeout in seconds |
| `image_filter` | str | `""` | Bing | Image type: `line`, `photo`, `clipart`, `gif`, `transparent` |
| `verbose` | bool | True | both | Print download progress |
| `badsites` | list | `[]` | both | Domains to exclude |
| `name` | str | `'Image'` | both | Base filename prefix |
| `max_workers` | int | 4 | both | Parallel download threads (1–16) |
| `mkt` | str | `'en-US'` | Bing | Market code for language/region |
| `ddg_safe_search` | str | `'moderate'` | DuckDuckGo | `strict`, `moderate`, or `off` |
| `ddg_region` | str | `'us-en'` | DuckDuckGo | Region code (e.g. `us-en`, `uk-en`) |

## Examples

### Download with type filter (Bing)

```python
from better_bing_image_downloader import downloader

# Download transparent PNGs (useful for logos/icons)
downloader(
    query="logo design",
    limit=50,
    image_filter="transparent",
    max_workers=8,
    output_dir="logos",
)
```

### Use DuckDuckGo for the same query

```python
from better_bing_image_downloader import downloader

downloader(
    query="logo design",
    limit=50,
    engine="duckduckgo",
    ddg_safe_search="off",  # don't filter logos as adult content
    max_workers=8,
    output_dir="logos",
)
```

### Exclude stock photo sites

```python
downloader(
    query="nature photography",
    limit=200,
    badsites=["stock.adobe.com", "shutterstock.com", "gettyimages.com"],
    max_workers=8,
)
```

### Resume a long-running download

```python
# Run 1: start a 500-image download
downloader("mountain landscape", limit=500, output_dir="dataset")

# ... process is killed or the network drops ...

# Run 2: pick up where we left off — only the missing images are fetched
downloader("mountain landscape", limit=500, output_dir="dataset")
```

## Multidownloader (Deprecated)

The Selenium-based `multidownloader` CLI is **deprecated** and will be removed in v4.0.0. The Google path no longer works: Google serves a JavaScript-only shell page to all non-browser HTTP requests, so image URLs cannot be extracted without a real browser.

For the Bing path, prefer the new `bbid` CLI or `downloader()` function with `engine="bing"`. As a DuckDuckGo alternative, install the `[duckduckgo]` extra and use `bbid --engine duckduckgo`.

If you have a hard requirement on the Selenium path, you can still import it directly, but expect a `DeprecationWarning`:

```python
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from better_bing_image_downloader.multidownloader import main
main(["query", "--engine", "Bing", "--driver", "firefox_headless"])
```

## Changelog

### 3.1.0

- **New:** DuckDuckGo image search engine — works without Selenium, no API key, Brotli-compressed JSON API
- **New:** `engine="bing" | "duckduckgo"` parameter on `downloader()` and `--engine` flag on `bbid`
- **New:** DuckDuckGo-specific options: `ddg_safe_search` (`strict` / `moderate` / `off`) and `ddg_region`
- **New:** Optional `[duckduckgo]` extra installs the required `brotli` package
- **New:** `ImageEngine` base class — both engines now share download, dedup, resume, and manifest logic (less duplication, fewer bugs)
- **Fix:** Atomic file writes in `bing.save_image` (temp file → rename on success, no partial files on failure)
- **Fix:** Per-future timeout on parallel downloads (was blocking indefinitely on stalled connections)
- **Fix:** Exponential backoff on Bing network errors (was a fixed 2-second sleep, no retry cap)
- **Fix:** Bing now stops cleanly when a page yields no new images (was risking infinite loops)
- **Fix:** `helperdownload` uses `logging` instead of `print()` (no more stdout pollution when used as a library)
- **Deprecation:** Selenium-based `multidownloader` CLI is deprecated; will be removed in v4.0.0
- **Tests:** 41 → 72 tests (added atomic-write, parallel-future, DuckDuckGo, engine-dispatch tests)

### 3.0.1

- Updated Bing headers to advertise gzip/deflate; decompresses compressed responses
- Default adult filter changed to `moderate` (Bing's recommended safe search)
- New `mkt` parameter (default `en-US`) for region-specific Bing results

### 3.0.0

- **Breaking:** `filter` parameter renamed to `image_filter` in `downloader()` (old `filter=` still works with a `DeprecationWarning`)
- **New:** `bbid` CLI command installed automatically via entry point
- **New:** Resume support — skips existing files, downloads only what's missing
- **New:** `_manifest.json` written per run with filename → source URL mapping
- **New:** MD5-based image deduplication — same image from different URLs saved only once
- **New:** `pyproject.toml` with proper `install_requires` and `python_requires = ">=3.8"`
- **New:** Selenium dependencies moved to optional `[google]` extra — core install is lightweight
- **New:** `bbid --version` flag
- **Fix:** `input()` and `sys.exit()` removed from library API (were blocking programmatic use)
- **Fix:** Broken relative imports in `multidownloader.py` (was crashing on installed package)
- **Fix:** `urllib.request.urlopen` now passes `timeout` parameter (was hanging indefinitely)
- **Fix:** Thread-safe `download_count` increment with `threading.Lock`
- **Fix:** Mutable default argument `badsites=[]` replaced with `badsites=None`
- **Fix:** Global `socket.setdefaulttimeout()` side-effect removed from `helperdownload`
- **Fix:** Atomic file writes in `helperdownload` (temp file → move on success)
- **Fix:** Exponential backoff on download retries
- **Fix:** Stale Google Images Selenium selectors updated
- **Fix:** `resolve_dependencies(driver=str)` broken default fixed
- **Fix:** `chromedriver_autoinstaller` now lazy-loaded (only when Chrome driver requested)
- **Fix:** Complete test suite (was 0 working tests; now 41)

### 2.0.0

- Added parallel downloading for significantly faster image retrieval
- Improved error handling and recovery
- Added `max_workers` parameter to control parallel downloads

### 1.1.3

- Fixed issue with invalid image types
- Replaced `imghdr` with `filetype` for more reliable image type detection

## Disclaimer

This program lets you download images from search engines. Please do not download or use any image that violates its copyright terms. The developers of this tool are not responsible for any misuse.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Contact

Questions or feedback: [shentharkrishnatejaswi@gmail.com](mailto:shentharkrishnatejaswi@gmail.com)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=KTS-o7/better-bing-image-downloader&type=Date)](https://www.star-history.com/#KTS-o7/better-bing-image-downloader&Date)
