"""Download images by URL list with automatic renaming.

Used by the optional Selenium-based ``multidownloader`` path.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import shutil
import tempfile
import time

import filetype
import requests

from .base import MAX_FUTURE_TIMEOUT, VALID_IMAGE_EXTENSIONS

__all__ = ["VALID_IMAGE_EXTENSIONS", "download_image", "download_images"]


# DuckDuckGo's CDN sometimes returns AVIF/WebP; ``filetype`` supports them
# natively, so we just need to make sure the extension set we use for
# renaming covers what the validator can detect.
_DOWNLOAD_EXTENSIONS = VALID_IMAGE_EXTENSIONS | {"avif", "ico"}


# Backward-compatible export for downstream tests/users.
VALID_IMAGE_EXTENSIONS = _DOWNLOAD_EXTENSIONS  # noqa: F811

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


def download_image(
    image_url: str,
    dst_dir: str,
    file_name: str,
    timeout: int = 20,
    proxy_type: str | None = None,
    proxy: str | None = None,
) -> bool:
    """Download a single image to ``dst_dir`` atomically.

    Returns ``True`` on success, ``False`` on failure. On failure, no
    partial file is left behind.
    """
    proxies = None
    if proxy_type is not None and proxy is not None:
        proxies = {
            "http": f"{proxy_type}://{proxy}",
            "https": f"{proxy_type}://{proxy}",
        }

    for attempt in range(1, 4):  # 3 total attempts
        try:
            response = requests.get(image_url, headers=_HEADERS, timeout=timeout, proxies=proxies)
            response.raise_for_status()
            break
        except Exception as e:
            if attempt < 3:
                wait = 2**attempt  # 2s, 4s
                logging.warning(
                    "download_image: %s failed (attempt %d/3): %s. Retrying in %ds.",
                    image_url,
                    attempt,
                    e,
                    wait,
                )
                time.sleep(wait)
                continue
            logging.error("download_image: %s failed after 3 attempts: %s", image_url, e)
            return False

    fd, tmp_path = tempfile.mkstemp(dir=dst_dir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(response.content)
        kind = filetype.guess(tmp_path)
        if kind and kind.extension in _DOWNLOAD_EXTENSIONS:
            final_path = os.path.join(dst_dir, f"{file_name}.{kind.extension}")
            shutil.move(tmp_path, final_path)
            logging.info("OK: %s <- %s", os.path.basename(final_path), image_url)
            return True
        logging.warning("Invalid image type: %s", image_url)
        return False
    except Exception as e:
        logging.error("Failed to save %s: %s", image_url, e)
        return False
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def download_images(
    image_urls: list[str],
    dst_dir: str,
    file_prefix: str = "img",
    concurrency: int = 10,
    timeout: int = 20,
    proxy_type: str | None = None,
    proxy: str | None = None,
) -> None:
    """Download a list of images into ``dst_dir`` concurrently.

    Files are named ``{file_prefix}_NNNN.{ext}``.
    """
    os.makedirs(dst_dir, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                download_image,
                url,
                dst_dir,
                f"{file_prefix}_{i:04d}",
                timeout,
                proxy_type,
                proxy,
            )
            for i, url in enumerate(image_urls)
        ]
        concurrent.futures.wait(futures, timeout=MAX_FUTURE_TIMEOUT)
