"""Crawl image URLs from image search engines.

.. deprecated::
    The Google crawler path is no longer functional: Google now serves
    a JavaScript-only shell page to all non-browser HTTP requests, so
    no image URLs can be extracted without a headless browser.
    Use :func:`better_bing_image_downloader.downloader` with
    ``engine="bing"`` or ``engine="duckduckgo"`` instead.

    The Bing path in this module is also legacy; prefer
    :class:`better_bing_image_downloader.bing.Bing`. This module will
    be removed in v4.0.0.
"""

# author: Krishnatejaswi S
# Email: shentharkrishnatejaswi@gmail.com


import json
import logging
import re
import shutil
import time
from urllib.parse import quote

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Default headers for HTTP requests
g_headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Accept-Encoding": "gzip, deflate, sdch",
    "Proxy-Connection": "keep-alive",
}


def my_print(msg, quiet=False):
    """Print messages if not in quiet mode"""
    if not quiet:
        print(msg)


def google_gen_query_url(keywords, face_only=False, safe_mode=False, image_type=None, color=None):
    """Generate Google Images search URL with filters"""
    base_url = "https://www.google.com/search?tbm=isch&hl=en"
    keywords_str = "&q=" + quote(keywords)
    query_url = base_url + keywords_str

    # Add safe search parameter
    query_url += "&safe=" + ("on" if safe_mode else "off")

    # Build filter URL
    filter_url = "&tbs="
    filter_parts = []

    # Add color filter
    if color is not None:
        if color == "bw":
            filter_parts.append("ic:gray")
        else:
            filter_parts.append(f"ic:specific,isc:{color.lower()}")

    # Add image type filter
    if image_type is not None:
        if image_type.lower() == "linedrawing":
            image_type = "lineart"
        filter_parts.append(f"itp:{image_type}")

    # Add face filter
    if face_only:
        filter_parts.append("itp:face")

    # Combine all filter parts
    if filter_parts:
        query_url += filter_url + ",".join(filter_parts)

    return query_url


def google_image_url_from_webpage(driver, max_number=10000):
    """Extract image URLs from Google Images search results page"""
    from urllib.parse import parse_qs, unquote, urlparse

    image_urls = []
    seen = set()
    scroll_count = 0
    max_scrolls = max(30, max_number // 5)

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "a")))
    except Exception:
        time.sleep(2)

    while len(image_urls) < max_number and scroll_count < max_scrolls:
        try:
            # Extract full image URLs from anchor hrefs containing imgurl= parameter
            anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='imgurl=']")
            for anchor in anchors:
                href = anchor.get_attribute("href") or ""
                if "imgurl=" not in href:
                    continue
                # Parse the imgurl parameter out
                try:
                    parsed = urlparse(href)
                    params = parse_qs(parsed.query)
                    img_url = params.get("imgurl", [None])[0]
                    if img_url and img_url not in seen:
                        seen.add(img_url)
                        image_urls.append(unquote(img_url))
                        if len(image_urls) >= max_number:
                            break
                except Exception:
                    continue
        except Exception as e:
            logging.error("Error collecting Google image URLs: %s", e)

        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(0.8)
        scroll_count += 1

    return image_urls


def bing_gen_query_url(keywords, face_only=False, safe_mode=False, image_type=None, color=None):
    """Generate Bing Images search URL with filters"""
    base_url = "https://www.bing.com/images/search?"
    keywords_str = "&q=" + quote(keywords)
    query_url = base_url + keywords_str
    filter_url = "&qft="
    filter_parts = []

    # Add face filter
    if face_only:
        filter_parts.append("filterui:face-face")

    # Add image type filter
    if image_type is not None:
        filter_parts.append(f"filterui:photo-{image_type}")

    # Add color filter
    if color is not None:
        if color in ["bw", "color"]:
            filter_parts.append(f"filterui:color2-{color.lower()}")
        else:
            filter_parts.append(f"filterui:color2-FGcls_{color.upper()}")

    # Combine all filter parts
    if filter_parts:
        query_url += filter_url + "+".join(filter_parts)

    if safe_mode:
        query_url += "&adlt=strict"

    return query_url


def bing_image_url_from_webpage(driver, max_number=10000):
    """Extract image URLs from Bing Images search results page"""
    image_urls = []
    image_elements = []
    img_count = 0
    scroll_count = 0
    max_scrolls = max(50, max_number // 5)

    # Wait for Bing's actual result containers (class iusc)
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".iusc")))
    except Exception:
        time.sleep(2)  # fallback

    # Scroll and load more images until no more are available
    while img_count < max_number and scroll_count < max_scrolls:
        try:
            image_elements = driver.find_elements(By.CLASS_NAME, "iusc")
            if len(image_elements) > img_count:
                img_count = len(image_elements)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            else:
                # Check for "See more" button
                smb = driver.find_elements(By.CLASS_NAME, "btn_seemore")
                if len(smb) > 0 and smb[0].is_displayed():
                    smb[0].click()
                else:
                    break
            time.sleep(0.5)
        except Exception as e:
            logging.error("Error while scrolling: %s", e)
            break
        scroll_count += 1

    # Extract image URLs from JSON data
    for image_element in image_elements:
        try:
            m_json_str = image_element.get_attribute("m")
            m_json = json.loads(m_json_str)
            image_urls.append(m_json["murl"])
        except Exception as e:
            logging.error("Error extracting URL: %s", e)

    return image_urls


def bing_get_image_url_using_api(
    keywords, max_number=10000, face_only=False, proxy=None, proxy_type=None
):
    """Get image URLs from Bing using API requests instead of browser"""
    # Setup proxies if provided
    proxies = None
    if proxy and proxy_type:
        proxies = {
            "http": f"{proxy_type}://{proxy}",
            "https": f"{proxy_type}://{proxy}",
        }

    start = 1
    image_urls = []
    last_url = None

    # Fetch image URLs in batches
    while start <= max_number:
        try:
            url = f"https://www.bing.com/images/async?q={quote(keywords)}&first={start}&count=35"
            res = requests.get(url, proxies=proxies, headers=g_headers, timeout=30)
            res.raise_for_status()  # Raise exception for HTTP errors
            res.encoding = "utf-8"

            # Extract image URLs using regex
            image_urls_batch = re.findall("murl&quot;:&quot;(.*?)&quot;", res.text)

            # Break if no new images or we've seen the last URL before
            if not image_urls_batch or (image_urls and image_urls_batch[-1] == last_url):
                break

            last_url = image_urls_batch[-1]
            image_urls.extend(image_urls_batch)
            start += len(image_urls_batch)

            # Optional delay to be nice to the server
            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            logging.error("Error fetching image URLs: %s", e)
            break

    return image_urls[:max_number]


def crawl_image_urls(
    keywords,
    engine="Google",
    max_number=10000,
    face_only=False,
    safe_mode=False,
    proxy=None,
    proxy_type="http",
    quiet=False,
    browser="chrome_headless",
    image_type=None,
    color=None,
):
    """
    Scrape image urls from search engines

    Args:
        keywords: keywords you want to search
        engine: search engine used to search images
        max_number: limit the max number of image urls the function output
        face_only: image type set to face only, provided by Google
        safe_mode: switch for safe mode of Search
        proxy: proxy address, example: socks5 127.0.0.1:1080
        proxy_type: socks5, http
        browser: browser to use when crawl image urls
        image_type: type of images to search for
        color: color filter for images

    Returns:
        list of scraped image urls
    """
    engine = engine.capitalize()

    my_print(f"\nScraping From {engine} Image Search ...\n", quiet)
    my_print(f"Keywords: {keywords}", quiet)

    if max_number <= 0:
        my_print("Number: No limit", quiet)
        max_number = 10000
    else:
        my_print(f"Number: {max_number}", quiet)

    my_print(f"Face Only: {face_only}", quiet)
    my_print(f"Safe Mode: {safe_mode}", quiet)

    # Generate appropriate query URL based on engine
    if engine == "Google":
        query_url = google_gen_query_url(keywords, face_only, safe_mode, image_type, color)
    elif engine == "Bing":
        query_url = bing_gen_query_url(keywords, face_only, safe_mode, image_type, color)
    else:
        logging.error("Unsupported engine: %s", engine)
        return []

    my_print(f"Query URL: {query_url}", quiet)
    image_urls = []

    # Use API approach if specified
    if browser == "api":
        if engine == "Bing":
            image_urls = bing_get_image_url_using_api(
                keywords,
                max_number=max_number,
                face_only=face_only,
                proxy=proxy,
                proxy_type=proxy_type,
            )
        else:
            my_print(f"Engine {engine} is not supported on API mode.")
            return []

    # Use browser automation approach
    else:
        try:
            # Setup appropriate browser
            browser = browser.lower()
            driver = None

            if "firefox" in browser:
                firefox_path = shutil.which("geckodriver")
                firefox_options = webdriver.FirefoxOptions()
                if "headless" in browser:
                    firefox_options.add_argument("-headless")
                if proxy and proxy_type:
                    firefox_options.add_argument(f"--proxy-server={proxy_type}://{proxy}")
                service = Service(executable_path=firefox_path)
                driver = webdriver.Firefox(service=service, options=firefox_options)
            else:
                chrome_path = shutil.which("chromedriver")
                chrome_options = webdriver.ChromeOptions()
                if "headless" in browser:
                    chrome_options.add_argument("headless")
                if proxy and proxy_type:
                    chrome_options.add_argument(f"--proxy-server={proxy_type}://{proxy}")
                service = Service(executable_path=chrome_path)
                driver = webdriver.Chrome(service=service, options=chrome_options)

            if not driver:
                raise ValueError("Failed to initialize WebDriver")

            # Set window size and load URL
            driver.set_window_size(1920, 1080)
            driver.get(query_url)

            # Extract image URLs based on engine
            if engine == "Google":
                image_urls = google_image_url_from_webpage(driver, max_number)
            elif engine == "Bing":
                image_urls = bing_image_url_from_webpage(driver, max_number)

            # Close browser
            driver.quit()

        except Exception as e:
            logging.error("Error during web scraping: %s", e)
            if "driver" in locals() and driver:
                driver.quit()

    # Limit number of results if needed
    output_num = min(max_number, len(image_urls))
    my_print(
        f"\n== {output_num} out of {len(image_urls)} crawled image URLs will be used.\n",
        quiet,
    )

    return image_urls[:output_num]
