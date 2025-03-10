from yt_dlp import YoutubeDL
from fastapi import HTTPException
from database.operations import get_from_cache, save_to_cache
from utils.quality_mapper import map_resolution_to_standard

def get_video_info(url: str) -> dict:
    cached_data = get_from_cache(url)
    if cached_data:
        return cached_data
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'writeinfojson': True,
        'skip_download': True
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            seen_qualities = set()
            formats = []
            
            quality_order = {
                "MP3": 0, "144p": 1, "240p": 2, "360p": 3, "480p": 4,
                "720p": 5, "1080p": 6, "2K": 7, "4K": 8
            }
            
            if "formats" in info:
                sorted_formats = sorted(
                    info.get("formats", []),
                    key=lambda x: (
                        0 if x.get("acodec") != "none" and x.get("vcodec") != "none" else 1,
                        -(x.get("height") or 0)
                    )
                )
                
                for format_data in sorted_formats:
                    quality = map_resolution_to_standard(format_data)
                    
                    if quality is None or quality in seen_qualities:
                        continue
                    
                    filesize = format_data.get("filesize")
                    
                    if filesize is None:
                        filesize = format_data.get("file_size")
                    if filesize is None:
                        filesize = format_data.get("filesize_approx")
                    
                    if filesize is None and info.get("duration") and format_data.get("tbr"):
                        filesize = int((format_data.get("tbr", 0) * info.get("duration", 0) * 1000) / 8)
                    
                    formats.append({
                        "format_id": format_data.get("format_id"),
                        "quality": quality,
                        "ext": format_data.get("ext", ""),
                        "filesize": filesize
                    })
                    
                    seen_qualities.add(quality)
            
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
            
            save_to_cache(url, result)
            
            return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))