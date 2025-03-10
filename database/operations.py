from datetime import datetime
import json
import time
from database.connection import get_db_connection
import config

def create_download_record(download_id, url, format_id, quality=None):
    """Ma'lumotlar bazasida yangi yuklash yozuvini yaratish"""
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
    conn = get_db_connection()
    cursor = conn.cursor()
    
    update_fields = []
    params = []
    
    for key, value in kwargs.items():
        if key != 'id':
            update_fields.append(f"{key} = ?")
            params.append(value)
    
    update_fields.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    
    params.append(download_id)
    
    sql = f"UPDATE downloads SET {', '.join(update_fields)} WHERE id = ?"
    cursor.execute(sql, params)
    
    conn.commit()
    conn.close()

def get_download_progress(download_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM downloads WHERE id = ?', (download_id,))
    record = cursor.fetchone()
    
    conn.close()
    
    if not record:
        return None
    
    return dict(record)

def save_to_cache(url, data):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    json_data = json.dumps(data)
    
    cursor.execute('''
    INSERT OR REPLACE INTO cache (url, data, timestamp)
    VALUES (?, ?, ?)
    ''', (url, json_data, time.time()))
    
    conn.commit()
    conn.close()

def get_from_cache(url):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT data, timestamp FROM cache WHERE url = ?', (url,))
    record = cursor.fetchone()
    
    conn.close()
    
    if not record:
        return None
    
    if time.time() - record['timestamp'] > config.CACHE_TIMEOUT:
        return None
    
    return json.loads(record['data'])

def clear_cache_db():
    """Barcha kesh yozuvlarini tozalash"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM cache')
    
    conn.commit()
    conn.close()