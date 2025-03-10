import sqlite3
import requests
import random
import time
import threading
import logging
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta

# Logger o'rnatish
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='proxy_manager.log'
)
logger = logging.getLogger('proxy_manager')

class ProxyManager:
    """
    Proxylarni boshqarish tizimi:
    - Proxylarni yig'ish
    - Ularni tekshirish
    - Ishlamaydiganlarni o'chirish
    - Ishlaydigan proxylarni rotatsiya qilib berish
    """
    
    def __init__(self, db_path: str = "database/proxies.db", check_interval: int = 3600):
        """
        Proxy boshqaruvchisini ishga tushirish
        
        :param db_path: Proxylar saqlanadigan ma'lumotlar bazasi
        :param check_interval: Proxylarni tekshirish oralig'i (sekundda)
        """
        self.db_path = db_path
        self.check_interval = check_interval
        self.last_proxy_index = 0
        
        # Ma'lumotlar bazasini ishga tushirish
        self._init_db()
        
        # Proxylarni yig'ish va tekshirish jarayonini boshlash
        self._start_proxy_checker()
    
    def _init_db(self):
        """Ma'lumotlar bazasini ishga tushirish"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Proxylar jadvali
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            port INTEGER NOT NULL,
            protocol TEXT NOT NULL,
            username TEXT,
            password TEXT,
            working INTEGER DEFAULT 1,
            last_checked TIMESTAMP,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            response_time REAL,
            source TEXT,
            UNIQUE(ip, port, protocol)
        )
        ''')
        
        # Proxylar manbasi jadvali
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS proxy_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            parser_type TEXT NOT NULL,
            last_fetch TIMESTAMP,
            enabled INTEGER DEFAULT 1
        )
        ''')
        
        conn.commit()
        conn.close()
        
        # Oldindan belgilangan manbalarni qo'shish
        self._add_default_sources()
    
    def _add_default_sources(self):
        """Oldindan belgilangan manbalarni qo'shish"""
        default_sources = [
            ("https://www.proxy-list.download/api/v1/get?type=http", "simple_list"),
            ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "simple_list"),
            ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt", "simple_list"),
            ("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list.txt", "custom_format"),
            ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "simple_list"),
            ("https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all", "simple_list"),
        ]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for url, parser_type in default_sources:
            cursor.execute(
                "INSERT OR IGNORE INTO proxy_sources (url, parser_type) VALUES (?, ?)",
                (url, parser_type)
            )
        
        conn.commit()
        conn.close()
    
    def _start_proxy_checker(self):
        """Proxylarni tekshirish jarayonini boshlash"""
        thread = threading.Thread(target=self._proxy_checker_thread, daemon=True)
        thread.start()
    
    def _proxy_checker_thread(self):
        """Proxylarni tekshirish jarayoni"""
        while True:
            try:
                # Yangi proxylarni olish
                self.fetch_new_proxies()
                
                # Mavjud proxylarni tekshirish
                self.check_proxies()
                
                # Keyingi tekshirishgacha kutish
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Proxy tekshirish jarayonida xatolik: {str(e)}")
                time.sleep(60)  # Xatolik yuz berganda 1 daqiqa kutish
    
    def fetch_new_proxies(self):
        """Manbalardan yangi proxylarni olish"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Yoqilgan manbalarni olish
        cursor.execute("SELECT id, url, parser_type FROM proxy_sources WHERE enabled = 1")
        sources = cursor.fetchall()
        
        for source_id, url, parser_type in sources:
            try:
                logger.info(f"Proxylarni olish: {url}")
                
                # Manbadan ma'lumotlarni olish
                response = requests.get(url, timeout=30)
                
                if response.status_code == 200:
                    # Parser turini tekshirish
                    if parser_type == "simple_list":
                        proxies = self._parse_simple_list(response.text)
                    elif parser_type == "json":
                        proxies = self._parse_json(response.text)
                    elif parser_type == "custom_format":
                        proxies = self._parse_custom_format(response.text)
                    else:
                        logger.warning(f"Noma'lum parser turi: {parser_type}")
                        continue
                    
                    # Proxylarni bazaga qo'shish
                    for proxy in proxies:
                        protocol, ip, port, username, password = proxy
                        
                        cursor.execute(
                            "INSERT OR IGNORE INTO proxies (protocol, ip, port, username, password, last_checked, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (protocol, ip, port, username, password, datetime.now(), url)
                        )
                    
                    # Manba ohirgi marta tekshirilgan vaqtni yangilash
                    cursor.execute(
                        "UPDATE proxy_sources SET last_fetch = ? WHERE id = ?",
                        (datetime.now(), source_id)
                    )
                    
                    conn.commit()
                    logger.info(f"Qo'shildi: {len(proxies)} proxylar from {url}")
                else:
                    logger.warning(f"Manbadan ma'lumot olishda xatolik: {url}, Holat: {response.status_code}")
            
            except Exception as e:
                logger.error(f"Manba bilan ishlashda xatolik: {url}, Xatolik: {str(e)}")
        
        conn.close()
    
    def _parse_simple_list(self, text: str) -> List[Tuple[str, str, int, Optional[str], Optional[str]]]:
        """Oddiy ro'yxat formatidagi proxylarni tahlil qilish (har bir qatorda ip:port)"""
        proxies = []
        
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            try:
                if '@' in line:  # auth ma'lumotlari bo'lsa
                    auth, addr = line.split('@')
                    username, password = auth.split(':')
                    ip, port = addr.split(':')
                else:  # auth ma'lumotlari bo'lmasa
                    username, password = None, None
                    ip, port = line.split(':')
                
                protocol = 'http'  # odatiy protokol
                port = int(port)
                
                proxies.append((protocol, ip, port, username, password))
            except Exception as e:
                logger.debug(f"Qatorni tahlil qilishda xatolik: {line}, Xatolik: {str(e)}")
        
        return proxies
    
    def _parse_json(self, text: str) -> List[Tuple[str, str, int, Optional[str], Optional[str]]]:
        """JSON formatidagi proxylarni tahlil qilish"""
        # Bu metodka manba turlariga qarab kengaytirish kerak
        # Siz ishlayotgan JSON manbalariga mos keltirishingiz mumkin
        return []
    
    def _parse_custom_format(self, text: str) -> List[Tuple[str, str, int, Optional[str], Optional[str]]]:
        """Boshqa formatdagi proxylarni tahlil qilish"""
        proxies = []
        
        try:
            lines = text.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                parts = line.split()
                if len(parts) >= 2:
                    ip_port = parts[0].strip()
                    if ':' in ip_port:
                        ip, port_str = ip_port.split(':')
                        try:
                            port = int(port_str)
                            protocol = 'http'
                            proxies.append((protocol, ip, port, None, None))
                        except ValueError:
                            pass
        except Exception as e:
            logger.debug(f"Custom format tahlil qilishda xatolik: {str(e)}")
        
        return proxies
    
    def check_proxies(self):
        """Mavjud proxylarni tekshirish"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Tekshirish kerak bo'lgan proxylarni olish
        cursor.execute(
            "SELECT id, protocol, ip, port, username, password FROM proxies "
            "WHERE working = 1 OR (last_checked IS NULL OR last_checked < datetime('now', '-1 day'))"
        )
        proxies = cursor.fetchall()
        
        if not proxies:
            logger.info("Tekshirish uchun proxylar topilmadi")
            conn.close()
            return
        
        logger.info(f"Proxylarni tekshirish: {len(proxies)}")
        
        for proxy_id, protocol, ip, port, username, password in proxies:
            # Proxy URL yaratish
            if username and password:
                proxy_url = f"{protocol}://{username}:{password}@{ip}:{port}"
            else:
                proxy_url = f"{protocol}://{ip}:{port}"
            
            # Proxyni tekshirish
            working, response_time = self._check_proxy(proxy_url)
            
            # Natijalarni yangilash
            if working:
                cursor.execute(
                    "UPDATE proxies SET last_checked = ?, working = 1, success_count = success_count + 1, "
                    "response_time = ? WHERE id = ?",
                    (datetime.now(), response_time, proxy_id)
                )
                logger.debug(f"Proxy ishlaydi: {proxy_url}")
            else:
                cursor.execute(
                    "UPDATE proxies SET last_checked = ?, working = 0, fail_count = fail_count + 1 WHERE id = ?",
                    (datetime.now(), proxy_id)
                )
                logger.debug(f"Proxy ishlamaydi: {proxy_url}")
            
            conn.commit()
        
        # Ishlamaydigan proxylarni o'chirish (juda ko'p urinishdan keyin)
        cursor.execute(
            "DELETE FROM proxies WHERE working = 0 AND fail_count > 5"
        )
        
        conn.commit()
        conn.close()
    
    def _check_proxy(self, proxy_url: str) -> Tuple[bool, Optional[float]]:
        """
        Proxyni tekshirish
        
        :param proxy_url: Proxy URL
        :return: (ishlayaptimi, javob vaqti) juftligi
        """
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }
        
        test_urls = [
            "https://www.google.com",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # YouTube-ga maxsus so'rov
        ]
        
        for url in test_urls:
            try:
                start_time = time.time()
                response = requests.get(url, proxies=proxies, timeout=10)
                end_time = time.time()
                
                if response.status_code == 200:
                    return True, (end_time - start_time)
            
            except Exception as e:
                logger.debug(f"Proxy tekshirishda xatolik: {proxy_url}, URL: {url}, Xatolik: {str(e)}")
        
        return False, None
    
    def get_proxy(self) -> Optional[str]:
        """
        Ishlaydigan proxyni olish
        
        :return: Proxy URL yoki None
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Ishlaydigan proxylarni olish
        cursor.execute(
            "SELECT protocol, ip, port, username, password FROM proxies "
            "WHERE working = 1 ORDER BY response_time ASC LIMIT 50"
        )
        proxies = cursor.fetchall()
        conn.close()
        
        if not proxies:
            logger.warning("Hech qanday ishlayotgan proxylar topilmadi")
            return None
        
        # Tasodifiy proxy tanlash (tezroqlarni afzal ko'rish)
        proxy = random.choice(proxies[:10] if len(proxies) > 10 else proxies)
        protocol, ip, port, username, password = proxy
        
        # Proxy URL yaratish
        if username and password:
            return f"{protocol}://{username}:{password}@{ip}:{port}"
        else:
            return f"{protocol}://{ip}:{port}"
    
    def add_proxy_source(self, url: str, parser_type: str):
        """
        Yangi proxy manbasi qo'shish
        
        :param url: Manba URL
        :param parser_type: simple_list, json yoki custom_format
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "INSERT OR IGNORE INTO proxy_sources (url, parser_type, enabled) VALUES (?, ?, 1)",
            (url, parser_type)
        )
        
        conn.commit()
        conn.close()
    
    def disable_proxy_source(self, url: str):
        """
        Proxy manbasi o'chirish
        
        :param url: Manba URL
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE proxy_sources SET enabled = 0 WHERE url = ?",
            (url,)
        )
        
        conn.commit()
        conn.close()

# Singleton instance
_proxy_manager = None

def get_proxy_manager(db_path: str = "database/proxies.db") -> ProxyManager:
    """
    ProxyManager singleton olish
    
    :param db_path: Proxylar saqlanadigan ma'lumotlar bazasi
    :return: ProxyManager instance
    """
    global _proxy_manager
    
    if _proxy_manager is None:
        _proxy_manager = ProxyManager(db_path)
    
    return _proxy_manager

def get_proxy() -> Optional[str]:
    """
    Ishlaydigan proxyni olish
    
    :return: Proxy URL yoki None
    """
    manager = get_proxy_manager()
    return manager.get_proxy()