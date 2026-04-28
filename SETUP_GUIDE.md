# BLS YouTube Uploader — Setup Guide v2.0
## NeoBrutalism Dashboard

---

## STEP 1: Google Cloud Project Setup (Per Account)

Har YouTube channel ke liye alag Google Cloud Project banana hoga.

### 1.1 Project Banao
1. https://console.cloud.google.com par jao
2. "New Project" → Name: `BLS-Teamwork` (theme ke naam per)
3. Project create ho jaye to usse select karo

### 1.2 YouTube Data API Enable Karo
1. Left menu → "APIs & Services" → "Library"
2. Search: `YouTube Data API v3`
3. Click → "Enable"

### 1.3 OAuth Credentials Banao
1. "APIs & Services" → "Credentials"
2. "Create Credentials" → "OAuth 2.0 Client ID"
3. Application type: **Desktop App**
4. Name: `BLS-Teamwork-OAuth`
5. Download the JSON file — isey secure rakh

### 1.4 Test Users Add Karo (Agar app unverified hai)
1. "APIs & Services" → "OAuth consent screen"
2. "Test users" section → apna email add karo

---

## STEP 2: Apps Script Setup

### 2.1 Script Kholna
1. Google Sheet kholo
2. Extensions → Apps Script
3. Naya project milega

### 2.2 Files Paste Karo
1. `Code.gs` → existing code replace karo
2. `+` button → HTML file → name: `Index` → dashboard HTML paste karo

### 2.3 YouTube Data API Service Add Karo
1. Left panel → "Services" (+ icon)
2. `YouTube Data API v3` dhundo → Add karo
3. Identifier: `YouTube` (default)

### 2.4 Config Setup Karo
1. Functions dropdown se `setupConfigSheet` select karo → Run
2. Sheet mein `YT_Config` tab aayega
3. Apne Channel IDs fill karo:
   - Channel ID nikalna: YouTube Studio → Settings → Channel → Basic Info → Channel ID

---

## STEP 3: OAuth Authorization (Per Account)

### 3.1 Script Properties mein Tokens Add Karo
1. Apps Script → Project Settings → Script Properties
2. Har theme ke liye:
   ```
   Key: CHANNEL_ID_Teamwork
   Value: UCxxxxxxxxxxxxxxxxxx
   
   Key: EMAIL_Teamwork  
   Value: kakife5916@nyspring.com
   
   Key: CATEGORY_Teamwork
   Value: 27
   
   Key: PRIVACY_Teamwork
   Value: public
   ```

### 3.2 Authorization Run Karo
1. `syncConfigFromSheet` function run karo
2. Pehli baar run karne par Google authorization popup aayega
3. Har account ke email se login karke allow karo

---

## STEP 4: Daily Trigger Set Karo

```javascript
// Apps Script mein run karo:
setDailyTrigger(10)  // 10 AM PKT par daily auto-upload
```

Ya manually:
1. Apps Script → Triggers (alarm icon)
2. "Add Trigger"
3. Function: `autoUpload`
4. Event: Time-driven → Day timer → 5am-6am (UTC = 12am-1am PKT)

---

## STEP 5: Web App Deploy Karo

1. Apps Script → "Deploy" → "New Deployment"
2. Type: **Web App**
3. Execute as: **Me**
4. Who has access: **Anyone** (ya "Anyone with Google Account")
5. Deploy → URL copy karo → yeh dashboard URL hai

---

## Column Mapping (Sheet)

| Col | Letter | Field | Use |
|-----|--------|-------|-----|
| A | Status | Status | Ignored |
| B | Theme | Theme | Channel selection |
| C | Title | Title | Fallback title |
| D | Story | Story | Fallback desc |
| E | Moral | Moral | Added to description |
| F | Gen_Title | Gen_Title | ✅ VIDEO TITLE |
| G | Gen_Summary | Gen_Summary | ✅ DESCRIPTION |
| H | Gen_Tags | Gen_Tags | ✅ TAGS |
| M | Drive_Link | Drive_Link | ✅ VIDEO FILE |
| N | DriveImg_Link | DriveImg_Link | ✅ THUMBNAIL |
| Q | Email_Used | Email_Used | Reference only |
| R | Done | Done | TRUE/FALSE |

---

## YouTube Categories

| ID | Category |
|----|---------|
| 1 | Film & Animation |
| 10 | Music |
| 13 | How-to & Style |
| 22 | People & Blogs |
| 23 | Comedy |
| 24 | Entertainment |
| **27** | **Education** ← Default |
| 28 | Science & Technology |

---

## Quota Calculator

| Action | Units |
|--------|-------|
| Video Upload | ~1,600 |
| Thumbnail Set | 50 |
| Playlist Insert | 50 |
| **Total per video** | **~1,700** |
| **Daily quota** | **10,000** |
| **Max videos/day** | **~5** |

💡 Har account ka alag Google Cloud Project → alag 10,000 quota!

---

## Troubleshooting

**Error: "The caller does not have permission"**
→ OAuth scope missing. Re-authorize: Apps Script → Run any function → Allow all scopes

**Error: "Daily Limit Exceeded"**  
→ Quota khatam. Kal try karo ya naya Cloud Project banao.

**Error: "File not found" on Drive**  
→ Drive file ki sharing setting check karo — "Anyone with link" hona chahiye

**Thumbnail upload hoti nahi**  
→ Channel ko 1,000+ subscribers chahiye thumbnails ke liye. Tab tak custom thumbnail disabled rehti hai.

**Video upload kiya but YouTube pe nahi dikh raha**  
→ YouTube processing mein 5-15 min lagte hain. Normal hai.

---

## Important Notes

- ✅ Make for Kids: Animated kids content ke liye TRUE rakhna
- ✅ Drive files: "Anyone with link — Viewer" sharing honi chahiye  
- ✅ Video format: MP4 (H.264) best results deta hai
- ✅ Thumbnail: 1280×720 JPG/PNG, under 2MB
- ⚠️ Do not run autoUpload manually too many times — quota waste hoga
- ⚠️ Har Cloud Project mein sirf ek YouTube account authorize karo

---

*BLS YouTube Uploader v2.0 — NeoBrutalism Edition*
