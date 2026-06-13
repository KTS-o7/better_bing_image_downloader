"""DuckDuckGo image search engine.

DuckDuckGo's image search exposes a clean JSON API (``/i.js``) that does
not require a headless browser, an API key, or rate-limit tokens beyond
a short-lived ``vqd`` token obtained from the search page.

The flow is:

1. ``GET https://duckduckgo.com/?q=...&iax=images&ia=images`` and extract
   the ``vqd`` token from the page HTML.
2. ``GET https://duckduckgo.com/i.js?q=...&s=<offset>&vqd=<token>`` for
   each page; parse ``results[].image`` for full-resolution URLs.

We use a :class:`http.cookiejar.CookieJar` so the session-cookie set on
the initial fetch is replayed to ``i.js`` (otherwise ``i.js`` returns
``403 Forbidden``).
"""

from __future__ import annotations

import gzip
import http.cookiejar
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import brotli

    _HAS_BROTLI = True
except ImportError:  # pragma: no cover
    brotli = None
    _HAS_BROTLI = False

from .base import MAX_FUTURE_TIMEOUT, ImageEngine

__all__ = ["DuckDuckGo"]

# Brotli is required because DuckDuckGo's CDN advertises ``br`` encoding
# on the image search endpoints and returns 403 if the client refuses
# it.  We declare ``brotli`` as a runtime optional dependency in
# ``pyproject.toml`` and emit a clear error if it's missing.
_BROTLI_MISSING_MSG = (
    "DuckDuckGo image search requires the 'brotli' package to decode "
    "Brotli-compressed responses. Install it with "
    "`pip install brotli` (or `pip install 'better-bing-image-downloader"
    "[duckduckgo]'`)."
)


class DuckDuckGo(ImageEngine):
    """Download images from DuckDuckGo's image search.

    Parameters
    ----------
    query : str
        Search query.
    limit : int
        Maximum number of images to download.
    output_dir : str | Path
        Directory where images will be saved.
    timeout : int
        Per-request timeout in seconds.
    verbose : bool
        Whether to print progress.
    badsites : Iterable[str] | None
        Hostnames to exclude from results.
    name : str
        Base filename for downloaded images.
    max_workers : int
        Number of parallel download workers (1..16).
    force_replace : bool
        Re-download images even if they already exist.
    safe_search : str
        ``"strict"``, ``"moderate"`` (default), or ``"off"``.
    region : str
        DuckDuckGo region code (e.g. ``"us-en"``, ``"uk-en"``). Default
        ``"us-en"``.
    """

    PAGE_SIZE = 100  # DDG's i.js returns up to 100 results per page
    BACKOFF_INITIAL = 2.0
    BACKOFF_FACTOR = 2.0
    BACKOFF_MAX = 60.0

    VALID_SAFE_SEARCH = {"strict", "moderate", "off"}

    def __init__(
        self,
        query: str,
        limit: int,
        output_dir,
        timeout: int = 30,
        verbose: bool = True,
        badsites=None,
        name: str = "Image",
        max_workers: int = 4,
        force_replace: bool = False,
        safe_search: str = "moderate",
        region: str = "us-en",
        cancel=None,
    ):
        super().__init__(
            query=query,
            limit=limit,
            output_dir=output_dir,
            timeout=timeout,
            verbose=verbose,
            badsites=badsites,
            name=name,
            max_workers=max_workers,
            force_replace=force_replace,
            cancel=cancel,
        )
        if safe_search not in self.VALID_SAFE_SEARCH:
            raise ValueError(
                f"safe_search must be one of {sorted(self.VALID_SAFE_SEARCH)}, "
                f"got {safe_search!r}"
            )
        self.safe_search = safe_search
        self.region = region
        self._backoff = self.BACKOFF_INITIAL
        self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookie_jar)
        )
        if not _HAS_BROTLI:
            raise ImportError(_BROTLI_MISSING_MSG)

    # --- HTTP helpers ---

    def _decode(self, raw: bytes, encoding: str) -> str:
        """Decode a response body, handling gzip and brotli."""
        if encoding == "gzip":
            return gzip.decompress(raw).decode("utf8", errors="replace")
        if encoding == "br":
            if not _HAS_BROTLI:  # pragma: no cover
                raise ImportError(_BROTLI_MISSING_MSG)
            decompressed: bytes = brotli.decompress(raw)
            return decompressed.decode("utf8", errors="replace")
        return raw.decode("utf8", errors="replace")

    def _get(self, url: str, referer: str | None = None) -> tuple[bytes, str]:
        """GET a URL with the standard browser-like headers.

        Returns the raw response body and the ``Content-Encoding`` header
        value (which may be empty for uncompressed responses).
        """
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        if referer:
            headers["Referer"] = referer
        request = urllib.request.Request(url, None, headers=headers)
        with self._opener.open(request, timeout=self.timeout) as response:
            return response.read(), response.headers.get("Content-Encoding", "")

    # --- Search ---

    def _fetch_vqd(self) -> str:
        """Fetch the short-lived ``vqd`` token required by ``i.js``."""
        url = (
            "https://duckduckgo.com/?q="
            + urllib.parse.quote_plus(self.query)
            + "&iax=images&ia=images"
        )
        raw, enc = self._get(url)
        html = self._decode(raw, enc)
        m = re.search(r'vqd=([\'"])(\d[\d\-]+)\1', html)
        if not m:
            raise RuntimeError(
                "Could not extract vqd token from DuckDuckGo response. "
                "The page format may have changed."
            )
        return m.group(2)

    def _build_page_url(self, vqd: str, offset: int) -> str:
        """Construct the i.js URL for a given page offset (v3.5.0+).

        Split out from :meth:`_fetch_page` so the manifest writer can
        record the exact URL the engine requested.
        """
        return (
            "https://duckduckgo.com/i.js?q="
            + urllib.parse.quote_plus(self.query)
            + "&o=json&p=1&s="
            + str(offset)
            + "&f=,,,,"
            + "&l="
            + urllib.parse.quote_plus(self.region)
            + "&vqd="
            + urllib.parse.quote_plus(vqd)
        )

    def _fetch_page(self, vqd: str, offset: int) -> list[str]:
        """Fetch a single page of image URLs from ``i.js``."""
        url = self._build_page_url(vqd, offset)
        # i.js must be requested as XHR
        opener_with_xhr = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookie_jar)
        )
        # Tell opener to add X-Requested-With via a custom addheaders
        opener_with_xhr.addheaders = [
            ("X-Requested-With", "XMLHttpRequest"),
            ("Accept", "application/json, text/plain, */*"),
        ]
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": (
                "https://duckduckgo.com/?q="
                + urllib.parse.quote_plus(self.query)
                + "&iax=images&ia=images"
            ),
            "X-Requested-With": "XMLHttpRequest",
        }
        request = urllib.request.Request(url, None, headers=headers)
        with opener_with_xhr.open(request, timeout=self.timeout) as response:
            raw = response.read()
            enc = response.headers.get("Content-Encoding", "")
        text = self._decode(raw, enc)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse DuckDuckGo i.js response as JSON: {e}") from e
        return [r["image"] for r in data.get("results", []) if r.get("image")]

    # --- Main loop ---

    def _consume_backoff(self) -> float:
        wait = self._backoff
        self._backoff = min(self._backoff * self.BACKOFF_FACTOR, self.BACKOFF_MAX)
        return wait

    def _reset_backoff(self) -> None:
        self._backoff = self.BACKOFF_INITIAL

    def run(self) -> None:
        """Download images until ``self.limit`` is reached or pages exhausted."""
        if not _HAS_BROTLI:  # pragma: no cover
            raise ImportError(_BROTLI_MISSING_MSG)

        if self.verbose:
            logging.info("\n\n[!]Indexing DuckDuckGo for: %s\n", self.query)

        try:
            vqd = self._fetch_vqd()
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            logging.error("Failed to fetch vqd token from DuckDuckGo: %s", e)
            return
        except Exception as e:  # pragma: no cover - defensive
            logging.error("Unexpected error fetching vqd: %s", e)
            return

        offset = 0
        page_num = 0
        while self._slots_used < self.limit:
            # Check the cancel token (v3.3.0+). Returns immediately if
            # the user called ``cancel_token.cancel()`` from another
            # thread.
            if self.is_cancelled():
                if self.verbose:
                    logging.info("[!] Cancellation requested; stopping.")
                return
            if self.verbose:
                logging.info("[!]Indexing page: %d (offset=%d)", page_num + 1, offset)
            try:
                # Track the URL we are about to fetch so the manifest
                # writer (v3.5.0+) can record provenance for every
                # image sourced from this page.
                self.last_page_url = self._build_page_url(vqd, offset)
                links = self._fetch_page(vqd, offset)
            except (urllib.error.HTTPError, urllib.error.URLError) as e:
                wait = self._consume_backoff()
                logging.error(
                    "Network error from DuckDuckGo: %s. Retrying in %.1fs.",
                    e,
                    wait,
                )
                time.sleep(wait)
                continue
            except Exception as e:  # pragma: no cover - defensive
                logging.error("Unexpected error from DuckDuckGo: %s", e)
                break

            self._reset_backoff()

            if not links:
                logging.info("[%%] No more images are available")
                break

            # Filter seen/badsites
            filtered = [
                link
                for link in links
                if link not in self.seen and not any(badsite in link for badsite in self.badsites)
            ]
            self.seen.update(links)

            if not filtered:
                # No new URLs on this page; try the next one.
                offset += self.PAGE_SIZE
                page_num += 1
                if page_num > 20:  # safety: stop after 20 empty pages
                    logging.info("[%%] No new images after %d pages, stopping", page_num)
                    break
                continue

            remaining = self.limit - self._slots_used
            to_download = filtered[:remaining]
            self._download_batch(to_download, start_index=self.download_count + 1)

            if self._slots_used >= self.limit:
                break
            offset += self.PAGE_SIZE
            page_num += 1

        logging.info("\n\n[%%] Done. Downloaded %d images.", self.download_count)

    def _download_batch(self, links: list[str], start_index: int) -> None:
        """Download a batch of links starting at ``start_index``.

        The base class already updates counters inside ``download_image``,
        so this just dispatches work.
        """
        if not links:
            return
        if self.max_workers > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [
                    executor.submit(self.download_image, link, i)
                    for i, link in enumerate(links, start_index)
                ]
                for future in as_completed(futures, timeout=MAX_FUTURE_TIMEOUT):
                    try:
                        future.result()
                    except Exception as e:
                        logging.error("Error processing download: %s", e)
        else:
            for i, link in enumerate(links, start_index):
                if self._slots_used >= self.limit:
                    break
                self.download_image(link, i)
