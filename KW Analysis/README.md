# Keyword Analysis

This Python script filters keyword data stored in a CSV or Excel file. It can filter queries by minimum word count, a regular expression, or both.

Persian text is normalized before filtering by removing zero-width characters and extra spaces. The original columns and values are preserved in the output.

## Requirements

- Python 3.10 or newer
- A CSV or Excel input file

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
python kw-analysis.py
```

The script will ask for:

1. The input CSV or Excel file path
2. The output file path
3. The query column name
4. The minimum number of words, or Enter to skip
5. A regular expression, or Enter to skip

## Regex Example

To keep queries containing any of these words:

```text
why|how|where
```

To keep all rows without applying a filter, press Enter for both the minimum word count and regular expression questions.

The output format is selected from the output filename. Use `.csv` for CSV output or `.xlsx` for Excel output.
