# QR Code Generator

This Python script creates a QR code from a URL and saves it in both PNG and PDF formats.

## Requirements

- Python 3.10 or newer

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
python -m pip install "qrcode[pil]" reportlab
```

## Run

```bash
python generate_qr.py
```

Enter the URL when requested:

```text
https://example.com
```

If the URL does not start with `http://` or `https://`, the script automatically adds `https://`.

## Output

The script creates a folder named `qr_codes` in the current working directory and saves two timestamped files:

```text
qr_20260101_123000.png
qr_20260101_123000.pdf
```

The PDF contains the QR code and a shortened display version of the URL.
