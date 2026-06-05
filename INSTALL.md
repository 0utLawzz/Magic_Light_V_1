# Installation Guide

## Requirements

- Python 3.10+
- FFmpeg on system PATH
- Google service account JSON (Sheets + Drive APIs)

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Place `credentials.json` in the project root and fill in `.env`.

## GitHub Actions

Add secrets: `ENV_FILE`, `ACCOUNTS_TXT`, `GCP_CREDENTIALS`.

---

**By OutLawZ™** | https://www.brandex.pk | net2tara@gmail.com
