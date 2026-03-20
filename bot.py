import os
import json
import logging
from flask import Flask, request, jsonify, send_file
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, PreCheckoutQueryHandler, MessageHandler, filters, ContextTypes
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
    
    # Регистрируем пользователя
    user_data = db.add_user(user.id, user.first_name, f"@{user.username}" if user.username else f"user_{user.id}", ref)
    
    # Проверка блокировки
    if user_data and user_data.get('status') == 'blocked':
        await update.message.reply_text(
            f"🚫 Доступ заблокирован\n\nПричина: {user_data.get('block_reason', 'Нарушение правил')}\n\nПо вопросам: @avito_vidnoe_support"
        )
        return
    
    # Кнопка для открытия Mini App
    keyboard = [[InlineKeyboardButton("📱 Открыть Mini App", web_app={"url": f"{config.WEBAPP_URL}/app"})]]
    
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"Добро пожаловать в **Авито Видное** — твою локальную доску объявлений!\n\n"
        f"✅ Размещай товары\n"
        f"✅ Находи покупателей\n"
        f"✅ Зарабатывай Stars\n\n"
        f"Нажми на кнопку ниже, чтобы открыть Mini App 👇",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ **Помощь**\n\n"
        "📱 **Как пользоваться:**\n"
        "1. Нажми кнопку 'Открыть Mini App'\n"
        "2. Размещай объявления\n"
        "3. Общайся с продавцами\n\n"
        "⭐ **Stars:** внутренняя валюта для продвижения\n\n"
        "📞 **Поддержка:** @avito_vidnoe_support",
        parse_mode='Markdown'
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = json.loads(query.data)
    
    if data.get('action') == 'view_reason':
        item = db.get_item(data.get('item_id'))
        if item and item.get('reject_reason'):
            await query.edit_message_text(
                f"❌ **Причина отклонения**\n\n"
                f"Товар: {item['title']}\n"
                f"Причина: {item['reject_reason']}\n\n"
                f"Исправьте ошибки и попробуйте снова.",
                parse_mode='Markdown'
            )
    
    elif data.get('action') == 'help':
        await help_command(update, context)

# ========== ОПЛАТА STARS ==========
async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    payload = update.message.successful_payment.invoice_payload
    amount = int(payload.split('_')[1])
    
    user_data = db.get_user(user.id)
    db.update_user(user.id, stars=user_data['stars'] + amount)
    db.add_transaction(user.id, amount, f"Покупка {amount} Stars", "earn")
    
    await update.message.reply_text(
        f"✅ **Оплата прошла успешно!**\n\n"
        f"Вам начислено **{amount} ⭐**\n\n"
        f"Теперь вы можете использовать Stars для премиум продвижения!",
        parse_mode='Markdown'
    )

# ========== ОТПРАВКА УВЕДОМЛЕНИЙ ==========
def send_notification(user_id, title, message, button_text=None, button_data=None):
    """Отправка уведомления пользователю"""
    import requests
    
    if button_text and button_data:
        keyboard = [[InlineKeyboardButton(button_text, callback_data=json.dumps(button_data))]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        data = {
            "chat_id": user_id,
            "text": f"🔔 **{title}**\n\n{message}",
            "parse_mode": "Markdown",
            "reply_markup": json.dumps(reply_markup.to_dict())
        }
    else:
        data = {
            "chat_id": user_id,
            "text": f"🔔 **{title}**\n\n{message}",
            "parse_mode": "Markdown"
        }
    
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json=data)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")

# ========== WEBHOOK ==========
@app.route('/webhook', methods=['POST'])
def webhook():
    """Принимаем данные из Mini App"""
    try:
        data = request.json
        action = data.get('action')
        user_id = data.get('user_id')
        payload = data.get('payload', {})
        
        logger.info(f"Webhook: {action} from {user_id}")
        
        if action == 'new_item':
            # Добавляем товар
            item = [
                payload.get('title'), payload.get('price'), payload.get('category'),
                payload.get('description'), payload.get('photo'), payload.get('seller'),
                payload.get('seller_avatar'), 'сейчас', user_id, 'pending', 'pending',
                1 if payload.get('premium') else 0
            ]
            db.add_item(item)
            
            # Уведомляем админа
            if config.ADMIN_ID:
                send_notification(
                    config.ADMIN_ID,
                    "🆕 Новый товар на модерации",
                    f"📦 {payload.get('title')}\n💰 {payload.get('price')} ₽\n👤 {payload.get('seller')}\n⭐ {'Премиум' if payload.get('premium') else 'Обычный'}"
                )
            
            return jsonify({"status": "ok"})
        
        elif action == 'moderate_item':
            # Модерация товара (только для админа)
            item_id = payload.get('item_id')
            approved = payload.get('approved')
            reason = payload.get('reason', '')
            
            if approved:
                db.update_item(item_id, moderation='approved', status='active')
                item = db.get_item(item_id)
                if item:
                    send_notification(
                        item['seller_id'],
                        "✅ Товар одобрен",
                        f"Ваш товар \"{item['title']}\" прошёл модерацию и опубликован!\n\n📱 Откройте Mini App, чтобы посмотреть."
                    )
            else:
                db.update_item(item_id, moderation='rejected', status='rejected', reject_reason=reason)
                item = db.get_item(item_id)
                if item:
                    # Возвращаем Stars если был премиум
                    if item.get('premium'):
                        seller = db.get_user(item['seller_id'])
                        if seller:
                            db.update_user(item['seller_id'], stars=seller['stars'] + 15)
                    
                    send_notification(
                        item['seller_id'],
                        "❌ Товар отклонён",
                        f"Ваш товар \"{item['title']}\" не прошёл модерацию.\n\nПричина: {reason}\n\nИсправьте ошибки и попробуйте снова.",
                        "📋 Посмотреть причину",
                        {"action": "view_reason", "item_id": item_id}
                    )
            
            return jsonify({"status": "ok"})
        
        elif action == 'block_user':
            # Блокировка пользователя (только для админа)
            target_id = payload.get('user_id')
            reason = payload.get('reason', 'Нарушение правил')
            
            db.update_user(target_id, status='blocked', block_reason=reason)
            
            send_notification(
                target_id,
                "🚫 Вы заблокированы",
                f"Причина: {reason}\n\nПо вопросам разблокировки обратитесь в поддержку.",
                "❓ Помощь",
                {"action": "help"}
            )
            
            return jsonify({"status": "ok"})
        
        elif action == 'unblock_user':
            target_id = payload.get('user_id')
            db.update_user(target_id, status='active', block_reason=None)
            return jsonify({"status": "ok"})
        
        elif action == 'buy_stars':
            # Покупка Stars через Telegram Stars
            amount = payload.get('amount')
            return jsonify({
                "status": "ok",
                "invoice": {
                    "title": f"Покупка {amount} Stars",
                    "description": f"{amount} ⭐ для продвижения объявлений",
                    "payload": f"stars_{amount}",
                    "currency": "XTR",
                    "prices": [{"label": f"{amount} Stars", "amount": amount * 100}]
                }
            })
        
        return jsonify({"status": "ok"})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/app')
def serve_app():
    """Отдаём HTML Mini App"""
    return send_file('web_app.html')

@app.route('/')
def index():
    return jsonify({"status": "ok", "message": "Bot is running"})

def set_webhook():
    """Устанавливаем вебхук для бота"""
    import requests
    webhook_url = f"{config.WEBAPP_URL}/webhook"
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/setWebhook"
    response = requests.post(url, json={"url": webhook_url})
    logger.info(f"Webhook set: {response.json()}")

if __name__ == '__main__':
    # Регистрируем команды для бота (для обработки callback)
    bot_app = Application.builder().token(config.BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CallbackQueryHandler(handle_callback))
    bot_app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    bot_app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    
    # Устанавливаем вебхук
    set_webhook()
    
    # Запускаем Flask
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
