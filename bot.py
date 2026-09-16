"""
BIMZZ STORE AI BOT v2.1
Telegram Bot dengan AI (Groq) + Firebase REST API
+ BANNER DI /start
+ OWNER PANEL PAKE KEY (BIMZZ STORE)
+ SESSION MANAGEMENT
"""

import os
import json
import logging
import requests
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

# ============================================================
# KONFIGURASI
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ADMIN_TELEGRAM_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "8138527737"))
FIREBASE_DB_URL = os.environ.get("FIREBASE_DB_URL", "https://bimzz-store-default-rtdb.asia-southeast1.firebasedatabase.app")

WEB_STORE_URL = "https://bimzz-store-tipe-x-tr.vercel.app/"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

# BANNER URL - GANTI PAKE LINK CATBOX LO!
BANNER_URL = "https://files.catbox.moe/1wppiv.jpg"

# OWNER KEY
OWNER_KEY = "BIMZZ STORE"
MAX_KEY_ATTEMPTS = 3

# State order
(PILIH_PRODUK, PILIH_PAKET, INPUT_USERNAME, INPUT_PASSWORD, INPUT_WA, UPLOAD_BUKTI) = range(6)

# State owner
(OWNER_INPUT_KEY, OWNER_MENU) = range(100, 102)

user_order_state = {}
owner_attempts = {}  # {user_id: attempts}
owner_session = {}  # {user_id: True/False} - permanen sampe logout manual

# ============================================================
# SETUP LOGGING
# ============================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# FIREBASE REST API
# ============================================================
def firebase_get(path):
    try:
        url = f"{FIREBASE_DB_URL}/{path}.json"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"Firebase GET error: {e}")
        return None

def firebase_set(path, data):
    try:
        url = f"{FIREBASE_DB_URL}/{path}.json"
        response = requests.put(url, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Firebase SET error: {e}")
        return False

def firebase_delete(path):
    try:
        url = f"{FIREBASE_DB_URL}/{path}.json"
        response = requests.delete(url, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Firebase DELETE error: {e}")
        return False

def get_web_store_url():
    data = firebase_get("settings/links/web")
    if data and isinstance(data, str):
        return data
    return WEB_STORE_URL

def get_products():
    data = firebase_get('products')
    if not data:
        return []
    products = []
    for key, val in data.items():
        if isinstance(val, dict):
            val['_key'] = key
            products.append(val)
    return products

def get_product_by_key(key):
    return firebase_get(f'products/{key}')

def get_promo_codes():
    data = firebase_get('promo')
    if not data:
        return []
    promos = []
    for key, val in data.items():
        if isinstance(val, dict) and val.get('active'):
            promos.append(val)
    return promos

def get_order(order_id):
    return firebase_get(f'orders/{order_id}')

def update_order_status(order_id, status):
    return firebase_set(f'orders/{order_id}/status', status)

def get_user_by_username(username):
    data = firebase_get('users')
    if not data:
        return None
    for key, val in data.items():
        if isinstance(val, dict) and val.get('username') == username:
            val['_key'] = key
            return val
    return None

def get_stats():
    products = firebase_get('products') or {}
    users = firebase_get('users') or {}
    orders = firebase_get('orders') or {}
    reviews = firebase_get('ulasan') or {}
    return {
        'products': len(products) if isinstance(products, dict) else 0,
        'users': len(users) if isinstance(users, dict) else 0,
        'orders': len(orders) if isinstance(orders, dict) else 0,
        'reviews': len(reviews) if isinstance(reviews, dict) else 0
    }

def create_user(uid, username, password, email, role, expired_days):
    from datetime import datetime, timedelta
    expired = (datetime.now() + timedelta(days=expired_days)).strftime('%Y-%m-%d')
    data = {
        "username": username,
        "password": password,
        "email": email,
        "role": role,
        "expired": expired,
        "blocked": False,
        "deviceLimit": 1,
        "devices": {},
        "createdAt": int(datetime.now().timestamp() * 1000),
        "createdBy": "BOT_TELEGRAM",
        "lastLogin": None
    }
    return firebase_set(f'users/{uid}', data)

# ============================================================
# DUMMY HTTP SERVER
# ============================================================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'BIMZZ Store AI Bot v2.1 is running!')
    def log_message(self, format, *args):
        pass

def run_dummy_server():
    port = int(os.environ.get('PORT', 8080))
    try:
        server = HTTPServer(('0.0.0.0', port), DummyHandler)
        logger.info(f'✅ Dummy HTTP server running on port {port}')
        server.serve_forever()
    except Exception as e:
        logger.warning(f'Dummy server error: {e}')

threading.Thread(target=run_dummy_server, daemon=True).start()
