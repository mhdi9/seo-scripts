from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
import trafilatura
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


OUTPUT_COLUMNS = ["Page URL", "Title", "Description", "Body Content"]
URL_COLUMN_NAMES = {
    "url",
    "urls",
    "link",
    "links",
    "address",
}


def clean_text(value: str | None) -> str:
    """Remove extra whitespace and prepare text for Excel output."""
    if not value:
        return ""
    value = value.replace("\x00", " ")
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(value: object) -> str:
    if pd.isna(value):
        return ""
    url = str(value).strip()
    if not url:
        return ""
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36 OnPageContentCrawler/1.0"
            ),
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
        }
    )
    return session


def extract_metadata(soup: BeautifulSoup) -> tuple[str, str]:
    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"]
    elif soup.title:
        title = soup.title.get_text(" ", strip=True)

    description = ""
    meta_description = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    og_description = soup.find("meta", attrs={"property": "og:description"})
    if meta_description and meta_description.get("content"):
        description = meta_description["content"]
    elif og_description and og_description.get("content"):
        description = og_description["content"]

    return clean_text(title), clean_text(description)


def fallback_main_text(html: str) -> str:
    """Remove layout elements and extract main/article text as a fallback."""
    soup = BeautifulSoup(html, "lxml")
    selectors = [
        "header", "footer", "nav", "aside", "script", "style", "noscript",
        "form", "iframe", "svg", "canvas", "template", "dialog",
        "[role='navigation']", "[role='banner']", "[role='contentinfo']",
        "[role='complementary']", ".sidebar", "#sidebar", ".side-bar", "#side-bar",
        ".menu", "#menu", ".navbar", "#navbar", ".breadcrumb", ".breadcrumbs",
        ".cookie", "#cookie", ".popup", ".modal", ".social-share", ".share-buttons",
        ".related-posts", ".related-articles", ".comments", "#comments",
    ]
    for selector in selectors:
        for element in soup.select(selector):
            element.decompose()

    content = soup.find("main") or soup.find("article")
    if content is None:
        content = soup.body
    return clean_text(content.get_text(" ", strip=True) if content else "")


def crawl_page(session: requests.Session, url: str, timeout: int = 30) -> dict[str, str]:
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    if "html" not in content_type:
        raise ValueError(f"The URL does not return HTML: {content_type or 'unknown'}")

    response.encoding = response.apparent_encoding or response.encoding
    html = response.text
    soup = BeautifulSoup(html, "lxml")
    title, description = extract_metadata(soup)

    body = trafilatura.extract(
        html,
        url=response.url,
        output_format="txt",
        include_comments=False,
        include_tables=True,
        include_links=False,
        include_images=False,
        favor_precision=True,
        deduplicate=True,
    )
    body = clean_text(body) or fallback_main_text(html)

    return {
        "Page URL": url,
        "Title": title,
        "Description": description,
        "Body Content": body,
    }


def find_url_column(frame: pd.DataFrame) -> object:
    normalized_names = {clean_text(str(column)).casefold(): column for column in frame.columns}
    for candidate in URL_COLUMN_NAMES:
        if candidate.casefold() in normalized_names:
            return normalized_names[candidate.casefold()]
    return frame.columns[0]


def main() -> None:
    print("Main Web Page Content Crawler")
    input_path = Path(input("Enter the input Excel file path: ").strip().strip('"'))
    if not input_path.is_file():
        raise SystemExit(f"File not found: {input_path}")

    default_output = input_path.with_name(f"{input_path.stem}_crawled.xlsx")
    output_value = input(
        f"Enter the output Excel file path (press Enter for {default_output}): "
    ).strip().strip('"')
    output_path = Path(output_value) if output_value else default_output

    frame = pd.read_excel(input_path, sheet_name=0)
    if frame.empty or len(frame.columns) == 0:
        raise SystemExit("The Excel file is empty.")

    url_column = find_url_column(frame)
    urls = [normalize_url(value) for value in frame[url_column].tolist()]
    urls = [url for url in urls if url]
    if not urls:
        raise SystemExit("No valid URL was found in the URL column.")

    session = build_session()
    results: list[dict[str, str]] = []
    failures: list[tuple[str, str]] = []

    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] Crawling: {url}")
        try:
            results.append(crawl_page(session, url))
        except Exception as error:
            failures.append((url, str(error)))
            results.append(
                {"Page URL": url, "Title": "", "Description": "", "Body Content": ""}
            )
            print(f"  Error: {error}")
        time.sleep(0.5)  # Reduce server load; increase this delay if necessary.

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results, columns=OUTPUT_COLUMNS).to_excel(
        output_path, index=False, sheet_name="Crawled Content"
    )

    print(f"\nOutput saved to: {output_path.resolve()}")
    print(f"Successful: {len(results) - len(failures)} | Failed: {len(failures)}")
    if failures:
        print("Failed URLs remain in the output with empty content cells.")


if __name__ == "__main__":
    main()
