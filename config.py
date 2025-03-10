import os
from slowapi import Limiter
from slowapi.util import get_remote_address

DB_PATH = "database/video_api.sql"

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs("database", exist_ok=True)

CACHE_TIMEOUT = 3600  # 1 soat

limiter = Limiter(key_func=get_remote_address)

SUPPORTED_QUALITIES = ["144p", "240p", "360p", "480p", "720p", "1080p", "2K", "4K", "MP3"]

QUALITY_FORMAT_MAP = {
    "144p": "worst[height<=144]",
    "240p": "worst[height<=240][height>144]",
    "360p": "worst[height<=360][height>240]",
    "480p": "worst[height<=480][height>360]",
    "720p": "best[height<=720][height>480]",
    "1080p": "best[height<=1080][height>720]",
    "2K": "best[height<=1440][height>1080]",
    "4K": "best[height<=2160][height>1440]",
    "MP3": "bestaudio/best"
}