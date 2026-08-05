from datetime import datetime
import math
import os
from pathlib import Path
import re
import signal
import sys
import time
from collections import Counter, deque
from urllib.parse import urljoin, urlparse, urlunparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm


SCRIPT_DIRECTORY = Path(__file__).resolve().parent

# Main crawl data (same information as the original script)
data = []

# Internal-link data for the separate Excel sheet
internal_links = []
internal_link_keys = set()

# Successfully parsed HTML pages. This is used to identify repeated sitewide
# links that escaped the DOM filters, such as unsemantic mobile menus.
parsed_page_urls = set()

# Stores the first HTTP response status for every crawled URL.
# Example: if /old-page returns 301 and then redirects to a 200 page,
# this dictionary stores 301 for /old-page.
page_status_codes = {}

# These variables are set when crawling starts and are also used by Ctrl+C save.
active_output_path = None
active_session = None
active_headers = None


UNWANTED_EXTENSIONS = [
    ".css", ".js", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".avi", ".wav", ".zip", ".rar", ".tar", ".gz",
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".ico", ".txt", ".xml", ".json",
]

# Semantic and common naming signals for non-content areas.
EXCLUDED_CONTAINER_TOKENS = {
    "header",
    "footer",
    "masthead",
    "navbar",
    "nav-bar",
    "navigation",
    "navigator",
    "menu",
    "menubar",
    "drawer",
    "sidebar",
    "offcanvas",
    "off-canvas",
    "breadcrumb",
    "breadcrumbs",
    "toolbar",
    "tabbar",
    "tab-bar",
    "mobile-nav",
    "desktop-nav",
    "mobile-menu",
    "desktop-menu",
    "top-nav",
    "bottom-nav",
    "site-nav",
    "primary-nav",
    "secondary-nav",
    "main-nav",
    "site-header",
    "site-footer",
    "main-header",
    "main-footer",
    "top-header",
    "bottom-footer",
}

# Content roots are checked by priority. The first group with matches is used.
# This changes report extraction from a blacklist-only approach to a whitelist
# approach: links are normally collected only from the actual page content.
CONTENT_ROOT_GROUPS = (
    ("main", '[role="main"]'),
    (
        ".entry-content",
        ".post-content",
        ".article-content",
        ".single-post-content",
        ".single-content",
        ".page-content",
        ".main-content",
        ".content-area",
        "#main-content",
        "#content",
    ),
    ("article",),
)

# Final safety net for navigation/footer links that use only generic utility
# classes and therefore have no semantic tag, role, id, or class name.
SITEWIDE_LINK_RATIO = 0.60
MIN_SITEWIDE_LINK_SOURCES = 3

HTTP_SCHEMES = {"http", "https"}
SKIPPED_HREF_PREFIXES = ("mailto:", "tel:", "javascript:", "data:")


def build_output_path():
    """Create a unique timestamped Excel path next to this script."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    candidate = SCRIPT_DIRECTORY / f"site_crawl_{timestamp}.xlsx"

    # Normally the timestamp is enough. The counter also prevents overwriting
    # when the function is called more than once during the same second.
    counter = 2
    while candidate.exists():
        candidate = SCRIPT_DIRECTORY / f"site_crawl_{timestamp}_{counter}.xlsx"
        counter += 1

    return candidate


def normalize_url(url):
    """Return a consistent HTTP(S) URL without a fragment."""
    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in HTTP_SCHEMES:
        return ""

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
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


def split_identifier_tokens(value):
    """Normalize a class/id/attribute value into searchable lowercase tokens."""
    normalized = str(value).strip().lower().replace("_", "-")
    return set(filter(None, re.split(r"[^a-z0-9-]+", normalized)))


def has_excluded_identifier(parent):
    """Detect menu/navigation signals in ids, classes, labels, and data attributes."""
    values = []

    for attribute_name in (
        "id",
        "class",
        "aria-label",
        "data-testid",
        "data-component",
        "data-section",
        "name",
    ):
        attribute_value = parent.get(attribute_name)
        if not attribute_value:
            continue

        if isinstance(attribute_value, (list, tuple)):
            values.extend(str(item) for item in attribute_value)
        else:
            values.append(str(attribute_value))

    for value in values:
        normalized = value.strip().lower().replace("_", "-")
        tokens = split_identifier_tokens(value)

        if normalized in EXCLUDED_CONTAINER_TOKENS:
            return True

        if tokens.intersection(EXCLUDED_CONTAINER_TOKENS):
            return True

        # Handles compound identifiers such as site-header-inner,
        # mobileMenuWrapper, and primary-navigation-container.
        if re.search(
            r"(^|[-_])(header|footer|nav|navbar|navigation|menu|menubar|drawer|"
            r"sidebar|offcanvas|breadcrumb|toolbar|tabbar)([-_]|$)",
            normalized,
        ):
            return True

    return False


def is_probable_fixed_navigation(parent):
    """Detect utility-class navigation overlays with no semantic name."""
    classes = parent.get("class", []) if hasattr(parent, "get") else []
    if isinstance(classes, str):
        classes = classes.split()

    utility_tokens = {
        str(item).lower().split(":")[-1]
        for item in classes
        if str(item).strip()
    }

    positioned_like_overlay = bool(
        utility_tokens.intersection({"fixed", "sticky"})
        or (
            "absolute" in utility_tokens
            and utility_tokens.intersection({"inset-0", "top-0", "bottom-0"})
        )
    )

    if not positioned_like_overlay:
        return False

    # A fixed/sticky container with several links is very likely a menu,
    # toolbar, or persistent site navigation rather than editorial content.
    return len(parent.find_all("a", href=True, limit=4)) >= 4


def is_link_inside_excluded_area(link):
    """
    Detect links inside header, footer, navigation, menu, sidebar, or overlays.

    This filter is used only for the 'internal links' report. These links remain
    available to the main crawler for URL discovery.
    """
    excluded_tags = {"header", "footer", "nav", "aside", "dialog"}
    excluded_roles = {
        "banner",
        "contentinfo",
        "navigation",
        "menu",
        "menubar",
        "complementary",
        "dialog",
    }

    for parent in link.parents:
        parent_name = getattr(parent, "name", None)
        if parent_name in excluded_tags:
            return True

        if not hasattr(parent, "attrs"):
            continue

        role = str(parent.get("role", "")).strip().lower()
        if role in excluded_roles:
            return True

        if str(parent.get("aria-modal", "")).strip().lower() == "true":
            return True

        if has_excluded_identifier(parent):
            return True

        if is_probable_fixed_navigation(parent):
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


def unique_top_level_elements(elements):
    """Deduplicate matching content roots and remove roots nested in another root."""
    unique_elements = []
    seen_ids = set()

    for element in elements:
        element_id = id(element)
        if element_id in seen_ids:
            continue
        seen_ids.add(element_id)
        unique_elements.append(element)

    top_level_elements = []
    element_ids = {id(element) for element in unique_elements}

    for element in unique_elements:
        if any(id(parent) in element_ids for parent in element.parents):
            continue
        top_level_elements.append(element)

    return top_level_elements


def find_content_roots(soup):
    """
    Find the real page-content containers.

    Returns (roots, fallback_mode). In fallback mode, the page has no semantic
    content root and extraction starts at the first H1 to avoid top-of-page
    desktop/mobile navigation built with generic divs.
    """
    for selector_group in CONTENT_ROOT_GROUPS:
        matches = []
        for selector in selector_group:
            matches.extend(soup.select(selector))

        roots = unique_top_level_elements(matches)
        if roots:
            return roots, False

    return [soup.body or soup], True


def links_from_content_root(root, fallback_mode=False):
    """Return candidate anchors from a content root."""
    if fallback_mode:
        first_h1 = root.find("h1")
        if first_h1:
            # Hidden mobile menus and desktop navigation are usually rendered
            # before the page's H1. Starting here avoids them when the site has
            # no usable main/article/content wrapper.
            return first_h1.find_all_next("a", href=True)

    return root.find_all("a", href=True)


def collect_internal_content_links(soup, source_url, domain, skip_patterns):
    """Collect internal links from page content, excluding global UI/navigation."""
    content_roots, fallback_mode = find_content_roots(soup)
    seen_link_nodes = set()

    for root in content_roots:
        for link in links_from_content_root(root, fallback_mode=fallback_mode):
            link_node_id = id(link)
            if link_node_id in seen_link_nodes:
                continue
            seen_link_nodes.add(link_node_id)

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
    Preserve URL discovery by scanning the full document, including menus.

    Only the Excel internal-link report is content-restricted; the crawler can
    still discover pages through header, footer, and mobile navigation links.
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


def filter_sitewide_boilerplate_links(rows):
    """
    Remove repeated sitewide links that escaped DOM-based filters.

    Some JavaScript/Tailwind sites render a second mobile menu as ordinary divs
    with only utility classes. Such links can be impossible to identify reliably
    from a single page's markup. A destination+anchor repeated on at least 60%
    of successfully parsed pages is treated as template/navigation boilerplate.
    """
    total_pages = len(parsed_page_urls)
    if total_pages < MIN_SITEWIDE_LINK_SOURCES:
        return list(rows)

    sources_by_link = {}
    for row in rows:
        key = (row["destination"], row["anchor text"])
        sources_by_link.setdefault(key, set()).add(row["source"])

    minimum_sources = max(
        MIN_SITEWIDE_LINK_SOURCES,
        math.ceil(total_pages * SITEWIDE_LINK_RATIO),
    )

    boilerplate_keys = {
        key
        for key, sources in sources_by_link.items()
        if len(sources) >= minimum_sources
    }

    filtered_rows = [
        row
        for row in rows
        if (row["destination"], row["anchor text"]) not in boilerplate_keys
    ]

    removed_count = len(rows) - len(filtered_rows)
    if removed_count:
        print(
            f"Removed {removed_count} repeated sitewide navigation/template links "
            f"from the internal-links report."
        )

    return filtered_rows


def resolve_missing_status_codes(session, headers, link_rows, timeout=10):
    """Resolve statuses for report destinations not reached by the main crawl."""
    destinations = {row["destination"] for row in link_rows}
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
    """Save crawl data and filtered internal-link data into two Excel sheets."""
    if not data and not internal_links:
        print("No data collected, so no file was saved.")
        return

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report_links = filter_sitewide_boilerplate_links(internal_links)

    if resolve_missing:
        resolve_missing_status_codes(
            active_session,
            active_headers,
            report_links,
        )

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
    for row in report_links:
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
        output_path = active_output_path or build_output_path()

        # Avoid potentially lengthy extra requests during an interrupted crawl.
        # Already crawled destination URLs still receive their real status codes.
        save_results(output_path, resolve_missing=False)
    except Exception as error:
        print(
            f"\nError saving file: {error}. "
            "Check whether the output directory is accessible."
        )

    sys.exit(0)


# Register the signal handler for Ctrl+C.
signal.signal(signal.SIGINT, save_and_exit)


def crawl_website(start_url, skip_patterns=None, output_path=None):
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
    parsed_page_urls.clear()
    page_status_codes.clear()

    if output_path is None:
        output_path = build_output_path()
    else:
        output_path = Path(output_path)

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

                if status_code != 200:
                    data.append(
                        {
                            "URL": current_url,
                            "Title": "",
                            "Description": "",
                            "Canonical": "",
                            "Meta Robots": "",
                            "H1": "",
                            "Status Code": page_status_codes[current_url],
                        }
                    )
                    pbar.update(1)
                    continue

                # lxml produces a more browser-like tree for malformed/complex HTML.
                # The script still works without it by falling back automatically.
                try:
                    soup = BeautifulSoup(response.text, "lxml")
                except Exception:
                    soup = BeautifulSoup(response.text, "html.parser")

                parsed_page_urls.add(current_url)

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

                canonical_tag = soup.find(
                    "link",
                    attrs={"rel": lambda value: value and "canonical" in value},
                )
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
                        "Status Code": page_status_codes[current_url],
                    }
                )

                # Collect internal links only from actual page-content roots.
                collect_internal_content_links(
                    soup=soup,
                    source_url=current_url,
                    domain=domain,
                    skip_patterns=skip_patterns,
                )

                # Discover crawl URLs from the full document, including menus.
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
            "Check whether the output directory is accessible."
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
