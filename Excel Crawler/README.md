# Excel URL Content Crawler

A simple Python script that reads page URLs from an Excel file, visits each URL, and saves the main page content in a new Excel file.

The crawler extracts:

- Page URL
- Page title
- Meta description
- Main body content

It tries to remove repeated website sections such as headers, footers, navigation menus, sidebars, forms, popups, comments, and related-post blocks.

## Requirements

- Python 3.10 or newer
- An `.xlsx` input file
- Internet access

## Installation

Open PowerShell, Command Prompt, or the VS Code terminal and install the required packages:

```bash
python -m pip install pandas openpyxl requests beautifulsoup4 lxml trafilatura
```

If `python` is not recognized, try:

```bash
py -m pip install pandas openpyxl requests beautifulsoup4 lxml trafilatura
```

It is recommended to use a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Then install the packages:

```bash
python -m pip install pandas openpyxl requests beautifulsoup4 lxml trafilatura
```

## Input File

Create an Excel file with the page URLs in one column. The first row must contain a column name.

Example:

| URL |
| --- |
| https://example.com/ |
| https://example.com/about/ |
| https://example.com/blog/example-post/ |

The script recognizes common column names such as:

- `url`
- `urls`
- `link`
- `links`
- `address`

If none of these names are found, the script uses the first column in the Excel file.

URLs without `http://` or `https://` are automatically treated as HTTPS URLs.

## Usage

Run the script from the terminal:

```bash
python excel_url_content_crawler.py
```

The script will ask for the input Excel file path:

```text
Enter the input Excel file path:
```

Example:

```text
C:\SEO\urls.xlsx
```

It will then ask for the output file path:

```text
Enter the output Excel file path:
```

Press Enter to use the default output path. The default file is created next to the input file with `_crawled` added to its name.

Example:

```text
urls_crawled.xlsx
```

## Output File

The output Excel file contains these columns in this order:

| Column | Description |
| --- | --- |
| Page URL | The original page URL |
| Title | The HTML title or Open Graph title |
| Description | The meta description or Open Graph description |
| Body Content | The extracted main content of the page |

## How Content Extraction Works

The script uses Trafilatura to detect the main content of articles and landing pages. It removes most repeated layout sections automatically.

If Trafilatura cannot find the main content, the script uses a fallback method. The fallback removes common layout elements and then reads the content inside the page's `main`, `article`, or `body` element.

## Error Handling

The script retries temporary server errors up to three times.

If a URL cannot be processed:

- The crawler continues with the next URL.
- The failed URL remains in the output file.
- Its title, description, and body cells are left empty.
- The error is shown in the terminal.

The script also waits 0.5 seconds between pages to reduce server load.

## Limitations

- The crawler reads the HTML returned by the server.
- It may not extract content that appears only after JavaScript runs.
- Login-protected pages are not supported.
- Some websites may block automated requests.
- Excel cells can hold a maximum of 32,767 characters, so very long page content may be limited by Excel.
- Content extraction is automatic and may need custom rules for unusual website layouts.

For JavaScript-heavy websites, a browser automation tool such as Playwright may be required.

## Responsible Use

Only crawl websites that you own or have permission to access. Respect the website's terms, robots rules, rate limits, and server resources.

## Project File

```text
excel_url_content_crawler.py
```

## License

You can add the license that best fits your project, such as the MIT License.
