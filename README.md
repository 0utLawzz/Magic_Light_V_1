# MagicLight Auto 🪄

<div align="center">

![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge&logo=python)
![Playwright](https://img.shields.io/badge/playwright-1.40%2B-green?style=for-the-badge)
![FFmpeg](https://img.shields.io/badge/FFmpeg-4.4%2B-orange?style=for-the-badge)
![Version](https://img.shields.io/badge/version-v2.1.0-brightgreen?style=for-the-badge)

**Automated kids story video pipeline**
MagicLight.ai generation → FFmpeg processing → Google Drive upload → Sheets tracking

</div>

---

## What It Does

1. Reads pending stories from a Google Sheet.
2. Logs into MagicLight.ai with auto-account rotation (from `accounts.txt`).
3. Generates the video clips and automatically clicks through the Storyboard to the final Video output.
4. Downloads the raw video + thumbnail.
5. Optionally processes the video (Applies logo overlay, trims the outro).
6. Uploads outputs to Google Drive.
7. Writes Drive links, run metadata, and credit balances back to the Google Sheet.

---

## ⚙️ Setup Instructions

### 1. Clone & Install

```bash
git clone https://github.com/net2t/Magiclight-Automation.git
cd Magiclight-Automation
# (Optional) Create venv
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill it out:

```bash
   cp .env.example .env
```
> **Note:** The script relies entirely on `.env` and authentication files. 

### 3. Authentication & Credentials

**Google Cloud Services:**
1. Enable **Google Sheets API** and **Google Drive API** in your Google Cloud Console.
2. Create a Service Account, generate a JSON key, and save it as `credentials.json` in the root folder.
3. Share your target Google Sheet and Google Drive folder with the Service Account email.

*Note: Since you asked if `auth` JSONs are necessary: Yes, Google requires `credentials.json` (or `token.json`/`oauth_credentials.json` if using OAuth instead) in order for the bot to edit the tracking spreadsheet and upload to Drive.*

**MagicLight Accounts (`accounts.txt`):**
Create an `accounts.txt` file in the root directory. Place one account per line in `email:password` format. The script will automatically shuffle these to prevent account blocking, and rotate across them if credits run low.

```text
email1@gmail.com:Password1
email2@gmail.com:Password2
```

### 4. Create Directory Assets
If running Video Encoding Process locally, place your logo at `assets/logo.png`. 

---

## 📊 Google Sheet Structure

You must configure a specific 21-column layout in your Google Sheets file for the bot to read/write accurately. 

> **Quick setup:** Run `python main.py --migrate-schema` to automatically build these 21 columns in your linked Sheet.

For a full breakdown of all columns, see the [Sheet Structure Documentation (docs/SHEET_STRUCTURE.md)](docs/SHEET_STRUCTURE.md).

---

## 🚀 Running the Pipeline

### Local CLI Menu

Simply run `main.py`! The console will display a clean prompt to pick your automation mode:

```bash
python main.py
```

**Options:**
1. **Full Pipeline:** Generate Video + Encode/Process Video + Upload to Drive.
2. **Just Video Story Making:** Generate Video + Upload raw version to Drive.
3. **Video Encoding Process:** Scan local `output/` files, process them with FFmpeg + Upload to Drive.

*The script will ask you how many stories to process, if you want it to run on Loop, and if you want to push to Drive.*

---

## ☁️ GitHub Actions Workflow (Fully Automatic)

You can run the script remotely on GitHub Actions. It is programmed to automatically handle Drive Uploads.

### Setup Repository Secrets
Go to your GitHub repository -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**.

You must add the following Secrets:
1. `ENV_FILE`: Paste the full contents of your `.env` file.
2. `ACCOUNTS_TXT`: Paste the full contents of your `accounts.txt`.
3. `GCP_CREDENTIALS`: Paste the full contents of your `credentials.json`.

### Trigger The Workflow
1. Navigate to the **Actions** tab in your GitHub repository.
2. Select **MagicLight Generation Pipeline** on the left.
3. Click the **Run workflow** dropdown.
4. You will see a panel where you can define:
   * **Mode** (`combined`, `generate`, `process`)
   * **Quantity Limit** (How many pending rows to process)
   * **Upload to Google Drive?** (Checkbox)
   * **Run Loop Option?** (Checkbox)
5. Click **Run**. The server will take care of the rest automatically!
