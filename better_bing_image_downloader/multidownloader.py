# author: Krishnatejaswi S
# Email: shentharkrishnatejaswi@gmail.com
"""
Deprecated Selenium-based CLI for Google/Bing image scraping.

.. deprecated::
    The Google path no longer works: Google serves a JavaScript-only
    shell to all non-browser HTTP requests, so this crawler cannot
    extract image URLs without a real browser.  Use
    :func:`better_bing_image_downloader.downloader` with
    ``engine="bing"`` or ``engine="duckduckgo"`` instead.

    This module will be removed in v4.0.0.
"""

from __future__ import annotations

import argparse
import sys
import warnings

from . import crawler, helperdownload, utils


def main(argv: list[str] | None = None) -> None:
    warnings.warn(
        "better_bing_image_downloader.multidownloader is deprecated and will "
        "be removed in v4.0.0. The Google path no longer works (Google returns "
        "a JS-only shell to automated requests). Use bbid --engine duckduckgo "
        "or bbid --engine bing instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    parser = argparse.ArgumentParser(
        description=(
            "[DEPRECATED] Selenium-based image helper. "
            "Use bbid --engine bing or bbid --engine duckduckgo."
        )
    )
    parser.add_argument("keywords", type=str, help='Keywords to search. ("in quotes")')
    parser.add_argument(
        "--engine",
        "-e",
        type=str,
        default="Bing",
        help="Image search engine.",
        choices=["Google", "Bing"],
    )
    parser.add_argument(
        "--driver",
        "-d",
        type=str,
        default="firefox_headless",
        help="Image search engine.",
        choices=["chrome_headless", "chrome", "api", "firefox", "firefox_headless"],
    )
    parser.add_argument(
        "--max-number",
        "-n",
        type=int,
        default=100,
        help="Max number of images download for the keywords.",
    )
    parser.add_argument(
        "--num-threads",
        "-j",
        type=int,
        default=50,
        help="Number of threads to concurrently download images.",
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=10,
        help="Seconds to timeout when download an image.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="./download_images",
        help="Output directory to save downloaded images.",
    )
    parser.add_argument(
        "--safe-mode",
        "-S",
        action="store_true",
        default=False,
        help="Turn on safe search mode. (Only effective in Google)",
    )
    parser.add_argument(
        "--face-only", "-F", action="store_true", default=False, help="Only search for "
    )
    parser.add_argument(
        "--proxy_http",
        "-ph",
        type=str,
        default=None,
        help="Set http proxy (e.g. 192.168.0.2:8080)",
    )
    parser.add_argument(
        "--proxy_socks5",
        "-ps",
        type=str,
        default=None,
        help="Set socks5 proxy (e.g. 192.168.0.2:1080)",
    )
    parser.add_argument(
        "--type",
        "-ty",
        type=str,
        default=None,
        help="What kinds of images to download.",
        choices=["clipart", "linedrawing", "photograph"],
    )
    parser.add_argument(
        "--color",
        "-cl",
        type=str,
        default=None,
        help="Specify the color of desired images.",
    )

    args = parser.parse_args(args=argv)

    proxy_type = None
    proxy = None
    if args.proxy_http is not None:
        proxy_type = "http"
        proxy = args.proxy_http
    elif args.proxy_socks5 is not None:
        proxy_type = "socks5"
        proxy = args.proxy_socks5

    if not utils.resolve_dependencies(args.driver):
        print("Dependencies not resolved, exit.")
        return

    if args.engine == "Google":
        warnings.warn(
            "The Google engine no longer works without a headless browser. "
            "Use --engine Bing or the new bbid --engine duckduckgo CLI.",
            DeprecationWarning,
            stacklevel=2,
        )

    crawled_urls = crawler.crawl_image_urls(
        args.keywords,
        engine=args.engine,
        max_number=args.max_number,
        face_only=args.face_only,
        safe_mode=args.safe_mode,
        proxy_type=proxy_type,
        proxy=proxy,
        browser=args.driver,
        image_type=args.type,
        color=args.color,
    )
    helperdownload.download_images(
        image_urls=crawled_urls,
        dst_dir=args.output,
        concurrency=args.num_threads,
        timeout=args.timeout,
        proxy_type=proxy_type,
        proxy=proxy,
        file_prefix=args.engine,
    )
    print("Finished.")


if __name__ == "__main__":
    main(sys.argv[1:])
