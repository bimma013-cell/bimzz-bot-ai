"""
BIMZZ STORE AI BOT v2.0
Telegram Bot dengan AI (Groq) + Firebase REST API
+ ORDER VIA TELEGRAM
+ OWNER PANEL VIA BOT
+ AUTO-KIRIM APK
"""

import os
import json
import logging
import requests
import threading
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

# State untuk order flow
(PILIH_PRODUK, PILIH_PAKET, INPUT_USERNAME, INPUT_PASSWORD, INPUT_WA, UPLOAD_BUKTI) = range(6)
# State untuk admin panel
(ADMIN_MENU, ADMIN_ADD_PRODUCT_NAME, ADMIN_ADD_PRODUCT_PRICE, ADMIN_ADD_PRODUCT_APK, ADMIN_EDIT_PRODUCT, ADMIN_DELETE_PRODUCT) = range(100, 106)

user_order_state = {}
user_admin_state = {}

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

def firebase_push(path, data):
    try:
        url = f"{FIREBASE_DB_URL}/{path}.json"
        response = requests.post(url, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Firebase PUSH error: {e}")
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

def get_user_by_uid(uid):
    return firebase_get(f'users/{uid}')

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
        self.wfile.write(b'BIMZZ Store AI Bot v2.0 is running!')
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
# KEYBOARD MENU UTAMA
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
# HANDLERS - COMMANDS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    web_url = get_web_store_url()
    welcome_msg = f"""Halo {user.first_name}! 👋

Selamat datang di *BIMZZ STORE AI* 🤖
Toko APK BUG/RAT premium terpercaya!

Saya CS AI yang siap bantu lo:
🛒 Order via Telegram - GAMPANG!
📱 Info produk & harga
🎫 Kode promo
❓ FAQ

*Klik tombol di bawah buat mulai!* 👇"""
    
    await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=get_main_menu())

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    # Cek username udah ada belum
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
    
    # Kirim QRIS
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
    
    # Ambil foto terbesar
    photo_file_id = update.message.photo[-1].file_id
    data = user_order_state[user_id]
    
    # Generate order ID
    import time
    order_id = f"ORD{int(time.time() * 1000)}"
    
    # Generate UID dummy
    user_uid = f"TG{user_id}"
    
    # Bikin akun user
    create_user(user_uid, data['username'], data['password'], f"{user_id}@telegram.user", "MEMBER", 30)
    
    # Simpen order ke Firebase
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
    
    # Kirim notif ke admin
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
    
    # Clear state
    del user_order_state[user_id]
    return ConversationHandler.END

async def order_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_order_state:
        del user_order_state[user_id]
    await update.message.reply_text("❌ Order dibatalkan.")
    return ConversationHandler.END
