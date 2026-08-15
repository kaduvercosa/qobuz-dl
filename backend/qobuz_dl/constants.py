import re

FORMAT_IDS = {
    5: "MP3 320 kbps",
    6: "FLAC 16-Bit / 44.1 kHz (CD Quality)",
    7: "FLAC 24-Bit / <= 96 kHz (Hi-Res)",
    27: "FLAC 24-Bit / 192 kHz (Hi-Res Extreme)",
}

DEFAULT_FOLDER_FORMAT = "{artist}/{year} - {album} [{quality}]"
DEFAULT_TRACK_FORMAT = "{track_number} - {title}"

QOBUZ_URL_REGEX = re.compile(
    r"https?://(?:www\.|open\.|play\.)?qobuz\.com/(?:[a-zA-Z]{2}-[a-zA-Z]{2}/)?(?P<type>album|track|playlist|artist|label)/(?:[^/]+/)?(?P<id>[a-zA-Z0-9_-]+)"
)

DEFAULT_CONFIG = {
    "auth": {
        "email": "",
        "password": "",
        "user_id": "",
        "user_auth_token": "",
        "app_id": "712108709",
        "app_secret": ""
    },
    "quality": {
        "format_id": 27,
        "fallback_quality": True,
        "max_sample_rate": 192000,
        "max_bit_depth": 24,
        "embed_art": True,
        "art_resolution": "max",
        "save_cover_file": True,
        "cover_filename": "cover.jpg",
        "embed_lyrics": True,
        "save_lrc_file": True,
        "calculate_replaygain": False
    },
    "paths": {
        "download_dir": "./downloads",
        "folder_format": "{artist}/{year} - {album} [{quality}]",
        "track_format": "{track_number} - {title}",
        "sanitize_fat32": True,
        "overwrite_policy": "skip"
    },
    "engine": {
        "max_workers": 4,
        "chunk_size_kb": 1024,
        "max_retries": 3,
        "retry_delay_sec": 2,
        "bandwidth_limit_mbps": 0,
        "keep_cache": False
    },
    "integrations": {
        "telegram_enabled": False,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "discord_webhook_url": "",
        "desktop_notifications": True,
        "sound_alerts": True
    },
    "ui": {
        "theme": "nothing_dark",
        "glyph_effects": True,
        "dot_matrix_font": True,
        "live_visualizer": True,
        "red_accent": "#D71921"
    }
}

COUNTRY_NAMES = {
    'US': 'United States',
    'GB': 'United Kingdom',
    'FR': 'France',
    'DE': 'Germany',
    'IT': 'Italy',
    'ES': 'Spain',
    'NL': 'Netherlands',
    'BE': 'Belgium',
    'LU': 'Luxembourg',
    'CH': 'Switzerland',
    'AT': 'Austria',
    'IE': 'Ireland',
    'PT': 'Portugal',
    'SE': 'Sweden',
    'NO': 'Norway',
    'DK': 'Denmark',
    'FI': 'Finland',
    'AU': 'Australia',
    'NZ': 'New Zealand',
    'CA': 'Canada',
    'JP': 'Japan',
    'BR': 'Brazil',
    'MX': 'Mexico',
    'AR': 'Argentina',
    'CL': 'Chile',
    'CO': 'Colombia',
}
