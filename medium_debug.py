import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def debug_url_request(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    
    try:
        response = requests.get(url, headers=headers, allow_redirects=True)
        
        logging.info(f"Initial URL: {url}")
        logging.info(f"Final URL: {response.url}")
        logging.info(f"Status Code: {response.status_code}")
        logging.info(f"Content Type: {response.headers.get('Content-Type')}")
        
        for i, r in enumerate(response.history):
            logging.info(f"Redirect {i + 1}:")
            logging.info(f"  URL: {r.url}")
            logging.info(f"  Status Code: {r.status_code}")
        
        logging.info("Response Headers:")
        for header, value in response.headers.items():
            logging.info(f"  {header}: {value}")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        title = soup.title.string if soup.title else "No title found"
        logging.info(f"Extracted Title: {title}")
        
        return response
    
    except requests.exceptions.RequestException as e:
        logging.error(f"Error during request: {e}")
        return None

if __name__ == "__main__":
    url = input("Enter the Medium URL to debug: ")
    debug_url_request(url)
