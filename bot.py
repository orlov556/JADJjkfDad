import os
import json
import logging
from flask import Flask, request, jsonify, send_file
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, PreCheckoutQueryHandler, MessageHandler, filters, ContextTypes
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
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\nДобро пожаловать в Авито Видное!\n\n✅ Размещай товары\n✅ Находи покупателей\n✅ Зарабатывай Stars\n\nНажми на кнопку ниже 👇",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)
    logger.info(f"Pre-checkout approved for user {update.effective_user.id}")

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    payload = update.message.successful_payment.invoice_payload
    amount = int(payload.split('_')[1])
    
    user_data = db.get_user(user.id)
    db.update_user(user.id, stars=user_data['stars'] + amount)
    db.add_transaction(user.id, amount, f"Покупка {amount} Stars", "earn")
    
    await update.message.reply_text(f"✅ Оплата прошла успешно!\n\nВам начислено {amount} ⭐")
    logger.info(f"User {user.id} bought {amount} stars")

# ========== WEBHOOK ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        action = data.get('action')
        user_id = data.get('user_id')
        payload = data.get('payload', {})
        
        logger.info(f"Webhook: {action} from {user_id}")
        
        if action == 'buy_stars':
            amount = payload.get('amount', 100)
            return jsonify({
                "status": "ok",
                "invoice": {
                    "title": f"Покупка {amount} Stars",
                    "description": f"{amount} ⭐ для продвижения",
                    "payload": f"stars_{amount}",
                    "currency": "XTR",
                    "prices": [{"label": f"{amount} Stars", "amount": amount * 100}]
                }
            })
        
        elif action == 'new_item':
            item_data = payload
            item = [
                item_data.get('title'), item_data.get('price'), item_data.get('category'),
                item_data.get('description'), item_data.get('photo'), item_data.get('seller'),
                item_data.get('seller_avatar'), 'сейчас', int(user_id), 'pending', 'pending',
                1 if item_data.get('premium') else 0
            ]
            db.add_item(item)
            
            if config.ADMIN_ID:
                send_telegram_message(
                    config.ADMIN_ID,
                    f"🆕 Новый товар\n📦 {item_data.get('title')}\n💰 {item_data.get('price')} ₽"
                )
            return jsonify({"status": "ok"})
        
        elif action == 'moderate_item':
            item_id = payload.get('item_id')
            approved = payload.get('approved')
            reason = payload.get('reason', '')
            
            if approved:
                db.update_item(item_id, moderation='approved', status='active')
                item = db.get_item(item_id)
                if item:
                    send_telegram_message(
                        item['seller_id'],
                        f"✅ Товар одобрен!\n{item['title']} опубликован."
                    )
            else:
                db.update_item(item_id, moderation='rejected', status='rejected', reject_reason=reason)
                item = db.get_item(item_id)
                if item:
                    if item.get('premium'):
                        seller = db.get_user(item['seller_id'])
                        if seller:
                            db.update_user(item['seller_id'], stars=seller['stars'] + 15)
                    send_telegram_message(
                        item['seller_id'],
                        f"❌ Товар отклонён\n{item['title']}\nПричина: {reason}"
                    )
            return jsonify({"status": "ok"})
        
        elif action == 'block_user':
            target_id = payload.get('user_id')
            reason = payload.get('reason', 'Нарушение правил')
            db.update_user(int(target_id), status='blocked', block_reason=reason)
            send_telegram_message(
                int(target_id),
                f"🚫 Вы заблокированы\nПричина: {reason}"
            )
            return jsonify({"status": "ok"})
        
        elif action == 'unblock_user':
            target_id = payload.get('user_id')
            db.update_user(int(target_id), status='active', block_reason=None)
            return jsonify({"status": "ok"})
        
        return jsonify({"status": "ok"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/app')
def serve_app():
    return send_file('web_app.html')

@app.route('/')
def index():
    return jsonify({"status": "ok", "message": "Bot is running"})

def send_telegram_message(chat_id, text):
    import requests
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text})

def set_webhook():
    import requests
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/setWebhook"
    webhook_url = f"{config.WEBAPP_URL}/webhook"
    response = requests.post(url, json={"url": webhook_url})
    logger.info(f"Webhook set: {response.json()}")

if __name__ == '__main__':
    set_webhook()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
