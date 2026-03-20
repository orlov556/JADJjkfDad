import os
import json
import logging
from flask import Flask, request, jsonify, send_file
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import config
from database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
db = Database(config.DATABASE_URL)

# ========== КОМАНДЫ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ref = context.args[0] if context.args else None
    
    user_data = db.add_user(user.id, user.first_name, f"@{user.username}" if user.username else f"user_{user.id}", ref)
    
    if user_data and user_data.get('status') == 'blocked':
        await update.message.reply_text(f"🚫 Доступ заблокирован\nПричина: {user_data.get('block_reason', 'Нарушение правил')}\nПо вопросам: @avito_vidnoe_support")
        return
    
    keyboard = [[InlineKeyboardButton("📱 Открыть Mini App", web_app={"url": f"{config.WEBAPP_URL}/app"})]]
    await update.message.reply_text(f"👋 Привет, {user.first_name}!\nДобро пожаловать в Авито Видное!", reply_markup=InlineKeyboardMarkup(keyboard))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Помощь\n\n📱 Как пользоваться:\n1. Нажми кнопку 'Открыть Mini App'\n2. Размещай объявления\n3. Общайся с продавцами\n\n📞 Поддержка: @avito_vidnoe_support")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = json.loads(query.data)
    if data.get('action') == 'view_reason':
        item = db.get_item(data.get('item_id'))
        if item and item.get('reject_reason'):
            await query.edit_message_text(f"❌ Причина отклонения\n\nТовар: {item['title']}\nПричина: {item['reject_reason']}")

# ========== WEBHOOK ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    action = data.get('action')
    user_id = data.get('user_id')
    
    if action == 'new_item':
        item_data = data.get('payload')
        item = [item_data.get('title'), item_data.get('price'), item_data.get('category'),
                item_data.get('description'), item_data.get('photo'), item_data.get('seller'),
                item_data.get('seller_avatar'), 'сейчас', user_id, 'pending', 'pending',
                1 if item_data.get('premium') else 0]
        db.add_item(item)
        if config.ADMIN_ID:
            send_telegram_message(config.ADMIN_ID, f"🆕 Новый товар на модерации\n📦 {item_data.get('title')}\n💰 {item_data.get('price')} ₽")
        return jsonify({"status": "ok"})
    
    elif action == 'moderate_item':
        item_id = data.get('payload').get('item_id')
        approved = data.get('payload').get('approved')
        reason = data.get('payload').get('reason', '')
        
        if approved:
            db.update_item(item_id, moderation='approved', status='active')
            item = db.get_item(item_id)
            if item:
                send_telegram_message(item['seller_id'], f"✅ Товар одобрен!\nВаш товар \"{item['title']}\" опубликован.")
        else:
            db.update_item(item_id, moderation='rejected', status='rejected', reject_reason=reason)
            item = db.get_item(item_id)
            if item:
                keyboard = [[InlineKeyboardButton("📋 Причина", callback_data=json.dumps({"action": "view_reason", "item_id": item_id}))]]
                send_telegram_message(item['seller_id'], f"❌ Товар отклонён\n\"{item['title']}\"\nПричина: {reason}", reply_markup=InlineKeyboardMarkup(keyboard))
        return jsonify({"status": "ok"})
    
    return jsonify({"status": "ok"})

@app.route('/app')
def serve_app():
    return send_file('web_app.html')

@app.route('/')
def index():
    return jsonify({"status": "ok", "message": "Bot is running"})

def send_telegram_message(chat_id, text, reply_markup=None):
    import requests
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup.to_dict() if hasattr(reply_markup, 'to_dict') else reply_markup)
    requests.post(url, json=data)

def set_webhook():
    import requests
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/setWebhook"
    requests.post(url, json={"url": f"{config.WEBAPP_URL}/webhook"})

if __name__ == '__main__':
    set_webhook()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
