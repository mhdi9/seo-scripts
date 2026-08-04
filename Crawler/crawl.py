import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import deque
import pandas as pd
import time
import signal
from tqdm import tqdm
import os
import re

# Global variable to store data
data = []

def save_and_exit(signum, frame):
    """Save collected data to Excel and exit on Ctrl+C."""
    global data
    try:
        output_path = r"C:\Users\Lenovo\Documents\site_crawl.xlsx"
        if data:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)  # Ensure directory exists
            df = pd.DataFrame(data)
            df.to_excel(output_path, index=False)
            print(f"\nCrawling interrupted by user. Data saved to {output_path}")
        else:
            print("\nCrawling interrupted by user. No data collected, so no file was saved.")
    except Exception as e:
        print(f"\nError saving file: {str(e)}. Check if the path is accessible or you have write permissions.")
    exit(0)

# Register the signal handler for Ctrl+C
signal.signal(signal.SIGINT, save_and_exit)

def crawl_website(start_url, skip_patterns=None):
    global data
    if skip_patterns is None:
        skip_patterns = []
    
    visited = set()
    queue = deque([start_url])
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # List of unwanted file extensions to skip
    unwanted_extensions = [
        '.css', '.js', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
        '.mp3', '.mp4', '.avi', '.wav', '.zip', '.rar', '.tar', '.gz',
        '.ttf', '.otf', '.woff', '.woff2', '.eot', '.ico', '.txt', '.xml', '.json'
    ]

    pbar = tqdm(desc="Crawling pages", unit="page", dynamic_ncols=True)

    while queue:
        current_url = queue.popleft()
        if current_url in visited:
            continue
        visited.add(current_url)

        try:
            response = requests.get(current_url, headers=headers, timeout=10)
            status_code = response.status_code

            if status_code == 301:
                data.append({
                    'URL': current_url,
                    'Title': '',
                    'Description': '',
                    'Canonical': '',
                    'Meta Robots': '',
                    'H1': '',
                    'Status Code': status_code
                })
                pbar.update(1)
                continue

            if status_code != 200:
                data.append({
                    'URL': current_url,
                    'Title': '',
                    'Description': '',
                    'Canonical': '',
                    'Meta Robots': '',
                    'H1': '',
                    'Status Code': status_code
                })
                pbar.update(1)
                continue

            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else ''
            description = ''
            meta_robots = ''
            canonical = ''
            h1 = ''

            desc_tag = soup.find('meta', attrs={'name': 'description'})
            if desc_tag:
                description = desc_tag.get('content', '').strip()

            robots_tag = soup.find('meta', attrs={'name': 'robots'})
            if robots_tag:
                meta_robots = robots_tag.get('content', '').strip()

            canonical_tag = soup.find('link', attrs={'rel': 'canonical'})
            if canonical_tag:
                canonical = canonical_tag.get('href', '').strip()

            h1_tag = soup.find('h1')
            if h1_tag:
                h1 = h1_tag.text.strip()

            data.append({
                'URL': current_url,
                'Title': title,
                'Description': description,
                'Canonical': canonical,
                'Meta Robots': meta_robots,
                'H1': h1,
                'Status Code': status_code
            })

            domain = urlparse(start_url).netloc
            for link in soup.find_all('a', href=True):
                href = link['href']
                full_url = urljoin(current_url, href)
                parsed_url = urlparse(full_url)
                path = parsed_url.path.lower()

                # Skip if the URL has an unwanted extension
                if any(path.endswith(ext) for ext in unwanted_extensions):
                    continue

                # Skip URLs matching any of the provided regex patterns
                if skip_patterns and any(re.search(pattern, full_url) for pattern in skip_patterns):
                    continue

                if parsed_url.netloc == domain and full_url not in visited:
                    queue.append(full_url)

            time.sleep(1)
            pbar.update(1)

        except Exception as e:
            data.append({
                'URL': current_url,
                'Title': '',
                'Description': '',
                'Canonical': '',
                'Meta Robots': '',
                'H1': '',
                'Status Code': f'Error: {str(e)}'
            })
            pbar.update(1)

    pbar.close()

    try:
        output_path = r"C:\Users\Lenovo\Documents\site_crawl.xlsx"
        if data:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)  # Ensure directory exists
            df = pd.DataFrame(data)
            df.to_excel(output_path, index=False)
            print(f"Crawling completed. Output saved to {output_path}")
        else:
            print("Crawling completed. No data collected, so no file was saved.")
    except Exception as e:
        print(f"Error saving file: {str(e)}. Check if the path is accessible or you have write permissions.")

if __name__ == "__main__":
    url = input("Please enter the website URL (e.g., https://example.com): ")
    skip_input = input("Enter comma-separated regex patterns to skip (e.g., '#,login,admin'): ").strip()
    skip_patterns = [p.strip() for p in skip_input.split(',')] if skip_input else []
    crawl_website(url, skip_patterns)