"""
MagicLight Auto — Kids Story Video Pipeline
===========================================
Version : 2.0.3  [Sheet Write Guaranteed]
Released: 2026-04-11
Repo    : https://github.com/net2t/MagicLight-Auto

Three Modes:
  combined  — Generate → FFmpeg Process → Upload (full pipeline)
  generate  — Video generation only (MagicLight.ai automation)
  process   — FFmpeg post-processing only

Flags:
  --mode combined|generate|process
  --max N        Stories limit (0 = all pending)
  --upload-drive Upload to Google Drive
  --headless     Run browser without UI
  --loop         Infinite loop (1 story per cycle)
  --debug        Verbose debug logging
  --dry-run      Preview only, no encoding
  --migrate-schema  Write correct headers to sheet (run once)

Usage:
    python main.py                              # Interactive menu
    python main.py --mode combined --max 1      # Full pipeline, 1 story
    python main.py --mode generate --max 5 --upload-drive --headless
    python main.py --mode process --upload-drive
    python main.py --mode combined --loop --upload-drive --headless
    python main.py --migrate-schema
"""

__version__ = "2.0.3"

import re
import os
import sys
import time
from pathlib import Path
import subprocess
import signal
import warnings
import argparse
import json
import shutil

_has_rich = True
try:
    from rich.progress import (Progress, SpinnerColumn, TextColumn,
                                BarColumn, TimeElapsedColumn)
except ImportError:
    _has_rich = False

VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv'}
import requests
import gdown
from datetime import datetime

if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console(highlight=False, emoji=False)

DEBUG = os.getenv("DEBUG", "0") == "1"

def _step(label): console.print(f"\n[bold cyan]{label}[/bold cyan]")
def _ok(msg):     console.print(f"  [bold green]OK[/bold green] {msg}")
def _warn(msg):   console.print(f"  [bold yellow]!![/bold yellow]  {msg}")
def _err(msg):    console.print(f"  [bold red]XX[/bold red] {msg}")
def _info(msg):   console.print(f"  [dim]{msg}[/dim]")
def _dbg(msg):
    if DEBUG: console.print(f"  [dim magenta][DBG] {msg}[/dim magenta]")

# ── Config ────────────────────────────────────────────────────────────────────
_ENV_PATH = Path(__file__).resolve().with_name(".env")
load_dotenv(dotenv_path=_ENV_PATH, override=True)

EMAIL    = os.getenv("EMAIL", "")
PASSWORD = os.getenv("PASSWORD", "")

SHEET_ID        = os.getenv("SHEET_ID",   "")
SHEET_NAME      = os.getenv("SHEET_NAME", "Database")
CREDS_JSON      = os.getenv("CREDS_JSON", "credentials.json")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")

STEP1_WAIT     = int(os.getenv("STEP1_WAIT",            "60"))
STEP2_WAIT     = int(os.getenv("STEP2_WAIT",            "30"))
STEP3_WAIT     = int(os.getenv("STEP3_WAIT",           "180"))
RENDER_TIMEOUT = int(os.getenv("STEP4_RENDER_TIMEOUT", "1200"))
POLL_INTERVAL  = 10
RELOAD_INTERVAL = 120

OUT_BASE  = "output"
OUT_SHOTS = os.path.join(OUT_BASE, "screenshots")

MAGICLIGHT_OUTPUT   = Path(os.getenv("MAGICLIGHT_OUTPUT", OUT_BASE))
LOGO_PATH           = Path(os.getenv("LOGO_PATH",   "assets/logo.png"))
ENDSCREEN_VIDEO     = Path(os.getenv("ENDSCREEN_VIDEO", "assets/endscreen.mp4"))

TRIM_SECONDS        = int(os.getenv("TRIM_SECONDS",   "4"))
LOGO_X              = int(os.getenv("LOGO_X",         "7"))
LOGO_Y              = int(os.getenv("LOGO_Y",         "5"))
LOGO_WIDTH          = int(os.getenv("LOGO_WIDTH",     "300"))
LOGO_OPACITY        = float(os.getenv("LOGO_OPACITY", "1.0"))
ENDSCREEN_ENABLED   = os.getenv("ENDSCREEN_ENABLED",  "true").lower() == "true"
ENDSCREEN_DURATION  = os.getenv("ENDSCREEN_DURATION", "auto")
UPLOAD_TO_DRIVE     = os.getenv("UPLOAD_TO_DRIVE", "false").lower() == "true"

_shutdown = False
_browser  = None

def close_browser():
    """Close the browser cleanly."""
    global _browser
    if _browser:
        try:
            _info("[browser] Closing browser...")
            for context in _browser.contexts:
                try:
                    for page in context.pages:
                        page.close()
                except: pass
                context.close()
            _browser.close()
            _browser = None
            _ok("[browser] Browser closed")
        except Exception as e:
            _warn(f"[browser] Error closing browser: {e}")

def _sig(sig, frame):
    global _shutdown, _browser
    _warn("[STOP] Ctrl+C — cleaning up...")
    _shutdown = True
    close_browser()
    import os as _os
    _os._exit(1)

signal.signal(signal.SIGINT, _sig)

for _d in [OUT_BASE, OUT_SHOTS]:
    os.makedirs(_d, exist_ok=True)

# ── Google Sheets ─────────────────────────────────────────────────────────────
import gspread
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

_gc    = None
_ws    = None
_hdr   = []
_cws   = None
CREDIT_PER_GEN = 60
_credits_total = 0
_credits_used  = 0

SHEET_SCHEMA: dict[str, int] = {
    "Status":           1,   # A
    "Theme":            2,   # B
    "Title":            3,   # C
    "Story":            4,   # D
    "Moral":            5,   # E
    "Gen_Title":        6,   # F
    "Gen_Summary":      7,   # G
    "Gen_Tags":         8,   # H
    "Project_URL":      9,   # I
    "Created_Time":    10,   # J
    "Completed_Time":  11,   # K
    "Notes":           12,   # L
    "Drive_Link":      13,   # M
    "DriveImg_Link":   14,   # N
    "Credit_Before":   15,   # O
    "Credit_After":    16,   # P
    "Email_Used":      17,   # Q
    "Credit_Acct":     18,   # R
    "Credit_Total":    19,   # S
    "Credit_Used":     20,   # T
    "Credit_Remaining": 21,  # U
}

LAYER_COLS: dict[str, set] = {
    "generation": set(SHEET_SCHEMA.keys()),
    "video":      set(SHEET_SCHEMA.keys()),
    "processing": set(SHEET_SCHEMA.keys()),
    "credit":     set(SHEET_SCHEMA.keys()),
}

def _get_service_account_credentials():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file"
    ]
    if not os.path.exists(CREDS_JSON):
        raise FileNotFoundError(f"Service account credentials not found: {CREDS_JSON}")
    return ServiceAccountCredentials.from_service_account_file(CREDS_JSON, scopes=scopes)

def _get_oauth_credentials():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file"
    ]
    oauth_file = "oauth_credentials.json"
    if not os.path.exists(oauth_file):
        raise FileNotFoundError(f"OAuth credentials file not found: {oauth_file}")
    token_file = "token.json"
    creds = None
    if os.path.exists(token_file):
        try:
            from google.auth.transport.requests import Request
            creds = Credentials.from_authorized_user_file(token_file, scopes)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
        except:
            creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(oauth_file, scopes)
        creds = flow.run_local_server(port=0, access_type='offline', prompt='consent')
        with open(token_file, 'w') as token:
            token.write(creds.to_json())
    return creds

def _get_credentials():
    try:
        if os.path.exists("oauth_credentials.json"):
            return _get_oauth_credentials()
    except:
        pass
    return _get_service_account_credentials()

def _get_sheet():
    global _gc, _ws, _hdr
    if _ws is not None:
        return _ws
    if not SHEET_ID:
        raise ValueError(f"SHEET_ID not set in .env (cwd={os.getcwd()}, env_path={_ENV_PATH})")
    creds = _get_credentials()
    _gc = gspread.authorize(creds)
    sh = _gc.open_by_key(SHEET_ID)
    _ws = sh.worksheet(SHEET_NAME)
    _hdr = _ws.row_values(1)
    return _ws

def ensure_credits_sheet():
    global _gc, _cws
    if _cws is not None:
        return _cws
    _get_sheet()
    sh = _gc.open_by_key(SHEET_ID)
    try:
        _cws = sh.worksheet("Credits")
    except Exception:
        _info("[credits] Creating Credits sheet...")
        _cws = sh.add_worksheet(title="Credits", rows="500", cols="10")
        _cws.update("A1:G1", [["Email", "Total_Credits", "Used_Credits",
                                "Remaining", "Last_Checked",
                                "Log_Timestamp", "Log_Detail"]])
        _ok("[credits] Credits sheet created")
    return _cws

def _read_credits_from_page(page):
    try:
        credit_selectors = [
            ".home-top-navbar-credit-amount",
            ".credit-amount",
            "[class*='credit']",
        ]
        credit_text = None
        for selector in credit_selectors:
            try:
                credit_element = page.locator(selector).first
                if credit_element.is_visible(timeout=2000):
                    credit_text = credit_element.inner_text().strip()
                    if credit_text and any(c.isdigit() for c in credit_text):
                        break
            except:
                continue
        if credit_text:
            clean_text = credit_text.replace(',', '')
            credit_match = re.search(r'(\d+)', clean_text)
            if credit_match:
                return int(credit_match.group(1)), 0
        return 0, 0
    except Exception as e:
        _warn(f"Error reading credits: {e}")
        return 0, 0

def _update_credits_login(email, total):
    try:
        ws = ensure_credits_sheet()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = ws.get_all_values()
        found_row = None
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0].strip().lower() == email.strip().lower():
                found_row = i
                break
        data = [email, str(total), "", "", now_str]
        if found_row:
            ws.update(f"A{found_row}:E{found_row}", [data])
        else:
            ws.append_row(data)
        return 0
    except Exception as e:
        _warn(f"[credits] Login update error: {e}")
        return 0

def _update_credits_completion(email, total, used, row_num, action, status):
    try:
        ws = ensure_credits_sheet()
        remaining = max(0, total - used)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = ws.get_all_values()
        found_row = None
        for i, row in enumerate(rows[1:], start=2):
            if row and row[0].strip().lower() == email.strip().lower():
                found_row = i
                break
        if found_row:
            detail = f"{action} | Row:{row_num} | Status:{status}"
            ws.update(f"C{found_row}:G{found_row}",
                      [[str(used), str(remaining), now_str, detail]])
        else:
            data = [email, str(total), str(used), str(remaining), now_str, now_str,
                    f"{action} | Row:{row_num} | Status:{status}"]
            ws.append_row(data)
    except Exception as e:
        _warn(f"[credits] Completion update error: {e}")

def _col(name: str) -> int | None:
    return SHEET_SCHEMA.get(name)

def read_sheet():
    ws = _get_sheet()
    return ws.get_all_records(head=1)

def _actual_sheet_cols() -> set:
    """Return set of column names that actually exist in row 1 of the sheet."""
    try:
        ws = _get_sheet()
        return set(h.strip() for h in _hdr if h.strip())
    except:
        return set(SHEET_SCHEMA.keys())

def update_sheet_row(sheet_row_num: int, layer: str | None = None, **kw):
    ws = _get_sheet()
    actual_cols = _actual_sheet_cols()
    for col_name, value in kw.items():
        col_idx = _col(col_name)
        if col_idx is None:
            _dbg(f"[sheet] IGNORED unknown column '{col_name}'")
            continue
        # Only write if the column header exists in the actual sheet
        if col_name not in actual_cols:
            _dbg(f"[sheet] SKIPPED '{col_name}' — not in sheet headers")
            continue
        try:
            ws.update_cell(sheet_row_num, col_idx, str(value) if value is not None else "")
            _dbg(f"[sheet] Row {sheet_row_num} col '{col_name}'({col_idx}) = '{str(value)[:40]}'")
        except Exception as e:
            _warn(f"[sheet] update_cell({col_name} → col {col_idx}): {e}")

def ensure_sheet_schema():
    ws = _get_sheet()
    headers = [""] * max(SHEET_SCHEMA.values())
    for name, idx in SHEET_SCHEMA.items():
        headers[idx - 1] = name
    end_col = chr(ord('A') + len(headers) - 1)
    ws.update(f"A1:{end_col}1", [headers])
    _ok(f"[schema] Headers written to row 1 (A–{end_col})")

def upload_to_drive(file_path, folder_name=None):
    file_path = str(file_path)
    if not file_path or not os.path.exists(file_path):
        _warn(f"[drive] File not found: {file_path}")
        return ""
    if not DRIVE_FOLDER_ID:
        _warn("[drive] DRIVE_FOLDER_ID not set — skipping upload")
        return ""
    if not folder_name:
        folder_name = Path(file_path).stem.replace('_processed', '').replace('_thumb', '')
    _info(f"[drive] Uploading {os.path.basename(file_path)}...")
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        creds = _get_credentials()
        service = build('drive', 'v3', credentials=creds)
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [DRIVE_FOLDER_ID]
        }
        try:
            resp = service.files().list(
                q=f"name='{folder_name}' and '{DRIVE_FOLDER_ID}' in parents and mimeType='application/vnd.google-apps.folder'",
                fields='files(id,name)'
            ).execute()
            folder_id = resp['files'][0]['id'] if resp.get('files') else \
                service.files().create(body=folder_metadata, fields='id').execute()['id']
        except Exception:
            folder_id = service.files().create(body=folder_metadata, fields='id').execute()['id']
        file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
        media = MediaFileUpload(file_path, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media,
                                       fields='id, webViewLink').execute()
        link = file.get('webViewLink', '')
        _ok(f"[drive] Uploaded -> {link}")
        return link
    except Exception as e:
        _warn(f"[drive] Upload failed: {e}")
        return ""

def upload_story_to_drive(story_folder, safe_name, video_path, thumb_path,
                           sheet_row_num=None):
    result = {"folder_link": "", "video_link": "", "thumb_link": ""}

    if not DRIVE_FOLDER_ID:
        _warn("[drive] DRIVE_FOLDER_ID not set — skipping Drive upload")
        return result

    if not video_path or not os.path.exists(str(video_path)):
        _warn(f"[drive] Video file missing: {video_path}")
        return result

    _info(f"[drive] Creating Drive folder for {safe_name}...")
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        creds = _get_credentials()
        service = build('drive', 'v3', credentials=creds)

        folder_meta = {
            'name': safe_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [DRIVE_FOLDER_ID]
        }
        folder = service.files().create(body=folder_meta, fields='id,webViewLink').execute()
        folder_id   = folder.get('id')
        result["folder_link"] = folder.get('webViewLink', '')
        _ok(f"[drive] Folder created -> {result['folder_link']}")

        _info("[drive] Uploading video...")
        vid_meta  = {'name': os.path.basename(str(video_path)), 'parents': [folder_id]}
        vid_media = MediaFileUpload(str(video_path), resumable=True)
        vid_file  = service.files().create(body=vid_meta, media_body=vid_media,
                                            fields='id,webViewLink').execute()
        result["video_link"] = vid_file.get('webViewLink', '')
        _ok(f"[drive] Video uploaded -> {result['video_link']}")

        # Write Drive_Link to sheet IMMEDIATELY after video upload
        if sheet_row_num:
            try:
                update_sheet_row(
                    sheet_row_num,
                    Drive_Link=result["video_link"],
                    Notes=f"Video uploaded to Drive"
                )
                _ok(f"[sheet] Row {sheet_row_num} Drive_Link written")
            except Exception as se:
                _warn(f"[sheet] Drive_Link write failed: {se}")

        # Thumbnail upload — optional, failure does not block
        if thumb_path and os.path.exists(str(thumb_path)):
            try:
                _info("[drive] Uploading thumbnail...")
                thumb_meta  = {'name': os.path.basename(str(thumb_path)), 'parents': [folder_id]}
                thumb_media = MediaFileUpload(str(thumb_path), resumable=True)
                thumb_file  = service.files().create(body=thumb_meta, media_body=thumb_media,
                                                      fields='id,webViewLink').execute()
                result["thumb_link"] = thumb_file.get('webViewLink', '')
                _ok(f"[drive] Thumbnail uploaded -> {result['thumb_link']}")
                if sheet_row_num and result["thumb_link"]:
                    try:
                        update_sheet_row(sheet_row_num, DriveImg_Link=result["thumb_link"])
                    except Exception as se:
                        _warn(f"[sheet] DriveImg_Link write failed: {se}")
            except Exception as te:
                _warn(f"[drive] Thumbnail upload failed (non-fatal): {te}")
        else:
            _info("[drive] No thumbnail to upload")

        _ok(f"[drive] Story upload complete!")
        return result

    except Exception as e:
        _warn(f"[drive] Drive upload failed: {e}")
        if result["video_link"] and sheet_row_num:
            try:
                update_sheet_row(sheet_row_num, Drive_Link=result["video_link"])
            except: pass
        return result

def story_dir(safe_name):
    d = os.path.join(OUT_BASE, safe_name)
    os.makedirs(d, exist_ok=True)
    return d

def cleanup_local_files_if_drive_only(story_folder, video_path=None, thumb_path=None):
    if os.environ.get("DRIVE_ONLY_MODE") == "true":
        _info("[Drive-only] Cleaning up local files...")
        try:
            if video_path and os.path.exists(str(video_path)):
                os.remove(str(video_path))
            if thumb_path and os.path.exists(str(thumb_path)):
                os.remove(str(thumb_path))
            if story_folder and os.path.exists(story_folder):
                for file in Path(story_folder).glob("*_processed.*"):
                    file.unlink()
                if not any(Path(story_folder).iterdir()):
                    shutil.rmtree(story_folder)
        except Exception as e:
            _warn(f"[Drive-only] Cleanup error: {e}")

# ── Sleep helpers ─────────────────────────────────────────────────────────────
def sleep_log(seconds, reason=""):
    secs = int(seconds)
    if secs <= 0: return
    label = f" ({reason})" if reason else ""
    _info(f"[wait] {secs}s{label}...")
    for _ in range(secs):
        if _shutdown: return
        time.sleep(1)

def _wait_dismissing(page, seconds, reason=""):
    label = f" ({reason})" if reason else ""
    _info(f"[wait] {seconds}s{label} (popup-watch)...")
    start = time.time()
    last_pct = ""
    while time.time() - start < seconds:
        if _shutdown: return
        pct = min(100, int((time.time() - start) / seconds * 100))
        if str(pct) != last_pct and pct % 5 == 0:
            console.print(f"  [cyan]>[/cyan] Waiting{label}... [bold]{pct}%[/bold]")
            last_pct = str(pct)
        _dismiss_all(page)
        time.sleep(1)

# ── Popup helpers ─────────────────────────────────────────────────────────────
def _all_frames(page):
    try: return page.frames
    except: return [page]

_CLOSE_SELECTORS = [
    'button.notice-popup-modal__close',
    'button[aria-label="close"]',
    'button[aria-label="Close"]',
    '.sora2-modal-close',
    'button:has-text("Got it")',
    'button:has-text("Got It")',
    'button:has-text("Later")',
    'button:has-text("Not now")',
    'button:has-text("No thanks")',
    '.notice-bar__close',
    '.arco-modal-close-btn',
    '.arco-icon-close',
    'button.arco-btn-secondary:has-text("Cancel")',
    'button:has-text("Skip")',
    'button.close-btn',
    'span[class*="close"]'
]

_PROMO_CLOSE_JS = """\
() => {
    const promoClose = Array.from(document.querySelectorAll(
        '[class*="privilege-modal"] [class*="close"],' +
        '[class*="new-year"] [class*="close"],' +
        '[class*="promo"] [class*="close"],' +
        '[class*="upgrade"] [class*="close"],' +
        '.arco-modal-close-btn'
    )).filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    });
    if (promoClose.length) { promoClose[0].click(); return 'promo-closed'; }
    const svgBtns = Array.from(document.querySelectorAll(
        '.arco-modal .arco-modal-close-btn, .arco-modal-close-btn'
    )).filter(el => el.getBoundingClientRect().width > 0);
    if (svgBtns.length) { svgBtns[0].click(); return 'modal-x-closed'; }
    return null;
}"""

_POPUP_JS = """\
() => {
    const BAD = ["Got it","Got It","Close","Done","OK","Later","No thanks",
                 "Maybe later","Not now","Dismiss","Close samples","No","Cancel","Skip"];
    let n = 0;
    document.querySelectorAll('button,span,div,a').forEach(el => {
        const t = (el.innerText || el.textContent || '').trim();
        if (BAD.includes(t)) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { el.click(); n++; }
        }
    });
    document.querySelectorAll(
        '.arco-modal-mask,.driver-overlay,.diy-tour__mask,[class*="tour-mask"],[class*="modal-mask"]'
    ).forEach(el => { try { el.style.display='none'; } catch(e){} });
    return n;
}"""

def _dismiss_all(page):
    for fr in _all_frames(page):
        try: page.evaluate(_PROMO_CLOSE_JS)
        except: pass
        try: page.evaluate(_POPUP_JS)
        except: pass
        for sel in _CLOSE_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(timeout=1000)
            except: pass

def dismiss_popups(page, timeout=10, sweeps=3):
    for _ in range(sweeps):
        if _shutdown: return
        _dismiss_all(page)
        try: page.wait_for_timeout(800)
        except: time.sleep(0.8)

_REAL_DIALOG_JS = """\
() => {
    const masks = Array.from(document.querySelectorAll(
        '.arco-modal-mask,[class*="modal-mask"]'
    )).filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 100 && r.height > 100;
    });
    if (!masks.length) return null;
    const chk = Array.from(document.querySelectorAll(
        'input[type="checkbox"],.arco-checkbox-icon,label[class*="checkbox"]'
    )).find(el => {
        const par = el.closest('label') || el.parentElement;
        const txt = ((par && par.innerText) || el.innerText || '').toLowerCase();
        return txt.includes('remind') || txt.includes('again') || txt.includes('ask');
    });
    if (chk) { try { chk.click(); } catch(e) {} }
    const xBtn = document.querySelector(
        '.arco-modal-close-btn,[aria-label="Close"],[aria-label="close"],' +
        '.arco-icon-close,[class*="modal-close"],[class*="close-icon"]'
    );
    if (xBtn && xBtn.getBoundingClientRect().width > 0) {
        xBtn.click(); return 'dialog: closed X';
    }
    const wrapper = document.querySelector('.arco-modal-wrapper');
    if (wrapper) {
        wrapper.remove();
        masks.forEach(m => m.remove());
        return 'dialog: removed wrapper';
    }
    return 'dialog: mask found but no X';
}"""

def _dismiss_animation_modal(page):
    try: page.evaluate(_PROMO_CLOSE_JS)
    except: pass
    try:
        r = page.evaluate(_REAL_DIALOG_JS)
        if r:
            _info(f"[modal] {r}")
            time.sleep(2); return
    except: pass
    for sel in ["label:has-text(\"Don't remind again\")", "label:has-text(\"Don't ask again\")"]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500); time.sleep(0.5)
        except: pass
    for sel in ['.arco-modal-close-btn', 'button[aria-label="Close"]', '.arco-icon-close']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                loc.click(timeout=2000)
                time.sleep(2); return
        except: pass
    try: page.keyboard.press("Escape"); time.sleep(0.5)
    except: pass

def _wait_for_preview_page(page, timeout=60):
    _info("[post-render] Waiting for preview page...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        found = page.evaluate("""\
() => {
    const items = document.querySelectorAll('.previewer-new-body-right-item');
    const dlBtn = Array.from(document.querySelectorAll('button,a')).find(el => {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        return r.width > 0 && (t === 'Download video' || t === 'Download Video');
    });
    if (items.length > 0 || dlBtn) return true;
    return false;
}""")
        if found:
            _ok("Preview page loaded")
            return True
        time.sleep(2)
    _warn("Preview page timeout")
    return False

def _handle_generated_popup(page):
    _info("[post-render] Checking for generated popup...")
    submitted = False
    deadline = time.time() + 15
    while time.time() < deadline:
        for sel in [
            "button:has-text('Submit')",
            "button.arco-btn:has-text('Submit')",
            ".arco-modal button:has-text('Submit')",
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    _ok("Submit clicked")
                    submitted = True; break
            except: pass
        if submitted: break
        time.sleep(2)
    if submitted:
        sleep_log(4, "post-submit settle")
        _wait_for_preview_page(page, timeout=30)
    dl_deadline = time.time() + 30
    while time.time() < dl_deadline:
        for sel in [
            "button:has-text('Download video')",
            "a:has-text('Download video')",
            "button:has-text('Download Video')",
            "a:has-text('Download Video')",
        ]:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click()
                    _ok("Download video clicked")
                    return True
            except: pass
        time.sleep(2)
    _warn("[post-render] Download video button not found")
    return False

# ── DOM helpers ───────────────────────────────────────────────────────────────
def wait_site_loaded(page, key_locator=None, timeout=60):
    try: page.wait_for_load_state("domcontentloaded", timeout=timeout * 1000)
    except: pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        try:
            if page.evaluate("document.readyState") in ("interactive", "complete"):
                break
        except: pass
        time.sleep(0.3)
    if key_locator is not None:
        try:
            key_locator.wait_for(
                state="visible",
                timeout=max(1000, int((deadline - time.time()) * 1000))
            )
        except: return False
    return True

def dom_click_text(page, texts, timeout=60):
    js = """\
(texts) => {
    const all = Array.from(document.querySelectorAll(
        'button,div[class*="btn"],span[class*="btn"],a,' +
        'div[class*="vlog-btn"],div[class*="footer-btn"],' +
        'div[class*="shiny-action"],div[class*="header-left-btn"]'
    ));
    for (let i = all.length - 1; i >= 0; i--) {
        const el = all[i]; let dt = '';
        el.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) dt += n.textContent; });
        const t = dt.trim() || (el.innerText || '').trim();
        if (texts.includes(t)) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { el.click(); return t; }
        }
    }
    return null;
}"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        r = page.evaluate(js, texts)
        if r:
            _info(f"  '{r}'")
            return True
        time.sleep(2)
    return False

def dom_click_class(page, cls, timeout=30):
    js = f"""\
() => {{
    const all = Array.from(document.querySelectorAll('[class*="{cls}"]'));
    for (let i = all.length-1; i >= 0; i--) {{
        const el = all[i], r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {{ el.click(); return el.className; }}
    }}
    return null;
}}"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown: return False
        r = page.evaluate(js)
        if r: return True
        time.sleep(2)
    return False

def screenshot(page, name):
    path = os.path.join(OUT_SHOTS, f"{name}_{int(time.time())}.png")
    try: page.screenshot(path=path, full_page=True)
    except: pass
    return path

def debug_buttons(page):
    js = """\
() => Array.from(document.querySelectorAll(
    'button,div[class*="btn"],span[class*="btn"],a,div[class*="vlog-btn"]'
)).filter(el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && (el.innerText || '').trim();
}).map(el =>
    el.tagName + '.' + el.className.substring(0, 40) +
    ' | ' + (el.innerText || '').trim().substring(0, 60)
);"""
    try:
        items = page.evaluate(js)
        _info(f"[debug-url] {page.url}")
        for i in (items or []): _info(f"  {i}")
    except: pass

def _credit_exhausted(page):
    try:
        body = page.evaluate("() => (document.body && document.body.innerText) || ''")
        for kw in ["insufficient credits", "not enough credits", "out of credits",
                   "credits exhausted", "quota exceeded"]:
            if kw in body.lower():
                return True
    except: pass
    return False

# ── LOGIN ─────────────────────────────────────────────────────────────────────
def _logout(page):
    _info("   Clearing session...")
    try:
        page.goto("https://magiclight.ai/", timeout=30000)
        wait_site_loaded(page, None, timeout=20)
        time.sleep(2)
        page.evaluate("""\
() => {
    const logoutTexts = ['Log out','Logout','Sign out','Sign Out','Log Out'];
    const els = Array.from(document.querySelectorAll('a,button,div,span'));
    for (const el of els) {
        const t = (el.innerText || '').trim();
        if (logoutTexts.includes(t) && el.getBoundingClientRect().width > 0) {
            el.click(); return t;
        }
    }
    return null;
}""")
        time.sleep(1)
    except: pass
    try: page.context.clear_cookies()
    except: pass

def login(page, custom_email=None, custom_pw=None):
    _step("[Login] Starting fresh login...")
    try: page.context.clear_cookies()
    except: pass
    _logout(page)
    page.goto("https://magiclight.ai/login/?to=%252Fkids-story%252F", timeout=60000)
    try: page.wait_for_load_state("networkidle", timeout=15000)
    except: pass
    sleep_log(3, "page settle")
    clicked_email_tab = False
    for sel in ['.entry-email', 'text=Log in with Email',
                'button:has-text("Log in with Email")', '[class*="entry-email"]']:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=3000):
                loc.click(timeout=5000)
                clicked_email_tab = True
                sleep_log(3, "inputs settle")
                break
        except: pass
    if not clicked_email_tab:
        page.evaluate("""() => {
            const el = document.querySelector('.entry-email') ||
                       [...document.querySelectorAll('button')].find(b => b.innerText.includes('Email'));
            if (el) el.click();
        }""")
        sleep_log(2)
    email_filled = False
    for sel in ['input[type="text"]', 'input[type="email"]', 'input[name="email"]',
                'input.arco-input', 'input[placeholder*="mail" i]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=15000)
            loc.scroll_into_view_if_needed()
            loc.click()
            page.wait_for_timeout(500)
            loc.fill(custom_email or EMAIL)
            email_filled = True; break
        except: continue
    if not email_filled:
        screenshot(page, "login_fail_no_email")
        raise Exception("Login failed — email input not found")
    page.wait_for_timeout(500)
    pass_filled = False
    for sel in ['input[type="password"]', 'input[name="password"]',
                'input[placeholder*="password" i]']:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=8000)
            loc.fill(custom_pw or PASSWORD)
            pass_filled = True; break
        except: continue
    if not pass_filled:
        raise Exception("Login failed — password input not found")
    clicked = False
    for attempt in range(3):
        for sel in [".signin-continue", "text=Continue", "div.signin-continue",
                    "button:has-text('Continue')", "button.arco-btn-primary"]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click(); clicked = True; break
            except: pass
        if clicked: break
        page.wait_for_timeout(2000)
    if not clicked:
        raise Exception("Login failed — Continue button not found")
    try:
        page.wait_for_url("**/kids-story/**", timeout=30000)
    except:
        page.wait_for_timeout(5000)
    _ok(f"[Login] Logged in -> {page.url}")
    page.wait_for_timeout(3000)
    dismiss_popups(page, timeout=10, sweeps=4)
    _ok("[Login] Post-login popups cleared")
    _step("[credits] Reading credits from User Center...")
    try:
        page.goto("https://magiclight.ai/user-center", timeout=45000)
        page.wait_for_selector(".home-top-navbar-credit-amount, .credit-amount",
                                state="visible", timeout=15000)
        sleep_log(2, "user center settle")
    except Exception as e:
        _warn(f"[credits] Could not load user center: {e}")
    global _credits_total, _credits_used
    total, used = _read_credits_from_page(page)
    if total > 0:
        _credits_total = total
        _update_credits_login(custom_email or EMAIL, total)
    else:
        _warn("[credits] Could not read credit count")
    try:
        page.goto("https://magiclight.ai/kids-story/", timeout=45000)
        wait_site_loaded(page, None, timeout=30)
    except: pass

# ── STEP 1: Story Input ───────────────────────────────────────────────────────
def step1(page, story_text):
    _step("[Step 1] Story input ->")
    page.goto("https://magiclight.ai/kids-story/", timeout=60000)
    wait_site_loaded(page, None, timeout=60)
    dismiss_popups(page, timeout=10)
    ta = page.get_by_role("textbox", name="Please enter an original")
    wait_site_loaded(page, ta, timeout=60)
    dismiss_popups(page, timeout=6)
    ta.wait_for(state="visible", timeout=20000)
    ta.click(); ta.fill(story_text)
    _ok("Story text filled")
    sleep_log(1)
    try:
        page.locator("div").filter(has_text=re.compile(r"^Pixar 2\.0$")).first.click()
        _ok("Style: Pixar 2.0")
    except: _warn("Pixar 2.0 not found — default")
    try:
        page.locator("div").filter(has_text=re.compile(r"^16:9$")).first.click()
        _ok("Aspect: 16:9")
    except: _warn("16:9 not found — default")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    sleep_log(1)
    _select_dropdown(page, "Voiceover", "Sophia")
    _select_dropdown(page, "Background Music", "Silica")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    sleep_log(1)
    clicked = False
    for sel in ["button.arco-btn-primary:has-text('Next')", "button:has-text('Next')",
                ".vlog-bottom", "div[class*='footer-btn']:has-text('Next')"]:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(); clicked = True; break
        except: pass
    if not clicked:
        clicked = dom_click_text(page, ["Next", "Next Step", "Continue"], timeout=20)
    if not clicked:
        raise Exception("Step 1 Next button not found")
    _ok("Next -> Step 2")
    _wait_dismissing(page, STEP1_WAIT, "AI generating script")

def _select_dropdown(page, label_text, option_text):
    js_open = """\
(label) => {
    const all = Array.from(document.querySelectorAll('label,div,span,p'));
    for (const el of all) {
        const own = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
        if (own !== label && (el.innerText || '').trim() !== label) continue;
        let c = el.parentElement;
        for (let i = 0; i < 6; i++) {
            if (!c) break;
            const t = c.querySelector('.arco-select-view,.arco-select-view-input,' +
                '[class*="select-view"],[class*="arco-select"]');
            if (t && t.getBoundingClientRect().width > 0) { t.click(); return label; }
            c = c.parentElement;
        }
    }
    return null;
}"""
    js_pick = """\
(opt) => {
    const items = Array.from(document.querySelectorAll(
        '.arco-select-option,[class*="select-option"],[class*="option-item"]'
    )).filter(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
    for (const el of items)
        if ((el.innerText || '').trim() === opt) { el.click(); return opt; }
    return null;
}"""
    try:
        r = page.evaluate(js_open, label_text)
        if r:
            time.sleep(0.8)
            r2 = page.evaluate(js_pick, option_text)
            if r2: _ok(f"{label_text} -> {option_text}")
            else:
                page.keyboard.press("Escape")
                _warn(f"'{option_text}' not in {label_text} dropdown")
        else:
            _warn(f"{label_text} dropdown not found")
    except Exception as e:
        _warn(f"Dropdown error: {e}")

# ── STEP 2: Cast ──────────────────────────────────────────────────────────────
def step2(page):
    _step(f"[Step 2] Cast generation ({STEP2_WAIT}s)...")
    dismiss_popups(page, timeout=5)
    _wait_dismissing(page, STEP2_WAIT, "characters generating")
    dismiss_popups(page, timeout=5)
    clicked = False
    for sel in [
        "div[class*='step2-footer-btn-left']",
        "button:has-text('Next Step')",
        "div[class*='footer']:has-text('Next Step')",
    ]:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(); clicked = True; break
        except: pass
    if not clicked:
        clicked = dom_click_text(page, ["Next Step", "Next", "Animate All"], timeout=30)
    sleep_log(4)
    _dismiss_animation_modal(page)
    sleep_log(3)
    _ok("[Step 2] Done")

# ── STEP 3: Storyboard ────────────────────────────────────────────────────────
def step3(page):
    _step(f"[Step 3] Storyboard (up to {STEP3_WAIT}s)...")
    dismiss_popups(page, timeout=5)
    js_img = """\
() => document.querySelectorAll(
    '[class*="role-card"] img,[class*="scene"] img,' +
    '[class*="storyboard"] img,[class*="story-board"] img'
).length"""
    deadline = time.time() + STEP3_WAIT
    while time.time() < deadline:
        if _shutdown: break
        if page.evaluate(js_img) >= 2: break
        _dismiss_all(page)
        time.sleep(5)
    sleep_log(3)
    _set_subtitle_style(page)
    clicked = False
    for sel in [
        "[class*='header'] button:has-text('Next')",
        "[class*='header-shiny-action__btn']:has-text('Next')",
        "div[class*='step2-footer-btn-left']",
    ]:
        try:
            el = page.locator(sel)
            if el.count() > 0 and el.first.is_visible():
                el.first.click(); clicked = True; break
        except: pass
    if not clicked:
        clicked = dom_click_text(page, ["Next", "Next Step"], timeout=15)
    
    sleep_log(3, "checking for Animate All popup")
    # Do NOT blindly dismiss here. Check for 'Animate All' first!
    js_animate = """() => {
        const btns = Array.from(document.querySelectorAll('button, div[class*="btn"]'));
        for (let b of btns) {
            const t = (b.innerText || '').trim();
             if (t === 'Animate All') {
                const r = b.getBoundingClientRect();
                if (r.width > 0) { b.click(); return true; }
             }
        }
        return false;
    }"""
    if page.evaluate(js_animate):
        _info("[Step 3] Clicked 'Animate All' for scenes. Waiting for scenes to animate...")
        start = time.time()
        last_pct = ""
        while time.time() - start < RENDER_TIMEOUT:
            if _shutdown: break
            prog_js = """() => {
                const prog = Array.from(document.querySelectorAll('[class*="progress"],[class*="Progress"],[class*="render-progress"],[class*="generating"]'))
                    .find(el => el.getBoundingClientRect().width > 0 && (el.innerText || '').match(/[0-9]+\\s*%/));
                if (prog) {
                    const m = (prog.innerText || '').match(/(\\d+)\\s*%/);
                    return m ? m[1] : null;
                }
                const chk = document.body.innerText || '';
                if (chk.includes('have been generated') || !chk.includes('generating')) return 'DONE';
                return null;
            }"""
            res = page.evaluate(prog_js)
            if res and res != "DONE" and res != last_pct:
                console.print(f"  [cyan]>[/cyan] Scenes Animating... [bold]{res}%[/bold]")
                last_pct = res
            elif res == "DONE" or (not res and last_pct == "100"):
                break
            time.sleep(POLL_INTERVAL)
            # Carefully clear popups but don't close important windows
            try: page.evaluate(_POPUP_JS)
            except: pass
            
        sleep_log(3, "scenes animated")
        _info("Clicking Next to proceed to Edit stage...")
        for _ in range(3):
            if dom_click_text(page, ["Next"], timeout=5): break
            time.sleep(2)
    else:
        _dismiss_animation_modal(page)
        
    sleep_log(3)
    _ok("[Step 3] Done")

def _set_subtitle_style(page):
    for txt in ["Subtitle Settings", "Subtitle", "Caption"]:
        try:
            t = page.locator(f"text='{txt}'")
            if t.count() > 0 and t.first.is_visible():
                t.first.click(); sleep_log(2); break
        except: pass
    result = page.evaluate("""\
() => {
    let items = Array.from(document.querySelectorAll('.coverFontList-item'));
    if (!items.length) items = Array.from(document.querySelectorAll(
        '[class*="coverFont"] [class*="item"],[class*="subtitle-item"]'
    ));
    const vis = items.filter(el => {
        const r = el.getBoundingClientRect(); return r.width > 5 && r.height > 5;
    });
    if (vis.length >= 10) { vis[9].click(); return 'subtitle style #10 set'; }
    return 'only ' + vis.length + ' items';
}""")
    _info(f"[step3] {result}")

# ── STEP 4: Navigate to Generate -> Wait -> Download ──────────────────────────
def step4(page, safe_name, sheet_row_num=None):
    _step("[Step 4] Navigating to Generate...")
    MAX_NEXT = 100
    js_modal_blocking = """\
() => {
    const masks = Array.from(document.querySelectorAll(
        '.arco-modal-mask,[class*="modal-mask"]'
    )).filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 200 && r.height > 200;
    });
    if (masks.length) return 'mask';
    return null;
}"""
    js_header_next = """\
() => {
    if (typeof Node === 'undefined') return null;
    for (const el of Array.from(document.querySelectorAll(
        '[class*="header-shiny-action__btn"],[class*="header-left-btn"]'
    ))) {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if (t === 'Next' && r.width > 0) { el.click(); return 'header-shiny: Next'; }
    }
    for (const el of Array.from(document.querySelectorAll('button.arco-btn-primary'))) {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if (t === 'Next' && r.width > 0) { el.click(); return 'arco-primary: Next'; }
    }
    return null;
}"""
    js_has_gen = """\
() => {
    const texts = ["Generate","Create Video","Export","Create now","Render"];
    const all = Array.from(document.querySelectorAll(
        'button,div[class*="btn"],span[class*="btn"],div[class*="footer-btn"],' +
        'div[class*="header-shiny-action__btn"],[class*="animation-modal__tab"]'
    ));
    for (let i = all.length-1; i >= 0; i--) {
        const el = all[i]; let dt = '';
        el.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) dt += n.textContent; });
        const t = dt.trim() || (el.innerText || '').trim();
        if (texts.includes(t)) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return t + '|||' + el.className.substring(0,60);
        }
    }
    return null;
}"""
    for attempt in range(MAX_NEXT):
        _dismiss_animation_modal(page)
        sleep_log(2)
        raw = page.evaluate(js_has_gen)
        if raw:
            found_text, found_cls = raw.split("|||", 1)
            _ok(f"Generate button found after {attempt} attempts: '{found_text}'")
            break
        blocking = page.evaluate(js_modal_blocking)
        if blocking:
            _warn(f"Modal blocking — re-dismissing")
            _dismiss_animation_modal(page)
            sleep_log(3)
            continue
        r = page.evaluate(js_header_next)
        _info(f"[step4] attempt {attempt+1}: {r or 'no header Next'}")
        if not r:
            debug_buttons(page)
        sleep_log(4)
    else:
        raise Exception("Could not reach Generate button after max attempts")
    if not dom_click_text(page, ["Generate", "Create Video", "Export",
                                  "Create now"], timeout=20):
        raise Exception("Generate click failed")
    sleep_log(3)
    dom_click_text(page, ["OK", "Ok", "Confirm"], timeout=5)
    sleep_log(3)
    _dismiss_all(page)
    _info(f"[Step 4] Waiting for render (max {RENDER_TIMEOUT//60} min)...")
    start = time.time(); last_reload = start; render_done = False
    js_state = r"""
() => {
    const prog = Array.from(document.querySelectorAll(
        '[class*="progress"],[class*="Progress"],[class*="render-progress"],[class*="generating"]'
    )).filter(el => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && (el.innerText || '').match(/[0-9]+\s*%/);
    });
    if (prog.length > 0) {
        const m = (prog[0].innerText || '').match(/(\d+)\s*%/);
        return 'progress:' + (m ? m[1] : '?') + '%';
    }
    const body = (document.body && document.body.innerText) || '';
    const kws = ['video has been generated','generation complete',
                 'successfully generated','video is ready','has been generated'];
    for (const k of kws)
        if (body.toLowerCase().includes(k.toLowerCase())) return 'text:' + k;
    const btns = Array.from(document.querySelectorAll('button,a,div[class*="btn"]'));
    for (const el of btns) {
        const t = (el.innerText || '').trim();
        const r = el.getBoundingClientRect();
        if (r.width > 0 && (t === 'Download video' || t === 'Download Video' || t === 'Download'))
            return 'btn:' + t;
    }
    const vid = document.querySelector('video[src*=".mp4"],video source[src*=".mp4"]');
    if (vid && vid.src) return 'video:' + vid.src.substring(0, 60);
    return null;
}"""
    last_pct = ""
    while time.time() - start < RENDER_TIMEOUT:
        if _shutdown: break
        elapsed = int(time.time() - start)
        if time.time() - last_reload >= RELOAD_INTERVAL:
            try:
                page.reload(timeout=30000, wait_until="domcontentloaded")
                wait_site_loaded(page, None, timeout=30)
                _dismiss_all(page)
            except Exception as e:
                _warn(f"Reload error: {e}")
            last_reload = time.time()
        _dismiss_all(page)
        # Check if page is still valid before evaluating
        try:
            if page.is_closed():
                _err("Page was closed during render wait - aborting")
                break
            sig = page.evaluate(js_state)
        except Exception as e:
            _warn(f"Page evaluation error during render wait: {e}")
            # Try to reload the page if evaluation fails
            try:
                page.goto(page.url, timeout=30000)
                wait_site_loaded(page, None, timeout=30)
                _dismiss_all(page)
                sig = page.evaluate(js_state)
            except:
                _err("Cannot recover from page evaluation error - aborting")
                break
        if sig is None:
            if elapsed % 30 == 0:
                _info(f"[step4] {elapsed//60}m{elapsed%60}s elapsed")
        elif sig.startswith("progress:"):
            pct = sig.split(":", 1)[1]
            if pct != last_pct:
                console.print(f"  [cyan]>[/cyan] Rendering... [bold]{pct}[/bold]")
                last_pct = pct
        else:
            _ok(f"Render done ({elapsed}s) -> {sig}")
            render_done = True; break
        time.sleep(POLL_INTERVAL)
    if not render_done:
        _warn("Render timeout — attempting download anyway")
    sleep_log(3, "UI settle")
    popup_visible = page.evaluate("""\
() => {
    const body = (document.body && document.body.innerText) || '';
    return body.includes('has been generated') && body.includes('Submit');
}""")
    if popup_visible or render_done:
        _handle_generated_popup(page)
        sleep_log(3, "post-submit settle")
        _wait_for_preview_page(page, timeout=45)
    sleep_log(2)
    return _download(page, safe_name, sheet_row_num=sheet_row_num)

# ── DOWNLOAD ──────────────────────────────────────────────────────────────────
def _download(page, safe_name, sheet_row_num=None):
    out = {"video": "", "thumb": "", "gen_title": "", "summary": "", "tags": ""}
    sdir = story_dir(safe_name)
    meta = page.evaluate("""\
() => {
    const result = { title: '', summary: '', hashtags: '' };
    const items = document.querySelectorAll('.previewer-new-body-right-item');
    items.forEach(item => {
        const label = (item.querySelector('.previewer-new-body-right-item-header-title') || {}).innerText || '';
        const ta    = item.querySelector('textarea.arco-textarea');
        const val   = ta ? (ta.value || ta.innerText || '').trim() : '';
        const key   = label.trim().toLowerCase();
        if (key === 'title')    result.title    = val;
        if (key === 'summary')  result.summary  = val;
        if (key === 'hashtags') result.hashtags = val;
    });
    return result;
}""") or {}
    out["gen_title"] = meta.get("title", "")
    out["summary"]   = meta.get("summary", "")
    out["tags"]      = meta.get("hashtags", "")
    _info(f"[meta] Title='{out['gen_title'][:50]}'")
    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": page.url}
    thumb_dest = os.path.join(sdir, f"{safe_name}_thumb.jpg")
    try:
        page.mouse.move(1000, 400)
        page.mouse.wheel(0, 3000)
        time.sleep(1)
        page.keyboard.press("PageDown")
        page.keyboard.press("PageDown")
        time.sleep(1)
        page.evaluate("""() => {
            document.querySelectorAll('*').forEach(el => {
                try {
                    const ov = window.getComputedStyle(el).overflowY;
                    if(ov === 'auto' || ov === 'scroll' || ov === 'overlay') {
                        if (el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight;
                    }
                } catch(e) {}
            });
            window.scrollTo(0, document.body.scrollHeight);
        }""")
        time.sleep(3)
    except Exception as e:
        _warn(f"[thumb] Scroll warning: {e}")
    thumb_url = page.evaluate("""\
() => {
    return new Promise(async (resolve) => {
        function findImages(wrapper) {
            const imgs = Array.from(wrapper.querySelectorAll('img[src]'));
            for (let img of imgs) {
                let s = img.src.toLowerCase();
                if ((s.startsWith('http') || s.startsWith('blob:') || s.startsWith('data:'))
                    && img.naturalWidth > 100
                    && !s.includes('avatar') && !s.includes('icon') && !s.includes('logo')) {
                    return img.src;
                }
            }
            return null;
        }
        let src = null;
        const dlBtn = document.querySelector('.show-cover-download');
        if (dlBtn) {
            let wrapper = dlBtn;
            for (let i = 0; i < 4; i++) {
                if (!wrapper) break;
                src = findImages(wrapper);
                if (src) break;
                wrapper = wrapper.parentElement;
            }
        }
        if (!src) {
            const titles = Array.from(document.querySelectorAll('div, span'));
            for (const el of titles) {
                if ((el.innerText || '').trim().toLowerCase() === 'magic thumbnail') {
                    let wrapper = el;
                    for (let i = 0; i < 4; i++) {
                        if (!wrapper) break;
                        src = findImages(wrapper);
                        if (src) break;
                        wrapper = wrapper.parentElement;
                    }
                    if (src) break;
                }
            }
        }
        if (!src) return resolve(null);
        if (src.startsWith('data:')) return resolve(src);
        try {
            const response = await window.fetch(src);
            const blob = await response.blob();
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result);
            reader.onerror = () => resolve(src);
            reader.readAsDataURL(blob);
        } catch(e) { resolve(src); }
    });
}""")
    if thumb_url:
        try:
            content_bytes = None
            if thumb_url.startswith("data:"):
                import base64
                header, encoded = thumb_url.split(",", 1)
                content_bytes = base64.b64decode(encoded)
            elif thumb_url.startswith("http"):
                r = requests.get(thumb_url, timeout=30)
                if r.status_code == 200:
                    content_bytes = r.content
            if content_bytes and len(content_bytes) > 5000:
                with open(thumb_dest, "wb") as f: f.write(content_bytes)
                out["thumb"] = thumb_dest
                _ok(f"Thumbnail -> {thumb_dest} ({len(content_bytes)//1024} KB)")
        except Exception as e:
            _warn(f"Thumbnail error: {e}")
    if not out["thumb"]:
        fallback_url = page.evaluate("""\
() => {
    const selectors = [
        '[class*="timeline"] img[src]',
        '[class*="storyboard"] img[src]',
        '[class*="scene"] img[src]',
        'img[src*="oss"][src]',
    ];
    for (const sel of selectors) {
        const imgs = Array.from(document.querySelectorAll(sel))
            .filter(i => i.src.startsWith('http') && i.naturalWidth >= 50);
        if (imgs.length) return imgs[0].src;
    }
    return null;
}""")
        if fallback_url:
            try:
                r = requests.get(fallback_url, timeout=30, cookies=cookies, headers=headers)
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(thumb_dest, "wb") as f: f.write(r.content)
                    out["thumb"] = thumb_dest
                    _ok(f"Thumbnail (fallback) -> {thumb_dest}")
            except Exception as e:
                _warn(f"Thumbnail fallback error: {e}")
    video_dest = os.path.join(sdir, f"{safe_name}.mp4")
    try:
        cancel_btn = page.locator('button', has_text="Cancel")
        if cancel_btn.count() > 0 and cancel_btn.first.is_visible(timeout=1000):
            cancel_btn.first.click(timeout=1000)
            sleep_log(1)
    except: pass
    _info("[dl] Waiting for video element (max 60s)...")
    vid_wait_deadline = time.time() + 60
    while time.time() < vid_wait_deadline:
        vid_check = page.evaluate("""\
() => {
    const v = document.querySelector('video');
    if (v && v.src && v.src.includes('.mp4')) return v.src;
    const s = document.querySelector('video source');
    if (s && s.src && s.src.includes('.mp4')) return s.src;
    const a = document.querySelector('a[href*=".mp4"]');
    if (a) return a.href;
    return null;
}""")
        if vid_check: break
        time.sleep(2)
    for sel in [
        "button:has-text('Download video')",
        "a:has-text('Download video')",
        "button:has-text('Download Video')",
        "a:has-text('Download Video')",
        "a[download]",
        "a[href*='.mp4']",
    ]:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                _info(f"[dl] Clicking '{sel}'...")
                with page.expect_download(timeout=180000) as dl_info:
                    loc.first.click()
                dl = dl_info.value
                dl.save_as(video_dest)
                if os.path.exists(video_dest) and os.path.getsize(video_dest) > 10000:
                    out["video"] = video_dest
                    _ok(f"Video -> {video_dest} ({os.path.getsize(video_dest)//1024} KB)")
                    break
        except Exception as e:
            _warn(f"  {sel}: {e}")
    if not out["video"]:
        vid_url = page.evaluate("""\
() => {
    const v = document.querySelector('video');
    if (v && v.src && v.src.includes('.mp4')) return v.src;
    const s = document.querySelector('video source');
    if (s && s.src && s.src.includes('.mp4')) return s.src;
    const a = document.querySelector('a[href*=".mp4"]');
    if (a) return a.href;
    return null;
}""")
        if vid_url:
            try:
                _info(f"[dl] Direct URL: {vid_url[:80]}")
                r = requests.get(vid_url, stream=True, timeout=180,
                                  cookies=cookies, headers=headers)
                r.raise_for_status()
                total = 0
                with open(video_dest, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            f.write(chunk); total += len(chunk)
                if total > 10000:
                    out["video"] = video_dest
                    _ok(f"Video (URL) -> {video_dest} ({total//1024} KB)")
                else:
                    _warn(f"Video too small ({total}B)")
                    try: os.remove(video_dest)
                    except: pass
            except Exception as e:
                _warn(f"Video URL download error: {e}")
    if not out["video"]:
        _err("[dl] VIDEO DOWNLOAD FAILED")
    if out.get("video") and DRIVE_FOLDER_ID:
        try:
            story_folder = os.path.dirname(out["video"])
            drive_results = upload_story_to_drive(
                story_folder, safe_name,
                out["video"], out.get("thumb", ""),
                sheet_row_num=sheet_row_num
            )
            out["drive_folder"] = drive_results["folder_link"]
            out["drive_link"]   = drive_results["video_link"]
            out["drive_thumb"]  = drive_results["thumb_link"]
        except Exception as e:
            _warn(f"Drive upload error: {e}")
    return out

# ── RETRY via User Center ─────────────────────────────────────────────────────
def _retry_from_user_center(page, project_url, safe_name):
    _info("[retry] Opening User Center...")
    sleep_log(5, "pre-retry")
    try:
        page.goto("https://magiclight.ai/user-center/", timeout=60000)
        wait_site_loaded(page, None, timeout=45)
        sleep_log(4)
        _dismiss_all(page)
    except Exception as e:
        _warn(f"User Center failed: {e}"); return None
    clicked = page.evaluate("""\
(targetUrl) => {
    if (targetUrl) {
        const parts = targetUrl.replace(/[/]+$/, '').split('/');
        const projId = parts[parts.length - 1];
        if (projId && projId.length > 5) {
            const match = Array.from(document.querySelectorAll('a[href]'))
                .find(a => a.href && a.href.includes(projId));
            if (match && match.getBoundingClientRect().width > 0) {
                match.click(); return 'matched ID: ' + projId;
            }
        }
    }
    const editLinks = Array.from(document.querySelectorAll('a[href*="/project/edit/"],a[href*="/edit/"]'))
        .filter(a => a.getBoundingClientRect().width > 0);
    if (editLinks.length) { editLinks[0].click(); return 'edit-link'; }
    return null;
}""", project_url or "")
    if not clicked:
        if project_url and '/project/' in project_url:
            try:
                page.goto(project_url, timeout=60000)
                wait_site_loaded(page, None, timeout=30)
                sleep_log(3); _dismiss_all(page)
                _handle_generated_popup(page)
                sleep_log(2)
                return _download(page, safe_name)
            except Exception as e:
                _warn(f"Direct goto failed: {e}")
        _warn("[retry] Could not find project"); return None
    _ok(f"[retry] Project opened ({clicked})")
    sleep_log(5)
    wait_site_loaded(page, None, 30)
    _dismiss_all(page)
    _handle_generated_popup(page)
    sleep_log(2)
    try: return _download(page, safe_name)
    except Exception as e:
        _warn(f"[retry] Download failed: {e}"); return None

# ── Filename helpers ──────────────────────────────────────────────────────────
def _make_safe(row_num, title, file_type=""):
    if file_type:
        safe_title = re.sub(r"[^\w\-]", "_", str(title)[:40])
        return f"row{row_num}-{file_type}-{safe_title}".strip("_")
    return re.sub(r"[^\w\-]", "_", f"row{row_num}_{str(title)[:40]}").strip("_")

def extract_row_num(stem: str) -> int | None:
    m = re.match(r"row(\d+)[_\-]", stem, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None

# ── Video Processing ──────────────────────────────────────────────────────────
def check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False

def get_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def has_valid_video(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=10
        )
        return float(result.stdout.strip()) > 0
    except Exception:
        return False

def has_audio_stream(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True
        )
        return bool(result.stdout.strip())
    except Exception:
        return False

def scan_videos(base: Path) -> list[Path]:
    if not base or not base.exists():
        return []
    return sorted(
        p for p in base.rglob("*")
        if p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.stem.endswith("_processed")
        and "-Processed-" not in p.stem
        and "_thumb" not in p.stem
    )

_PROFILES = {
    "720p": {
        "label": "720p — Fast Encode",
        "resolution": "1280x720", "crf": 23,
        "preset": "fast", "audio_br": "128k",
    },
    "1080p": {
        "label": "1080p — Standard",
        "resolution": "1920x1080", "crf": 23,
        "preset": "veryfast", "audio_br": "128k",
    },
    "1080p_hq": {
        "label": "1080p HQ — Best Quality (Slow)",
        "resolution": "1920x1080", "crf": 18,
        "preset": "slow", "audio_br": "192k",
    },
}

def build_ffmpeg_cmd(
    input_file: Path, output_file: Path,
    trim_seconds: int, logo_path: Path,
    logo_x: int, logo_y: int, logo_width: int, logo_opacity: float,
    endscreen_enabled: bool, endscreen_path, profile_key: str = "1080p"
) -> list[str]:
    profile = _PROFILES.get(profile_key, _PROFILES["1080p"])
    res = profile["resolution"]
    w, h = res.split("x")
    scale = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    crf     = profile["crf"]
    preset  = profile["preset"]
    ab      = profile["audio_br"]
    dur = get_duration(input_file)
    trim_dur = max(0.1, dur - trim_seconds) if dur > trim_seconds > 0 else dur
    input_has_audio = has_audio_stream(input_file)
    has_logo      = logo_path.exists() and logo_width > 0
    has_endscreen = (endscreen_enabled and endscreen_path and
                     Path(endscreen_path).exists() and has_valid_video(Path(endscreen_path)))
    inputs = ["-i", str(input_file)]
    logo_idx = end_idx = None
    if has_logo:
        logo_idx = len(inputs) // 2
        inputs += ["-i", str(logo_path)]
    if has_endscreen:
        end_idx = len(inputs) // 2
        inputs += ["-i", str(endscreen_path)]
    filters = []
    filters.append(f"[0:v]trim=duration={trim_dur:.3f},setpts=PTS-STARTPTS,{scale}[base]")
    if input_has_audio:
        filters.append(f"[0:a]atrim=duration={trim_dur:.3f},asetpts=PTS-STARTPTS[main_a]")
    if has_logo:
        logo_scale = f"[{logo_idx}:v]scale={logo_width}:-1[logo_s]"
        if logo_opacity < 1.0:
            logo_scale += f";[logo_s]format=rgba,colorchannelmixer=aa={logo_opacity:.2f}[logo_f]"
            lref = "logo_f"
        else:
            lref = "logo_s"
        filters.append(logo_scale)
        filters.append(f"[base][{lref}]overlay={logo_x}:{logo_y}[vid_logo]")
        main_v = "vid_logo"
    else:
        main_v = "base"
    if has_endscreen:
        end_dur   = get_duration(Path(endscreen_path))
        cross     = min(0.5, trim_dur * 0.04, end_dur * 0.3)
        xfade_off = max(0, trim_dur - cross)
        filters.append(f"[{end_idx}:v]trim=duration={end_dur:.3f},setpts=PTS-STARTPTS,{scale}[end_v]")
        filters.append(f"[{end_idx}:a]atrim=duration={end_dur:.3f},asetpts=PTS-STARTPTS[end_a]")
        filters.append(f"[{main_v}][end_v]xfade=transition=fade:duration={cross:.3f}:offset={xfade_off:.3f}[final_v]")
        filters.append(f"[main_a][end_a]acrossfade=d={cross:.3f}[final_a]")
        map_v, map_a = "[final_v]", "[final_a]"
    else:
        map_v = f"[{main_v}]"
        map_a = "[main_a]" if input_has_audio else None
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", ";".join(filters),
            "-map", map_v])
    if map_a:
        cmd += ["-map", map_a, "-c:a", "aac", "-b:a", ab]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_file)]
    return cmd

def run_ffmpeg(cmd: list[str], input_file: Path, output_file: Path,
               dry_run: bool = False) -> bool:
    if dry_run:
        _info(f"[DRY-RUN] {' '.join(cmd[:6])} ...")
        return True
    duration = get_duration(input_file)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, universal_newlines=True)
        if _has_rich:
            from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
            with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                          BarColumn(), TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                          TimeElapsedColumn(), console=console) as progress:
                task = progress.add_task(f"[cyan]Encoding {input_file.name}", total=100)
                for line in proc.stdout:
                    if "time=" in line:
                        try:
                            tp = line.split("time=")[1].split()[0]
                            h, m, s = tp.split(":")
                            cur = int(h) * 3600 + int(m) * 60 + float(s)
                            if duration > 0:
                                progress.update(task, completed=min(100, int(cur/duration*100)))
                        except: pass
        else:
            for line in proc.stdout:
                if "time=" in line: console.print(f"  {line.strip()}")
        rc = proc.wait()
        if rc == 0:
            _ok(f"Encoded -> {output_file.name}")
            return True
        else:
            _err(f"FFmpeg exited with code {rc}")
            return False
    except Exception as e:
        _err(f"FFmpeg error: {e}")
        return False

def process_video(input_video: Path, dry_run: bool = False) -> bool:
    if not check_ffmpeg():
        _err("FFmpeg not found. Install FFmpeg and add to PATH.")
        return False
    stem = input_video.stem
    row_num = extract_row_num(stem)
    if "-Generated-" in stem:
        title_part = stem.split("-Generated-", 1)[1]
    elif "_" in stem:
        parts = stem.split("_", 1)
        title_part = parts[1] if len(parts) > 1 else stem
    else:
        title_part = stem
    if row_num:
        safe_name   = _make_safe(row_num, title_part.replace("_", " "), "Processed")
        output_file = input_video.parent / f"{safe_name}{input_video.suffix}"
    else:
        output_file = input_video.parent / f"{input_video.stem}_processed{input_video.suffix}"
    if output_file.exists():
        _info(f"Already processed — skipping ({output_file.name})")
        return True
    endscreen_enabled = ENDSCREEN_ENABLED
    endscreen_path    = ENDSCREEN_VIDEO
    if ENDSCREEN_ENABLED and not ENDSCREEN_VIDEO.exists():
        _warn(f"Endscreen not found — skipping endscreen")
        endscreen_enabled = False
        endscreen_path    = None
    cmd = build_ffmpeg_cmd(
        input_file=input_video, output_file=output_file,
        trim_seconds=TRIM_SECONDS, logo_path=LOGO_PATH,
        logo_x=LOGO_X, logo_y=LOGO_Y, logo_width=LOGO_WIDTH,
        logo_opacity=LOGO_OPACITY, endscreen_enabled=endscreen_enabled,
        endscreen_path=endscreen_path
    )
    _info(f"Processing -> {output_file.name}")
    return run_ffmpeg(cmd, input_video, output_file, dry_run=dry_run)

def process_all(cfg: dict, videos: list[Path] = None,
                dry_run: bool = False, upload: bool = False) -> int:
    base = cfg.get("magiclight_output", Path(OUT_BASE))
    if videos is None:
        videos = scan_videos(base)
    if not videos:
        _warn("No unprocessed videos found.")
        return 0
    ok = fail = 0
    total = len(videos)
    for i, vid in enumerate(videos, 1):
        console.rule(f"[cyan][{i}/{total}]  {vid.parent.name} / {vid.name}[/cyan]")
        row_num = extract_row_num(vid.stem)
        if "-Generated-" in vid.stem:
            title_part = vid.stem.split("-Generated-", 1)[1]
        elif "_" in vid.stem:
            title_part = vid.stem.split("_", 1)[1]
        else:
            title_part = vid.stem
        if row_num:
            safe_name  = _make_safe(row_num, title_part.replace("_", " "), "Processed")
            dst        = vid.parent / f"{safe_name}{vid.suffix}"
        else:
            dst = vid.parent / f"{vid.stem}_processed{vid.suffix}"
        if dst.exists():
            _info(f"Already processed — skipping ({dst.name})")
            ok += 1
            continue
        dur = get_duration(vid)
        mb  = vid.stat().st_size / 1_048_576
        _info(f"Duration : {dur:.1f}s   Size: {mb:.1f} MB")
        _info(f"Output   : {dst.name}")
        success = process_video(vid, dry_run=dry_run)
        if success:
            ok += 1
            if upload and not dry_run and dst.exists():
                folder_name       = vid.parent.name if vid.parent.name else vid.stem
                processed_link    = upload_to_drive(str(dst), folder_name)
                if row_num and processed_link:
                    try:
                        update_sheet_row(
                            row_num,
                            Status         = "Done",
                            Process_D_Link = processed_link,
                            Completed_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            Notes          = f"Processed OK"
                        )
                        _ok(f"[sheet] Row {row_num} -> Done | Process_D_Link written")
                    except Exception as se:
                        _warn(f"[sheet] Process_D_Link update: {se}")
                elif row_num and not processed_link:
                    try:
                        update_sheet_row(
                            row_num,
                            Status         = "Done",
                            Completed_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            Notes          = "Processed OK (Drive upload failed)"
                        )
                    except Exception as se:
                        _warn(f"[sheet] Status update: {se}")
        else:
            fail += 1
            if dst.exists() and not dry_run:
                try: dst.unlink()
                except: pass
    console.print()
    console.rule()
    _ok(f"Processing complete!  OK={ok}  FAIL={fail}")
    return 0 if fail == 0 else 1

# ── Config helpers ────────────────────────────────────────────────────────────
def load_process_cfg():
    return {
        "magiclight_output": Path(OUT_BASE),
        "logo_path":         LOGO_PATH,
        "endscreen_video":   ENDSCREEN_VIDEO,
        "trim_seconds":      TRIM_SECONDS,
        "logo_x": LOGO_X, "logo_y": LOGO_Y,
        "logo_width": LOGO_WIDTH, "logo_opacity": LOGO_OPACITY,
        "endscreen_enabled": ENDSCREEN_ENABLED,
        "upload_to_drive":   UPLOAD_TO_DRIVE,
        "drive_folder_id":   DRIVE_FOLDER_ID,
        "spreadsheet_id":    SHEET_ID,
    }

def run_health_check():
    console.rule("[bold cyan]System Health Check[/bold cyan]")
    issues = 0
    py = sys.version_info
    if py.major >= 3 and py.minor >= 8:
        _ok(f"Python {py.major}.{py.minor}.{py.micro}")
    else:
        _err(f"Python too old: {py.major}.{py.minor}"); issues += 1
    packages = {
        'playwright': 'playwright', 'gspread': 'gspread',
        'google-auth-oauthlib': 'google_auth_oauthlib',
        'google-api-python-client': 'googleapiclient', 'python-dotenv': 'dotenv'
    }
    for pkg, imp in packages.items():
        try:
            __import__(imp); _ok(f"Package: {pkg}")
        except ImportError:
            _err(f"Missing: {pkg}"); issues += 1
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0: _ok("FFmpeg installed")
        else: _err("FFmpeg error"); issues += 1
    except FileNotFoundError:
        _err("FFmpeg not found in PATH!"); issues += 1

    # Assets check
    if LOGO_PATH.exists():
        _ok(f"Logo found: {LOGO_PATH}")
    else:
        _warn(f"Logo missing: {LOGO_PATH}")
    if ENDSCREEN_VIDEO.exists():
        _ok(f"Endscreen found: {ENDSCREEN_VIDEO}")
    else:
        _warn(f"Endscreen missing: {ENDSCREEN_VIDEO} (optional)")

    # .env check
    for var in ["SHEET_ID", "DRIVE_FOLDER_ID"]:
        val = os.getenv(var, "")
        if val:
            _ok(f"{var} set")
        else:
            _warn(f"{var} not set in .env")

    console.print()
    if issues == 0:
        _ok("All core systems OK!")
    else:
        _err(f"Found {issues} issue(s)")
    return issues

# ── Menu State ────────────────────────────────────────────────────────────────
MENU_STATE_FILE = ".menu_state.json"

def load_menu_state():
    try:
        if os.path.exists(MENU_STATE_FILE):
            with open(MENU_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except: pass
    return {"last_mode": None, "last_amount": 0, "last_drive_choice": True, "preferences": {}}

def save_menu_state(state):
    try:
        with open(MENU_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f)
    except: pass

def show_pending_table():
    """Show pending stories in a styled Rich table."""
    try:
        records = read_sheet()
    except Exception as e:
        _warn(f"Could not read sheet: {e}")
        return 0

    pending   = [(i+2, r) for i, r in enumerate(records) if str(r.get("Status","")).strip().lower() == "pending"]
    done      = sum(1 for r in records if str(r.get("Status","")).strip().lower() == "done")
    errors    = sum(1 for r in records if str(r.get("Status","")).strip().lower() in ("error","no_video"))
    total     = len(records)

    # Stats row
    stats = Table.grid(padding=(0, 3))
    stats.add_column(); stats.add_column(); stats.add_column(); stats.add_column()
    stats.add_row(
        f"[bold]Total[/bold]  [cyan]{total}[/cyan]",
        f"[bold]Pending[/bold]  [yellow]{len(pending)}[/yellow]",
        f"[bold]Done[/bold]  [green]{done}[/green]",
        f"[bold]Errors[/bold]  [red]{errors}[/red]",
    )
    console.print(stats)
    console.print()

    if not pending:
        console.print("  [dim]No pending stories.[/dim]")
        return 0

    t = Table(
        show_header=True, header_style="bold cyan",
        border_style="dim", show_lines=False,
        title=f"[bold]Pending Stories ({len(pending)})[/bold]",
        title_style="cyan",
        min_width=70,
    )
    t.add_column("#",     style="dim",    width=4,  justify="right")
    t.add_column("Row",   style="cyan",   width=5,  justify="center")
    t.add_column("Theme", style="yellow", width=16)
    t.add_column("Title", style="white",  width=40)

    for idx, (row_num, row) in enumerate(pending[:15], 1):
        title = str(row.get("Title", "")).strip()[:38] or "(no title)"
        theme = str(row.get("Theme", "")).strip()[:14] or "—"
        t.add_row(str(idx), f"R{row_num}", theme, title)

    if len(pending) > 15:
        t.add_row("...", "", "", f"[dim]...and {len(pending)-15} more[/dim]")

    console.print(t)
    return len(pending)

def ask_amount(mode_label: str) -> int:
    state   = load_menu_state()
    default = state.get("last_amount", 1)
    ans = console.input(
        f"\n  [bold cyan]🔄[/bold cyan] How many stories for [bold]{mode_label}[/bold]?"
        f" [dim](0=all, last={default})[/dim] : "
    ).strip()
    amount = int(ans) if ans.isdigit() else (default if ans == "" else 0)
    state["last_amount"] = amount
    save_menu_state(state)
    return amount

def ask_drive() -> bool:
    state   = load_menu_state()
    default = state.get("last_drive_choice", True)
    dstr    = "Y" if default else "N"
    ans = console.input(
        f"  [bold cyan]🔄[/bold cyan] Upload to Google Drive?"
        f" [dim](Y/N, last={dstr})[/dim] : "
    ).strip().upper()
    choice = (ans == "Y") if ans in ("Y","N") else default
    state["last_drive_choice"] = choice
    save_menu_state(state)
    return choice

# ── FIX v2.0.3: _run_pipeline_core ───────────────────────────────────────────
def _run_pipeline_core(limit, source_type="auto"):
    global _browser, DRIVE_FOLDER_ID, _credits_total, _credits_used, _cws, _gc, _ws, _hdr
    try:
        records = read_sheet()
    except Exception as e:
        _err(f"Could not read sheet: {e}"); return
    pending = [(i, r) for i, r in enumerate(records)
               if str(r.get("Status", "")).strip().lower() == "pending"]
    if not pending:
        _warn("No pending stories found."); return
    if limit > 0:
        pending = pending[:limit]
    accounts = []
    if os.path.exists("accounts.txt"):
        with open("accounts.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and ":" in line:
                    u, p = line.split(":", 1)
                    accounts.append((u.strip(), p.strip()))
    if not accounts:
        if EMAIL and PASSWORD: accounts = [(EMAIL, PASSWORD)]
        else: _err("No credentials in accounts.txt or .env"); return
    
    import random
    random.shuffle(accounts)
    account_idx = 0
    _credits_total = 0
    _credits_used  = 0
    _ok(f"Processing {len(pending)} stor{'y' if len(pending)==1 else 'ies'}")
    _ok(f"Accounts loaded: {len(accounts)}")
    curr_email, curr_pw = accounts[account_idx]
    os.environ["CURRENT_EMAIL"] = curr_email
    context = _browser.new_context(accept_downloads=True, no_viewport=True)
    page    = context.new_page()
    try:
        login(page, custom_email=curr_email, custom_pw=curr_pw)
    except Exception as e:
        _err(f"[FATAL] Login failed for {curr_email}: {e}")
        return
    for rec_idx, row in pending:
        if _shutdown: break
        credit_before = 0
        try:
            page.goto("https://magiclight.ai/user-center", timeout=30000)
            page.wait_for_selector(".home-top-navbar-credit-amount, .credit-amount",
                                    state="visible", timeout=10000)
            credit_before, _ = _read_credits_from_page(page)
        except Exception as ce:
            _dbg(f"[credits] credit_before read failed: {ce}")
            credit_before = max(0, _credits_total - _credits_used)
        if credit_before == 0 or (credit_before > 0 and credit_before < 70):
            account_idx += 1
            if account_idx >= len(accounts):
                _err("All accounts exhausted — stopping."); break
            _credits_total = 0; _credits_used = 0
            curr_email, curr_pw = accounts[account_idx]
            os.environ["CURRENT_EMAIL"] = curr_email
            _step(f"[Rotate] Switching to {curr_email} (credit={credit_before})")
            try:
                context.close()
                context = _browser.new_context(accept_downloads=True, no_viewport=True)
                page = context.new_page()
                login(page, custom_email=curr_email, custom_pw=curr_pw)
                credit_before, _ = _read_credits_from_page(page)
            except Exception as re_err:
                _err(f"Login failed during rotation: {re_err}"); break
        vals = list(row.values())
        col_c = str(vals[2]).strip() if len(vals) > 2 else ""
        col_d = str(vals[3]).strip() if len(vals) > 3 else ""
        col_e = str(vals[4]).strip() if len(vals) > 4 else ""
        story = f"{col_c}\n\n{col_d}\n\n{col_e}".strip()
        if not story:
            _warn(f"Row {rec_idx+2}: empty Story — skipping"); continue
        title   = str(row.get("Title", f"Row{rec_idx+2}")).strip() or f"Row{rec_idx+2}"
        row_num = rec_idx + 2
        safe    = _make_safe(row_num, title, "Generated")
        console.print(Rule(style="cyan"))
        console.print(Panel(
            f"[bold]Row {row_num}[/bold]  {title}\n"
            f"[dim]Account: {curr_email}   Credit: {credit_before}[/dim]",
            border_style="cyan", expand=False, padding=(0, 1)
        ))
        try:
            update_sheet_row(row_num,
                Status       = "Processing",
                Email_Used   = curr_email,
                Credit_Before= str(credit_before) if credit_before else "",
                Created_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        except Exception as se:
            _warn(f"[sheet] Initial write failed: {se}")
        project_url = ""
        result      = None
        credit_after = 0
        try:
            step1(page, story)
            if _credit_exhausted(page):
                _err("[Low Credit] Stopping")
                update_sheet_row(row_num, Status="Low Credit",
                                  Notes="Credits exhausted before Step 2",
                                  Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                break
            step2(page)
            step3(page)
            project_url = page.url
            _credits_used += 60
            result = step4(page, safe, sheet_row_num=row_num)
            try:
                page.goto("https://magiclight.ai/user-center", timeout=40000)
                page.wait_for_selector(".home-top-navbar-credit-amount, .credit-amount",
                                        state="visible", timeout=20000)
                time.sleep(3)
                credit_after, _ = _read_credits_from_page(page)
                _credits_total = credit_after
                page.goto("https://magiclight.ai/kids-story/", timeout=30000)
            except Exception as ca_err:
                _dbg(f"[credits] credit_after read failed: {ca_err}")
                credit_after = max(0, credit_before - 60)
            _update_credits_completion(curr_email, credit_before, credit_before - credit_after,
                                       row_num, "Generation", "Step4+")
            if _credit_exhausted(page):
                update_sheet_row(row_num, Status="Low Credit",
                                  Credit_After=str(credit_after),
                                  Notes="Credits exhausted post-render",
                                  Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                break
        except Exception as e:
            screenshot(page, f"error_row{row_num}")
            debug_buttons(page)
            _err(f"Row {row_num} error: {e}")
            if _credit_exhausted(page):
                update_sheet_row(row_num, Status="Low Credit",
                                  Notes="Credits exhausted during generation",
                                  Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                break
            try: result = _retry_from_user_center(page, project_url, safe)
            except Exception as re_err:
                _warn(f"[retry] {re_err}"); result = None
            if not result:
                update_sheet_row(row_num, Status="Error",
                                  Notes=str(e)[:150],
                                  Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                _err(f"Row {row_num} -> Error")
                sleep_log(5); continue
        if result and result.get("video"):
            try:
                update_sheet_row(row_num,
                    Status        = "Generated",
                    Gen_Title     = result.get("gen_title", ""),
                    Gen_Summary   = result.get("summary", "")[:200],
                    Gen_Tags      = result.get("tags", ""),
                    Drive_Link    = result.get("drive_link", ""),
                    DriveImg_Link = result.get("drive_thumb", ""),
                    Project_URL   = project_url,
                    Completed_Time= datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    Email_Used    = curr_email,
                    Credit_Before = str(credit_before),
                    Credit_After  = str(credit_after),
                    Notes         = f"Generated OK | Credit: {credit_before}->{credit_after}"
                )
                _ok(f"[sheet] Row {row_num} -> Generated  Credit: {credit_before}->{credit_after}")
            except Exception as se:
                _warn(f"[sheet] Generated write failed: {se}")
        else:
            try:
                update_sheet_row(row_num,
                    Status        = "No_Video",
                    Email_Used    = curr_email,
                    Credit_Before = str(credit_before),
                    Credit_After  = str(credit_after),
                    Notes         = "Video generation failed",
                    Completed_Time= datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            except Exception as se:
                _warn(f"[sheet] No_Video write failed: {se}")
            _warn(f"Row {row_num} -> No_Video")
            continue
        # Inline processing: only in combined mode, not generate-only
        mode_env = os.environ.get("PIPELINE_MODE", "generate")
        if os.environ.get("RUN_PROCESS_INLINE") == "1" and mode_env == "combined":
            _info("[pipeline] Starting inline video processing...")
            video_path = result.get("video", "")
            if video_path and os.path.exists(video_path):
                try:
                    vid_path = Path(video_path)
                    success  = process_video(vid_path, dry_run=False)
                    if success:
                        row_n    = extract_row_num(vid_path.stem)
                        if "-Generated-" in vid_path.stem:
                            title_p = vid_path.stem.split("-Generated-", 1)[1]
                        else:
                            title_p = vid_path.stem.split("_", 1)[1] if "_" in vid_path.stem else vid_path.stem
                        if row_n:
                            proc_name = _make_safe(row_n, title_p.replace("_", " "), "Processed")
                            proc_path = vid_path.parent / f"{proc_name}{vid_path.suffix}"
                        else:
                            proc_path = vid_path.parent / f"{vid_path.stem}_processed{vid_path.suffix}"
                        if proc_path.exists():
                            _ok(f"[pipeline] Processed: {proc_path.name}")
                            processed_link = ""
                            if getattr(args, 'upload_drive', False) or UPLOAD_TO_DRIVE:
                                folder_name    = os.path.basename(os.path.dirname(str(proc_path)))
                                processed_link = upload_to_drive(str(proc_path), folder_name)
                            try:
                                # Write Process_D_Link if column exists, else overwrite Drive_Link
                                actual = _actual_sheet_cols()
                                if "Process_D_Link" in actual:
                                    update_sheet_row(row_num,
                                        Status         = "Done",
                                        Process_D_Link = processed_link,
                                        Completed_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        Notes          = f"Done | Account: {curr_email}"
                                    )
                                else:
                                    # No Process_D_Link column — update Drive_Link with processed video
                                    update_sheet_row(row_num,
                                        Status         = "Done",
                                        Drive_Link     = processed_link if processed_link else result.get("drive_link", ""),
                                        Completed_Time = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        Notes          = f"Done | Account: {curr_email}"
                                    )
                                _ok(f"[sheet] Row {row_num} -> Done")
                            except Exception as se:
                                _warn(f"[sheet] Done write failed: {se}")
                        else:
                            _warn("Processed file not found after processing")
                            update_sheet_row(row_num, Status="Error",
                                              Notes="Processed file missing after encoding")
                    else:
                        _warn("Video processing failed")
                        update_sheet_row(row_num, Status="Error",
                                          Notes="Video processing (FFmpeg) failed",
                                          Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                except Exception as pe:
                    _warn(f"Processing error: {pe}")
                    update_sheet_row(row_num, Status="Error",
                                      Notes=f"Processing error: {str(pe)[:150]}",
                                      Completed_Time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            else:
                _warn("Video file not available for processing")
                update_sheet_row(row_num, Status="Generated",
                                  Notes="Generated OK but local file missing for processing")
        else:
            _ok(f"[sheet] Row {row_num} -> Generated (generate-only mode)")
        if len(pending) > 1:
            sleep_log(5, "cooldown")
    try:
        context.close()
    except: pass
    console.rule(style="cyan")
    _ok("Generation sequence complete.")

# ── MENU ──────────────────────────────────────────────────────────────────────
def menu():
    state     = load_menu_state()
    
    console.print()
    console.print(Panel(
        f"[bold cyan]MagicLight Auto[/bold cyan]   [dim]v{__version__}[/dim]\n"
        f"[dim]Automated Kids Story Video Generation[/dim]",
        border_style="cyan", padding=(0, 2), expand=False
    ))
    console.print()

    show_pending_table()
    console.print()

    mt = Table(show_header=False, box=None, padding=(0, 2))
    mt.add_column("num",  style="bold cyan", width=4)
    mt.add_column("name", style="bold white", width=25)
    mt.add_row("1", "Full Pipeline")
    mt.add_row("2", "Just Video Story Making")
    mt.add_row("3", "Video Encoding Process")
    mt.add_row("4", "Exit")
    console.print(mt)
    console.print()

    choice = console.input("  [bold cyan]Select Mode [1-4]: [/bold cyan]").strip()
    if choice not in ["1", "2", "3"]: return

    mode_map = {"1": "combined", "2": "generate", "3": "process"}
    mode = mode_map[choice]

    amount = ask_amount("Stories")
    upload_drive = ask_drive()
    args.upload_drive = upload_drive
    
    loop_mode = False
    if mode in ["combined", "generate"]:
        loop_choice = console.input(f"  [bold cyan]🔄 Run on loop (Y/N)? [/bold cyan]").strip().upper()
        loop_mode = (loop_choice == "Y")
        if loop_mode:
            _ok("[loop] Loop mode enabled")
            if not DRIVE_FOLDER_ID:
                _err("DRIVE_FOLDER_ID required for Loop mode!"); return

    console.print()
    cfg = load_process_cfg()

    if mode in ["combined", "generate"]:
        pw_manager = sync_playwright().start()
        global _browser
        _browser = pw_manager.chromium.launch(
            headless=getattr(args, "headless", True),
            args=["--start-maximized"]
        )
        try:
            while True:
                os.environ["PIPELINE_MODE"]      = mode
                os.environ["RUN_PROCESS_INLINE"] = "1" if mode == "combined" else "0"
                _credits_used = 0
                _run_pipeline_core(limit=amount, source_type="auto")
                
                if not loop_mode:
                    break
                else:
                    sleep_log(30, "Loop cooldown...")
        finally:
            try:
                if _browser: _browser.close()
            except: pass
            try: pw_manager.stop()
            except: pass
    elif mode == "process":
        vids = scan_videos(Path(OUT_BASE))
        vids = vids[:amount] if amount > 0 else vids
        process_all(cfg, videos=vids, upload=args.upload_drive)

# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="MagicLight Auto v" + __version__)
    parser.add_argument("--mode", choices=["combined", "generate", "process", "loop"])
    parser.add_argument("--max", type=int, default=0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--upload-drive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--migrate-schema", action="store_true")
    return parser.parse_args()

def run_cli_mode(args):
    global _browser, _credits_used, DEBUG
    if getattr(args, 'debug', False):
        DEBUG = True
        os.environ["DEBUG"] = "1"
    if getattr(args, 'mode', None) == 'loop':
        args.mode = 'combined'
        args.loop = True
    # If no mode specified but other CLI flags are present, default to generate mode
    if not args.mode and (getattr(args, 'max', 0) > 0 or getattr(args, 'headless', False) or getattr(args, 'upload_drive', False)):
        args.mode = 'generate'
    if not args.mode:
        return False
    mode      = args.mode.lower()
    amount    = args.max
    loop_mode = getattr(args, 'loop', False)

    console.print()
    console.print(Panel(
        f"[bold cyan]MagicLight Auto[/bold cyan]   [dim]v{__version__}[/dim]\n"
        f"[dim]Mode: [bold]{mode.upper()}[/bold]"
        f"{'  +LOOP' if loop_mode else ''}"
        f"   Limit: {amount if amount > 0 else 'All pending'}[/dim]",
        border_style="cyan", padding=(0, 2), expand=False
    ))
    console.print()

    if mode == "process":
        vids = scan_videos(Path(OUT_BASE))
        vids = vids[:amount] if amount > 0 else vids
        if not vids:
            _warn("No unprocessed videos found in output/")
            return True
        _ok(f"Found {len(vids)} video(s) to process")
        cfg = load_process_cfg()
        process_all(cfg, videos=vids, dry_run=args.dry_run, upload=args.upload_drive)
        return True
    elif mode in ["combined", "generate"]:
        os.environ["PIPELINE_MODE"] = mode  # track mode for inline processing guard
        os.environ["RUN_PROCESS_INLINE"] = "1" if mode == "combined" else "0"
        run_once = False
        if loop_mode:
            args.upload_drive = True
            amount = amount if amount > 0 else 1
            if not DRIVE_FOLDER_ID:
                _err("DRIVE_FOLDER_ID required for --loop mode!")
                return False
            if os.environ.get("GITHUB_ACTIONS") == "true":
                os.environ["DRIVE_ONLY_MODE"] = "true"
            run_once = os.environ.get("LOOP_RUN_ONCE", "false").lower() == "true"
        pw_manager = sync_playwright().start()
        _browser = pw_manager.chromium.launch(
            headless=args.headless or loop_mode,
            args=["--start-maximized"]
        )
        try:
            cycle_count = 0
            while True:
                cycle_count += 1
                _credits_used = 0
                console.rule(f"[cyan]Cycle {cycle_count}[/cyan]" if loop_mode else "[cyan]Starting[/cyan]")
                _run_pipeline_core(limit=amount, source_type="auto")
                if not loop_mode:
                    break
                try:
                    for ctx in list(_browser.contexts):
                        try: ctx.close()
                        except: pass
                except: pass
                if run_once and cycle_count >= 1:
                    _ok("[loop] Run-once complete.")
                    break
                sleep_log(30, "loop cooldown")
            return True
        finally:
            try:
                if _browser: _browser.close()
            except: pass
            try: pw_manager.stop()
            except: pass
    return False

if __name__ == "__main__":
    try:
        args = parse_args()
        if getattr(args, 'migrate_schema', False):
            console.print(Panel.fit("[bold cyan]Schema Migration[/bold cyan]", border_style="cyan"))
            ensure_sheet_schema()
            _ok("Done.")
            raise SystemExit(0)
        if not run_cli_mode(args):
            class Args: pass
            args = Args()
            args.headless     = False
            args.upload_drive = False
            menu()
    except KeyboardInterrupt:
        console.print("\n[bold yellow][STOP] Exiting...[/bold yellow]")
        if _browser:
            try:
                for context in _browser.contexts:
                    try:
                        for page in context.pages: page.close()
                    except: pass
                    context.close()
                _browser.close()
            except: pass
        import os as _os
        _os._exit(0)
    except Exception as e:
        console.print(f"\n[bold red][FATAL] {e}[/bold red]")
