import shutil
import argparse
import logging
from importlib.metadata import version as pkg_version, PackageNotFoundError
from pathlib import Path
from .bing import Bing
from tqdm import tqdm


def downloader(
    query: str,
    limit: int = 100,
    output_dir: str = 'dataset',
    adult_filter_off: bool = True,
    force_replace: bool = False,
    timeout: int = 60,
    image_filter: str = "",
    verbose: bool = True,
    badsites: list = None,  # type: ignore[assignment]
    name: str = 'Image',
    max_workers: int = 4,
    **kwargs  # backward compat
) -> int:
    """
    Download images using the Bing image scraper.
    
    Parameters:
    query (str): The search query.
    limit (int): The maximum number of images to download.
    output_dir (str): The directory to save the images in.
    adult_filter_off (bool): Whether to turn off the adult filter.
    force_replace (bool): Whether to replace existing files.
    timeout (int): The timeout for the image download.
    image_filter (str): The filter to apply to the search results.
    verbose (bool): Whether to print detailed output.
    badsites (list): List of bad sites to be excluded.
    name (str): The name of the images.
    max_workers (int): Maximum number of parallel download workers (default: 4).
    """
    # Backward compatibility: accept old 'filter' keyword arg
    if 'filter' in kwargs:
        import warnings
        warnings.warn(
            "The 'filter' parameter is deprecated, use 'image_filter' instead.",
            DeprecationWarning,
            stacklevel=2
        )
        image_filter = kwargs.pop('filter')

    # Set adult filter setting
    adult = 'off' if adult_filter_off else 'on'

    # Resolve mutable default
    badsites = badsites or []

    # Create output directory path
    image_dir = Path(output_dir) / query
    
    # Handle directory replacement if requested
    if force_replace and image_dir.exists():
        shutil.rmtree(image_dir)
    
    # Create directory if it doesn't exist
    try:
        image_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(f'Failed to create directory {image_dir}: {e}') from e
        
    logging.info("Downloading Images to %s", image_dir)

    # Initialize and configure progress bar
    with tqdm(total=limit, unit='img', ncols=100, colour="green", 
             bar_format='{l_bar}{bar} {n_fmt}/{total_fmt} imgs | Speed: {rate_fmt} | ETA: {remaining}') as pbar:
        
        # Define callback for progress updates
        def update_progress_bar(download_count):
            pbar.n = download_count
            pbar.refresh()

        # Initialize and run Bing downloader with parallel processing
        bing = Bing(
            query=query, 
            limit=limit, 
            output_dir=image_dir, 
            adult=adult, 
            timeout=timeout, 
            filter=image_filter, 
            verbose=verbose, 
            badsites=badsites, 
            name=name,
            max_workers=max_workers
        )
        # Type annotation is ignored in runtime
        bing.download_callback = update_progress_bar  # type: ignore
        bing.run()

    return bing.download_count


def main():
    """Entry point for the 'bbid' CLI command."""
    parser = argparse.ArgumentParser(description='Download images using Bing.')
    try:
        _version = pkg_version("better-bing-image-downloader")
    except PackageNotFoundError:
        _version = "unknown"
    parser.add_argument('--version', action='version', version=f'%(prog)s {_version}')
    parser.add_argument('query', type=str, help='The search query.')
    parser.add_argument('-l', '--limit', type=int, default=100, help='The maximum number of images to download.')
    parser.add_argument('-d', '--output_dir', type=str, default='dataset', help='The directory to save the images in.')
    parser.add_argument('-a', '--adult_filter_off', action='store_true', help='Whether to turn off the adult filter.')
    parser.add_argument('-F', '--force_replace', action='store_true', help='Whether to replace existing files.')
    parser.add_argument('-t', '--timeout', type=int, default=60, help='The timeout for the image download.')
    parser.add_argument('-f', '--filter', type=str, default="", dest='image_filter', help='The filter to apply to the search results.')
    parser.add_argument('-v', '--verbose', action='store_true', help='Whether to print detailed output.')
    parser.add_argument('-b', '--bad-sites', nargs='*', default=[], help='List of bad sites to be excluded.')
    parser.add_argument('-n', '--name', type=str, default='Image', help='The name of the images.')
    parser.add_argument('-w', '--workers', type=int, default=4, help='Maximum number of parallel download workers.')

    args = parser.parse_args()
    logging_level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(level=logging_level, format='%(levelname)s: %(message)s')

    downloader(
        args.query,
        args.limit,
        args.output_dir,
        args.adult_filter_off,
        args.force_replace,
        args.timeout,
        args.image_filter,
        args.verbose,
        args.bad_sites,
        args.name,
        args.workers
    )


if __name__ == '__main__':
    main()
