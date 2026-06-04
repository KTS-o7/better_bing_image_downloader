"""Shared base class for image search engines.

Bing and DuckDuckGo differ only in how they fetch the list of image URLs;
the download, validation, deduplication, resume, and progress logic is
identical. That logic lives here.
"""
from __future__ import annotations

import hashlib
import logging
import posixpath
import shutil
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import filetype

__all__ = ["ImageEngine", "MAX_FUTURE_TIMEOUT", "VALID_IMAGE_EXTENSIONS"]

# How long a single parallel download future may block before we give up.
MAX_FUTURE_TIMEOUT = 180.0  # seconds

# Extensions we accept when renaming downloaded images. Bing sometimes
# returns URLs without an extension, so we use this set for the fallback.
VALID_IMAGE_EXTENSIONS = {
    "jpe", "jpeg", "jfif", "exif", "tiff",
    "gif", "bmp", "png", "webp", "jpg",
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


class ImageEngine:
    """Base class for image search engine scrapers.

    Subclasses implement :meth:`run` to fetch URLs from their backend and
    then call :meth:`download_image` (or :meth:`_download_batch`) to save
    them. All common concerns — atomic writes, MD5 deduplication, resume
    support, manifest tracking, parallel execution — are handled here.
    """

    def __init__(
        self,
        query: str,
        limit: int,
        output_dir,
        timeout: int,
        verbose: bool = True,
        badsites=None,
        name: str = "Image",
        max_workers: int = 4,
        force_replace: bool = False,
    ):
        assert isinstance(limit, int), "limit must be integer"
        assert isinstance(timeout, int), "timeout must be integer"
        assert isinstance(max_workers, int), "max_workers must be integer"

        self.query = query
        self.limit = limit
        self.output_dir = Path(output_dir)
        self.timeout = timeout
        self.verbose = verbose
        self.badsites = set(badsites) if badsites is not None else set()
        self.image_name = name
        self.max_workers = max(1, min(max_workers, 16))
        self.force_replace = force_replace

        self.seen: set[str] = set()
        self.download_count = 0  # newly downloaded this run
        self._slots_used = 0     # slots consumed (downloaded + skipped existing)
        self.download_callback = None
        self._count_lock = threading.Lock()
        self.manifest: dict = {}  # filename -> source URL
        self._file_hashes: set = set()
        self._hash_lock = threading.Lock()

        self.output_dir.mkdir(parents=True, exist_ok=True)

    # --- HTTP helpers ---

    def _http_get(self, url: str, headers: dict | None = None) -> bytes:
        """GET ``url`` with the engine's default headers merged with overrides."""
        merged = dict(DEFAULT_HEADERS)
        if headers:
            merged.update(headers)
        request = urllib.request.Request(url, None, headers=merged)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    # --- Download pipeline ---

    def save_image(self, link: str, file_path) -> bool:
        """Download an image to ``file_path`` atomically.

        Returns ``True`` on success, ``False`` on any failure (network,
        invalid image, or duplicate). On success, ``file_path`` exists
        with the validated image bytes; on failure, no partial file is
        left behind.
        """
        try:
            image = self._http_get(link)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            logging.error("Network error while saving image %s: %s", link, e)
            return False
        except Exception as e:
            logging.error("Unexpected error while saving image %s: %s", link, e)
            return False

        kind = filetype.guess(image)
        if not kind or not kind.mime.startswith("image/"):
            logging.error("Invalid image, not saving %s", link)
            return False

        file_hash = hashlib.md5(image).hexdigest()
        with self._hash_lock:
            if file_hash in self._file_hashes:
                logging.info("Duplicate image detected (hash match), skipping: %s", link)
                return False
            self._file_hashes.add(file_hash)

        # Atomic write: write to a temp file in the same directory, then
        # rename. This prevents partially-written files from being picked
        # up by a subsequent resume run.
        file_path = Path(file_path)
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix=f".{file_path.name}.",
                dir=str(file_path.parent),
            )
        except OSError as e:
            logging.error("Failed to create temp file for %s: %s", file_path, e)
            return False
        try:
            with open(fd, "wb") as f:
                f.write(image)
            shutil.move(tmp_path, file_path)
        except Exception as e:
            logging.error("Failed to write image %s: %s", file_path, e)
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
            return False
        return True

    def download_image(self, link: str, index: int):
        """Download and save a single image.

        Returns
        -------
        int or None
            ``index`` on success, ``0`` if the file already existed (resume
            skip), or ``None`` on any error.
        """
        try:
            path = urllib.parse.urlsplit(link).path
            filename = posixpath.basename(path).split("?")[0]
            file_type = filename.split(".")[-1].lower()

            if file_type not in VALID_IMAGE_EXTENSIONS:
                file_type = "jpg"

            file_path = self.output_dir / f"{self.image_name}_{index}.{file_type}"

            # Resume support: skip if a file with this base name already exists.
            if not self.force_replace:
                existing = list(self.output_dir.glob(f"{self.image_name}_{index}.*"))
                if existing:
                    if self.verbose:
                        logging.info(
                            "Skipping already-downloaded image #%d (file exists)",
                            index,
                        )
                    return 0

            if self.verbose:
                logging.info("Downloading Image #%d from %s", index, link)

            if self.save_image(link, file_path):
                with self._count_lock:
                    self.manifest[file_path.name] = link
                if self.verbose:
                    logging.info("Downloaded File #%d", index)
                with self._count_lock:
                    self.download_count += 1
                    self._slots_used += 1
                if self.download_callback:
                    self.download_callback(self.download_count)
                return index
            return None
        except Exception as e:
            logging.error("Issue getting image %s: %s", link, e)
            return None
