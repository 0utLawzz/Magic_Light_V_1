/**
 * MagicLight Auto — Google Apps Script
 * =====================================
 * Handles YouTube upload requests from the dashboard (index.html).
 * 
 * SETUP (one-time):
 *   1. Go to script.google.com → New Project → paste this code
 *   2. In Apps Script: Extensions → YouTube Data API v3 → Enable
 *   3. Deploy → New Deployment → Web App
 *      - Execute as: Me
 *      - Who has access: Anyone
 *   4. Copy the Web App URL → paste into index.html as APPS_SCRIPT_URL
 *   5. Run authorizeYouTube() function once to grant OAuth permissions
 */

// ── Entry point for HTTP POST from dashboard ──────────────────────────────────
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    let result;
    switch(data.action) {
      case 'uploadToYouTube':
        result = uploadDriveVideoToYouTube(data);
        break;
      default:
        result = { success: false, error: 'Unknown action: ' + data.action };
    }
    return ContentService
      .createTextOutput(JSON.stringify(result))
      .setMimeType(ContentService.MimeType.JSON);
  } catch(err) {
    return ContentService
      .createTextOutput(JSON.stringify({ success: false, error: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ── CORS preflight for GET ────────────────────────────────────────────────────
function doGet(e) {
  return ContentService
    .createTextOutput(JSON.stringify({ status: 'MagicLight Apps Script online' }))
    .setMimeType(ContentService.MimeType.JSON);
}

// ── Upload Drive video to YouTube ─────────────────────────────────────────────
function uploadDriveVideoToYouTube(data) {
  const { driveUrl, title, description, privacy, tags } = data;

  if (!driveUrl) return { success: false, error: 'No driveUrl provided' };
  if (!title)    return { success: false, error: 'No title provided' };

  // Extract Drive file ID from the URL
  const fileId = extractDriveId(driveUrl);
  if (!fileId) return { success: false, error: 'Could not extract Drive file ID from: ' + driveUrl };

  try {
    // Get the video file from Google Drive
    const file = DriveApp.getFileById(fileId);
    const blob = file.getBlob();

    // Build YouTube video metadata
    const resource = {
      snippet: {
        title:       (title || 'Story Video').substring(0, 100),
        description: description || '',
        tags:        tags ? tags.split(',').map(t => t.trim()).filter(Boolean) : [],
        categoryId:  '27'  // Education
      },
      status: {
        privacyStatus:          privacy || 'public',
        selfDeclaredMadeForKids: true,
        embeddable:             true,
        publicStatsViewable:    true
      }
    };

    // Upload to YouTube
    const video = YouTube.Videos.insert(resource, 'snippet,status', blob);
    return {
      success: true,
      videoId: video.id,
      url:     'https://youtu.be/' + video.id
    };

  } catch(err) {
    return { success: false, error: err.toString() };
  }
}

// ── Drive ID extractor ────────────────────────────────────────────────────────
function extractDriveId(url) {
  // Matches formats:
  //   /file/d/{ID}/
  //   id={ID}
  //   /d/{ID}
  const patterns = [
    /\/file\/d\/([a-zA-Z0-9_-]+)/,
    /id=([a-zA-Z0-9_-]+)/,
    /\/d\/([a-zA-Z0-9_-]+)/
  ];
  for (const p of patterns) {
    const m = url.match(p);
    if (m) return m[1];
  }
  return null;
}

// ── One-time authorization trigger ───────────────────────────────────────────
// Run this function manually once from the Apps Script editor to grant YouTube access
function authorizeYouTube() {
  const check = YouTube.Channels.list('snippet', { mine: true });
  Logger.log('Channel: ' + JSON.stringify(check));
  Logger.log('Authorization successful!');
}
