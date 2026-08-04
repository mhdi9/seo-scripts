import os
from pathlib import Path
import re
import signal
import sys
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm


OUTPUT_PATH = Path(__file__).resolve().parent / "site_crawl.xlsx"

# Main crawl data (same information as the original script)
data = []

# Internal-link data for the separate Excel sheet
internal_links = []
internal_link_keys = set()

# Stores the first HTTP response status for every crawled URL.
# Example: if /old-page returns 301 and then redirects to a 200 page,
# this dictionary stores 301 for /old-page.
page_status_codes = {}

# These variables are set when crawling starts and are also used by Ctrl+C save.
active_output_path = OUTPUT_PATH
active_session = None
active_headers = None


UNWANTED_EXTENSIONS = [
    ".css", ".js", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".avi", ".wav", ".zip", ".rar", ".tar", ".gz",
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".ico", ".txt", ".xml", ".json",
]

# Common identifiers used by headers, footers, menus, and navigation areas.
EXCLUDED_CONTAINER_KEYWORDS = {
    "header",
    "footer",
    "site-header",
    "site-footer",
    "main-header",
    "main-footer",
    "top-header",
    "bottom-footer",
    "navbar",
    "nav-bar",
    "navigation",
    "main-navigation",
    "primary-navigation",
    "secondary-navigation",
    "main-menu",
    "primary-menu",
    "secondary-menu",
    "menu-container",
    "menu-wrapper",
    "mobile-menu",
    "desktop-menu",
}


HTTP_SCHEMES = {"http", "https"}
SKIPPED_HREF_PREFIXES = ("mailto:", "tel:", "javascript:", "data:")


def normalize_url(url):
    """Return a consistent HTTP(S) URL without a fragment."""
    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in HTTP_SCHEMES:
        return ""

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # A URL with an empty path is normalized to '/'.
    path = parsed.path or "/"

    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))


def get_first_response_status(response):
    """Return the status before redirects, or the final status when no redirect exists."""
    if response.history:
        return response.history[0].status_code
    return response.status_code


def matches_skip_pattern(url, skip_patterns):
    """Return True when the URL matches one of the user-provided regex patterns."""
    return bool(skip_patterns and any(re.search(pattern, url) for pattern in skip_patterns))


def has_unwanted_extension(url):
    """Return True for static/document/media URLs that should not be crawled or reported."""
    path = urlparse(url).path.lower()
    return any(path.endswith(extension) for extension in UNWANTED_EXTENSIONS)


def is_internal_url(url, domain):
    """Check whether a URL belongs to the starting website domain."""
    return urlparse(url).netloc.lower() == domain.lower()


def is_link_inside_excluded_area(link):
    """
    Detect links inside header, footer, navigation, or menu containers.

    This filter is used only for the 'internal links' report. Links from these
    areas are still available to the main crawler for URL discovery.
    """
    for parent in link.parents:
        if getattr(parent, "name", None) in {"header", "footer", "nav"}:
            return True

        if not hasattr(parent, "attrs"):
            continue

        role = str(parent.get("role", "")).strip().lower()
        if role in {"banner", "contentinfo", "navigation"}:
            return True

        identifiers = []

        element_id = parent.get("id")
        if element_id:
            identifiers.append(str(element_id))

        classes = parent.get("class", [])
        if isinstance(classes, str):
            identifiers.append(classes)
        else:
            identifiers.extend(str(item) for item in classes)

        normalized_identifiers = {
            identifier.strip().lower().replace("_", "-")
            for identifier in identifiers
            if identifier and identifier.strip()
        }

        for identifier in normalized_identifiers:
            if identifier in EXCLUDED_CONTAINER_KEYWORDS:
                return True

            # Handles identifiers such as "site-header-inner" or "footer-widgets".
            identifier_tokens = set(filter(None, re.split(r"[^a-z0-9]+", identifier)))
            if "header" in identifier_tokens or "footer" in identifier_tokens:
                return True

            if identifier.endswith("-menu") or identifier.startswith("menu-"):
                return True

            if "navigation" in identifier_tokens or "navbar" in identifier_tokens:
                return True

    return False


def extract_anchor_text(link):
    """Extract visible anchor text, falling back to an image alt attribute."""
    anchor_text = " ".join(link.get_text(" ", strip=True).split())
    if anchor_text:
        return anchor_text

    image = link.find("img", alt=True)
    if image:
        return " ".join(image.get("alt", "").split())

    return ""


def collect_internal_content_links(soup, source_url, domain, skip_patterns):
    """Collect internal links while excluding header/footer/menu links from the report."""
    for link in soup.find_all("a", href=True):
        if is_link_inside_excluded_area(link):
            continue

        href = link.get("href", "").strip()
        if not href or href == "#" or href.lower().startswith(SKIPPED_HREF_PREFIXES):
            continue

        destination = normalize_url(urljoin(source_url, href))
        if not destination:
            continue

        if not is_internal_url(destination, domain):
            continue

        if has_unwanted_extension(destination):
            continue

        if matches_skip_pattern(destination, skip_patterns):
            continue

        anchor_text = extract_anchor_text(link)
        row_key = (source_url, destination, anchor_text)

        # Identical occurrences on the same page do not add useful information
        # because the output has no DOM-position column.
        if row_key in internal_link_keys:
            continue

        internal_link_keys.add(row_key)
        internal_links.append(
            {
                "source": source_url,
                "destination": destination,
                "anchor text": anchor_text,
            }
        )


def discover_urls_for_crawl(soup, current_url, domain, visited, queued, queue, skip_patterns):
    """
    Preserve the original discovery behavior by scanning every link, including
    links in headers and footers. Only report extraction excludes those areas.
    """
    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not href or href == "#" or href.lower().startswith(SKIPPED_HREF_PREFIXES):
            continue

        full_url = normalize_url(urljoin(current_url, href))
        if not full_url:
            continue

        if has_unwanted_extension(full_url):
            continue

        if matches_skip_pattern(full_url, skip_patterns):
            continue

        if is_internal_url(full_url, domain) and full_url not in visited and full_url not in queued:
            queue.append(full_url)
            queued.add(full_url)


def resolve_missing_status_codes(session, headers, timeout=10):
    """
    Resolve statuses for report destinations not reached by the main crawl.

    Normally every reported internal destination is eventually crawled, so this
    function has little or no extra work. It mainly helps when crawling is
    interrupted or a destination was not reached for another reason.
    """
    destinations = {row["destination"] for row in internal_links}
    missing_destinations = [url for url in destinations if url not in page_status_codes]

    if not missing_destinations or session is None:
        return

    print(f"Checking status codes for {len(missing_destinations)} unresolved internal URLs...")

    for destination in tqdm(
        missing_destinations,
        desc="Checking link statuses",
        unit="URL",
        dynamic_ncols=True,
    ):
        try:
            response = session.get(
                destination,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                stream=True,
            )
            page_status_codes[destination] = get_first_response_status(response)
            response.close()
        except requests.RequestException as error:
            page_status_codes[destination] = f"Error: {error}"


def save_results(output_path, resolve_missing=True):
    """Save crawl data and internal-link data into two Excel worksheets."""
    if not data and not internal_links:
        print("No data collected, so no file was saved.")
        return

    if resolve_missing:
        resolve_missing_status_codes(active_session, active_headers)

    output_directory = os.path.dirname(output_path)
    if output_directory:
        os.makedirs(output_directory, exist_ok=True)

    crawl_columns = [
        "URL",
        "Title",
        "Description",
        "Canonical",
        "Meta Robots",
        "H1",
        "Status Code",
    ]
    link_columns = ["source", "destination", "anchor text", "status code"]

    crawl_df = pd.DataFrame(data, columns=crawl_columns)

    link_rows = []
    for row in internal_links:
        link_rows.append(
            {
                "source": row["source"],
                "destination": row["destination"],
                "anchor text": row["anchor text"],
                "status code": page_status_codes.get(row["destination"], "Not checked"),
            }
        )

    internal_links_df = pd.DataFrame(link_rows, columns=link_columns)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        crawl_df.to_excel(writer, sheet_name="crawl data", index=False)
        internal_links_df.to_excel(writer, sheet_name="internal links", index=False)

    print(f"Output saved to {output_path}")


def save_and_exit(signum, frame):
    """Save collected data to Excel and exit on Ctrl+C."""
    print("\nCrawling interrupted by user. Saving collected data...")

    try:
        # Avoid potentially lengthy extra requests during an interrupted crawl.
        # Already crawled destination URLs still receive their real status codes.
        save_results(active_output_path, resolve_missing=False)
    except Exception as error:
        print(
            f"\nError saving file: {error}. "
            "Check whether the output path is accessible and the Excel file is closed."
        )

    sys.exit(0)


# Register the signal handler for Ctrl+C.
signal.signal(signal.SIGINT, save_and_exit)


def crawl_website(start_url, skip_patterns=None, output_path=OUTPUT_PATH):
    global active_output_path, active_session, active_headers

    if skip_patterns is None:
        skip_patterns = []

    start_url = normalize_url(start_url)
    if not start_url:
        raise ValueError("Please enter a valid URL beginning with http:// or https://")

    # Reset global collections in case the function is called more than once.
    data.clear()
    internal_links.clear()
    internal_link_keys.clear()
    page_status_codes.clear()

    active_output_path = output_path

    visited = set()
    queued = {start_url}
    queue = deque([start_url])
    domain = urlparse(start_url).netloc.lower()

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    session = requests.Session()
    active_session = session
    active_headers = headers

    pbar = tqdm(desc="Crawling pages", unit="page", dynamic_ncols=True)

    try:
        while queue:
            current_url = queue.popleft()
            queued.discard(current_url)

            if current_url in visited:
                continue

            visited.add(current_url)

            try:
                response = session.get(
                    current_url,
                    headers=headers,
                    timeout=10,
                    allow_redirects=True,
                )
                status_code = response.status_code
                page_status_codes[current_url] = get_first_response_status(response)

                if status_code == 301:
                    data.append(
                        {
                            "URL": current_url,
                            "Title": "",
                            "Description": "",
                            "Canonical": "",
                            "Meta Robots": "",
                            "H1": "",
                            "Status Code": status_code,
                        }
                    )
                    pbar.update(1)
                    continue

                if status_code != 200:
                    data.append(
                        {
                            "URL": current_url,
                            "Title": "",
                            "Description": "",
                            "Canonical": "",
                            "Meta Robots": "",
                            "H1": "",
                            "Status Code": status_code,
                        }
                    )
                    pbar.update(1)
                    continue

                soup = BeautifulSoup(response.text, "html.parser")

                title = ""
                if soup.title:
                    title = " ".join(soup.title.get_text(" ", strip=True).split())

                description = ""
                meta_robots = ""
                canonical = ""
                h1 = ""

                desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
                if desc_tag:
                    description = desc_tag.get("content", "").strip()

                robots_tag = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
                if robots_tag:
                    meta_robots = robots_tag.get("content", "").strip()

                canonical_tag = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
                if canonical_tag:
                    canonical = canonical_tag.get("href", "").strip()

                h1_tag = soup.find("h1")
                if h1_tag:
                    h1 = " ".join(h1_tag.get_text(" ", strip=True).split())

                data.append(
                    {
                        "URL": current_url,
                        "Title": title,
                        "Description": description,
                        "Canonical": canonical,
                        "Meta Robots": meta_robots,
                        "H1": h1,
                        "Status Code": status_code,
                    }
                )

                # Collect only content-area internal links for the report.
                collect_internal_content_links(
                    soup=soup,
                    source_url=current_url,
                    domain=domain,
                    skip_patterns=skip_patterns,
                )

                # Discover crawl URLs from the full document, including header/footer links.
                discover_urls_for_crawl(
                    soup=soup,
                    current_url=current_url,
                    domain=domain,
                    visited=visited,
                    queued=queued,
                    queue=queue,
                    skip_patterns=skip_patterns,
                )

                time.sleep(1)
                pbar.update(1)

            except requests.RequestException as error:
                page_status_codes[current_url] = f"Error: {error}"
                data.append(
                    {
                        "URL": current_url,
                        "Title": "",
                        "Description": "",
                        "Canonical": "",
                        "Meta Robots": "",
                        "H1": "",
                        "Status Code": f"Error: {error}",
                    }
                )
                pbar.update(1)

            except Exception as error:
                page_status_codes[current_url] = f"Error: {error}"
                data.append(
                    {
                        "URL": current_url,
                        "Title": "",
                        "Description": "",
                        "Canonical": "",
                        "Meta Robots": "",
                        "H1": "",
                        "Status Code": f"Error: {error}",
                    }
                )
                pbar.update(1)

    finally:
        pbar.close()

    try:
        save_results(output_path, resolve_missing=True)
        print("Crawling completed successfully.")
    except Exception as error:
        print(
            f"Error saving file: {error}. "
            "Check whether the output path is accessible and the Excel file is closed."
        )
    finally:
        session.close()
        active_session = None


if __name__ == "__main__":
    url = input("Please enter the website URL (e.g., https://example.com): ").strip()
    skip_input = input(
        "Enter comma-separated regex patterns to skip (e.g., '#,login,admin'): "
    ).strip()
    skip_patterns = [pattern.strip() for pattern in skip_input.split(",") if pattern.strip()]

    crawl_website(url, skip_patterns)
