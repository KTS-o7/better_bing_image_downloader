from pathlib import Path
import urllib.request
import urllib
import imghdr
import posixpath
import re
import logging
logging.basicConfig(level=logging.DEBUG)

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
    def __init__(self, query, limit, output_dir, adult, timeout, filter='', verbose=True,badsites=[], name='Image'):
        self.download_count = 0
        self.query = query
        self.output_dir = output_dir
        self.adult = adult
        self.filter = filter
        self.verbose = verbose
        self.seen = set()
        self.urls = []
        self.badsites = badsites
        self.image_name = name
        
        if self.badsites:
            logging.info("Download links will not include: %s", ', '.join(self.badsites))

        assert type(limit) == int, "limit must be integer"
        self.limit = limit
        assert type(timeout) == int, "timeout must be integer"
        self.timeout = timeout

        self.page_counter = 0
        self.headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) ' 
      'AppleWebKit/537.11 (KHTML, like Gecko) '
      'Chrome/23.0.1271.64 Safari/537.11',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
      'Accept-Encoding': 'none',
      'Accept-Language': 'en-US,en;q=0.8',
      'Connection': 'keep-alive'}


    def get_filter(self, shorthand):
        if shorthand == "line" or shorthand == "linedrawing":
            return "+filterui:photo-linedrawing"
        elif shorthand == "photo":
            return "+filterui:photo-photo"
        elif shorthand == "clipart":
            return "+filterui:photo-clipart"
        elif shorthand == "gif" or shorthand == "animatedgif":
            return "+filterui:photo-animatedgif"
        elif shorthand == "transparent":
            return "+filterui:photo-transparent"
        else:
            return ""


    def save_image(self, link, file_path) -> None:
        try:
            request = urllib.request.Request(link, None, self.headers)
            image = urllib.request.urlopen(request, timeout=self.timeout).read()
            if not imghdr.what(None, image):
                logging.error('Invalid image, not saving %s', link)
                raise ValueError('Invalid image, not saving %s' % link)
            with open(str(file_path), 'wb') as f:
                f.write(image)
        except urllib.error.HTTPError as e:
            logging.error('HTTPError while saving image %s: %s', link, e)
        except urllib.error.URLError as e:
            logging.error('URLError while saving image %s: %s', link, e)

    
    def download_image(self, link):
        self.download_count += 1
        # Get the image link
        try:
            path = urllib.parse.urlsplit(link).path
            filename = posixpath.basename(path).split('?')[0]
            file_type = filename.split(".")[-1]
            if file_type.lower() not in ["jpe", "jpeg", "jfif", "exif", "tiff", "gif", "bmp", "png", "webp", "jpg"]:
                file_type = "jpg"
                
            if self.verbose:
                # Download the image
                print("[%] Downloading Image #{} from {}".format(self.download_count, link))
                
            self.save_image(link, self.output_dir.joinpath("{}_{}.{}".format(
                self.image_name, str(self.download_count), file_type)))
            if self.verbose:
                print("[%] File Downloaded !\n")

        except Exception as e:
            self.download_count -= 1
            logging.error('Issue getting: %s\nError: %s', link, e)
    
    def run(self):
        while self.download_count < self.limit:
            if self.verbose:
                logging.info('\n\n[!]Indexing page: %d\n', self.page_counter + 1)
            # Parse the page source and download pics
            try:
                request_url = (
                    'https://www.bing.com/images/async?q=' 
                    + urllib.parse.quote_plus(self.query) 
                    + '&first=' + str(self.page_counter) 
                    + '&count=' + str(self.limit) 
                    + '&adlt=' + self.adult 
                    + '&qft=' + ('' if self.filter is None else self.get_filter(self.filter))
                )
                request = urllib.request.Request(request_url, None, headers=self.headers)
                response = urllib.request.urlopen(request)
                html = response.read().decode('utf8')
                if html ==  "":
                    logging.info("[%] No more images are available")
                    break
                links = re.findall('murl&quot;:&quot;(.*?)&quot;', html)
                if self.verbose:
                    logging.info("[%%] Indexed %d Images on Page %d.", len(links), self.page_counter + 1)
                    logging.info("\n===============================================\n")

                for link in links:
                    
                    isbadsite = False
                    for badsite in self.badsites:
                        isbadsite = badsite in link
                        if isbadsite:
                            if self.verbose:
                                logging.info("[!] Link included in badsites %s %s", badsite, link)
                                break
                    if isbadsite:
                        continue
                                
                    if self.download_count < self.limit and link not in self.seen:
                        self.seen.add(link)
                        self.download_image(link)

                self.page_counter += 1
            except urllib.error.HTTPError as e:
                logging.error('HTTPError while making request to Bing: %s', e)
            except urllib.error.URLError as e:
                logging.error('URLError while making request to Bing: %s', e)

        logging.info("\n\n[%%] Done. Downloaded %d images.", self.download_count)