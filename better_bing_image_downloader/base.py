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
from abc import ABC, abstractmethod
from pathlib import Path

import filetype

__all__ = [
    "DEFAULT_VERBOSE",
    "ImageEngine",
    "ImageSaveError",
    "NetworkError",
    "InvalidImageError",
    "DuplicateImageError",
    "WriteError",
    "BelowMinDimension",
    "MAX_FUTURE_TIMEOUT",
    "VALID_IMAGE_EXTENSIONS",
]

# How long a single parallel download future may block before we give up.
MAX_FUTURE_TIMEOUT = 180.0  # seconds


class ImageSaveError(Exception):
    """Base class for save_image failures surfaced by ``Downloader.search``.

    This is a control-flow exception: it is not a programming error.
    It exists so that the user's ``on_error`` hook and the
    ``Result.errors`` list receive a uniform signal whether the
    failure was a network error, an invalid image body, or a
    duplicate (same MD5) image.

    As of v3.4.0, the four typed subclasses below give callers a
    way to distinguish failure reasons without parsing the
    ``reason`` string. Catching ``ImageSaveError`` continues to
    catch all of them (Liskov substitution).

    Attributes
    ----------
    reason : str
        Human-readable reason. One of:
        ``"network"``, ``"invalid_image"``, ``"duplicate"``,
        ``"write_failed"``.
    url : str
        The image URL that failed to save.
    """

    def __init__(self, reason: str, url: str, message: str = "") -> None:
        self.reason = reason
        self.url = url
        if not message:
            message = f"image save failed: reason={reason!r} url={url!r}"
        super().__init__(message)


class NetworkError(ImageSaveError):
    """The HTTP fetch in ``_http_get`` failed (timeout, 5xx, DNS, etc.)."""

    def __init__(self, url: str, message: str = "") -> None:
        if not message:
            message = f"network error fetching {url!r}"
        super().__init__(reason="network", url=url, message=message)


class InvalidImageError(ImageSaveError):
    """The fetched bytes don't look like an image (filetype rejected them)."""

    def __init__(self, url: str, message: str = "") -> None:
        if not message:
            message = f"invalid image body at {url!r}"
        super().__init__(reason="invalid_image", url=url, message=message)


class DuplicateImageError(ImageSaveError):
    """An image with the same MD5 hash has already been saved this run."""

    def __init__(self, url: str, message: str = "") -> None:
        if not message:
            message = f"duplicate image (same MD5) at {url!r}"
        super().__init__(reason="duplicate", url=url, message=message)


class WriteError(ImageSaveError):
    """Failed to create the temp file or write the image bytes to disk."""

    def __init__(self, url: str, message: str = "") -> None:
        if not message:
            message = f"failed to write image at {url!r}"
        super().__init__(reason="write_failed", url=url, message=message)


class BelowMinDimension(ImageSaveError):
    """The fetched image's width or height is below ``min_dimension`` (v3.6.0+).

    Raised by ``_save_image_raising`` when ``self.min_dimension`` is set
    and the downloaded image is smaller than that threshold on either
    side. ``Downloader.search`` treats this differently from the other
    ``ImageSaveError`` subclasses: it's recorded in the manifest as a
    ``"skipped"`` record (not an ``"error"``) and counted in
    ``Result.skipped`` rather than ``Result.errors``, since a too-small
    image is an intentional filter outcome, not a failure.
    """

    def __init__(
        self, url: str, width: int, height: int, min_dimension: int, message: str = ""
    ) -> None:
        self.width = width
        self.height = height
        self.min_dimension = min_dimension
        if not message:
            message = (
                f"image below minimum dimension at {url!r}: "
                f"{width}x{height} < {min_dimension}px"
            )
        super().__init__(reason="below_min_dimension", url=url, message=message)


# Extensions we accept when renaming downloaded images. Bing sometimes
# returns URLs without an extension, so we use this set for the fallback.
VALID_IMAGE_EXTENSIONS = {
    "jpe",
    "jpeg",
    "jfif",
    "exif",
    "tiff",
    "gif",
    "bmp",
    "png",
    "webp",
    "jpg",
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9," "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

DEFAULT_VERBOSE = False


def _read_jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Walk JPEG markers looking for a Start-Of-Frame (SOFn) segment."""
    pos = 2  # skip the SOI marker (0xFFD8)
    length = len(data)
    while pos + 4 <= length:
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker == 0xDA:
            # Start of Scan: entropy-coded data follows, with no more
            # markers to find. SOFn always precedes SOS in a
            # well-formed JPEG, so reaching this means dimensions
            # weren't found; stop before scanning byte-stuffed scan
            # data that could false-match a marker.
            return None
        # Standalone markers (no length field, no payload).
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        seg_len = int.from_bytes(data[pos + 2 : pos + 4], "big")
        is_sof = 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC)
        if is_sof:
            if pos + 9 > length:
                return None
            height = int.from_bytes(data[pos + 5 : pos + 7], "big")
            width = int.from_bytes(data[pos + 7 : pos + 9], "big")
            return width, height
        pos += 2 + seg_len
    return None


def _read_webp_dimensions(data: bytes) -> tuple[int, int] | None:
    """Parse a WEBP file's VP8 / VP8L / VP8X chunk header for canvas dimensions."""
    chunk = data[12:16]
    payload = data[20:]
    if chunk == b"VP8X":
        if len(payload) < 10:
            return None
        width = int.from_bytes(payload[4:7], "little") + 1
        height = int.from_bytes(payload[7:10], "little") + 1
        return width, height
    if chunk == b"VP8L":
        if len(payload) < 5 or payload[0] != 0x2F:
            return None
        bits = int.from_bytes(payload[1:5], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    if chunk == b"VP8 ":
        # 3-byte frame tag + 3-byte start code (0x9d 0x01 0x2a), then
        # width/height as 16-bit little-endian (low 14 bits = size).
        if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
            return None
        width = int.from_bytes(payload[6:8], "little") & 0x3FFF
        height = int.from_bytes(payload[8:10], "little") & 0x3FFF
        return width, height
    return None


def _read_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Best-effort ``(width, height)`` from raw image bytes (v3.6.0+).

    Parses container headers directly for PNG, GIF, BMP, JPEG, and WEBP
    without decoding pixel data, so it's cheap to run on every
    downloaded image. Returns ``None`` for formats we don't parse
    (e.g. TIFF) or on any malformed/truncated input. Callers must
    treat ``None`` as "dimensions unknown, don't filter" rather than
    "image too small" — we'd rather let an unmeasurable image through
    than drop a valid one.
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            # IHDR is always the first chunk: 4-byte length, "IHDR",
            # then 4-byte width and 4-byte height (big-endian).
            if len(data) >= 24 and data[12:16] == b"IHDR":
                width = int.from_bytes(data[16:20], "big")
                height = int.from_bytes(data[20:24], "big")
                return width, height
            return None

        if data[:6] in (b"GIF87a", b"GIF89a"):
            if len(data) >= 10:
                width = int.from_bytes(data[6:8], "little")
                height = int.from_bytes(data[8:10], "little")
                return width, height
            return None

        if data[:2] == b"BM":
            # BITMAPFILEHEADER (14 bytes) then BITMAPINFOHEADER width
            # (offset 18) / height (offset 22) as little-endian int32.
            # Height may be negative for top-down bitmaps.
            if len(data) >= 26:
                width = int.from_bytes(data[18:22], "little", signed=True)
                height = int.from_bytes(data[22:26], "little", signed=True)
                return abs(width), abs(height)
            return None

        if data[:2] == b"\xff\xd8":
            return _read_jpeg_dimensions(data)

        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return _read_webp_dimensions(data)
    except (IndexError, ValueError):
        # Truncated/malformed header. Dimension sniffing must never
        # crash a download, so treat this the same as "unmeasurable".
        return None
    return None


class ImageEngine(ABC):
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
        timeout: int = 60,
        verbose: bool = DEFAULT_VERBOSE,
        badsites=None,
        name: str = "Image",
        max_workers: int = 4,
        force_replace: bool = False,
        cancel=None,
        min_dimension: int | None = None,
    ):
        # Abstract base class — subclasses MUST override ``run()``.
        # The abstractmethod below is what makes
        # ``ImageEngine`` uncallable as ``ImageEngine(...)`` directly,
        # while still letting concrete subclasses (Bing, DuckDuckGo)
        # call ``super().__init__()``.
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
        # ``cancel`` is an optional ``CancelToken`` (from
        # ``downloader.py``). The base class stores it; concrete
        # engines (Bing, DuckDuckGo) check it between page fetches
        # and image downloads. We don't import CancelToken here to
        # avoid a circular import; the type is duck-typed.
        self.cancel = cancel
        # ``min_dimension`` (v3.6.0+): minimum width/height in pixels an
        # image must have to be kept. ``None`` (the default) disables
        # the check entirely. Subclasses (Bing, DuckDuckGo) accept this
        # in their own constructors and forward via ``super().__init__()``;
        # ``Downloader.search`` routes it through ``engine_kwargs``.
        self.min_dimension: int | None = min_dimension

        self.seen: set[str] = set()
        self.download_count = 0  # newly downloaded this run
        self._slots_used = 0  # slots consumed (downloaded + skipped existing)
        self.download_callback = None
        self._count_lock = threading.Lock()
        self.manifest: dict = {}  # filename -> source URL
        self._file_hashes: set = set()
        self._hash_lock = threading.Lock()
        # ``last_page_url`` (v3.5.0+) is the URL of the most recently
        # fetched search-results page. Set by each engine's ``run()``
        # method after a page fetch; read by the manifest writer to
        # capture per-image provenance. ``None`` until the first page
        # fetch; remains ``None`` for engines that don't track it.
        self.last_page_url: str | None = None

        self.output_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def run(self) -> None:
        """Fetch image URLs from the engine and download them.

        Subclasses implement this to call :meth:`download_image` (or
        :meth:`_download_batch`) for each URL returned by their
        backend.
        """
        raise NotImplementedError

    # Re-declare instance attributes as class-level annotations so
    # static analysers (mypy) can see them on ``self`` without having
    # to walk the ``__init__`` body.
    query: str
    limit: int
    output_dir: Path
    timeout: int
    verbose: bool
    badsites: set
    image_name: str
    max_workers: int
    force_replace: bool

    # --- HTTP helpers ---

    def _http_get(self, url: str, headers: dict | None = None) -> bytes:
        """GET ``url`` with the engine's default headers merged with overrides."""
        merged = dict(DEFAULT_HEADERS)
        if headers:
            merged.update(headers)
        request = urllib.request.Request(url, None, headers=merged)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data: bytes = response.read()
            return data

    def is_cancelled(self) -> bool:
        """Return ``True`` if the user has called ``cancel_token.cancel()``.

        Engines should call this between page fetches and individual
        image downloads. The check is O(1) and lock-free.
        """
        if self.cancel is None:
            return False
        return bool(self.cancel.cancelled)

    # --- Download pipeline ---

    def save_image(self, link: str, file_path) -> bool:
        """Download an image to ``file_path`` atomically.

        Returns ``True`` on success. On failure, returns ``False`` and
        logs the error. (As of v3.4.0, the underlying
        ``_save_image_raising`` raises typed ``ImageSaveError``
        subclasses; ``save_image`` catches them and returns ``False``
        for backwards compatibility. ``Downloader.search`` uses the
        raising variant directly so it can surface typed errors via
        ``Result.errors`` and ``on_error``.)
        """
        try:
            self._save_image_raising(link, file_path)
            return True
        except ImageSaveError as e:
            # The raising variant already logged the underlying cause.
            logging.info("Image save skipped: %s", e)
            return False

    def _save_image_raising(self, link: str, file_path) -> str:
        """Download an image to ``file_path`` atomically, raising on failure.

        Returns
        -------
        str
            The MD5 hex digest of the saved image bytes. Returned on
            success so the manifest writer (v3.5.0+) can record it
            without re-reading the file.

        Raises
        ------
        NetworkError
            The HTTP fetch failed (timeout, 5xx, DNS error, etc.).
        InvalidImageError
            The fetched bytes don't look like an image.
        BelowMinDimension
            ``self.min_dimension`` is set and the image's width or
            height is smaller than it (v3.6.0+).
        DuplicateImageError
            An image with the same MD5 hash has already been saved
            this run.
        WriteError
            Failed to create the temp file or write the image bytes.
        """
        try:
            image = self._http_get(link)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            raise NetworkError(url=link, message=f"network error: {e}") from e
        except Exception as e:
            raise NetworkError(url=link, message=f"unexpected error: {e}") from e

        kind = filetype.guess(image)
        if not kind or not kind.mime.startswith("image/"):
            raise InvalidImageError(url=link)

        if self.min_dimension is not None:
            dimensions = _read_image_dimensions(image)
            if dimensions is not None:
                width, height = dimensions
                if width < self.min_dimension or height < self.min_dimension:
                    raise BelowMinDimension(
                        url=link,
                        width=width,
                        height=height,
                        min_dimension=self.min_dimension,
                    )

        file_hash = hashlib.md5(image).hexdigest()
        with self._hash_lock:
            if file_hash in self._file_hashes:
                raise DuplicateImageError(url=link)
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
            raise WriteError(url=link, message=f"mkstemp: {e}") from e
        try:
            with open(fd, "wb") as f:
                f.write(image)
            shutil.move(tmp_path, file_path)
        except Exception as e:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
            raise WriteError(url=link, message=f"write: {e}") from e
        return file_hash

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
