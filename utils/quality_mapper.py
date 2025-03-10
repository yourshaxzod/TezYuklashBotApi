from yt_dlp import YoutubeDL

def map_resolution_to_standard(format_data):
    resolution = format_data.get('resolution')
    format_note = format_data.get('format_note', '')
    height = format_data.get('height')
    
    if format_data.get('vcodec') == 'none' and format_data.get('acodec') != 'none':
        return "MP3"
    
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
    return None

def get_best_format_for_quality(url: str, quality: str):
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