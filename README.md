# Better Bing Image Downloader

A fast, reliable Python library and CLI tool for bulk downloading images from Bing (and Google via Selenium).

[![GitHub top language](https://img.shields.io/github/languages/top/KTS-o7/better_bing_image_downloader)](https://github.com/KTS-o7/better_bing_image_downloader)
[![GitHub](https://img.shields.io/github/license/KTS-o7/better_bing_image_downloader)](https://github.com/KTS-o7/better_bing_image_downloader/blob/main/LICENSE)
[![PyPI version](https://badge.fury.io/py/better-bing-image-downloader.svg)](https://pypi.org/project/better-bing-image-downloader/)
[![Hits](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2FKTS-o7%2Fbetter_bing_image_downloader&count_bg=%2379C83D&title_bg=%23555555&icon=&icon_color=%23E7E7E7&title=hits&edge_flat=false)](https://hits.seeyoufarm.com)

## Features

- **Bing image search** via direct API — no browser required
- **Parallel downloading** with configurable worker threads
- **Resume support** — re-running skips already-downloaded files and fills the gap
- **Download manifest** — `_manifest.json` written per run mapping filenames to source URLs
- **Image deduplication** — MD5 hash check prevents saving the same image twice from different URLs
- **Image type validation** — `filetype` library rejects non-image responses
- **Filtering** by image type (photo, clipart, line drawing, animated gif, transparent)
- **Adult content filter** control
- **Bad sites exclusion** list
- **Google image search** (optional, requires Selenium — see [Google support](#google-support))
- **`bbid` CLI command** installed automatically with the package
- **Proxy support** (HTTP and SOCKS5)
- Requires Python 3.8+

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Python API](#python-api)
- [CLI — bbid](#cli--bbid)
- [Parameters](#parameters)
- [Examples](#examples)
- [Google Support](#google-support)
- [Changelog](#changelog)
- [Disclaimer](#disclaimer)
- [License](#license)

## Installation

```bash
pip install better-bing-image-downloader
```

For **Google image search** support (installs Selenium + chromedriver):

```bash
pip install "better-bing-image-downloader[google]"
```

### From source

```bash
git clone https://github.com/KTS-o7/better_bing_image_downloader
cd better_bing_image_downloader
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
```

## Quick Start

```python
from better_bing_image_downloader import downloader

downloader("golden retriever", limit=50)
# → downloads to ./dataset/golden retriever/
# → writes ./dataset/golden retriever/_manifest.json
```

```bash
bbid "golden retriever" --limit 50
```

## Python API

```python
from better_bing_image_downloader import downloader

count = downloader(
    query="cute puppies",
    limit=100,
    output_dir="my_images",
    adult_filter_off=True,
    force_replace=False,       # False = resume (skip existing files)
    timeout=60,
    image_filter="photo",      # "line", "photo", "clipart", "gif", "transparent"
    verbose=True,
    badsites=["stock.adobe.com", "shutterstock.com"],
    name="Puppy",
    max_workers=8
)
print(f"Downloaded {count} images")
```

### Resume behaviour

By default (`force_replace=False`), re-running the same query skips already-downloaded files and downloads only what's missing:

```python
# First run: downloads 100 images
downloader("cats", limit=100, output_dir="dataset")

# Second run: all 100 exist — downloads nothing, returns 0
downloader("cats", limit=100, output_dir="dataset")

# Third run with higher limit: skips 100 existing, downloads 50 new ones
downloader("cats", limit=150, output_dir="dataset")
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

# Basic
bbid "mountain landscape" --limit 100

# With options
bbid "logo design" \
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
| `--limit` | `-l` | 100 | Maximum images to download |
| `--output_dir` | `-d` | `dataset` | Output directory |
| `--adult_filter_off` | `-a` | False | Disable adult content filter |
| `--force_replace` | `-F` | False | Delete and recreate output dir |
| `--timeout` | `-t` | 60 | Connection timeout (seconds) |
| `--filter` | `-f` | `""` | Image type filter |
| `--verbose` | `-v` | False | Detailed output |
| `--bad-sites` | `-b` | `[]` | Sites to exclude |
| `--name` | `-n` | `Image` | Base filename prefix |
| `--workers` | `-w` | 4 | Parallel download threads |
| `--version` | | | Show version and exit |

## Parameters

### `downloader()` API parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | (required) | Search term |
| `limit` | int | 100 | Maximum images to download |
| `output_dir` | str | `'dataset'` | Root output directory |
| `adult_filter_off` | bool | True | Disable adult content filter |
| `force_replace` | bool | False | Delete existing dir before download |
| `timeout` | int | 60 | Connection timeout in seconds |
| `image_filter` | str | `""` | Image type: `line`, `photo`, `clipart`, `gif`, `transparent` |
| `verbose` | bool | True | Print download progress |
| `badsites` | list | `[]` | Domains to exclude |
| `name` | str | `'Image'` | Base filename prefix |
| `max_workers` | int | 4 | Parallel download threads (1–16) |

## Examples

### Download with type filter

```python
from better_bing_image_downloader import downloader

# Download transparent PNGs (useful for logos/icons)
downloader(
    query="logo design",
    limit=50,
    image_filter="transparent",
    max_workers=8,
    output_dir="logos"
)
```

### Exclude stock photo sites

```python
downloader(
    query="nature photography",
    limit=200,
    badsites=["stock.adobe.com", "shutterstock.com", "gettyimages.com"],
    max_workers=8
)
```

### Use from CLI with Google (requires `[google]` extra)

```bash
# Download using Google image search via Firefox headless
python -m better_bing_image_downloader.multidownloader "mountain landscape" \
  --engine Google \
  --driver firefox_headless \
  --max-number 50 \
  --type photograph
```

## Google Support

Google image search requires the optional Selenium dependencies:

```bash
pip install "better-bing-image-downloader[google]"
```

Then use the `multidownloader` CLI:

```bash
python -m better_bing_image_downloader.multidownloader "query" \
  --engine Google \
  --driver chrome_headless \
  --max-number 100
```

### Multidownloader CLI options

| Argument | Short | Default | Description |
|----------|-------|---------|-------------|
| `--engine` | `-e` | `Bing` | Search engine: `Google` or `Bing` |
| `--driver` | `-d` | `firefox_headless` | Browser: `chrome_headless`, `chrome`, `firefox`, `firefox_headless`, `api` |
| `--max-number` | `-n` | 100 | Maximum images to download |
| `--num-threads` | `-j` | 10 | Concurrent download threads |
| `--timeout` | `-t` | 10 | Download timeout (seconds) |
| `--output` | `-o` | `./download_images` | Output directory |
| `--safe-mode` | `-S` | False | Enable safe search |
| `--face-only` | `-F` | False | Face images only |
| `--proxy_http` | `-ph` | None | HTTP proxy (e.g. `192.168.0.2:8080`) |
| `--proxy_socks5` | `-ps` | None | SOCKS5 proxy (e.g. `192.168.0.2:1080`) |
| `--type` | `-ty` | None | Image type: `clipart`, `linedrawing`, `photograph` |
| `--color` | `-cl` | None | Color filter |

## Changelog

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
