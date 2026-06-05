# Architecture Documentation

## Single-Script Architecture

**main.py** (110KB) is the monolithic orchestrator handling all stages sequentially.

```mermaid
graph TD
    Sheets[(Google Sheets)] --> main.py
    main.py -->|Login| ML[MagicLight.ai Playwright]
    ML -->|Generate + Download| Local[Local MP4]
    Local -->|FFmpeg| Processed[Processed MP4]
    Processed -->|Upload| Drive[(Google Drive)]
    Drive --> Sheets
```

## Key Modules

- `accounts.txt`: Multi-account credential pool with auto-rotation.
- `credentials.json`: Google service account for Sheets + Drive.
- `assets/logo.png`: Logo used for FFmpeg overlay.

---

**By OutLawZ™** | https://www.brandex.pk | net2tara@gmail.com
