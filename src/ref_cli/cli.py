#!/usr/bin/env python3
"""
CLI tool for recording and managing URL references.
Author: draeician (July 22, 2023)
Purpose: To allow for fast CLI recording from the command line for later reference
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse, parse_qs, quote
import os
import re
import sys
import argparse
import warnings
import logging
import yaml
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv, set_key
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import subprocess
import time
import select
from urllib3.exceptions import InsecureRequestWarning
import importlib.resources
from ref_cli import __version__
from colorama import init
from ref_cli.utils.colors import success, error, warning, info, url, title, highlight, dim

# Initialize colorama
init()

# Configuration and setup
def get_default_config():
    """Load the default configuration from the package."""
    try:
        with importlib.resources.files('ref_cli').joinpath('config/default_config.yaml').open('r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logging.error(f"Error loading default config: {e}")
        return {
            'paths': {
                'references': '~/references',
                'transcripts': '~/references/transcripts'
            },
            'removable_keys': [
                'utm_source', 'utm_medium', 'utm_campaign', 
                'utm_term', 'utm_content', 'fbclid', 'gclid',
                '_ga', 'gi', 'ref', 'source', 'medium', 
                'campaign', 'feature', 'share', 'src'
            ]
        }

# Define the directory where you want the logs to be stored
log_directory = os.path.expanduser("~/references/logs")
os.makedirs(log_directory, exist_ok=True)

# Define the log file paths
log_file_path = os.path.join(log_directory, "ref.log")
error_log_file_path = os.path.join(log_directory, "ref_errors.log")

# Logging configuration
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s:%(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)

# Create a separate logger for errors
error_logger = logging.getLogger('error_logger')
error_logger.setLevel(logging.ERROR)
error_file_handler = logging.FileHandler(error_log_file_path)
error_file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s:%(message)s'))
error_logger.addHandler(error_file_handler)

# Filter out warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="urllib3")

# Set environment path and load configuration
env_path = os.path.join(os.path.expanduser("~"), '.env')
load_dotenv(dotenv_path=env_path)

# YouTube API details
YOUTUBE_API_SERVICE_NAME = 'youtube'
YOUTUBE_API_VERSION = 'v3'
DEVELOPER_KEY = os.getenv('YOUTUBE_API_KEY')

# Load configuration
CONFIG_DIR = os.path.join(os.path.expanduser("~"), '.config', 'ref')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.yaml')

config = get_default_config()
BASE = os.path.expanduser(config['paths']['references'])
UNIFIED = os.path.join(BASE, "references.md")
TRANSCRIPTS_DIR = os.path.expanduser(config['paths']['transcripts'])

# Copy all functions from original file
def ensure_config_exists():
    """Ensures that the configuration directory and file exist."""
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w') as file:
            yaml.dump(get_default_config(), file)

def load_config() -> dict:
    """Loads the configuration from the YAML file."""
    ensure_config_exists()
    with open(CONFIG_FILE, 'r') as file:
        config = yaml.safe_load(file)
    return config

# Copy all the remaining functions from the original file here
def simplify_url(url: str) -> str:
    """
    Simplifies the URL by removing tracking parameters and normalizing the format.
    
    Args:
        url (str): The URL to simplify
        
    Returns:
        str: The simplified URL
    """
    # Additional parameters to remove
    removable_keys = set(config['removable_keys'] + [
        'gi',  # GitConnected parameter
        'ref',  # Common referral parameter
        'source',  # Source tracking
        'medium',  # Medium tracking
        'campaign',  # Campaign tracking
        'feature',  # Feature tracking
        'share',  # Share tracking
        'src',  # Source tracking alternative
    ])
    
    parsed_url = urlparse(url)
    
    # Parse query parameters
    query_params = parse_qs(parsed_url.query)
    
    # Remove tracking parameters
    filtered_query_params = {k: v for k, v in query_params.items() if k.lower() not in removable_keys}
    
    # Sort parameters for consistent ordering
    sorted_params = sorted(filtered_query_params.items())
    
    # Rebuild query string
    simplified_query = '&'.join([f"{k}={v[0]}" for k, v in sorted_params])
    
    # Remove trailing slashes and normalize
    path = re.sub(r'/+$', '', parsed_url.path)
    
    # Rebuild URL with normalized components
    simplified_url = urlunparse((
        parsed_url.scheme,
        parsed_url.netloc.lower(),
        path,
        parsed_url.params,
        simplified_query,
        None  # Remove fragments
    ))
    
    logging.debug(f"Simplified URL: {simplified_url}")
    return simplified_url

def resolve_redirect(url: str) -> str:
    """
    Resolves the final URL after following any redirects. Specifically handles YouTube redirect URLs
    and authentication redirects. Includes better handling for Medium/GitConnected rate limiting.

    Args:
        url (str): The original URL to resolve.

    Returns:
        str: The final URL after following redirects, or the original URL if redirected to authentication.
    """
    # List of common authentication/login URL patterns
    auth_patterns = [
        r'/auth/login',
        r'/login',
        r'/signin',
        r'/authenticate',
        r'/oauth',
        r'/auth/oauth',
        r'/auth/signin',
        r'/auth/authenticate',
        r'/m/global-identity',  # Medium auth pattern
    ]
    
    # Special handling for Medium/GitConnected URLs that are known to cause issues
    medium_patterns = [
        r'levelup\.gitconnected\.com',
        r'medium\.com',
        r'towardsdatascience\.com',
        r'betterprogramming\.pub',
    ]
    
    # Check if this is a known problematic Medium URL
    if any(re.search(pattern, url) for pattern in medium_patterns):
        logging.debug(f"Detected Medium-based URL, using original URL to avoid rate limiting: {url}")
        return url
    
    youtube_redirect_pattern = re.compile(r'https://www\.youtube\.com/redirect\?')
    if youtube_redirect_pattern.match(url):
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        if 'q' in query_params:
            return query_params['q'][0]
    
    session = requests.Session()
    retry_strategy = Retry(
        total=2,  # Reduced retries to avoid excessive requests
        backoff_factor=2,  # Increased backoff factor for rate limiting
        status_forcelist=[500, 502, 503, 504],  # Removed 429 from forcelist to handle separately
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', InsecureRequestWarning)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
            }
            response = session.get(url, 
                                allow_redirects=True, 
                                verify=False, 
                                timeout=15,  # Increased timeout
                                headers=headers)
            
            # Check if we got a 429 response
            if response.status_code == 429:
                logging.warning(f"Rate limited (429) for URL: {url}, using original URL")
                return url
            
            # Check if the final URL is an authentication page
            final_url = response.url
            if any(re.search(pattern, final_url) for pattern in auth_patterns):
                logging.debug(f"Authentication redirect detected, keeping original URL: {url}")
                return url
                
            # If we got redirected to the homepage, return the original URL
            if response.url == "https://www.msn.com/" and url != "https://www.msn.com/":
                logging.debug(f"Prevented incorrect redirect to homepage, keeping original URL: {url}")
                return url
                
            return response.url
        except requests.exceptions.RequestException as e:
            # Check if it's specifically a 429 error
            if "429" in str(e) or "too many 429 error responses" in str(e).lower():
                logging.warning(f"Rate limited for URL: {url}, using original URL")
                return url
            else:
                logging.error(f"Error resolving redirect for URL: {url}, error: {e}")
                return url

def get_title_from_url(url: str) -> str:
    """
    Fetches the title of a webpage given its URL by dumping HTML with lynx and parsing it.

    Args:
        url (str): The URL of the webpage.

    Returns:
        str: The title of the webpage, or an error message if the title cannot be fetched.
    """
    # Check if lynx is installed
    try:
        subprocess.run(['which', 'lynx'], capture_output=True, check=True)
    except subprocess.CalledProcessError:
        error_msg = "Error: 'lynx' is not installed. Please install it to fetch webpage titles."
        logging.error(error_msg)
        return error_msg

    lynx_command = f'lynx -dump -nolist -force_html -hiddenlinks=ignore -display_charset=UTF-8 -assume_charset=UTF-8 -pseudo_inlines -dont_wrap_pre -source "{url}"'

    try:
        result = subprocess.run(lynx_command, shell=True, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logging.error(f"Lynx command failed with return code {result.returncode}")
            return f"Error: Lynx command failed with return code {result.returncode}"

        soup = BeautifulSoup(result.stdout, 'html.parser')

        title = None

        # Try different title sources based on the website
        if "rumble.com" in url:
            # For Rumble, try to get the video title from meta tags
            og_title = soup.find('meta', property='og:title')
            if og_title:
                title = og_title.get('content', '').strip()
            if not title:
                # Fallback to h1 tag which often contains the video title on Rumble
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text().strip()
        else:
            # For other sites, try the standard title sources
            if soup.title:
                title = soup.title.string.strip()
            if not title:
                og_title = soup.find('meta', {'property': 'og:title'})
                if og_title:
                    title = og_title.get('content', '').strip()
            if not title:
                twitter_title = soup.find('meta', {'name': 'twitter:title'})
                if twitter_title:
                    title = twitter_title.get('content', '').strip()
            if not title:
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text().strip()

        if title:
            logging.info(f"Title found: {title}")
            return title
        else:
            logging.warning("No suitable title found in the HTML content")
            return "No title found"

    except subprocess.TimeoutExpired:
        logging.error("Lynx command timed out")
        return "Error: Request timed out"
    except subprocess.SubprocessError as e:
        logging.error(f"Subprocess error occurred: {e}")
        return f"Error: Subprocess error - {e}"
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return f"Error: Unexpected error - {e}"

def check_integrity():
    """
    Checks the integrity of the 'references.md' file to ensure that each line follows the expected format.
    
    Returns:
        list: A list of tuples containing details of lines that do not match the expected format.
    """
    errors = []
    with open(UNIFIED, "r") as file:
        for line_number, line in enumerate(file, start=1):
            if not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\|\[.*\]\(.*\)\|\(.*\)\|.*\|(YouTube|General)\n$', line):
                expected_line = f'{datetime.now().isoformat()}|[URL]|(Title)|Source|(YouTube|General)'
                errors.append((f"references.md", line_number, line.strip(), expected_line))
    return errors

def set_developer_key():
    """Prompts the user to enter their YouTube API key and sets it in the environment variables."""
    key = input("Please enter your YOUTUBE_API_KEY: ")
    os.environ['YOUTUBE_API_KEY'] = key
    set_key(env_path, 'YOUTUBE_API_KEY', key)
    print("YOUTUBE_API_KEY set successfully!")

def get_youtube_data(url: str) -> tuple:
    """
    Fetches YouTube video or playlist data using the YouTube Data API.

    Args:
        url (str): The YouTube URL to fetch data for.

    Returns:
        tuple: Video ID, title, and channel title for a single video.
        tuple: Playlist title, uploader, and list of video details for a playlist.

    Raises:
        ValueError: If the YouTube URL is invalid.
    """
    youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=DEVELOPER_KEY)
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    
    if 'list' in query_params:
        return get_youtube_playlist_data(query_params['list'][0], youtube)
    
    video_id = query_params.get('v')
    if not video_id:
        shorts_match = re.match(r'/shorts/([^/?]+)', parsed_url.path)
        if shorts_match:
            video_id = shorts_match.group(1)
        else:
            live_match = re.match(r'/live/([^/?]+)', parsed_url.path)
            if live_match:
                video_id = live_match.group(1)
            else:
                raise ValueError("Invalid YouTube URL")
    
    if isinstance(video_id, list):
        video_id = video_id[0]
    video_response = youtube.videos().list(part='snippet', id=video_id).execute()
    items = video_response.get('items', [])
    if not items:
        raise ValueError(f"No video found for id '{video_id}'")
    video_data = items[0]['snippet']
    return video_id, video_data['title'], video_data['channelTitle']

def get_youtube_playlist_data(playlist_id: str, youtube) -> tuple:
    """
    Fetches YouTube playlist data using the YouTube Data API.

    Args:
        playlist_id (str): The YouTube playlist ID.
        youtube: The YouTube API client.

    Returns:
        tuple: A tuple containing the playlist title, uploader, and a list of tuples for each video in the playlist.
               Each video tuple contains video ID, title, and uploader.
    """
    # Get playlist metadata
    playlist_response = youtube.playlists().list(part='snippet', id=playlist_id).execute()
    if not playlist_response['items']:
        raise ValueError("Invalid YouTube Playlist ID")

    playlist_snippet = playlist_response['items'][0]['snippet']
    playlist_title = playlist_snippet['title']
    playlist_uploader = playlist_snippet['channelTitle']

    # Get videos in the playlist
    video_details = []
    next_page_token = None
    while True:
        playlist_items_response = youtube.playlistItems().list(
            part='snippet',
            maxResults=50,
            playlistId=playlist_id,
            pageToken=next_page_token
        ).execute()
        for item in playlist_items_response['items']:
            video_id = item['snippet']['resourceId']['videoId']
            title = item['snippet']['title']
            uploader = item['snippet']['channelTitle']
            video_details.append((video_id, title, uploader))
        next_page_token = playlist_items_response.get('nextPageToken')
        if not next_page_token:
            break

    return playlist_title, playlist_uploader, video_details

def ensure_path_exists(file_path: str):
    """
    Ensures that the directory and file specified by `file_path` exist. Creates them if they do not exist.
    
    Args:
        file_path (str): The path to the file to ensure existence.
    """
    directory = os.path.dirname(file_path)
    if not os.path.exists(directory):
        os.makedirs(directory)
    if not os.path.exists(file_path):
        open(file_path, 'w').close()

def append_to_file(file_path: str, line: str) -> None:
    """
    Appends a line to the specified file, ensuring the path exists.
    
    Args:
        file_path (str): The path to the file.
        line (str): The line to append to the file.
    """
    ensure_path_exists(file_path)
    with open(file_path, "a") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())

def search_entries(search_term: str, search_field: str, file_path: str) -> dict:
    """
    Searches for entries in a file based on a specified search term and field.

    Args:
        search_term (str): The term to search for within the specified field.
        search_field (str): The field to search within. Valid options are "url", "title", "date", "source", and "uploader".
        file_path (str): The path to the file where the search will be conducted.

    Returns:
        dict: A dictionary where keys are lines from the file that match the search criteria and values are lists of hit types.
    """
    results = {}
    search_term_lower = search_term.lower()

    with open(file_path, "r") as file:
        for line in file:
            fields = line.split('|')
            if len(fields) < 5:
                logging.warning(f"Line does not have the expected number of fields: {line.strip()}")
                continue

            hit_types = []
            if search_field == "url" and search_term_lower in fields[1].lower():
                hit_types.append("Url")
            elif search_field == "title" and search_term_lower in fields[2].lower():
                hit_types.append("Title")
            elif search_field == "date" and search_term_lower in fields[0].lower():
                hit_types.append("Date")
            elif search_field == "source" and search_term_lower in fields[4].lower():
                hit_types.append("Source")
            elif search_field == "uploader" and search_term_lower in fields[3].lower():
                hit_types.append("Uploader")

            if hit_types:
                if line not in results:
                    results[line] = hit_types
                else:
                    results[line].extend(hit_types)

    return results

def update_transcript(video_url: str) -> None:
    """
    Updates the transcript for an existing YouTube entry in the references.md file.

    Args:
        video_url (str): The URL of the YouTube video to update.
    """
    with open(UNIFIED, 'r') as file:
        lines = file.readlines()

    updated = False
    with open(UNIFIED, 'w') as file:
        for line in lines:
            if video_url in line and line.strip().endswith("|None"):
                video_id = re.search(r'v=([^&]+)', video_url).group(1)
                print(info(f"Fetching transcript for: {url(video_url)}"))
                transcript_file = fetch_youtube_transcript(video_id)
                if transcript_file:
                    line = line.replace("|None", f"|{transcript_file}")
                    updated = True
                    logging.info(f"Transcript updated for URL: {video_url}")
                else:
                    print(warning(f"Failed to fetch transcript for: {url(video_url)}"))
            file.write(line)

    if updated:
        print(success(f"Transcript for {url(video_url)} has been updated."))
    else:
        print(warning(f"No matching entry found for {url(video_url)} or transcript already exists."))

def parse_arguments() -> argparse.Namespace:
    """
    Parses command-line arguments and returns the parsed arguments as a Namespace object.

    Returns:
        argparse.Namespace: The parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Add or search URL entries in markdown files.")
    parser.add_argument("url", nargs='?', default=None, help="URL to be added.")
    parser.add_argument("-f", "--force", action="store_true", help="Force addition even if URL already exists.")
    parser.add_argument("-e", "--edit", action="store_true", help="Open markdown file for editing.")
    parser.add_argument("-d", "--debug", type=int, choices=[1, 2, 3], help="Set the debug level: 1 for INFO, 2 for WARNING, 3 for DEBUG.")
    parser.add_argument("--integrity", action="store_true", help="Check the integrity of log files.")
    parser.add_argument("-b", "--backup", action="store_true", help="Create a backup of the references.md file.")
    parser.add_argument("--search-url", help="Search entries by URL.")
    parser.add_argument("--search-title", help="Search entries by title.")
    parser.add_argument("--search-date", help="Search entries by date.")
    parser.add_argument("--search-source", help="Search entries by source.")
    parser.add_argument("--search-uploader", help="Search entries by uploader.")
    parser.add_argument("--search", help="Search entries across all fields (URL, title, date, source, uploader).")
    parser.add_argument("--transcript", action="store_true", help="Update the transcript for an existing YouTube entry.")
    parser.add_argument("--file", help="Read URLs from a file (one URL per line)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()
    if args.edit:
        os.system(f"vim {UNIFIED}")
        sys.exit()
    # No manual escaping is necessary; the URL arrives as a single argument
    # and should be preserved exactly for later processing.
    return args

def url_exists_in_file(url: str, file_path: str) -> bool:
    """
    Checks if a URL already exists in the specified file.
    Compares simplified versions of URLs to catch duplicates with different parameters.
    
    Args:
        url (str): The URL to check
        file_path (str): The path to the file
    
    Returns:
        bool: True if the URL exists in the file, False otherwise
    """
    simplified_input_url = simplify_url(url)
    
    with open(file_path, "r") as f:
        for line in f:
            match = re.search(r'\[([^\]]+)\]', line)
            if match:
                existing_url = match.group(1)
                simplified_existing_url = simplify_url(existing_url)
                if simplified_input_url == simplified_existing_url:
                    return True
    return False

def read_urls_from_file(file_path: str, force: bool = False) -> None:
    """
    Reads URLs from a file and processes each one sequentially.
    Comments out successfully processed URLs in the original file.
    
    Args:
        file_path (str): Path to the file containing URLs (one per line)
        force (bool): Whether to force processing even if URL exists
    """
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()

        modified_lines = []
        for line_number, line in enumerate(lines, 1):
            original_line = line
            url = line.strip()
            
            if not url or url.startswith('#'):
                modified_lines.append(original_line)
                continue

            print(f"\nProcessing URL {line_number}: {url}")
            try:
                process_url(url, force)
                modified_lines.append(f"# {original_line}")
                print(f"Successfully processed and commented out: {url}")
            except Exception as e:
                modified_lines.append(original_line)
                print(f"Error processing URL on line {line_number}: {e}")
                logging.error(f"Error processing URL '{url}' on line {line_number}: {e}")
            
            time.sleep(1)

        with open(file_path, 'w') as file:
            file.writelines(modified_lines)

        print("\nFinished processing all URLs from file.")
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found")
        logging.error(f"File not found: {file_path}")
    except Exception as e:
        print(f"Error reading file: {e}")
        logging.error(f"Error reading file {file_path}: {e}")

def fetch_youtube_transcript(video_id: str) -> str:
    """
    Fetches the transcript for a given YouTube or Rumble video ID and saves it in the transcript directory.

    Args:
        video_id (str): The YouTube or Rumble video ID or URL.

    Returns:
        str: The path to the saved transcript file.
    """
    # Ensure the transcripts directory exists
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    
    # Determine if this is a Rumble URL
    is_rumble = "rumble.com" in video_id
    
    # Extract the video ID based on the platform
    if is_rumble:
        # Extract the video ID from the Rumble URL
        match = re.search(r'rumble\.com/([^/?]+)', video_id)
        if match:
            video_id = match.group(1)
        else:
            logging.error(f"Could not extract video ID from Rumble URL: {video_id}")
            return None
    else:
        # For YouTube, extract the video ID if it's a full URL
        if "youtube.com" in video_id:
            match = re.search(r'v=([^&]+)', video_id)
            if match:
                video_id = match.group(1)
    
    safe_video_id = re.sub(r'[^\w\-_.]', '_', video_id)
    base_transcript_file = os.path.join(TRANSCRIPTS_DIR, safe_video_id)
    
    if is_rumble:
        # For Rumble, we need to ensure the URL is properly formatted
        rumble_url = f"https://rumble.com/{video_id}"
        
        # First, check video info
        info_command = [
            "yt-dlp",
            "--dump-json",
            rumble_url
        ]
        
        try:
            # Get video info
            result = subprocess.run(info_command, check=True, capture_output=True, text=True)
            logging.info(f"Video info:\n{result.stdout}")
            
            # Try to download subtitles with different approaches
            approaches = [
                # Try with auto-generated subtitles
                [
                    "yt-dlp",
                    "--skip-download",
                    "--write-auto-subs",
                    "--sub-lang", "en",
                    "--sub-format", "vtt",
                    "--output", f"{base_transcript_file}.%(ext)s",
                    rumble_url
                ],
                # Try with manual subtitles
                [
                    "yt-dlp",
                    "--skip-download",
                    "--write-subs",
                    "--sub-lang", "en",
                    "--sub-format", "vtt",
                    "--output", f"{base_transcript_file}.%(ext)s",
                    rumble_url
                ],
                # Try with all available subtitles
                [
                    "yt-dlp",
                    "--skip-download",
                    "--write-subs",
                    "--write-auto-subs",
                    "--all-subs",
                    "--sub-format", "vtt",
                    "--output", f"{base_transcript_file}.%(ext)s",
                    rumble_url
                ]
            ]
            
            for approach in approaches:
                try:
                    result = subprocess.run(approach, check=True, capture_output=True, text=True)
                    logging.info(f"yt-dlp output:\n{result.stdout}")
                    logging.info(f"yt-dlp error output:\n{result.stderr}")
                    
                    # Check for any subtitle files that might have been created
                    for ext in ['.en-auto.vtt', '.en.vtt', '.vtt']:
                        transcript_file = f"{base_transcript_file}{ext}"
                        if os.path.exists(transcript_file):
                            with open(transcript_file, 'r') as f:
                                content = f.read()
                                if content.strip():
                                    logging.info(f"Successfully saved transcript to: {transcript_file}")
                                    return transcript_file
                            
                    logging.warning(f"Failed to get subtitles with current approach")
                except subprocess.CalledProcessError as e:
                    logging.warning(f"Failed to get subtitles: {e}")
                    logging.warning(f"yt-dlp stderr: {e.stderr}")
                    continue
            
            logging.error(f"Failed to get subtitles with any approach for video: {rumble_url}")
            return None
            
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to get video info for Rumble video ID {video_id}: {e}")
            logging.error(f"yt-dlp stderr: {e.stderr}")
            return None
    else:
        # YouTube URL handling - using youtube_transcript_api instead of non-existent 'yt' command
        try:
            result = subprocess.run([
                "youtube_transcript_api", 
                video_id, 
                "--format", "json"
            ], check=True, capture_output=True, text=True)
            
            # Save the JSON output to file
            transcript_file = f"{base_transcript_file}.json"
            with open(transcript_file, 'w') as f:
                f.write(result.stdout)
            
            logging.info(f"Transcript saved to: {transcript_file}")
            return transcript_file
            
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to fetch transcript for YouTube video ID {video_id}: {e}")
            logging.error(f"youtube_transcript_api stderr: {e.stderr}")
            return None

def log_error(error_type: str, url: str, error_message: str) -> None:
    """
    Logs an error to both the error log file and standard logging.
    
    Args:
        error_type (str): The type of error that occurred
        url (str): The URL that caused the error
        error_message (str): The detailed error message
    """
    error_msg = f"{error_type} - URL: {url} - Error: {error_message}"
    error_logger.error(error_msg)
    logging.error(error_msg)

def translate_arxiv_url(url: str) -> str:
    """
    Translates arXiv PDF URLs to their corresponding article URLs.
    Only processes URLs that contain 'arxiv.org/pdf/'.
    
    Args:
        url (str): The URL to check and potentially translate
        
    Returns:
        str: Translated article URL if it was an arXiv PDF URL, otherwise original URL
    """
    if 'arxiv.org/pdf/' not in url:
        return url
        
    arxiv_pdf_pattern = re.compile(r'(?:https?://)?arxiv\.org/pdf/(\d+\.\d+)')
    if match := arxiv_pdf_pattern.search(url):
        article_id = match.group(1)
        article_url = f"https://arxiv.org/abs/{article_id}"
        logging.debug(f"Translated arXiv PDF URL to article URL: {article_url}")
        return article_url
    return url

def process_url(url: str, force: bool) -> None:
    """
    Processes a given URL to extract and record relevant information.
    """
    logging.debug(f"Original URL: {url}")
    
    if "youtube.com/results" in url:
        log_error("URL Processing", url, "YouTube search results pages are not supported")
        print("Error: YouTube search results pages are not supported")
        raise ValueError("YouTube search results pages are not supported")
    
    if url.lower().endswith('.pdf'):
        current_time = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        title = os.path.basename(urlparse(url).path)
        if not url_exists_in_file(url, UNIFIED) or force:
            append_to_file(UNIFIED, f"{current_time}|[{url}]|({title})|PDF Document|General\n")
            print(f"{current_time}|[{url}]|({title})|PDF Document|General")
            logging.info(f"Added PDF URL: {url}")
        return

    try:
        resolved_url = resolve_redirect(url)
        logging.debug(f"Resolved URL: {resolved_url}")
        simplified_url = simplify_url(resolved_url)
        logging.debug(f"Simplified URL after resolving redirects: {simplified_url}")
    except Exception as e:
        error_message = f"Failed to process URL: {e}"
        log_error("URL Processing", url, error_message)
        print(f"Error: {error_message}. Skipping...")
        raise

    current_time = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    
    if "rumble.com" in simplified_url:
        try:
            # Extract video ID from the Rumble URL for file naming
            match = re.search(r"rumble\.com/([^/?]+)", simplified_url)
            if match:
                video_id = match.group(1)
            else:
                video_id = simplified_url
            safe_video_id = re.sub(r"[^\w\-_.]", "_", video_id)
            title = get_title_from_url(simplified_url)
            if title.startswith("Error: 'lynx' is not installed"):
                print(title)
                print("Please install lynx to fetch webpage titles, or use the --force flag to add the URL without a title.")
                return
            
            # Always check if transcript exists and fetch if it doesn't
            transcript_file = os.path.join(TRANSCRIPTS_DIR, f"{safe_video_id}.json")
            transcript_file_exists = os.path.exists(transcript_file)

            if not transcript_file_exists:
                transcript_file = fetch_youtube_transcript(simplified_url)
                if transcript_file is None:
                    log_error("Transcript Retrieval", video_id, "Failed to fetch transcript")
            
            # Add or update the reference entry
            if not url_exists_in_file(simplified_url, UNIFIED) or force:
                append_to_file(UNIFIED, f"{current_time}|[{simplified_url}]|({title})|Rumble|General|{transcript_file}\n")
                print(f"{current_time}|[{simplified_url}]|({title})|Rumble|General|{transcript_file}")
                logging.info(f"Added Rumble URL: {simplified_url}")
            else:
                # Update existing entry with transcript if needed
                update_reference_entry(simplified_url, title, "Rumble", transcript_file)
        except Exception as e:
            error_message = f"Failed to process Rumble URL: {e}"
            log_error("Rumble Processing", simplified_url, error_message)
            print(f"Error: {error_message}")
    elif "youtube.com" in simplified_url and not simplified_url.startswith('https://www.youtube.com/redirect'):
        try:
            result = get_youtube_data(simplified_url)
            if isinstance(result, tuple) and isinstance(result[2], list):  # Playlist
                playlist_title, playlist_uploader, videos = result
                playlist_url = simplified_url
                if not url_exists_in_file(playlist_url, UNIFIED) or force:
                    append_to_file(UNIFIED, f"{current_time}|[{playlist_url}]|({playlist_title})|{playlist_uploader}|YouTube\n")
                    print(f"{current_time}|[{playlist_url}]|({playlist_title})|{playlist_uploader}|YouTube")
                    logging.info(f"Added playlist URL: {playlist_url}")
                for video_id, title, uploader in videos:
                    title = re.sub('[^0-9a-zA-Z]+', ' ', title).strip()
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    transcript_file = os.path.join(TRANSCRIPTS_DIR, f"{video_id}.json")
                    transcript_file_exists = os.path.exists(transcript_file)
                    url_exists = url_exists_in_file(video_url, UNIFIED)

                    if not url_exists or force or not transcript_file_exists or not reference_has_transcript(video_url):
                        if not transcript_file_exists:
                            transcript_file = fetch_youtube_transcript(video_id)
                            if transcript_file is None:
                                log_error("Transcript Retrieval", video_url, "Failed to fetch transcript")
                        update_reference_entry(video_url, title, uploader, transcript_file)
                    else:
                        print(f"URL {video_url} already recorded.")
                        logging.info(f"Duplicate URL: {video_url}")
            else:  # Single Video
                video_id, title, uploader = result
                title = re.sub('[^0-9a-zA-Z]+', ' ', title).strip()
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                transcript_file = os.path.join(TRANSCRIPTS_DIR, f"{video_id}.json")
                transcript_file_exists = os.path.exists(transcript_file)
                url_exists = url_exists_in_file(video_url, UNIFIED)

                if not url_exists or force or not transcript_file_exists or not reference_has_transcript(video_url):
                    if not transcript_file_exists:
                        transcript_file = fetch_youtube_transcript(video_id)
                        if transcript_file is None:
                            log_error("Transcript Retrieval", video_url, "Failed to fetch transcript")
                    update_reference_entry(video_url, title, uploader, transcript_file)
                    print(f"Title: {title}")
                else:
                    print(f"URL {video_url} already recorded.")
                    print(f"Title: {title}")
                    logging.info(f"Duplicate URL: {video_url}")
        except ValueError as e:
            error_message = f"Invalid YouTube URL: {e}"
            log_error("YouTube Processing", simplified_url, error_message)
            print(f"Error: {error_message}")
    else:
        title = get_title_from_url(simplified_url)
        logging.debug(f"Fetched title: {title}")
        if title.startswith("Error: 'lynx' is not installed"):
            print(title)
            print("Please install lynx to fetch webpage titles, or use the --force flag to add the URL without a title.")
            return
        elif title == "Dead link":
            log_error("URL Processing", simplified_url, "Dead link detected")
            print(f"Error: The URL {simplified_url} is a dead link.")
        elif title in ("Timeout error", "Error: Request timed out"):
            log_error("URL Processing", simplified_url, "Request timed out")
            print(f"Error: The request to {simplified_url} timed out.")
        elif title == "Too many redirects":
            log_error("URL Processing", simplified_url, "Too many redirects")
            print(f"Error: The URL {simplified_url} has too many redirects.")
        elif title.startswith("Error: Unexpected error"):
            log_error("URL Processing", simplified_url, title)
            print("Error: An unexpected error occurred.")
        elif title and not title.startswith("Error"):
            if url_exists_in_file(simplified_url, UNIFIED) and not force:
                print(f"URL {simplified_url} already recorded.")
                logging.info(f"Duplicate URL: {simplified_url}")
            else:
                append_to_file(UNIFIED, f"{current_time}|[{simplified_url}]|({title})|General|General\n")
                print(f"{current_time}|[{simplified_url}]|({title})|General|General")
                logging.info(f"Added URL: {simplified_url}")
        else:
            log_error("URL Processing", simplified_url, f"Invalid URL with title: {title}")
            print("Invalid URL")

def update_reference_entry(video_url: str, video_title: str, uploader: str, transcript_file: str) -> None:
    """
    Updates or adds a YouTube video entry in the references.md file with the transcript file reference.
    """
    updated = False
    with open(UNIFIED, 'r') as file:
        lines = file.readlines()

    with open(UNIFIED, 'w') as file:
        for line in lines:
            if video_url in line:
                if line.strip().endswith("|None"):
                    line = line.replace("|None", f"|{transcript_file}")
                elif not line.strip().endswith(f"|{transcript_file}"):
                    line = line.rstrip() + f"|{transcript_file}\n"
                updated = True
            file.write(line)

    if not updated:
        entry = f"{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}|[{video_url}]|({video_title})|{uploader}|YouTube|{transcript_file}\n"
        append_to_file(UNIFIED, entry)

    logging.info(f"Updated reference entry for URL: {video_url} with transcript file: {transcript_file}")
    print(success(f"Updated reference entry for {url(video_url)}"))
    print(info(f"Title: {title(video_title)}"))
    print(info(f"Transcript: {dim(transcript_file)}"))

def reference_has_transcript(url: str) -> bool:
    """
    Checks if a reference entry for a given URL has a transcript file referenced.

    Args:
        url (str): The URL to check.

    Returns:
        bool: True if the reference entry has a transcript file referenced, False otherwise.
    """
    with open(UNIFIED, "r") as f:
        for line in f:
            if url in line:
                parts = line.strip().split('|')
                if len(parts) > 5 and parts[-1] != "None":
                    return True
    return False

def create_backup(file_path: str) -> None:
    """
    Creates a backup of the specified file.
    
    Args:
        file_path (str): The path to the file that needs to be backed up.
    """
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_file_path = f"{os.path.dirname(file_path)}/{timestamp}_{os.path.basename(file_path)}"
    try:
        with open(file_path, 'r') as original_file:
            with open(backup_file_path, 'w') as backup_file:
                backup_file.write(original_file.read())
        print(f"Backup created: {backup_file_path}")
        logging.info(f"Backup created: {backup_file_path}")
    except Exception as e:
        print(f"Error creating backup: {e}")
        logging.error(f"Error creating backup: {e}")

def main():
    """Main function to handle the command-line interface for recording URLs."""
    ensure_path_exists(UNIFIED)
    try:
        args = parse_arguments()

        # Set logging level based on the debug argument
        if args.debug == 1:
            logging.getLogger().setLevel(logging.INFO)
        elif args.debug == 2:
            logging.getLogger().setLevel(logging.WARNING)
        elif args.debug == 3:
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            logging.getLogger().setLevel(logging.ERROR)

        if args.integrity:
            integrity_errors = check_integrity()
            if integrity_errors:
                print(error("Integrity check failed:"))
                for err in integrity_errors:
                    file_name, line_number, line_contents, expected_line = err
                    print(warning(f"{file_name} line {line_number}: {line_contents}"))
                    print(info(f"Expected: {expected_line}"))
            else:
                print(success("Integrity check passed. Log files are formatted correctly."))
        elif args.backup:
            create_backup(UNIFIED)
        elif args.search:
            search_term = args.search
            all_fields = ["url", "title", "date", "source", "uploader"]
            results = {}
            for field in all_fields:
                field_results = search_entries(search_term, field, UNIFIED)
                for line, hit_types in field_results.items():
                    if line not in results:
                        results[line] = hit_types
                    else:
                        results[line].extend(hit_types)
            for line, hit_types in results.items():
                unique_hit_types = list(set(hit_types))
                print(line.strip())
                for hit_type in unique_hit_types:
                    print(f"-Hit Type: {hit_type}")
        elif args.search_url:
            results = search_entries(args.search_url, "url", UNIFIED)
            for line, hit_types in results.items():
                unique_hit_types = list(set(hit_types))
                print(line.strip())
                for hit_type in unique_hit_types:
                    print(f"-Hit Type: {hit_type}")
        elif args.search_title:
            results = search_entries(args.search_title, "title", UNIFIED)
            for line, hit_types in results.items():
                unique_hit_types = list(set(hit_types))
                print(line.strip())
                for hit_type in unique_hit_types:
                    print(f"-Hit Type: {hit_type}")
        elif args.search_date:
            results = search_entries(args.search_date, "date", UNIFIED)
            for line, hit_types in results.items():
                unique_hit_types = list(set(hit_types))
                print(line.strip())
                for hit_type in unique_hit_types:
                    print(f"-Hit Type: {hit_type}")
        elif args.search_source:
            results = search_entries(args.search_source, "source", UNIFIED)
            for line, hit_types in results.items():
                unique_hit_types = list(set(hit_types))
                print(line.strip())
                for hit_type in unique_hit_types:
                    print(f"-Hit Type: {hit_type}")
        elif args.search_uploader:
            results = search_entries(args.search_uploader, "uploader", UNIFIED)
            for line, hit_types in results.items():
                unique_hit_types = list(set(hit_types))
                print(line.strip())
                for hit_type in unique_hit_types:
                    print(f"-Hit Type: {hit_type}")
        elif args.transcript and args.url:
            update_transcript(args.url)
        elif args.file:
            read_urls_from_file(args.file, args.force)
        elif args.url:
            process_url(args.url, args.force)
        else:
            timeout = None
            while True:
                try:
                    print(highlight("Enter a URL to record (or press Ctrl+C to quit): "))
                    ready, _, _ = select.select([sys.stdin], [], [], timeout)
                    if ready:
                        url = sys.stdin.readline().strip()
                        if url:  # Only process non-empty URLs
                            force = False
                            process_url(url, force)
                        else:
                            print(warning("Empty URL. Please enter a valid URL."))
                        time.sleep(1)  # Add a delay between processing each URL
                    else:
                        print(info("\nNo input received. Exiting..."))
                        break
                except Exception as e:
                    print(error(f"An error occurred: {e}"))
                    logging.error(f"An error occurred: {e}")
    except KeyboardInterrupt:
        print(warning("\nExiting..."))
        sys.exit(0)

if __name__ == "__main__":
    if DEVELOPER_KEY is None:
        print(error('Error: YOUTUBE_API_KEY is not set in .env file or shell environment.'))
        choice = input(info('Would you like to set it now? (yes/no): '))
        if choice.lower() == 'yes':
            set_developer_key()
    else:
        if os.getenv('DEBUG') == 'True':
            print(success('YOUTUBE_API_KEY is set.'))
    main()