"""Bing image search scraper.

Original Author: Guru Prasad (g.gaurav541@gmail.com)
Improved Author: Krishnatejaswi S (shentharkrishnatejaswi@gmail.com)
"""

from __future__ import annotations

import gzip
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import MAX_FUTURE_TIMEOUT, ImageEngine

__all__ = ["Bing"]


class Bing(ImageEngine):
    """Download images from Bing's image search API.

    Parameters
    ----------
    query : str
        The search query.
    limit : int
        Maximum number of images to download.
    output_dir : str | Path
        Directory where images will be saved.
    adult : str
        Adult content filter, ``"off"`` or ``"moderate"``.
    timeout : int
        Per-request timeout in seconds.
    filter : str
        Optional Bing image-type filter shorthand
        (``"photo"``, ``"clipart"``, ``"line"``/``"linedrawing"``,
        ``"gif"``/``"animatedgif"``, ``"transparent"``).
    verbose : bool
        Whether to print progress information.
    badsites : Iterable[str] | None
        Hostnames to exclude from results.
    name : str
        Base filename for downloaded images.
    max_workers : int
        Number of parallel download workers (clamped to 1..16).
    force_replace : bool
        If ``True``, re-download images even if they already exist.
    mkt : str
        Bing market code (e.g. ``"en-US"``).
    """

    PAGE_SIZE = 35  # Bing's /images/async returns 35 results per page
    BACKOFF_INITIAL = 2.0  # seconds
    BACKOFF_FACTOR = 2.0
    BACKOFF_MAX = 60.0

    def __init__(
        self,
        query: str,
        limit: int,
        output_dir,
        adult: str = "moderate",
        timeout: int = 60,
        filter: str = "",
        verbose: bool = True,
        badsites=None,
        name: str = "Image",
        max_workers: int = 4,
        force_replace: bool = False,
        mkt: str = "en-US",
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
        )
        self.adult = adult
        self.filter = filter
        self.mkt = mkt
        self._backoff = self.BACKOFF_INITIAL
        # Bing returns compressed responses; we must advertise support.
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Referer": "https://www.bing.com/",
        }
        if self.badsites and self.verbose:
            logging.info("Download links will not include: %s", ", ".join(self.badsites))

    def get_filter(self, shorthand: str) -> str:
        """Convert filter shorthand to a Bing ``+filterui:`` string."""
        filters = {
            "line": "+filterui:photo-linedrawing",
            "linedrawing": "+filterui:photo-linedrawing",
            "photo": "+filterui:photo-photo",
            "clipart": "+filterui:photo-clipart",
            "gif": "+filterui:photo-animatedgif",
            "animatedgif": "+filterui:photo-animatedgif",
            "transparent": "+filterui:photo-transparent",
        }
        return filters.get(shorthand, "")

    def _fetch_page(self, page_counter: int) -> str:
        """Fetch and decode a single Bing image-search page.

        Returns the page HTML as a string, or an empty string if no more
        results are available.
        """
        request_url = (
            "https://www.bing.com/images/async?q="
            + urllib.parse.quote_plus(self.query)
            + "&first="
            + str(page_counter * self.PAGE_SIZE)
            + "&count="
            + str(self.PAGE_SIZE)
            + "&adlt="
            + self.adult
            + "&mkt="
            + urllib.parse.quote_plus(self.mkt)
            + "&qft="
            + ("" if self.filter is None else self.get_filter(self.filter))
        )
        request = urllib.request.Request(request_url, None, headers=self.headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw: bytes = response.read()
            content_encoding = response.headers.get("Content-Encoding", "")
        if content_encoding == "gzip":
            decompressed: bytes = gzip.decompress(raw)
            return decompressed.decode("utf8")
        return raw.decode("utf8", errors="replace")

    @staticmethod
    def _extract_links(html: str) -> list[str]:
        """Extract ``murl`` image URLs from a Bing result page."""
        return re.findall(r"murl&quot;:&quot;(.*?)&quot;", html)

    def run(self) -> None:
        """Download images until ``self.limit`` is reached or pages are exhausted."""
        page_counter = 0
        while self._slots_used < self.limit:
            if self.verbose:
                logging.info("\n\n[!]Indexing page: %d\n", page_counter + 1)
            try:
                html = self._fetch_page(page_counter)
            except (urllib.error.HTTPError, urllib.error.URLError) as e:
                wait = self._consume_backoff()
                logging.error(
                    "Network error while requesting from Bing: %s. " "Retrying in %.1fs.",
                    e,
                    wait,
                )
                time.sleep(wait)
                continue
            except Exception as e:  # pragma: no cover - defensive
                logging.error("Unexpected error while requesting from Bing: %s", e)
                break

            if not html:
                logging.info("[%%] No more images are available")
                break

            links = self._extract_links(html)
            if self.verbose:
                logging.info(
                    "[%%] Indexed %d Images on Page %d.",
                    len(links),
                    page_counter + 1,
                )
                logging.info("\n===============================================\n")

            filtered_links = [
                link
                for link in links
                if link not in self.seen and not any(badsite in link for badsite in self.badsites)
            ]
            if not filtered_links:
                logging.info("[%%] No new images are available")
                break
            self.seen.update(filtered_links)

            remaining = self.limit - self._slots_used
            links_to_download = filtered_links[:remaining]
            slots_before = self._slots_used
            self._download_batch(links_to_download, start_index=self.download_count + 1)
            if self._slots_used == slots_before:
                logging.warning("No images could be downloaded from this page")
                # If a page yielded no downloads, treat it as exhaustion so we
                # don't loop forever against an empty result set.
                break

            if self._slots_used >= self.limit:
                break
            page_counter += 1
            self._reset_backoff()

        logging.info("\n\n[%%] Done. Downloaded %d images.", self.download_count)

    # --- Internal helpers used by ``run`` and the parallel executor ---

    def _consume_backoff(self) -> float:
        """Return the current backoff delay and double it for next time."""
        wait = self._backoff
        self._backoff = min(self._backoff * self.BACKOFF_FACTOR, self.BACKOFF_MAX)
        return wait

    def _reset_backoff(self) -> None:
        self._backoff = self.BACKOFF_INITIAL

    def _download_batch(self, links: list[str], start_index: int) -> None:
        """Download a batch of links starting at ``start_index``.

        ``ImageEngine.download_image`` updates counters itself; this method
        just dispatches work in parallel or sequentially.
        """
        if not links:
            return
        if self.max_workers > 1:
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
