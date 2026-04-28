// Configuration file for YouTube Uploader Web App
const CONFIG = {
  // Google Sheet URL for story data
  SHEET_URL: 'https://docs.google.com/spreadsheets/d/e/2PACX-1vQrwn7Tei_9QBxtJ-Ka_wGtKNISq4TfafHKu2ANAiACNOZagNrl6uG2WghkPogOQNUXsDb618bFMqbB/pub?gid=2087344095&single=true&output=csv',
  
  // Apps Script Web App URL (replace after deployment)
  APPS_SCRIPT_URL: 'https://script.google.com/macros/s/AKfycbxIb22Qo_3BxI73PgD5PbaDu6ocMXQu7T_FV7kBKZztcJvcOMKuTERZVg1AKAAnV7f3qg/exec',
  
  // API Quota settings
  QUOTA_PER_DAY: 10000,
  QUOTA_UNITS_PER_UPLOAD: 1600,
  
  // Default theme to channel mappings
  DEFAULT_ACCOUNTS: [
    {
      theme: 'Teamwork',
      channel: 'Bright Little Stories',
      channelId: 'UC2FdFOP-XrLFlWN9VJWmYWQ',
      email: 'net2tara@gmail.com',
      category: '27',
      privacy: 'public'
    }
  ],
  
  // YouTube categories
  YOUTUBE_CATEGORIES: [
    { value: '1', label: 'Film & Animation' },
    { value: '10', label: 'Music' },
    { value: '13', label: 'How-to & Style' },
    { value: '20', label: 'Gaming' },
    { value: '22', label: 'People & Blogs' },
    { value: '23', label: 'Comedy' },
    { value: '24', label: 'Entertainment' },
    { value: '27', label: 'Education' },
    { value: '28', label: 'Science & Technology' }
  ],
  
  // Language options
  LANGUAGES: [
    { value: 'en', label: 'English' },
    { value: 'ur', label: 'Urdu' },
    { value: 'hi', label: 'Hindi' },
    { value: 'ar', label: 'Arabic' },
    { value: 'es', label: 'Spanish' }
  ],
  
  // Privacy options
  PRIVACY_OPTIONS: [
    { value: 'public', label: '🌐 Public' },
    { value: 'unlisted', label: '🔗 Unlisted' },
    { value: 'private', label: '🔒 Private' }
  ],
  
  // License options
  LICENSE_OPTIONS: [
    { value: 'youtube', label: 'Standard YouTube' },
    { value: 'creativeCommon', label: 'Creative Commons' }
  ],
  
  // Timezone options
  TIMEZONES: [
    'Asia/Karachi (PKT)',
    'UTC',
    'America/New_York',
    'Europe/London'
  ],
  
  // Upload schedule settings
  DEFAULT_SCHEDULE_TIME: '10:00',
  DEFAULT_MAX_VIDEOS_PER_DAY: 2,
  
  // Local storage keys
  STORAGE_KEYS: {
    LOG: 'bls_log',
    ACCOUNTS: 'bls_accounts'
  }
};
