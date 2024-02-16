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

### License

This project is licensed under the terms of the MIT license.

### Contact

If you have any questions or feedback, please contact us at [email](mailto:shentharkrishnatejaswi@gmail.com).
