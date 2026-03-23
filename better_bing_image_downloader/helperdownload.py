""" Download image according to given urls and automatically rename them in order. """
# author: Krishnatejaswi S
# Email: shentharkrishnatejaswi@gmail.com

from __future__ import print_function

import shutil
import os
import concurrent.futures
import tempfile as _tempfile
import time
import requests
import filetype

headers = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Proxy-Connection": "keep-alive",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Accept-Encoding": "gzip, deflate, sdch",
    # 'Connection': 'close',
}

VALID_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "bmp", "webp", "gif", "tiff", "ico"}


def download_image(image_url, dst_dir, file_name, timeout=20, proxy_type=None, proxy=None):
    proxies = None
    if proxy_type is not None:
        proxies = {
            "http": proxy_type + "://" + proxy,
            "https": proxy_type + "://" + proxy
        }

    response = None
    try_times = 0
    while True:
        try:
            try_times += 1
            response = requests.get(
                image_url, headers=headers, timeout=timeout, proxies=proxies)
            tmp_fd, tmp_path = _tempfile.mkstemp(dir=dst_dir)
            try:
                with os.fdopen(tmp_fd, 'wb') as f:
                    f.write(response.content)
                response.close()
                kind = filetype.guess(tmp_path)
                if kind and kind.extension in VALID_IMAGE_EXTENSIONS:
                    final_path = os.path.join(dst_dir, "{}.{}".format(file_name, kind.extension))
                    shutil.move(tmp_path, final_path)
                    print("## OK:  {}  {}".format(os.path.basename(final_path), image_url))
                else:
                    os.remove(tmp_path)
                    print("## Err: Invalid image type  {}".format(image_url))
            except Exception:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise
            break
        except Exception as e:
            if try_times < 3:
                time.sleep(2 ** try_times)  # 2s, 4s
                continue
            if response:
                response.close()
            print("## Fail:  {}  {}".format(image_url, e.args))
            break


def download_images(image_urls, dst_dir, file_prefix="img", concurrency=10, timeout=20, proxy_type=None, proxy=None):
    """
    Download image according to given urls and automatically rename them in order.
    :param timeout:
    :param proxy:
    :param proxy_type:
    :param image_urls: list of image urls
    :param dst_dir: output the downloaded images to dst_dir
    :param file_prefix: if set to "img", files will be in format "img_xxx.jpg"
    :param concurrency: number of requests process simultaneously
    :return: none
    """

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_list = list()
        count = 0
        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir)
        for image_url in image_urls:
            file_name = file_prefix + "_" + "%04d" % count
            future_list.append(executor.submit(
                download_image, image_url, dst_dir, file_name, timeout, proxy_type, proxy))
            count += 1
        concurrent.futures.wait(future_list, timeout=180)
