import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="better_bing_image_downloader",
    version="1.0.3",
    author="Krishnatejaswi S",
    author_email="shentharkrishnatejaswi@gmail.com",
    description="This package is built on top of bing-image-downloader by gaurav singh",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/KTS-o7/better_bing_image_downloader",
    keywords=['bing', 'images', 'scraping', 'image download', 'bulk image downloader',],
    packages=['better_bing_image_downloader'],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
   
)