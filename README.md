# Better Bing Image Downloader

A powerful Python tool for downloading images from Bing and Google image search engines.

[![GitHub top language](https://img.shields.io/github/languages/top/KTS-o7/better_bing_image_downloader)](https://github.com/KTS-o7/better_bing_image_downloader)
[![GitHub](https://img.shields.io/github/license/KTS-o7/better-bing-image-downloader)](https://github.com/KTS-o7/better-bing-image-downloader/blob/main/LICENSE)
[![PyPI version](https://badge.fury.io/py/better-bing-image-downloader.svg)](https://pypi.org/project/better-bing-image-downloader/)
[![Hits](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2FKTS-o7%2Fbetter_bing_image_downloader&count_bg=%2379C83D&title_bg=%23555555&icon=&icon_color=%23E7E7E7&title=hits&edge_flat=false)](https://hits.seeyoufarm.com)

## Features

- Download images from Bing and Google search engines
- Parallel downloading for significantly faster performance
- Multiple filtering options (image type, color, adult content, etc.)
- Support for both API and browser-based image retrieval
- Command-line interface and Python API
- Multiple browser support (Firefox, Chrome, headless options)
- Proxy support

## Table of Contents

- [Installation](#installation)
- [Usage](#usage)
  - [Python API](#python-api)
  - [Command Line Interface](#command-line-interface)
- [Parameters](#parameters)
- [Examples](#examples)
- [License](#license)
- [Disclaimer](#disclaimer)
- [Changelog](#changelog)
- [Contact](#contact)

## Installation

### Using pip

```bash
pip install better-bing-image-downloader
```

### From source

```bash
git clone https://github.com/KTS-o7/better_bing_image_downloader
cd better_bing_image_downloader
python -m venv ./env
source env/bin/activate  # On Windows: env\Scripts\activate
pip install -r requirements.txt
pip install .
```

## Usage

### Python API

```python
from better_bing_image_downloader import downloader

# Basic usage
downloader("cute puppies", limit=50)

# Advanced usage
downloader(
    query="cute puppies",
    limit=100,
    output_dir="my_images",
    adult_filter_off=True,
    force_replace=False,
    timeout=60,
    filter="photo",  # Options: "line", "photo", "clipart", "gif", "transparent"
    verbose=True,
    badsites=["stock.adobe.com", "shutterstock.com"],
    name="Puppy",
    max_workers=8  # Parallel downloads
)
```

### Command Line Interface

The package provides two command-line interfaces:

#### 1. Simple CLI (Bing-only)

```bash
python -m better_bing_image_downloader.download "query" [options]
```

#### 2. Advanced CLI (Bing and Google)

```bash
python -m better_bing_image_downloader.multidownloader "query" [options]
```

## Parameters

### Python API Parameters

| Parameter        | Type | Default    | Description                                                |
| ---------------- | ---- | ---------- | ---------------------------------------------------------- |
| query            | str  | (required) | Search term                                                |
| limit            | int  | 100        | Maximum number of images to download                       |
| output_dir       | str  | 'dataset'  | Directory to save images                                   |
| adult_filter_off | bool | True       | Disable adult content filter                               |
| force_replace    | bool | False      | Replace existing files and directories                     |
| timeout          | int  | 60         | Connection timeout in seconds                              |
| filter           | str  | ""         | Image type filter (line, photo, clipart, gif, transparent) |
| verbose          | bool | True       | Display detailed output                                    |
| badsites         | list | []         | List of sites to exclude from results                      |
| name             | str  | 'Image'    | Base name for downloaded images                            |
| max_workers      | int  | 4          | Number of parallel download threads                        |

### Command Line Arguments (multidownloader.py)

| Argument       | Short | Default             | Description                                          |
| -------------- | ----- | ------------------- | ---------------------------------------------------- |
| --engine       | -e    | "Bing"              | Search engine ("Google" or "Bing")                   |
| --driver       | -d    | "firefox_headless"  | Browser driver to use                                |
| --max-number   | -n    | 100                 | Maximum number of images to download                 |
| --num-threads  | -j    | 50                  | Number of concurrent download threads                |
| --timeout      | -t    | 10                  | Download timeout in seconds                          |
| --output       | -o    | "./download_images" | Output directory                                     |
| --safe-mode    | -S    | False               | Enable safe search mode                              |
| --face-only    | -F    | False               | Only search for faces                                |
| --proxy_http   | -ph   | None                | HTTP proxy address (e.g., 192.168.0.2:8080)          |
| --proxy_socks5 | -ps   | None                | SOCKS5 proxy address (e.g., 192.168.0.2:1080)        |
| --type         | -ty   | None                | Image type filter (clipart, linedrawing, photograph) |
| --color        | -cl   | None                | Color filter for images                              |

## Examples

### Basic Search

```python
from better_bing_image_downloader import downloader

# Download 100 cat images to ./dataset/cats
downloader("cats", limit=100)
```

### Advanced Search with Filters

```python
# Download 50 transparent clipart images with parallel processing
downloader(
    query="logo design",
    limit=50,
    filter="transparent",
    max_workers=8,
    output_dir="logos"
)
```

### Command Line Usage

```bash
# Download 50 landscape photographs using Google
python -m better_bing_image_downloader.multidownloader "mountain landscape" --engine "Google" --max-number 50 --type "photograph"

# Download 100 cat images using Bing with Firefox headless
python -m better_bing_image_downloader.multidownloader "cats" --engine "Bing" --driver "firefox_headless" --max-number 100
```

## Disclaimer

This program lets you download images from search engines. Please do not download or use any image that violates its copyright terms. The developers of this tool are not responsible for any misuse.

## Changelog

### 2.0.0

- Added parallel downloading for significantly faster image retrieval
- Improved error handling and recovery
- Better memory management and code organization
- Fixed progress bar display issues
- Added max_workers parameter to control parallel downloads
- Added new requirements

### 1.1.3

- Fixed issue with invalid image types
- Replaced imghdr with filetype for more reliable image type detection

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contact

If you have any questions or feedback, please contact the developer at [shentharkrishnatejaswi@gmail.com](mailto:shentharkrishnatejaswi@gmail.com).

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=KTS-o7/better-bing-image-downloader&type=Date)](https://www.star-history.com/#KTS-o7/better-bing-image-downloader&Date)
