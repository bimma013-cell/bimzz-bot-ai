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
# ============================================================
# SYSTEM PROMPT AI
# ============================================================
def get_system_prompt():
    web_url = get_web_store_url()
    return f"""Kamu adalah CS (Customer Service) dari BIMZZ STORE, toko jual APK BUG/RAT premium.

PERSONALITY:
- Ramah, sopan, tapi santai (pake bahasa gaul Indonesia)
- Suka pake emoji biar chat gak kaku
- Sabar jawab pertanyaan target
- Gak pernah bohong soal produk

CARA ORDER:
1. Via Telegram: Ketik /order → ikutin instruksi
2. Via Web: {web_url} → login → pilih produk → bayar QRIS

ATURAN:
- Kalo target mau order, arahin ke /order
- JANGAN kasih harga diskon tanpa persetujuan admin
- Kalo target minta bantuan lebih lanjut, arahin ke admin @BIMZZZZZZZZZZZZ
- Bales chat dengan SINGKAT (max 3-4 baris)
- Pake emoji secukupnya
"""

# ============================================================
# HISTORY CHAT
# ============================================================
user_histories = {}

def get_user_history(user_id):
    if user_id not in user_histories:
        user_histories[user_id] = []
    return user_histories[user_id]

def add_to_history(user_id, role, content):
    history = get_user_history(user_id)
    history.append({"role": role, "content": content})
    if len(history) > 20:
        user_histories[user_id] = history[-20:]

# ============================================================
# GROQ API
# ============================================================
def call_groq(user_id, user_message):
    if not GROQ_API_KEY:
        return "Maaf kak, AI lagi error 😔 Coba chat admin langsung ya."
    
    history = get_user_history(user_id)
    history.append({"role": "user", "content": user_message})
    
    products = get_products()
    products_text = ""
    if products:
        products_text = "\n\nPRODUK YANG TERSEDIA SAAT INI:\n"
        for p in products:
            name = p.get('name', '-')
            prices = p.get('prices', [])
            products_text += f"• {name}:\n"
            for pr in prices:
                if isinstance(pr, dict):
                    try:
                        cost = int(pr.get('cost', 0))
                        products_text += f"  - {pr.get('duration', '-')}: Rp {cost:,}\n"
                    except:
                        pass
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": get_system_prompt() + products_text},
            *history
        ],
        "temperature": 0.7,
        "max_tokens": 500
    }
    
    try:
        response = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        bot_reply = data['choices'][0]['message']['content']
        history.append({"role": "assistant", "content": bot_reply})
        user_histories[user_id] = history[-20:]
        return bot_reply
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        return "Maaf kak, AI lagi error 😔 Coba chat admin langsung ya: @BIMZZZZZZZZZZZZ"

# ============================================================
# MENU UTAMA DENGAN BANNER
# ============================================================
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🛒 ORDER SEKARANG", callback_data="menu_order")],
        [InlineKeyboardButton("📦 LIHAT PRODUK", callback_data="menu_produk"), InlineKeyboardButton("🎫 KODE PROMO", callback_data="menu_promo")],
        [InlineKeyboardButton("💬 CHAT ADMIN", url="https://wa.me/62895405292836"), InlineKeyboardButton("🌐 BUKA WEB", url=get_web_store_url())],
        [InlineKeyboardButton("❓ BANTUAN", callback_data="menu_help")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ============================================================
# HANDLER /start DENGAN BANNER
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_msg = f"""Halo {user.first_name}! 👋

Selamat datang di *BIMZZ STORE AI* 🤖
Toko APK BUG/RAT premium terpercaya!

Saya CS AI yang siap bantu lo:
🛒 Order via Telegram - GAMPANG!
📱 Info produk & harga
🎫 Kode promo
❓ FAQ

*Klik tombol di bawah buat mulai!* 👇"""
    
    try:
        # Kirim banner + welcome + tombol
        await update.message.reply_photo(
            photo=BANNER_URL,
            caption=welcome_msg,
            parse_mode='Markdown',
            reply_markup=get_main_menu()
        )
    except Exception as e:
        logger.warning(f"Gagal kirim banner, kirim text aja: {e}")
        await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=get_main_menu())

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_photo(
            photo=BANNER_URL,
            caption="📋 *MENU UTAMA BIMZZ STORE*",
            parse_mode='Markdown',
            reply_markup=get_main_menu()
        )
    except Exception:
        await update.message.reply_text("📋 *MENU UTAMA BIMZZ STORE*", parse_mode='Markdown', reply_markup=get_main_menu())

async def produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = get_products()
    if not products:
        await update.message.reply_text("Belum ada produk kak 😔 Coba cek lagi nanti ya!")
        return
    
    msg = "📦 *DAFTAR PRODUK BIMZZ STORE*\n\n"
    for p in products:
        msg += f"🔥 *{p.get('name', '-')}*\n"
        for pr in p.get('prices', []):
            if isinstance(pr, dict):
                try:
                    cost = int(pr.get('cost', 0))
                    msg += f"   • {pr.get('duration', '-')}: Rp {cost:,}\n"
                except:
                    pass
        msg += "\n"
    
    msg += "Mau order? Langsung aja:\n👉 Ketik /order"
    keyboard = [[InlineKeyboardButton("🛒 ORDER SEKARANG", callback_data="menu_order")]]
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    promos = get_promo_codes()
    if not promos:
        await update.message.reply_text("Belum ada kode promo aktif kak 😔 Pantengin terus ya!")
        return
    
    msg = "🎫 *KODE PROMO AKTIF*\n\n"
    for p in promos:
        code = p.get('code', '-')
        discount = p.get('discount', 0)
        dtype = p.get('type', 'percent')
        slots = p.get('slots', 0)
        used = len(p.get('usedBy', {}) or {})
        diskon_text = f"{discount}%" if dtype == 'percent' else f"Rp {discount:,}"
        msg += f"🎁 *{code}*\n   Diskon: {diskon_text}\n   Slot tersisa: {slots - used}/{slots}\n\n"
    
    msg += "Masukin kode pas order ya! 🚀"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 *Chat Admin Langsung:*\n\n"
        "📱 Telegram: @BIMZZZZZZZZZZZZ\n"
        "💬 WhatsApp: +62 895-4052-92836\n\n"
        "Kalo urgent, langsung chat aja ya kak! 🔥",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """❓ *BANTUAN*

*Commands:*
/start - Mulai chat
/order - Order via Telegram
/menu - Lihat menu
/produk - List produk
/promo - Kode promo
/admin - Chat admin
/help - Bantuan ini

*Pertanyaan umum:*
• "Harga APK X berapa?"
• "Cara order gimana?"
• "APK ini work gak?"

Langsung ketik aja, saya jawab otomatis! 🤖"""
    await update.message.reply_text(msg, parse_mode='Markdown')

# ============================================================
# ORDER VIA TELEGRAM
# ============================================================
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    products = get_products()
    if not products:
        await update.message.reply_text("Maaf kak, produk lagi kosong 😔")
        return ConversationHandler.END
    
    keyboard = []
    for p in products:
        keyboard.append([InlineKeyboardButton(f"💀 {p.get('name', '-')}", callback_data=f"order_prod_{p.get('_key')}")])
    keyboard.append([InlineKeyboardButton("❌ BATAL", callback_data="order_cancel")])
    
    await update.message.reply_text(
        "🛒 *ORDER VIA TELEGRAM*\n\nPilih produk yang mau lo beli:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PILIH_PRODUK

async def order_pilih_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "order_cancel":
        await query.edit_message_text("❌ Order dibatalkan.")
        return ConversationHandler.END
    
    if query.data.startswith("order_prod_"):
        product_key = query.data.replace("order_prod_", "")
        product = get_product_by_key(product_key)
        
        if not product:
            await query.edit_message_text("❌ Produk gak ketemu!")
            return ConversationHandler.END
        
        user_id = query.from_user.id
        user_order_state[user_id] = {"product": product, "product_key": product_key}
        
        keyboard = []
        for idx, pr in enumerate(product.get('prices', [])):
            keyboard.append([InlineKeyboardButton(
                f"📅 {pr.get('duration', '-')} - Rp {int(pr.get('cost', 0)):,}",
                callback_data=f"order_price_{idx}"
            )])
        keyboard.append([InlineKeyboardButton("❌ BATAL", callback_data="order_cancel")])
        
        await query.edit_message_text(
            f"💀 *{product.get('name', '-')}*\n\nPilih paket:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return PILIH_PAKET

async def order_pilih_paket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "order_cancel":
        await query.edit_message_text("❌ Order dibatalkan.")
        return ConversationHandler.END
    
    if query.data.startswith("order_price_"):
        idx = int(query.data.replace("order_price_", ""))
        user_id = query.from_user.id
        
        if user_id not in user_order_state:
            await query.edit_message_text("❌ Session expired. Ketik /order lagi.")
            return ConversationHandler.END
        
        product = user_order_state[user_id]["product"]
        price = product['prices'][idx]
        user_order_state[user_id]["price"] = price
        
        await query.edit_message_text(
            f"✅ *{product.get('name', '-')}*\n"
            f"📅 Paket: {price.get('duration', '-')}\n"
            f"💰 Harga: Rp {int(price.get('cost', 0)):,}\n\n"
            f"👤 *Masukkan USERNAME* lo (buat dashboard):",
            parse_mode='Markdown'
        )
        return INPUT_USERNAME

async def order_input_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.message.text.strip()
    
    if len(username) < 3:
        await update.message.reply_text("❌ Username minimal 3 huruf! Coba lagi:")
        return INPUT_USERNAME
    
    if user_id not in user_order_state:
        await update.message.reply_text("❌ Session expired. Ketik /order lagi.")
        return ConversationHandler.END
    
    existing = get_user_by_username(username)
    if existing:
        await update.message.reply_text(f"❌ Username *{username}* udah ada! Coba yang lain:", parse_mode='Markdown')
        return INPUT_USERNAME
    
    user_order_state[user_id]["username"] = username
    await update.message.reply_text(
        f"✅ Username: *{username}*\n\n🔑 *Masukkan PASSWORD* (min 6 karakter):",
        parse_mode='Markdown'
    )
    return INPUT_PASSWORD

async def order_input_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    password = update.message.text.strip()
    
    if len(password) < 6:
        await update.message.reply_text("❌ Password minimal 6 karakter! Coba lagi:")
        return INPUT_PASSWORD
    
    if user_id not in user_order_state:
        await update.message.reply_text("❌ Session expired. Ketik /order lagi.")
        return ConversationHandler.END
    
    user_order_state[user_id]["password"] = password
    await update.message.reply_text(
        "✅ Password OK!\n\n📱 *Masukkan NOMOR WHATSAPP* lo (format 62xxx):",
        parse_mode='Markdown'
    )
    return INPUT_WA

async def order_input_wa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wa = update.message.text.strip().replace("-", "").replace(" ", "")
    
    if not wa.startswith("62"):
        await update.message.reply_text("❌ Nomor WA harus diawali *62* (contoh: 6281234567890). Coba lagi:", parse_mode='Markdown')
        return INPUT_WA
    
    if user_id not in user_order_state:
        await update.message.reply_text("❌ Session expired. Ketik /order lagi.")
        return ConversationHandler.END
    
    user_order_state[user_id]["wa"] = wa
    
    qris_url = firebase_get("settings/qris_url") or "https://files.catbox.moe/1wppiv.jpg"
    
    await update.message.reply_photo(
        photo=qris_url,
        caption=f"💳 *PEMBAYARAN QRIS*\n\n"
                f"💀 Produk: {user_order_state[user_id]['product'].get('name')}\n"
                f"📅 Paket: {user_order_state[user_id]['price'].get('duration')}\n"
                f"💰 Harga: Rp {int(user_order_state[user_id]['price'].get('cost', 0)):,}\n\n"
                f"📸 *SCAN QRIS DI ATAS, BAYAR, LALU KIRIM FOTO BUKTI PEMBAYARAN DI CHAT INI!*",
        parse_mode='Markdown'
    )
    return UPLOAD_BUKTI

async def order_upload_bukti(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id not in user_order_state:
        await update.message.reply_text("❌ Session expired. Ketik /order lagi.")
        return ConversationHandler.END
    
    if not update.message.photo:
        await update.message.reply_text("❌ Kirim FOTO bukti pembayaran ya (bukan text):")
        return UPLOAD_BUKTI
    
    photo_file_id = update.message.photo[-1].file_id
    data = user_order_state[user_id]
    
    order_id = f"ORD{int(time.time() * 1000)}"
    user_uid = f"TG{user_id}"
    
    create_user(user_uid, data['username'], data['password'], f"{user_id}@telegram.user", "MEMBER", 30)
    
    order_data = {
        "orderId": order_id,
        "uid": user_uid,
        "username": data['username'],
        "password": data['password'],
        "produk": data['product'].get('name'),
        "produkId": data['product_key'],
        "paket": data['price'].get('duration'),
        "subtotal": data['price'].get('cost'),
        "diskon": 0,
        "total": data['price'].get('cost'),
        "kodePromo": None,
        "wa": data['wa'],
        "telegram": f"@{update.effective_user.username}" if update.effective_user.username else "-",
        "telegram_user_id": user_id,
        "status": "pending",
        "via": "telegram",
        "timestamp": int(time.time() * 1000)
    }
    
    firebase_set(f'orders/{order_id}', order_data)
    
    try:
        admin_keyboard = [
            [
                InlineKeyboardButton("✅ DANA MASUK", callback_data=f"paid_{order_id}"),
                InlineKeyboardButton("⏳ BELUM MASUK", callback_data=f"pending_{order_id}")
            ],
            [
                InlineKeyboardButton("📱 KIRIM APK VIA BOT", callback_data=f"sendapk_{order_id}"),
                InlineKeyboardButton("❌ HAPUS ORDER", callback_data=f"delorder_{order_id}")
            ]
        ]
        
        await context.bot.send_photo(
            chat_id=ADMIN_TELEGRAM_ID,
            photo=photo_file_id,
            caption=f"🔔 *PESANAN BARU (VIA TELEGRAM)*\n\n"
                    f"🆔 Order ID: `{order_id}`\n"
                    f"👤 Username: `{data['username']}`\n"
                    f"🔑 Password: `{data['password']}`\n"
                    f"💀 Produk: {data['product'].get('name')}\n"
                    f"📅 Paket: {data['price'].get('duration')}\n"
                    f"💰 Total: Rp {int(data['price'].get('cost', 0)):,}\n"
                    f"📱 WA: `{data['wa']}`\n"
                    f"💬 Telegram: @{update.effective_user.username or '-'}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"PILIH AKSI:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(admin_keyboard)
        )
    except Exception as e:
        logger.error(f"Gagal kirim ke admin: {e}")
    
    await update.message.reply_text(
        f"✅ *PESANAN DITERIMA!*\n\n"
        f"🆔 Order ID: `{order_id}`\n\n"
        f"⏳ Tunggu admin verifikasi pembayaran lo ya.\n"
        f"📱 Kalo dana udah masuk, APK bakal otomatis dikirim ke chat ini!\n\n"
        f"*Terima kasih udah order di BIMZZ STORE!* 🔥",
        parse_mode='Markdown'
    )
    
    del user_order_state[user_id]
    return ConversationHandler.END

async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_order_state:
        del user_order_state[user_id]
    await update.message.reply_text("❌ Order dibatalkan.")
    return ConversationHandler.END
    # ============================================================
# OWNER PANEL - PAKE KEY (BIMZZ STORE)
# ============================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point Owner Panel - Minta Key"""
    user_id = update.effective_user.id
    
    # Kalo bukan Owner asli → tolak
    if user_id != ADMIN_TELEGRAM_ID:
        await update.message.reply_text(
            "❌ *AKSES DITOLAK!*\n\n"
            "Command ini cuma buat Owner BIMZZ STORE.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    # Kalo Owner udah punya session aktif → langsung masuk
    if owner_session.get(user_id, False):
        await show_owner_menu(update, context)
        return ConversationHandler.END
    
    # Minta KEY
    await update.message.reply_text(
        "🔐 *MASUKIN KEY OWNER:*\n\n"
        "Ketik key akses buat masuk ke Owner Panel.\n\n"
        f"⚠️ Maksimal salah: {MAX_KEY_ATTEMPTS}x",
        parse_mode='Markdown'
    )
    return OWNER_INPUT_KEY

async def owner_input_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verifikasi Key Owner"""
    user_id = update.effective_user.id
    input_key = update.message.text.strip()
    
    # Cek attempt
    attempts = owner_attempts.get(user_id, 0)
    
    if attempts >= MAX_KEY_ATTEMPTS:
        await update.message.reply_text(
            "❌ *AKSES DIBLOKIR!*\n\n"
            "Lo udah salah 3x. Coba lagi nanti atau restart bot.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    # Verifikasi Key (case sensitive)
    if input_key == OWNER_KEY:
        # KEY BENER!
        owner_attempts[user_id] = 0
        owner_session[user_id] = True  # SESSION PERMANEN sampe logout manual
        
        await update.message.reply_text(
            "✅ *KEY VALID!*\n\n"
            "Selamat datang di Owner Panel, Tuan! 👑",
            parse_mode='Markdown'
        )
        await show_owner_menu(update, context)
        return OWNER_MENU
    else:
        # KEY SALAH
        attempts += 1
        owner_attempts[user_id] = attempts
        sisa = MAX_KEY_ATTEMPTS - attempts
        
        if sisa <= 0:
            await update.message.reply_text(
                "❌ *KEY SALAH!*\n\n"
                "Lo udah salah 3x. Akses diblock!",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        else:
            await update.message.reply_text(
                f"❌ *KEY SALAH!*\n\n"
                f"Sisa percobaan: *{sisa}x*",
                parse_mode='Markdown'
            )
            return OWNER_INPUT_KEY

async def show_owner_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan Owner Panel Menu"""
    stats = get_stats()
    
    keyboard = [
        [InlineKeyboardButton("📦 KELOLA PRODUK", callback_data="adm_produk")],
        [InlineKeyboardButton("👥 KELOLA USER", callback_data="adm_user")],
        [InlineKeyboardButton("📊 STATISTIK", callback_data="adm_stats")],
        [InlineKeyboardButton("🔧 MAINTENANCE", callback_data="adm_maintenance")],
        [InlineKeyboardButton("🚫 WEB OFF", callback_data="adm_weboff")],
        [InlineKeyboardButton("🎫 KELOLA PROMO", callback_data="adm_promo")],
        [InlineKeyboardButton("📸 GANTI QRIS", callback_data="adm_qris")],
        [InlineKeyboardButton("🚪 LOGOUT OWNER PANEL", callback_data="adm_logout")]
    ]
    
    text = (
        f"👑 *OWNER PANEL - BIMZZ STORE*\n\n"
        f"📦 Total Produk: {stats['products']}\n"
        f"👥 Total User: {stats['users']}\n"
        f"🛒 Total Order: {stats['orders']}\n"
        f"⭐ Total Ulasan: {stats['reviews']}\n\n"
        f"🔓 *Status: LOGGED IN*\n\n"
        f"PILIH MENU:"
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def admin_logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Logout dari Owner Panel"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    owner_session[user_id] = False
    owner_attempts[user_id] = 0
    
    await query.edit_message_text(
        "✅ *LOGOUT BERHASIL!*\n\n"
        "Lo udah keluar dari Owner Panel.\n"
        "Ketik /admin_panel lagi buat masuk.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END

# ============================================================
# OWNER PANEL - SUB MENU
# ============================================================
async def admin_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    products = get_products()
    keyboard = []
    
    for p in products:
        keyboard.append([InlineKeyboardButton(
            f"💀 {p.get('name', '-')}",
            callback_data=f"adm_viewprod_{p.get('_key')}"
        )])
    
    keyboard.append([InlineKeyboardButton("➕ TAMBAH PRODUK", callback_data="adm_addprod")])
    keyboard.append([InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_back")])
    
    await query.edit_message_text(
        f"📦 *KELOLA PRODUK*\n\nTotal: {len(products)} produk",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_view_produk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    product_key = query.data.replace("adm_viewprod_", "")
    product = get_product_by_key(product_key)
    
    if not product:
        await query.edit_message_text("❌ Produk gak ketemu!")
        return
    
    prices_text = ""
    for pr in product.get('prices', []):
        prices_text += f"   • {pr.get('duration')}: Rp {int(pr.get('cost', 0)):,}\n"
    
    keyboard = [
        [InlineKeyboardButton("📥 GANTI LINK APK", callback_data=f"adm_editapk_{product_key}")],
        [InlineKeyboardButton("🗑️ HAPUS PRODUK", callback_data=f"adm_delprod_{product_key}")],
        [InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_produk")]
    ]
    
    await query.edit_message_text(
        f"💀 *{product.get('name', '-')}*\n\n"
        f"📝 Fitur:\n{product.get('features', '-')}\n\n"
        f"💰 Harga:\n{prices_text}\n"
        f"📥 APK: {product.get('apkLink', '-')}\n",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    users = firebase_get('users') or {}
    
    await query.edit_message_text(
        f"👥 *KELOLA USER*\n\n"
        f"Total: {len(users)} user\n\n"
        f"Buka web buat kelola user lengkap:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 BUKA WEB", url=get_web_store_url())],
            [InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_back")]
        ])
    )

async def admin_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    current = firebase_get("settings/maintenance") or False
    
    keyboard = [
        [InlineKeyboardButton(
            "🔴 MATIKAN" if current else "🟢 AKTIFKAN",
            callback_data="adm_toggle_maint"
        )],
        [InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_back")]
    ]
    
    await query.edit_message_text(
        f"🔧 *MODE MAINTENANCE*\n\n"
        f"Status: *{'🟢 ON' if current else '🔴 OFF'}*\n\n"
        f"Kalo ON, web bakal nampilin halaman Maintenance.\n"
        f"Owner tetep bisa akses.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_weboff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    current = firebase_get("settings/weboff") or False
    
    keyboard = [
        [InlineKeyboardButton(
            "🔴 MATIKAN" if current else "🟢 AKTIFKAN",
            callback_data="adm_toggle_weboff"
        )],
        [InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_back")]
    ]
    
    await query.edit_message_text(
        f"🚫 *MODE WEB OFF*\n\n"
        f"Status: *{'🟢 ON' if current else '🔴 OFF'}*\n\n"
        f"Kalo ON, web bakal nampilin 'Website Sedang Offline'.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    stats = get_stats()
    
    await query.edit_message_text(
        f"📊 *STATISTIK BIMZZ STORE*\n\n"
        f"📦 Total Produk: {stats['products']}\n"
        f"👥 Total User: {stats['users']}\n"
        f"🛒 Total Order: {stats['orders']}\n"
        f"⭐ Total Ulasan: {stats['reviews']}\n",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 REFRESH", callback_data="adm_stats")],
            [InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_back")]
        ])
    )

async def admin_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    promos = firebase_get('promo') or {}
    
    msg = "🎫 *KELOLA PROMO*\n\n"
    if promos:
        for code, p in promos.items():
            status = "✅" if p.get('active') else "❌"
            msg += f"{status} *{code}* - {p.get('discount')}{'%' if p.get('type') == 'percent' else ' Rp'}\n"
    else:
        msg += "Belum ada kode promo.\n"
    
    await query.edit_message_text(
        msg,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 BUKA WEB", url=get_web_store_url())],
            [InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_back")]
        ])
    )

async def admin_qris(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📸 *GANTI QRIS*\n\n"
        "Kirim FOTO QRIS baru di chat ini.\n"
        "Bot bakal otomatis simpen & pake buat pembayaran.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_back")]
        ])
    )

async def admin_save_qris(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_TELEGRAM_ID:
        return
    
    if not update.message.photo:
        return
    
    photo_file_id = update.message.photo[-1].file_id
    
    try:
        firebase_set("settings/qris_file_id", photo_file_id)
        await update.message.reply_text(
            "✅ *QRIS BARU DISIMPAN!*\n\n"
            "Bot bakal pake QRIS ini buat pembayaran otomatis.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Gagal save QRIS: {e}")
        await update.message.reply_text("❌ Gagal simpen QRIS!")

async def admin_toggle_maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    current = firebase_get("settings/maintenance") or False
    new_val = not current
    firebase_set("settings/maintenance", new_val)
    
    await query.edit_message_text(
        f"✅ *MAINTENANCE: {'🟢 ON' if new_val else '🔴 OFF'}*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_maintenance")]
        ])
    )

async def admin_toggle_weboff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    current = firebase_get("settings/weboff") or False
    new_val = not current
    firebase_set("settings/weboff", new_val)
    
    await query.edit_message_text(
        f"✅ *WEB OFF: {'🟢 ON' if new_val else '🔴 OFF'}*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ KEMBALI", callback_data="adm_weboff")]
        ])
    )

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_owner_menu(update, context)

async def admin_delprod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    product_key = query.data.replace("adm_delprod_", "")
    firebase_delete(f'products/{product_key}')
    await query.answer("✅ Produk dihapus!")
    await admin_produk(update, context)

# ============================================================
# HANDLE CALLBACK - SEMUA TOMBOL
# ============================================================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # ADMIN CALLBACKS
    if query.data == "adm_produk":
        await admin_produk(update, context); return
    if query.data == "adm_user":
        await admin_user(update, context); return
    if query.data == "adm_stats":
        await admin_stats(update, context); return
    if query.data == "adm_maintenance":
        await admin_maintenance(update, context); return
    if query.data == "adm_weboff":
        await admin_weboff(update, context); return
    if query.data == "adm_promo":
        await admin_promo(update, context); return
    if query.data == "adm_qris":
        await admin_qris(update, context); return
    if query.data == "adm_toggle_maint":
        await admin_toggle_maintenance(update, context); return
    if query.data == "adm_toggle_weboff":
        await admin_toggle_weboff(update, context); return
    if query.data == "adm_back":
        await admin_back(update, context); return
    if query.data == "adm_logout":
        await admin_logout(update, context); return
    if query.data.startswith("adm_viewprod_"):
        await admin_view_produk(update, context); return
    if query.data.startswith("adm_delprod_"):
        await admin_delprod(update, context); return
    
    # MENU CALLBACKS
    if query.data == "menu_order":
        await query.answer()
        await order_start(update, context); return
    if query.data == "menu_produk":
        await query.answer()
        await produk(update, context); return
    if query.data == "menu_promo":
        await query.answer()
        await promo(update, context); return
    if query.data == "menu_help":
        await query.answer()
        await help_command(update, context); return
    
    # ORDER CANCEL
    if query.data == "order_cancel":
        await query.answer()
        await query.edit_message_text("❌ Order dibatalkan.")
        return
    
    # ORDER NOTIF CALLBACKS
    await query.answer()
    data = query.data
    if '_' not in data:
        return
    
    action, order_id = data.split('_', 1)
    logger.info(f"Callback: action={action}, order={order_id}")
    
    # TOMBOL 1: DANA MASUK
    if action == 'paid':
        try:
            update_order_status(order_id, "paid")
            order_data = get_order(order_id)
            
            if order_data:
                target_chat_id = order_data.get('telegram_user_id')
                product_key = order_data.get('produkId')
                product = get_product_by_key(product_key)
                apk_link = product.get('apkLink') if product else None
                
                if target_chat_id and apk_link:
                    try:
                        await context.bot.send_document(
                            chat_id=target_chat_id,
                            document=apk_link,
                            caption=f"✅ *PEMBAYARAN DIKONFIRMASI!*\n\n"
                                    f"💀 Produk: {order_data.get('produk')}\n"
                                    f"📅 Paket: {order_data.get('paket')}\n"
                                    f"👤 Username: `{order_data.get('username')}`\n"
                                    f"🔑 Password: `{order_data.get('password')}`\n\n"
                                    f"⬇️ *DOWNLOAD APK DI ATAS*",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.warning(f"Gagal kirim file: {e}")
                        await context.bot.send_message(
                            chat_id=target_chat_id,
                            text=f"✅ *PEMBAYARAN DIKONFIRMASI!*\n\n"
                                 f"💀 Produk: {order_data.get('produk')}\n"
                                 f"👤 Username: `{order_data.get('username')}`\n"
                                 f"🔑 Password: `{order_data.get('password')}`\n\n"
                                 f"⬇️ *DOWNLOAD APK:*\n{apk_link}",
                            parse_mode='Markdown'
                        )
                
                await context.bot.send_message(
                    chat_id=ADMIN_TELEGRAM_ID,
                    text=f"✅ *ORDER DIKONFIRMASI*\n\n"
                         f"🆔 Order: `{order_id}`\n"
                         f"👤 User: `{order_data.get('username')}`\n"
                         f"📱 APK udah dikirim ke target!",
                    parse_mode='Markdown'
                )
            
            await query.edit_message_text(
                text=query.message.text + "\n\n━━━━━━━━━━━━━━━━━━━━\n✅ *STATUS: DANA MASUK*\n📱 APK OTOMATIS DIKIRIM KE TARGET!",
                parse_mode='Markdown',
                reply_markup=query.message.reply_markup
            )
        except Exception as e:
            logger.error(f"Error paid: {e}")
    
    # TOMBOL 2: BELUM MASUK
    elif action == 'pending':
        try:
            update_order_status(order_id, "pending")
            await query.edit_message_text(
                text=query.message.text + "\n\n━━━━━━━━━━━━━━━━━━━━\n⏳ *STATUS: BELUM MASUK*",
                parse_mode='Markdown',
                reply_markup=query.message.reply_markup
            )
        except Exception as e:
            logger.error(f"Error pending: {e}")
    
    # TOMBOL 3: KIRIM APK VIA BOT
    elif action == 'sendapk':
        try:
            order_data = get_order(order_id)
            if not order_data:
                await query.answer("Order gak ketemu!")
                return
            
            target_chat_id = order_data.get('telegram_user_id')
            product_key = order_data.get('produkId')
            product = get_product_by_key(product_key)
            apk_link = product.get('apkLink') if product else None
            
            if target_chat_id and apk_link:
                try:
                    await context.bot.send_document(
                        chat_id=target_chat_id,
                        document=apk_link,
                        caption=f"✅ *PESANAN LO UDAH SIAP!*\n\n"
                                f"💀 Produk: {order_data.get('produk')}\n"
                                f"👤 Username: `{order_data.get('username')}`\n"
                                f"🔑 Password: `{order_data.get('password')}`",
                        parse_mode='Markdown'
                    )
                    await query.answer("✅ APK terkirim ke target!")
                except Exception:
                    await context.bot.send_message(
                        chat_id=target_chat_id,
                        text=f"✅ *PESANAN LO UDAH SIAP!*\n\n⬇️ Download APK:\n{apk_link}",
                        parse_mode='Markdown'
                    )
                    await query.answer("✅ Link APK terkirim!")
            else:
                await query.answer("❌ Target gak punya Telegram / APK gak ada!")
        except Exception as e:
            logger.error(f"Error sendapk: {e}")
    
    # TOMBOL 4: HAPUS ORDER
    elif action == 'delorder':
        try:
            firebase_delete(f'orders/{order_id}')
            await query.edit_message_text("🗑️ Order dihapus!")
        except Exception as e:
            logger.error(f"Error delorder: {e}")

# ============================================================
# HANDLE PESAN BIASA (AI CHAT)
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text
    
    # Admin upload QRIS?
    if user_id == ADMIN_TELEGRAM_ID and update.message.photo:
        await admin_save_qris(update, context)
        return
    
    if not user_message:
        return
    
    logger.info(f"User {user_id} ({user.first_name}): {user_message}")
    await update.message.chat.send_action(action="typing")
    
    bot_reply = call_groq(user_id, user_message)
    
    if "forward ke admin" in bot_reply.lower() or "gak tau" in bot_reply.lower():
        try:
            admin_msg = f"🚨 *PESAN DARI TARGET*\n\n"
            admin_msg += f"👤 Nama: {user.first_name}\n"
            admin_msg += f"🆔 User ID: `{user_id}`\n"
            admin_msg += f"💬 Pesan: {user_message}\n\n"
            admin_msg += f"🤖 Bot jawab: {bot_reply}"
            await context.bot.send_message(chat_id=ADMIN_TELEGRAM_ID, text=admin_msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Gagal forward: {e}")
    
    try:
        await update.message.reply_text(bot_reply, parse_mode='Markdown')
    except Exception:
        await update.message.reply_text(bot_reply)

# ============================================================
# MAIN
# ============================================================
def main():
    logger.info("🤖 Starting BIMZZ Store AI Bot v2.1...")
    logger.info(f"Firebase URL: {FIREBASE_DB_URL}")
    
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN gak ada!")
        return
    
    if not GROQ_API_KEY:
        logger.warning("⚠️ GROQ_API_KEY gak ada!")
    
    test = firebase_get('products')
    if test is not None:
        logger.info(f"✅ Firebase connected! Products: {len(test) if test else 0}")
    else:
        logger.warning("⚠️ Firebase REST API gak keakses!")
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Conversation Handler - ORDER
    order_conv = ConversationHandler(
        entry_points=[
            CommandHandler("order", order_start),
            CallbackQueryHandler(order_start, pattern="^menu_order$")
        ],
        states={
            PILIH_PRODUK: [CallbackQueryHandler(order_pilih_produk, pattern="^order_(prod_|cancel)")],
            PILIH_PAKET: [CallbackQueryHandler(order_pilih_paket, pattern="^order_(price_|cancel)")],
            INPUT_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_input_username)],
            INPUT_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_input_password)],
            INPUT_WA: [MessageHandler(filters.TEXT & ~filters.COMMAND, order_input_wa)],
            UPLOAD_BUKTI: [MessageHandler(filters.PHOTO, order_upload_bukti)],
        },
        fallbacks=[CommandHandler("cancel", order_cancel)],
        per_user=True,
        per_chat=True,
    )
    app.add_handler(order_conv)
    
    # Conversation Handler - OWNER PANEL
    owner_conv = ConversationHandler(
        entry_points=[CommandHandler("admin_panel", admin_panel)],
        states={
            OWNER_INPUT_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, owner_input_key)],
            OWNER_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)],
        },
        fallbacks=[CommandHandler("cancel", admin_logout)],
        per_user=True,
        per_chat=True,
    )
    app.add_handler(owner_conv)
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("produk", produk))
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("help", help_command))
    
    # Callback handler
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Message handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Photo handler
    app.add_handler(MessageHandler(filters.PHOTO, admin_save_qris))
    
    logger.info("✅ Bot v2.1 aktif!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
