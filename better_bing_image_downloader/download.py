from distutils import extension
import os, sys
import shutil
from pathlib import Path
import argparse
import logging

try:
    from bing import Bing
except ImportError:  # Python 3
    from .bing import Bing

def download(query, limit=100, output_dir='dataset', adult_filter_off=True, 
force_replace=False, timeout=60, filter="", verbose=True, badsites= [], name='Image'):
    """
    Download images using the Bing image scraper.
    
    Parameters:
    query (str): The search query.
    limit (int): The maximum number of images to download.
    output_dir (str): The directory to save the images in.
    adult_filter_off (bool): Whether to turn off the adult filter.
    force_replace (bool): Whether to replace existing files.
    timeout (int): The timeout for the image download.
    filter (str): The filter to apply to the search results.
    verbose (bool): Whether to print detailed output._summary_
    badsites (list): List of bad sites to be excluded.
    name (str): The name of the images.
    """
    # engine = 'bing'
    if adult_filter_off:
        adult = 'off'
    else:
        adult = 'on'

    image_dir = Path(output_dir).joinpath(query).absolute()

    if force_replace:
        if Path.is_dir(image_dir):
            shutil.rmtree(image_dir)

    # check directory and create if necessary
    try:
        if not Path.is_dir(image_dir):
            Path.mkdir(image_dir, parents=True)
    except Exception as e:
        logging.error('Failed to create directory. %s', e)
        sys.exit(1)
        
    logging.info("Downloading Images to %s", str(image_dir.absolute()))
    bing = Bing(query, limit, image_dir, adult, timeout, filter, verbose, badsites, name)
    bing.run()
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download images using Bing.')
    parser.add_argument('query', type=str, help='The search query.')
    parser.add_argument('-l','--limit', type=int, default=100, help='The maximum number of images to download.')
    parser.add_argument('-d','--output_dir', type=str, default='dataset', help='The directory to save the images in.')
    parser.add_argument('-a','--adult_filter_off', action='store_true', help='Whether to turn off the adult filter.')
    parser.add_argument('-F','--force_replace', action='store_true', help='Whether to replace existing files.')
    parser.add_argument('-t','--timeout', type=int, default=60, help='The timeout for the image download.')
    parser.add_argument('-f','--filter', type=str, default="", help='The filter to apply to the search results.')
    parser.add_argument('-v','--verbose', action='store_true', help='Whether to print detailed output.')
    parser.add_argument('-b','--bad-sites', nargs='*', default=[], help='List of bad sites to be excluded.')
    parser.add_argument('-n', '--name', type=str, default='Image', help='The name of the images.')
    args = parser.parse_args()
    
    download(args.query, args.limit, args.output_dir, args.adult_filter_off, 
    args.force_replace, args.timeout, args.filter, args.verbose, args.bad_sites, args.name)
