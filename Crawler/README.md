# Website Crawler

This Python script crawls the internal pages of a website and creates an Excel report containing page information and internal content links.

The report includes:

- URL
- Page title
- Meta description
- Canonical URL
- Meta robots value
- First H1
- HTTP status code
- Internal link source, destination, anchor text, and status code

## Requirements

- Python 3.10 or newer
- Internet access

## Setup on a New System

Open a terminal in this folder and create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```powershell
.venv\Scripts\activate
```

Activate it on macOS or Linux:

```bash
source .venv/bin/activate
```

Install all required packages with one command:

```bash
python -m pip install pandas requests beautifulsoup4 tqdm openpyxl lxml
```

## Run

```bash
python crawl-v4.py
```

Enter the full website URL, including `https://`:

```text
https://example.com
```

The script will then ask for comma-separated regular expression patterns to skip. Press Enter to crawl without skip patterns.

Example:

```text
login,admin,/cart/
```

## Output

The Excel report is saved next to the script with a timestamped name similar to:

```text
site_crawl_2026-01-01_12-30-00.xlsx
```

It contains two sheets:

- `crawl data`
- `internal links`

Press `Ctrl+C` to stop the crawl early. The script will save the data collected up to that point.

Only crawl websites you are authorized to access. Large websites can take a long time to finish.
