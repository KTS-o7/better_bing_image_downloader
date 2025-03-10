# Better Bing Image Downloader

## Table of Contents

- [Disclaimer](#disclaimer)
- [Installation](#installation)
- [Usage](#usage)
- [License](#license)
- [Contact](#contact)

### Disclaimer<br />

This program lets you download tons of images from Bing.
Please do not download or use any image that violates its copyright terms.

![GitHub top language](https://img.shields.io/github/languages/top/KTS-o7/better_bing_image_downloader)
![GitHub](https://img.shields.io/github/license/KTS-o7/better-bing-image-downloader)
[![Hits](https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fgithub.com%2FKTS-o7%2Fbetter_bing_image_downloader&count_bg=%2379C83D&title_bg=%23555555&icon=&icon_color=%23E7E7E7&title=hits&edge_flat=false)](https://hits.seeyoufarm.com)

### Installation <br />

```bash
git clone https://github.com/KTS-o7better_bing_image_downloader
python -m venv ./env
source env/bin/activate
cd better_bing_image_downloader
pip install .
```

or

```bash
pip install better-bing-image-downloader
```

### PyPi <br />

[Package Link](https://pypi.org/project/better-bing-image-downloader/)

### Usage <br />

#### Using as a Package:

```python
from better_bing_image_downloader import downloader

downloader(query_string, limit=100, output_dir='dataset', adult_filter_off=True,
force_replace=False, timeout=60, filter="", verbose=True, badsites= [], name='Image')
```

`query_string` : String to be searched.<br />
`limit` : (optional, default is 100) Number of images to download.<br />
`output_dir` : (optional, default is 'dataset') Name of output dir.<br />
`adult_filter_off` : (optional, default is True) Enable of disable adult filteration.<br />
`force_replace` : (optional, default is False) Delete folder if present and start a fresh download.<br />
`timeout` : (optional, default is 60) timeout for connection in seconds.<br />
`filter` : (optional, default is "") filter, choose from [line, photo, clipart, gif, transparent]<br />
`verbose` : (optional, default is True) Enable downloaded message.<br />
`bad-sites` : (optional, defualt is empty list) Can limit the query to not access the bad sites.<br/>
`name` : (optional, default is 'Image') Can add a custom name for the images that are downloaded.<br/>

#### Using as a Command Line Tool:

```bash
    git clone https://github.com/KTS-o7/better_bing_image_downloader.git
    cd better_bing_image_downloader
    python -m venv ./env
    source env/bin/activate
    pip install -r requirements.txt
    cd better_bing_image_downloader
    # This is an example query
    python multidownloader.py "cool doggos" --engine "Bing"  --max-number 50 --num-threads 5 --driver "firefox_headless"
```

#### Command Line Arguments:

```bash
multidownloader.py "keywords" [-h] [--engine {Google,Bing}] [--driver {chrome_headless,chrome,api,firefox,firefox_headless}] [--max-number MAX_NUMBER] [--num-threads NUM_THREADS] [--timeout TIMEOUT] [--output OUTPUT] [--safe-mode] [--face-only] [--proxy_http PROXY_HTTP] [--proxy_socks5 PROXY_SOCKS5] [--type {clipart,linedrawing,photograph}] [--color COLOR]
```

- `"keywords"`: Keywords to search. ("in quotes")
- `-h, --help`: Show the help message and exit
- `--engine, -e`: Image search engine. Choices are "Google" and "Bing". Default is "Bing".
- `--driver, -d`: Image search engine. Choices are "chrome_headless", "chrome", "api", "firefox", "firefox_headless". Default is "firefox_headless".
- `--max-number, -n`: Max number of images download for the keywords. Default is 100.
- `--num-threads, -j`: Number of threads to concurrently download images. Default is 50.
- `--timeout, -t`: Seconds to timeout when download an image. Default is 10.
- `--output, -o`: Output directory to save downloaded images. Default is "./download_images".
- `--safe-mode, -S`: Turn on safe search mode. (Only effective in Google)
- `--face-only, -`F: Only search for faces.
- `--proxy_http, -ph`: Set http proxy (e.g. 192.168.0.2:8080)
- `--proxy_socks5, -ps`: Set socks5 proxy (e.g. 192.168.0.2:1080)
- -`-type, -ty`: What kinds of images to download. Choices are "clipart", "linedrawing", "photograph".
- `--color, -cl`: Specify the color of desired images.

```bash
# Example usage
python multidownloader.py "Cool Doggos" --engine "Google" --driver "chrome_headless" --max-number 50 --num-threads 10 --timeout 60 --output "./doggo_images" --safe-mode --proxy_http "192.168.0.2:8080" --type "photograph" --color "blue"
```

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=KTS-o7/better-bing-image-downloader&type=Date)](https://star-history.com/#KTS-o7/better-bing-image-downloader&Date)

### License

This project is licensed under the terms of the MIT license.

### Contact

If you have any questions or feedback, please contact us at [email](mailto:shentharkrishnatejaswi@gmail.com).

### Changelog

- 1.1.3:
  - Fixed issue with invalid image types. Deleted imghdr and used filetype to check image types.
