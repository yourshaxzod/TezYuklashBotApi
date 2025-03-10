from database.operations import update_download_progress

def download_progress_hook(d):
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