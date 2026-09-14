"""
BIMZZ STORE AI BOT
Telegram Bot dengan AI (Groq) + Firebase REST API
Gak butuh service account!
"""

import os
import json
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ============================================================
# KONFIGURASI
# ============================================================
TELEGRAM_TOKEN = "8746718198:AAGsieaMiKkarPirHR8Aztg2aqxNV7F4YVo"
GROQ_API_KEY = "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"
ADMIN_TELEGRAM_ID = "8138527737"
FIREBASE_DB_URL = "https://bimzz-store-default-rtdb.asia-southeast1.firebasedatabase.app"

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"

# ============================================================
# SETUP LOGGING
# ============================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# SYSTEM PROMPT AI
# ============================================================
SYSTEM_PROMPT = """Kamu adalah CS (Customer Service) dari BIMZZ STORE, toko jual APK BUG/RAT premium.

PERSONALITY:
- Ramah, sopan, tapi santai (pake bahasa gaul Indonesia)
- Suka pake emoji biar chat gak kaku
- Sabar jawab pertanyaan target
- Gak pernah bohong soal produk

CARA ORDER:
1. Buka web: tangerine-tapioca-834916.netlify.app
2. Pilih produk & paket
3. Bayar pake QRIS
4. Upload bukti + nomor WA
5. Tunggu admin konfirmasi 1-24 jam

ATURAN:
- JANGAN kasih harga diskon tanpa persetujuan admin
- Kalo target minta bantuan lebih lanjut, arahin ke admin @BIMZZZZZZZZZZZZ
- Bales chat dengan SINGKAT (max 3-4 baris)
- Pake emoji secukupnya
- Kalo gak tau jawabannya, bilang "Sabar ya kak, saya forward ke admin dulu"
"""

# ============================================================
# HISTORY CHAT PER USER
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
# FIREBASE REST API
# ============================================================
def firebase_get(path):
    """Ambil data dari Firebase via REST API"""
    try:
        url = f"{FIREBASE_DB_URL}/{path}.json"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        logger.warning(f"Firebase GET {path}: status {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Firebase GET error: {e}")
        return None

def get_products():
    """Ambil list produk dari Firebase"""
    data = firebase_get('products')
    if not data:
        return []
    products = []
    for key, val in data.items():
        if isinstance(val, dict):
            products.append(val)
    return products

def get_promo_codes():
    """Ambil kode promo aktif"""
    data = firebase_get('promo')
    if not data:
        return []
    promos = []
    for key, val in data.items():
        if isinstance(val, dict) and val.get('active'):
            promos.append(val)
    return promos

# ============================================================
# GROQ API
# ============================================================
def call_groq(user_id, user_message):
    """Panggil Groq API dengan history chat"""
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
            {"role": "system", "content": SYSTEM_PROMPT + products_text},
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
# HANDLERS - COMMANDS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_msg = f"""Halo {user.first_name}! 👋

Selamat datang di *BIMZZ STORE AI* 🤖
Toko APK BUG/RAT premium terpercaya!

Saya CS AI yang siap bantu lo:
📱 Info produk & harga
💳 Cara order
🎫 Kode promo
❓ FAQ

Langsung chat aja, saya jawab otomatis! 😊

*Kalo urgent / butuh admin langsung:*
👤 @BIMZZZZZZZZZZZZ"""
    
    keyboard = [
        [InlineKeyboardButton("🛒 Lihat Produk", url="https://tangerine-tapioca-834916.netlify.app")],
        [InlineKeyboardButton("💬 Chat Admin", url="https://t.me/BIMZZZZZZZZZZZZ")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_msg, parse_mode='Markdown', reply_markup=reply_markup)

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """📋 *MENU BIMZZ STORE AI*

🛒 */produk* - Lihat produk
🎫 */promo* - Kode promo aktif
💬 */admin* - Chat admin
❓ */help* - Bantuan

Atau langsung chat aja, saya jawab otomatis! 🤖"""
    await update.message.reply_text(msg, parse_mode='Markdown')

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
    
    msg += "Mau order? Langsung aja:\n👉 https://tangerine-tapioca-834916.netlify.app"
    
    keyboard = [[InlineKeyboardButton("🛒 Order Sekarang", url="https://tangerine-tapioca-834916.netlify.app")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=reply_markup)

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
        
        msg += f"🎁 *{code}*\n"
        msg += f"   Diskon: {diskon_text}\n"
        msg += f"   Slot tersisa: {slots - used}/{slots}\n\n"
    
    msg += "Masukin kode pas checkout ya! 🚀"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👤 *Chat Admin Langsung:*\n\n"
        "📱 Telegram: @BIMZZZZZZZZZZZZ\n"
        "💬 WhatsApp: +62 8xx-xxxx-xxxx\n\n"
        "Kalo urgent, langsung chat aja ya kak! 🔥",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """❓ *BANTUAN*

*Commands:*
/start - Mulai chat
/menu - Lihat menu
/produk - List produk
/promo - Kode promo
/admin - Chat admin
/help - Bantuan ini

*Pertanyaan umum:*
• "Harga APK X berapa?"
• "Cara order gimana?"
• "APK ini work gak?"
• "Bisa nego gak?"

Langsung ketik aja, saya jawab otomatis! 🤖"""
    await update.message.reply_text(msg, parse_mode='Markdown')

# ============================================================
# HANDLER PESAN BIASA
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_message = update.message.text
    
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
    logger.info("🤖 Starting BIMZZ Store AI Bot...")
    logger.info(f"Firebase URL: {FIREBASE_DB_URL}")
    
    # Test koneksi Firebase
    test = firebase_get('products')
    if test is not None:
        logger.info(f"✅ Firebase connected! Products: {len(test) if test else 0}")
    else:
        logger.warning("⚠️ Firebase REST API gak keakses! Cek Firebase Rules.")
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("produk", produk))
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ Bot aktif! Chat di @BIMZZ_Store_AI_bot")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()