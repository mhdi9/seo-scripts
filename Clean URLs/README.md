# Clean URLs

This Python script removes rows from an Excel file when a selected column contains a specific piece of text. The result is saved as a new Excel file.

## Requirements

- Python 3.10 or newer
- An Excel input file

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
python -m pip install pandas openpyxl
```

## Run

```bash
python clean-urls-functional.py
```

The script will ask for:

1. The full path to the input Excel file
2. The full path for the output Excel file
3. The name of the column to check, such as `URL`
4. The exact text to find, such as `otp?` or `#respond`

Rows containing that text are removed. The search is case-insensitive and does not treat the input as a regular expression.

## Example

```text
Input file: C:\Data\urls.xlsx
Output file: C:\Data\cleaned-urls.xlsx
Column: URL
Text to remove: otp?
```

The original input file is not changed.
