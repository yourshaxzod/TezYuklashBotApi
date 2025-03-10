from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List, Dict, Any, Union

class ApiResponse(BaseModel):
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