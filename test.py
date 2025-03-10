from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request, Query
from fastapi.responses import JSONResponse, FileResponse
from yt_dlp import YoutubeDL
from typing import Optional, List, Dict, Any, Union
import uvicorn
import os
import time
import uuid
from functools import lru_cache
from pydantic import BaseModel, HttpUrl, Field
import asyncio
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import sqlite3
from datetime import datetime
import json

# ----- CONFIGURATION -----

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize FastAPI app
app = FastAPI(
    title="Tez Yuklash API",
    description="Ijtimoiy tarmoqlardan video va audio yuklash yoki malumot olish uchun api.",
    version="1.0.1"
)

# Set up rate limit handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Create necessary directories
os.makedirs("downloads", exist_ok=True)
os.makedirs("database", exist_ok=True)

# Cache configuration
CACHE_TIMEOUT = 3600  # Cache timeout in seconds (1 hour)
cache = {}

# Quality standards
SUPPORTED_QUALITIES = ["144p", "240p", "360p", "480p", "720p", "1080p", "2K", "4K", "MP3"]

# ----- DATABASE SETUP -----

DB_PATH = "database/video_api.sql"

def get_db_connection():
    """Create a connection to the SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with required tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create downloads table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS downloads (
        id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        format_id TEXT NOT NULL,
        quality TEXT,
        status TEXT NOT NULL,
        progress REAL DEFAULT 0,
        eta REAL,
        speed REAL,
        downloaded_bytes INTEGER,
        total_bytes INTEGER,
        filename TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    ''')
    
    # Create cache table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS cache (
        url TEXT PRIMARY KEY,
        data TEXT NOT NULL,
        timestamp REAL NOT NULL
    )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

# ----- DATA MODELS -----

class ApiResponse(BaseModel):
    """Base model for API responses with status field"""
    status: bool
    message: str
    data: Optional[Dict] = None
    error: Optional[str] = None

class FormatInfo(BaseModel):
    format_id: str
    quality: str
    ext: str
    filesize: Optional[int] = None
    
class VideoInfo(BaseModel):
    url: HttpUrl
    title: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
    author: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    formats: Optional[List[FormatInfo]] = None

class DownloadProgress(BaseModel):
    id: str
    url: str
    format_id: str
    quality: Optional[str] = None
    status: str = "pending"
    progress: float = 0
    eta: Optional[float] = None
    speed: Optional[float] = None
    downloaded_bytes: Optional[int] = None
    total_bytes: Optional[int] = None
    filename: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: str

# ----- DATABASE FUNCTIONS -----

def create_download_record(download_id, url, format_id, quality=None):
    """Create a new download record in the database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute('''
    INSERT INTO downloads (id, url, format_id, quality, status, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (download_id, url, format_id, quality, 'pending', now, now))
    
    conn.commit()
    conn.close()

def update_download_progress(download_id, **kwargs):
    """Update download progress in the database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Start building the SQL query and parameters
    update_fields = []
    params = []
    
    # Add each provided parameter to the update
    for key, value in kwargs.items():
        if key != 'id':  # Don't update the ID
            update_fields.append(f"{key} = ?")
            params.append(value)
    
    # Always update the updated_at timestamp
    update_fields.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    
    # Add the ID as the last parameter for the WHERE clause
    params.append(download_id)
    
    # Build and execute the SQL query
    sql = f"UPDATE downloads SET {', '.join(update_fields)} WHERE id = ?"
    cursor.execute(sql, params)
    
    conn.commit()
    conn.close()

def get_download_progress(download_id):
    """Get download progress from the database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM downloads WHERE id = ?', (download_id,))
    record = cursor.fetchone()
    
    conn.close()
    
    if not record:
        return None
    
    # Convert SQLite row to dictionary
    return dict(record)

def save_to_cache(url, data):
    """Save data to cache table"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Convert data to JSON string
    json_data = json.dumps(data)
    
    # Insert or replace
    cursor.execute('''
    INSERT OR REPLACE INTO cache (url, data, timestamp)
    VALUES (?, ?, ?)
    ''', (url, json_data, time.time()))
    
    conn.commit()
    conn.close()

def get_from_cache(url):
    """Get data from cache table if not expired"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT data, timestamp FROM cache WHERE url = ?', (url,))
    record = cursor.fetchone()
    
    conn.close()
    
    if not record:
        return None
    
    # Check if cache is expired
    if time.time() - record['timestamp'] > CACHE_TIMEOUT:
        return None
    
    # Parse JSON data
    return json.loads(record['data'])

def clear_cache_db():
    """Clear all cache entries"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM cache')
    
    conn.commit()
    conn.close()

# ----- HELPER FUNCTIONS -----

def map_resolution_to_standard(format_data):
    """
    Map YouTube's format data to standardized quality format
    Returns None if format doesn't match our standard qualities
    """
    # Extract resolution or format_note
    resolution = format_data.get('resolution')
    format_note = format_data.get('format_note', '')
    height = format_data.get('height')
    
    # Check if it's an audio format (no video stream)
    if format_data.get('vcodec') == 'none' and format_data.get('acodec') != 'none':
        return "MP3"
    
    # Map resolutions to standard formats
    if height is not None:
        if height <= 144:
            return "144p"
        elif height <= 240:
            return "240p"
        elif height <= 360:
            return "360p"
        elif height <= 480:
            return "480p"
        elif height <= 720:
            return "720p"
        elif height <= 1080:
            return "1080p"
        elif height <= 1440:
            return "2K"
        elif height <= 2160:
            return "4K"
    
    # If height is not available, try to parse from format_note or resolution
    if isinstance(format_note, str) and format_note:
        if '144p' in format_note:
            return "144p"
        elif '240p' in format_note:
            return "240p"
        elif '360p' in format_note:
            return "360p"
        elif '480p' in format_note:
            return "480p"
        elif '720p' in format_note:
            return "720p"
        elif '1080p' in format_note:
            return "1080p"
        elif '1440p' in format_note or '2k' in format_note.lower():
            return "2K"
        elif '2160p' in format_note or '4k' in format_note.lower():
            return "4K"
    
    # Check resolution string if available
    if isinstance(resolution, str) and resolution:
        if '144p' in resolution:
            return "144p"
        elif '240p' in resolution:
            return "240p"
        elif '360p' in resolution:
            return "360p"
        elif '480p' in resolution:
            return "480p"
        elif '720p' in resolution:
            return "720p"
        elif '1080p' in resolution:
            return "1080p"
        elif '1440p' in resolution or '2k' in resolution.lower():
            return "2K"
        elif '2160p' in resolution or '4k' in resolution.lower():
            return "4K"
    
    # Couldn't map to a standard quality
    return None

def get_best_format_for_quality(url: str, quality: str):
    """
    Get the best format_id for the given quality standard
    """
    # Define quality mappings to yt-dlp format selectors
    quality_format_map = {
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
    
    if quality not in quality_format_map:
        raise ValueError(f"Unsupported quality: {quality}")
    
    format_selector = quality_format_map[quality]
    
    # Get the best format for the requested quality
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': format_selector,
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'format_id' in info:
                return info['format_id']
            else:
                return None
    except Exception as e:
        print(f"Error getting format for quality {quality}: {str(e)}")
        return None

def download_progress_hook(d):
    """
    Hook for tracking download progress
    """
    url = d.get('info_dict', {}).get('webpage_url')
    if url is None:
        return
        
    format_id = d.get('info_dict', {}).get('format_id', 'unknown')
    download_id = d.get('info_dict', {}).get('download_id', None)
    
    if download_id is None:
        return
    
    if d['status'] == 'downloading':
        progress_data = {
            'status': 'downloading',
            'downloaded_bytes': d.get('downloaded_bytes'),
            'total_bytes': d.get('total_bytes'),
            'eta': d.get('eta'),
            'speed': d.get('speed'),
            'filename': d.get('filename')
        }
        
        if d.get('total_bytes'):
            progress_data['progress'] = d.get('downloaded_bytes', 0) / d.get('total_bytes', 1) * 100
        elif d.get('total_bytes_estimate'):
            progress_data['progress'] = d.get('downloaded_bytes', 0) / d.get('total_bytes_estimate', 1) * 100
            
        update_download_progress(download_id, **progress_data)
        
    elif d['status'] == 'finished':
        update_download_progress(
            download_id, 
            status='finished',
            progress=100,
            filename=d.get('filename')
        )

def get_video_info(url: str) -> dict:
    """
    Get video information with caching mechanism
    """
    # Check if we have a valid cached response
    cached_data = get_from_cache(url)
    if cached_data:
        return cached_data
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Process formats to standard qualities
            seen_qualities = set()
            formats = []
            
            if "formats" in info:
                # Sort formats by quality (typically higher quality formats have higher format_ids)
                sorted_formats = sorted(
                    info.get("formats", []),
                    key=lambda x: (
                        # Prefer formats with both audio and video
                        0 if x.get("acodec") != "none" and x.get("vcodec") != "none" else 1,
                        # Then sort by resolution/height
                        -(x.get("height") or 0)
                    )
                )
                
                for format_data in sorted_formats:
                    # Map to standard quality
                    quality = map_resolution_to_standard(format_data)
                    
                    # Skip if couldn't map to standard quality or already seen this quality
                    if quality is None or quality in seen_qualities:
                        continue
                    
                    # Add to our standard formats and mark quality as seen
                    formats.append({
                        "format_id": format_data.get("format_id"),
                        "quality": quality,
                        "ext": format_data.get("ext", ""),
                        "filesize": format_data.get("filesize")
                    })
                    
                    # Add quality to seen set to avoid duplicates
                    seen_qualities.add(quality)
            
            # Sort formats by quality for better presentation
            quality_order = {
                "MP3": 0,
                "144p": 1, 
                "240p": 2, 
                "360p": 3, 
                "480p": 4, 
                "720p": 5, 
                "1080p": 6, 
                "2K": 7, 
                "4K": 8
            }
            
            formats = sorted(formats, key=lambda x: quality_order.get(x["quality"], 999))
            
            result = {
                "url": url,
                "title": info.get("title"),
                "description": info.get("description"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "author": info.get("uploader"),
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "formats": formats
            }
            
            # Cache the result
            save_to_cache(url, result)
            
            return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

async def download_video(download_id: str, url: str, format_id: str = None, quality: str = None, output_dir: str = "downloads"):
    """
    Download a video asynchronously by format_id or by finding the best format for a quality
    """
    try:
        # Get format_id if quality is provided but format_id is not
        if format_id is None and quality is not None:
            format_id = get_best_format_for_quality(url, quality)
            if not format_id:
                error_msg = f"Couldn't find format for quality {quality} for this video"
                update_download_progress(download_id, status='error', error_message=error_msg)
                raise HTTPException(status_code=404, detail=error_msg)
        
        # Update database with format_id
        update_download_progress(download_id, format_id=format_id, status='starting')
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
            'progress_hooks': [download_progress_hook],
            'quiet': True,
            'no_warnings': True,
        }
        
        # Add download_id to info dict so it can be accessed in the progress_hook
        ydl_opts['postprocessor_args'] = ['-download_id', download_id]
        
        # For MP3, add additional options
        if quality == "MP3":
            ydl_opts.update({
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            })
        
        def download_task():
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    # Add download_id to info_dict
                    ydl.params['download_id'] = download_id
                    info = ydl.extract_info(url, download=True)
                    
                    # Get the filename of the downloaded file
                    if info and 'requested_downloads' in info and info['requested_downloads']:
                        filename = info['requested_downloads'][0].get('filepath', '').split('/')[-1]
                        update_download_progress(download_id, filename=filename)
                    
                    return info
            except Exception as e:
                update_download_progress(download_id, status='error', error_message=str(e))
                raise e
        
        # Run in a separate thread
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, download_task)
        
        # Final update - mark as completed
        update_download_progress(download_id, status='completed', progress=100)
        
    except Exception as e:
        update_download_progress(download_id, status='error', error_message=str(e))
        raise e

# ----- API ENDPOINTS -----

@app.get("/", response_model=ApiResponse)
async def root():
    """
    API root with basic information
    """
    return ApiResponse(
        status=True,
        message="Video Information API",
        data={
            "version": "1.0.1",
            "endpoints": [
                "/youtube",
                "/youtube/download",
                "/youtube/download-quality",
                "/youtube/progress/{download_id}",
                "/downloads/{filename}",
                "/instagram",
                "/tiktok",
                "/likee",
                "/pinterest",
                "/clear-cache"
            ]
        }
    )

# ----- YOUTUBE ENDPOINTS -----

@app.get("/youtube", response_model=ApiResponse)
@limiter.limit("10/minute")
async def get_youtube_info(request: Request, url: HttpUrl):
    """
    Get video information from YouTube including available formats
    """
    try:
        if "youtube.com" not in str(url) and "youtu.be" not in str(url):
            return ApiResponse(
                status=False,
                message="Invalid YouTube URL",
                error="URL must be from youtube.com or youtu.be"
            )
        
        video_info = get_video_info(str(url))
        return ApiResponse(
            status=True,
            message="Video information retrieved successfully",
            data=video_info
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Failed to retrieve video information",
            error=str(e)
        )

@app.post("/youtube/download", response_model=ApiResponse)
@limiter.limit("3/minute")
async def download_youtube_video(
    request: Request,
    background_tasks: BackgroundTasks,
    url: HttpUrl,
    format_id: str
):
    """
    Download a YouTube video in the specified format
    """
    try:
        if "youtube.com" not in str(url) and "youtu.be" not in str(url):
            return ApiResponse(
                status=False,
                message="Invalid YouTube URL",
                error="URL must be from youtube.com or youtu.be"
            )
        
        # Generate a unique download ID
        download_id = str(uuid.uuid4())
        
        # Create initial record in database
        create_download_record(download_id, str(url), format_id)
        
        # Start download in background
        background_tasks.add_task(download_video, download_id, str(url), format_id=format_id)
        
        return ApiResponse(
            status=True,
            message="Download started",
            data={"download_id": download_id}
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Failed to start download",
            error=str(e)
        )

@app.post("/youtube/download-quality", response_model=ApiResponse)
@limiter.limit("3/minute")
async def download_youtube_by_quality(
    request: Request,
    background_tasks: BackgroundTasks,
    url: HttpUrl,
    quality: str = Query(..., description="Select quality", enum=SUPPORTED_QUALITIES)
):
    """
    Download a YouTube video by standard quality directly
    """
    try:
        if "youtube.com" not in str(url) and "youtu.be" not in str(url):
            return ApiResponse(
                status=False,
                message="Invalid YouTube URL",
                error="URL must be from youtube.com or youtu.be"
            )
        
        # Generate a unique download ID
        download_id = str(uuid.uuid4())
        
        # Create initial record in database
        create_download_record(download_id, str(url), "", quality)
        
        # Start download in background
        background_tasks.add_task(download_video, download_id, str(url), quality=quality)
        
        return ApiResponse(
            status=True,
            message=f"Download started for {quality} quality",
            data={"download_id": download_id, "quality": quality}
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Failed to start download",
            error=str(e)
        )

@app.get("/youtube/progress/{download_id}", response_model=ApiResponse)
@limiter.limit("30/minute")
async def get_download_progress_endpoint(request: Request, download_id: str):
    """
    Get the current progress of a YouTube download
    """
    try:
        progress = get_download_progress(download_id)
        
        if not progress:
            return ApiResponse(
                status=False,
                message="Download not found",
                error=f"No download found with ID {download_id}"
            )
        
        return ApiResponse(
            status=True,
            message="Download progress retrieved",
            data=progress
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Failed to retrieve download progress",
            error=str(e)
        )

@app.get("/downloads/{filename}", response_model=None)
@limiter.limit("10/minute")
async def get_downloaded_file(request: Request, filename: str):
    """
    Download a previously downloaded file
    """
    file_path = os.path.join("downloads", filename)
    if not os.path.exists(file_path):
        return ApiResponse(
            status=False,
            message="File not found",
            error=f"File {filename} does not exist"
        )
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )

# ----- OTHER PLATFORM ENDPOINTS -----

@app.get("/instagram", response_model=ApiResponse)
@limiter.limit("10/minute")
async def get_instagram_info(request: Request, url: HttpUrl):
    """
    Get video information from Instagram
    """
    try:
        if "instagram.com" not in str(url):
            return ApiResponse(
                status=False,
                message="Invalid Instagram URL",
                error="URL must be from instagram.com"
            )
        
        video_info = get_video_info(str(url))
        return ApiResponse(
            status=True,
            message="Video information retrieved successfully",
            data=video_info
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Failed to retrieve video information",
            error=str(e)
        )

@app.get("/tiktok", response_model=ApiResponse)
@limiter.limit("10/minute")
async def get_tiktok_info(request: Request, url: HttpUrl):
    """
    Get video information from TikTok
    """
    try:
        if "tiktok.com" not in str(url):
            return ApiResponse(
                status=False,
                message="Invalid TikTok URL",
                error="URL must be from tiktok.com"
            )
        
        video_info = get_video_info(str(url))
        return ApiResponse(
            status=True,
            message="Video information retrieved successfully",
            data=video_info
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Failed to retrieve video information",
            error=str(e)
        )

@app.get("/likee", response_model=ApiResponse)
@limiter.limit("10/minute")
async def get_likee_info(request: Request, url: HttpUrl):
    """
    Get video information from Likee
    """
    try:
        if "likee.com" not in str(url):
            return ApiResponse(
                status=False,
                message="Invalid Likee URL",
                error="URL must be from likee.com"
            )
        
        video_info = get_video_info(str(url))
        return ApiResponse(
            status=True,
            message="Video information retrieved successfully",
            data=video_info
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Failed to retrieve video information",
            error=str(e)
        )

@app.get("/pinterest", response_model=ApiResponse)
@limiter.limit("10/minute")
async def get_pinterest_info(request: Request, url: HttpUrl):
    """
    Get video information from Pinterest
    """
    try:
        if "pinterest.com" not in str(url):
            return ApiResponse(
                status=False,
                message="Invalid Pinterest URL",
                error="URL must be from pinterest.com"
            )
        
        video_info = get_video_info(str(url))
        return ApiResponse(
            status=True,
            message="Video information retrieved successfully",
            data=video_info
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Failed to retrieve video information",
            error=str(e)
        )

# ----- ADMIN ENDPOINTS -----

@app.get("/clear-cache", response_model=ApiResponse)
@limiter.limit("5/hour")
async def clear_cache(request: Request):
    """
    Clear the API cache (admin endpoint)
    """
    try:
        clear_cache_db()
        return ApiResponse(
            status=True,
            message="Cache cleared successfully"
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Failed to clear cache",
            error=str(e)
        )

# ----- ERROR HANDLERS -----

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content=ApiResponse(
            status=False,
            message="An internal server error occurred",
            error=str(exc)
        ).dict()
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse(
            status=False,
            message=exc.detail,
            error=exc.detail
        ).dict()
    )

# ----- START SERVER -----

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)