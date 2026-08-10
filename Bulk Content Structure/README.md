# Bulk Content Structure Generator

This Python script reads article titles from an Excel file, sends each title and a base prompt to an API, and saves every generated content structure as a separate Markdown file.

## Requirements

- Python 3.10 or newer
- An Excel file with a column named `title`
- A text file containing the base prompt
- A valid API URL, bearer token, and session ID

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
python -m pip install pandas requests openpyxl
```

## Configuration

Open `bulk-content-structure2.py` and update these values:

```python
API_URL = "YOUR_API_URL"
BEARER_TOKEN = "YOUR_BEARER_TOKEN"
SESSION_ID = "YOUR_SESSION_ID"
```

Also update the file paths near the bottom of the script:

```python
excel_file = r"PATH_TO_INPUT_EXCEL_FILE"
prompt_file = r"PATH_TO_PROMPT_TEXT_FILE"
output_directory = r"PATH_TO_OUTPUT_FOLDER"
```

The Excel file must contain a column named exactly `title`.

## Run

```bash
python bulk-content-structure2.py
```

The generated Markdown files will be saved in the configured output folder.

## Security Warning

Never publish bearer tokens in GitHub. Remove the token currently stored in the script and revoke or rotate it before publishing the repository. Environment variables are recommended for storing secrets.
