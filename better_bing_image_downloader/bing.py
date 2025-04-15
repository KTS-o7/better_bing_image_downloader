from pathlib import Path
import urllib.request
import urllib
import posixpath
import re
import logging
from tqdm import tqdm
import filetype
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

'''

Python api to download image form Bing.
Origina Author: Guru Prasad (g.gaurav541@gmail.com)
Improved Author: Krishnatejaswi S (shentharkrishnatejaswi@gmail.com) 

'''


class Bing:
    """_summary_
    A class to download images from Bing.
    
    _description_
    This class is used to download images from Bing. It uses the Bing Image Search API to get the links of the images and then downloads the images from the links. The class can be used to download images based on a query, with a limit on the number of images to be downloaded. The images can be filtered based on the type of image (photo, clipart, line drawing, animated gif, transparent) and the adult content can be filtered as well. The images are saved in the specified output directory. The class also has the option to be verbose, which will print the progress of the download.
    
    _parameters_
    
    query : str
        The query to be used to search for images.
    limit : int
        The number of images to be downloaded.
    output_dir : str
        The directory where the images are to be saved.
    adult : str
        The adult content filter. Can be "off" or "on".
    timeout : int
        The time in seconds to wait for the request to Bing to be completed.
    filter : str
        The type of image to be filtered. Can be "line", "photo", "clipart", "gif", "transparent".
    verbose : bool
        Whether to print the progress of the download.
    badsites : list
        List of websites to exclude from the search results.
    name : str
        Base name for the downloaded images.
    max_workers : int
        Maximum number of parallel download workers.
        
    _methods_
    
    get_filter(shorthand)
        Returns the filter string based on the shorthand.
        ============
        shorthand : str
            The shorthand for the filter. Can be "line", "photo", "clipart", "gif", "transparent".
        ============
        return : str
            The filter string based on the shorthand.
            
    save_image(link, file_path)
        Saves the image from the link to the file path.
        ============
        link : str
            The link of the image to be saved.
        file_path : str
            The file path where the image is to be saved.
        ============
        return : None
        
    download_image(link)
        Downloads the image from the link.
        ============
        link : str
            The link of the image to be downloaded.
        ============
        return : None
    run()
        Runs the download of the images.
        ============
        return : None
        
    """
    def __init__(self, query, limit, output_dir, adult, timeout, filter='', verbose=True, badsites=[], name='Image', max_workers=4):
        assert isinstance(limit, int), "limit must be integer"
        assert isinstance(timeout, int), "timeout must be integer"
        assert isinstance(max_workers, int), "max_workers must be integer"
        
        self.query = query
        self.limit = limit
        self.output_dir = Path(output_dir)
        self.adult = adult
        self.filter = filter
        self.verbose = verbose
        self.badsites = set(badsites)
        self.image_name = name
        self.timeout = timeout
        self.max_workers = max(1, min(max_workers, 16))  # Limit between 1 and 16
        
        self.seen = set()
        self.download_count = 0
        self.download_callback = None
        
        # Standard headers for HTTP requests
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
            'Accept-Encoding': 'none',
            'Accept-Language': 'en-US,en;q=0.8',
            'Connection': 'keep-alive'
        }
        
        # Ensure the output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        if self.badsites and self.verbose:
            logging.info("Download links will not include: %s", ', '.join(self.badsites))

    def get_filter(self, shorthand):
        """Convert filter shorthand to Bing filter parameter"""
        filters = {
            "line": "+filterui:photo-linedrawing",
            "linedrawing": "+filterui:photo-linedrawing",
            "photo": "+filterui:photo-photo",
            "clipart": "+filterui:photo-clipart",
            "gif": "+filterui:photo-animatedgif",
            "animatedgif": "+filterui:photo-animatedgif",
            "transparent": "+filterui:photo-transparent"
        }
        return filters.get(shorthand, "")

    def save_image(self, link, file_path):
        """Save image from link to file path"""
        try:
            request = urllib.request.Request(link, None, self.headers)
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                image = response.read()
            
            kind = filetype.guess(image)
            if not kind or not kind.mime.startswith('image/'):
                logging.error('Invalid image, not saving %s', link)
                return False
                
            file_path.write_bytes(image)
            return True
            
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            logging.error('Network error while saving image %s: %s', link, e)
            return False
        except Exception as e:
            logging.error('Unexpected error while saving image %s: %s', link, e)
            return False

    def download_image(self, link, index):
        """Download and save an image from the given link"""
        try:
            # Extract file extension from URL or default to jpg
            path = urllib.parse.urlsplit(link).path
            filename = posixpath.basename(path).split('?')[0]
            file_type = filename.split(".")[-1].lower()
            
            valid_extensions = {"jpe", "jpeg", "jfif", "exif", "tiff", "gif", "bmp", "png", "webp", "jpg"}
            if file_type not in valid_extensions:
                file_type = "jpg"
                
            # Create output filename
            file_path = self.output_dir / f"{self.image_name}_{index}.{file_type}"
            
            if self.verbose:
                print(f"[%] Downloading Image #{index} from {link}")
                
            if self.save_image(link, file_path):
                if self.verbose:
                    print(f"[%] File #{index} Downloaded!\n")
                return index
            return None
                
        except Exception as e:
            logging.error('Issue getting image %s: %s', link, e)
            return None

    def download_images_parallel(self, links):
        """Download images in parallel using ThreadPoolExecutor"""
        total_before = self.download_count
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            futures = [executor.submit(self.download_image, link, i) 
                       for i, link in enumerate(links, self.download_count + 1)]
            
            # Process each future as it completes
            for future in as_completed(futures):
                try:
                    if future.result() is not None:
                        self.download_count += 1
                        # Update progress bar with current count
                        if self.download_callback:
                            self.download_callback(self.download_count)
                except Exception as e:
                    logging.error(f"Error processing download: {e}")
                
        return self.download_count - total_before

    def run(self):
        """Run the image download process"""
        page_counter = 0
        while self.download_count < self.limit:
            if self.verbose:
                logging.info('\n\n[!]Indexing page: %d\n', page_counter + 1)
                
            # Parse the page source and download pics
            try:
                # Bing API page size is fixed at 35
                page_size = 35
                request_url = (
                    'https://www.bing.com/images/async?q='
                    + urllib.parse.quote_plus(self.query)
                    + '&first=' + str(page_counter * page_size)
                    + '&count=' + str(page_size)
                    + '&adlt=' + self.adult
                    + '&qft=' + ('' if self.filter is None else self.get_filter(self.filter))
                )
                
                request = urllib.request.Request(request_url, None, headers=self.headers)
                with urllib.request.urlopen(request) as response:
                    html = response.read().decode('utf8')
                
                if not html:
                    logging.info("[%] No more images are available")
                    break
                    
                links = re.findall('murl&quot;:&quot;(.*?)&quot;', html)
                
                if self.verbose:
                    logging.info("[%%] Indexed %d Images on Page %d.", len(links), page_counter + 1)
                    logging.info("\n===============================================\n")

                # Filter links - remove bad sites and already seen links
                filtered_links = [
                    link for link in links 
                    if link not in self.seen and not any(badsite in link for badsite in self.badsites)
                ]
                
                if not filtered_links:
                    logging.info("[%] No new images are available")
                    break
                    
                # Add all links to seen set to avoid duplicates
                self.seen.update(filtered_links)
                
                # Calculate how many more images we need to download
                remaining = self.limit - self.download_count
                links_to_download = filtered_links[:remaining]
                
                # Download images in parallel
                if self.max_workers > 1:
                    downloaded = self.download_images_parallel(links_to_download)
                    if downloaded == 0:
                        logging.warning("No images could be downloaded from this page")
                else:
                    # Sequential download if max_workers=1
                    for link in links_to_download:
                        if self.download_count >= self.limit:
                            break
                        if self.download_image(link, self.download_count + 1) is not None:
                            self.download_count += 1
                            # Update progress bar
                            if self.download_callback:
                                self.download_callback(self.download_count)

                # Check if we've reached the download limit
                if self.download_count >= self.limit:
                    break

                page_counter += 1
                
            except (urllib.error.HTTPError, urllib.error.URLError) as e:
                logging.error('Network error while requesting from Bing: %s', e)
                # Wait a moment before retrying
                time.sleep(2)
            except Exception as e:
                logging.error('Unexpected error while requesting from Bing: %s', e)
                break

        logging.info("\n\n[%%] Done. Downloaded %d images.", self.download_count)