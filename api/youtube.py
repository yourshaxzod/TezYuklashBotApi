import uuid
from fastapi import APIRouter, Request, BackgroundTasks, Query, HTTPException, Depends
from fastapi.responses import FileResponse
import os
from pydantic import HttpUrl, Field, BaseModel
from typing import Optional
from models.schemas import ApiResponse
from database.operations import create_download_record, get_download_progress
from services.info_service import get_video_info
from services.download_service import download_video
from utils.proxy_manager import get_proxy
import config

router = APIRouter()

class DownloadOptions(BaseModel):
    """Yuklash uchun qo'shimcha parametrlar"""
    use_proxy: Optional[bool] = Field(True, description="Proxy ishlatish")


# ----- YOUTUBE ENDPOINTLARI -----

@router.get("/youtube", response_model=ApiResponse, tags=["YouTube"])
@config.limiter.limit("10/minute")
async def get_youtube_info_route(request: Request, url: HttpUrl):
    try:
        if "youtube.com" not in str(url) and "youtu.be" not in str(url):
            return ApiResponse(
                status=False,
                message="Noto'g'ri YouTube URL",
                error="URL youtube.com yoki youtu.be dan bo'lishi kerak"
            )
        
        video_info = get_video_info(str(url))
        return ApiResponse(
            status=True,
            message="Video ma'lumotlari muvaffaqiyatli olindi",
            data=video_info
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Video ma'lumotlarini olishda xatolik",
            error=str(e)
        )

@router.post("/youtube/download", response_model=ApiResponse, tags=["YouTube"])
@config.limiter.limit("3/minute")
async def download_youtube_video_route(
    request: Request,
    background_tasks: BackgroundTasks,
    url: HttpUrl,
    format_id: str,
    options: Optional[DownloadOptions] = None
):
    try:
        if "youtube.com" not in str(url) and "youtu.be" not in str(url):
            return ApiResponse(
                status=False,
                message="Noto'g'ri YouTube URL",
                error="URL youtube.com yoki youtu.be dan bo'lishi kerak"
            )
        
        download_id = str(uuid.uuid4())
        
        create_download_record(download_id, str(url), format_id)
        
        use_proxy = options.use_proxy if options else True
        
        background_tasks.add_task(
            download_video, 
            download_id, 
            str(url), 
            format_id=format_id, 
            use_proxy=use_proxy
        )
        
        return ApiResponse(
            status=True,
            message="Yuklash boshlandi",
            data={
                "download_id": download_id,
                "using_proxy": use_proxy
            }
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Yuklashni boshlashda xatolik",
            error=str(e)
        )

@router.post("/youtube/download-quality", response_model=ApiResponse, tags=["YouTube"])
@config.limiter.limit("3/minute")
async def download_youtube_by_quality_route(
    request: Request,
    background_tasks: BackgroundTasks,
    url: HttpUrl,
    quality: str = Query(..., description="Sifatni tanlang", enum=config.SUPPORTED_QUALITIES),
    options: Optional[DownloadOptions] = None
):
    try:
        if "youtube.com" not in str(url) and "youtu.be" not in str(url):
            return ApiResponse(
                status=False,
                message="Noto'g'ri YouTube URL",
                error="URL youtube.com yoki youtu.be dan bo'lishi kerak"
            )
        
        download_id = str(uuid.uuid4())
        
        create_download_record(download_id, str(url), "", quality)
        
        use_proxy = options.use_proxy if options else True
        
        background_tasks.add_task(
            download_video, 
            download_id, 
            str(url), 
            quality=quality, 
            use_proxy=use_proxy
        )
        
        return ApiResponse(
            status=True,
            message=f"{quality} sifatda yuklash boshlandi",
            data={
                "download_id": download_id, 
                "quality": quality,
                "using_proxy": use_proxy
            }
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Yuklashni boshlashda xatolik",
            error=str(e)
        )

@router.get("/youtube/progress/{download_id}", response_model=ApiResponse, tags=["YouTube"])
@config.limiter.limit("30/minute")
async def get_download_progress_route(request: Request, download_id: str):
    try:
        progress = get_download_progress(download_id)
        
        if not progress:
            return ApiResponse(
                status=False,
                message="Yuklash topilmadi",
                error=f"{download_id} ID bilan yuklash topilmadi"
            )
        
        return ApiResponse(
            status=True,
            message="Yuklash holati olindi",
            data=progress
        )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Yuklash holatini olishda xatolik",
            error=str(e)
        )

@router.get("/youtube/proxy/status", response_model=ApiResponse, tags=["YouTube"])
@config.limiter.limit("10/minute")
async def get_proxy_status_route(request: Request):
    try:
        proxy = get_proxy()
        
        if proxy:
            # Proxyni yashirish (security maqsadida)
            proxy_parts = proxy.split('@')
            if len(proxy_parts) > 1:
                # Auth ma'lumotlari bo'lsa
                masked_proxy = f"***@{proxy_parts[1]}"
            else:
                # Auth ma'lumotlari bo'lmasa
                masked_proxy = proxy.replace(":", ":***@", 1) if ":" in proxy else proxy
                
            return ApiResponse(
                status=True,
                message="Proxy holati",
                data={
                    "proxy_available": True,
                    "proxy": masked_proxy
                }
            )
        else:
            return ApiResponse(
                status=True,
                message="Proxy holati",
                data={
                    "proxy_available": False,
                    "proxy": None
                }
            )
    except Exception as e:
        return ApiResponse(
            status=False,
            message="Proxy holatini olishda xatolik",
            error=str(e)
        )

@router.get("/downloads/{filename}", response_model=None, tags=["YouTube"])
@config.limiter.limit("10/minute")
async def get_downloaded_file_route(request: Request, filename: str):
    file_path = os.path.join(config.DOWNLOAD_DIR, filename)
    if not os.path.exists(file_path):
        return ApiResponse(
            status=False,
            message="Fayl topilmadi",
            error=f"{filename} fayli mavjud emas"
        )
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream"
    )