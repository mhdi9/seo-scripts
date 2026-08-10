# Google Search Console URL Inspection

This Python script checks a list of URLs with the Google Search Console URL Inspection API. It also requests each live URL using a Googlebot user agent and creates a CSV report.

## Requirements

- Python 3.10 or newer
- A Google Cloud project
- Google Search Console API enabled in that project
- OAuth credentials for a Desktop app
- Access to the relevant Search Console property
- A CSV input file with URLs in its first column

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
python -m pip install pandas requests beautifulsoup4 google-auth google-auth-oauthlib google-api-python-client
```

## Google API Setup

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable the **Google Search Console API**.
4. Configure the OAuth consent screen.
5. Create an OAuth Client ID with **Desktop app** as the application type.
6. Download the client JSON file.
7. Make sure the Google account used during sign-in has access to the Search Console property.

## Script Configuration

Open `GSC-Inspection-v2.py` and update:

```python
CLIENT_SECRET_FILE = r"PATH_TO_CLIENT_SECRET_JSON"
SITE_URL = "https://example.com/"
INPUT_CSV = r"PATH_TO_INPUT_CSV"
OUTPUT_CSV = r"PATH_TO_OUTPUT_CSV"
```

`SITE_URL` must exactly match the property name in Google Search Console. URL-prefix properties normally include a trailing slash.

## Run

```bash
python GSC-Inspection-v2.py
```

During the first run, a browser window will open for Google authorization. After approval, the script creates `token.json` and reuses it in future runs.

The output CSV includes GSC inspection data, live HTTP checks, robots directives, canonical information, errors, and a final status for every URL.

## Security

Do not upload these files to GitHub:

```gitignore
token.json
client_secret*.json
.venv/
__pycache__/
```

The URL Inspection API has usage limits. Large URL lists may take time and can reach the API quota.
