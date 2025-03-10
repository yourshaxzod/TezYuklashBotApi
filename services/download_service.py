import os
import asyncio
from yt_dlp import YoutubeDL
from fastapi import HTTPException
from database.operations import update_download_progress
from utils.quality_mapper import get_best_format_for_quality
from utils.proxy_manager import get_proxy
import config

async def download_video(download_id: str, url: str, format_id: str = None, quality: str = None, output_dir: str = "downloads", use_proxy: bool = True):
    try:
        if format_id is None and quality is not None:
            if quality == "360p":
                format_id = "18"
                if not format_id:
                    format_id = get_best_format_for_quality(url, quality, require_audio=True)
            else:
                format_id = get_best_format_for_quality(url, quality)
            
            if not format_id:
                error_msg = f"Bu video uchun {quality} sifat formatini topib bo'lmadi"
                update_download_progress(download_id, status='error', error_message=error_msg)
                raise HTTPException(status_code=404, detail=error_msg)
        
        update_download_progress(download_id, format_id=format_id, status='starting')
        
        def custom_progress_hook(d):
            if d['status'] == 'downloading':
                progress_data = {
                    'status': 'downloading',
                    'downloaded_bytes': d.get('downloaded_bytes'),
                    'total_bytes': d.get('total_bytes'),
                    'eta': d.get('eta'),
                    'speed': d.get('speed'),
                    'filename': d.get('filename')
                }
                
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
                if total_bytes and d.get('downloaded_bytes'):
                    progress_data['progress'] = d.get('downloaded_bytes') / total_bytes * 100
                    
                update_download_progress(download_id, **progress_data)
                
            elif d['status'] == 'finished':
                download_info = d.get('info_dict', {})
                if ('_mp4' in d.get('filename', '') and 'Merger' in download_info.get('__class__', '')) or 'requested_formats' not in download_info:
                    update_download_progress(
                        download_id, 
                        status='finished',
                        progress=100,
                        filename=d.get('filename')
                    )
        
        ydl_opts = {
            'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
            'progress_hooks': [custom_progress_hook],
            'quiet': False,
            'no_warnings': False,
            'cookiefile': 'youtube.com_cookies.txt',
        }
        
        if quality == "360p":
            ydl_opts['format'] = format_id
        elif quality == "MP3":
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['format'] = f"{format_id}+bestaudio/best" if format_id else 'bestvideo+bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
        
        if use_proxy:
            proxy = get_proxy()
            if proxy:
                ydl_opts['proxy'] = proxy
        
        def download_task():
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info and 'requested_downloads' in info and info['requested_downloads']:
                    filename = info['requested_downloads'][0].get('filepath', '').split('/')[-1]
                    update_download_progress(download_id, filename=filename)
                
                return info
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, download_task)
        update_download_progress(download_id, status='completed', progress=100)
        
    except Exception as e:
        update_download_progress(download_id, status='error', error_message=str(e))
        raise e