import os
import sqlite3
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters
)
import logging

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния
LANGUAGE, TRADE, ADMIN_MAIN, ADMIN_STATS, ADMIN_REQUESTS, ADMIN_BROADCAST, ADMIN_BROADCAST_CONFIRM = range(7)

# Настройки
ADMIN_IDS = [397419045]  # Замените на ваш ID
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or '8142469998:AAEvpw4cSE2hPjqwM7ZqRF9U-LiU_oLPmIU'

# База данных
def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        lang TEXT DEFAULT 'ru',
        blocked INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS requests (
        request_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        link TEXT,
        summer_id TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )''')
    
    conn.commit()
    conn.close()

init_db()

# Вспомогательные функции
def get_user(user_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def add_user(user_id, username, first_name, last_name, lang):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, lang) 
    VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name, lang))
    conn.commit()
    conn.close()

def update_user_lang(user_id, lang):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET lang = ? WHERE user_id = ?', (lang, user_id))
    conn.commit()
    conn.close()

def add_request(user_id, link, summer_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO requests (user_id, link, summer_id) 
    VALUES (?, ?, ?)
    ''', (user_id, link, summer_id))
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return request_id

def get_pending_requests(page=0, per_page=10):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT r.request_id, r.created_at, u.user_id, u.username 
    FROM requests r
    JOIN users u ON r.user_id = u.user_id
    WHERE r.status = 'pending'
    ORDER BY r.created_at DESC
    LIMIT ? OFFSET ?
    ''', (per_page, page * per_page))
    requests = cursor.fetchall()
    conn.close()
    return requests

def get_request(request_id):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT r.*, u.username 
    FROM requests r
    JOIN users u ON r.user_id = u.user_id
    WHERE r.request_id = ?
    ''', (request_id,))
    request = cursor.fetchone()
    conn.close()
    return request

def update_request_status(request_id, status):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE requests SET status = ? WHERE request_id = ?', (status, request_id))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT COUNT(*) FROM users 
    WHERE date(created_at) = date('now') AND blocked = 0
    ''')
    today = cursor.fetchone()[0]
    
    cursor.execute('''
    SELECT COUNT(*) FROM users 
    WHERE date(created_at) = date('now', '-1 day') AND blocked = 0
    ''')
    yesterday = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM users WHERE blocked = 0')
    total = cursor.fetchone()[0]
    
    conn.close()
    return today, yesterday, total

def get_all_users():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE blocked = 0')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

async def mark_blocked_users(context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    all_users = get_all_users()
    blocked_count = 0
    
    for user_id in all_users:
        try:
            await context.bot.send_chat_action(chat_id=user_id, action='typing')
        except Exception as e:
            if "bot was blocked by the user" in str(e).lower():
                cursor.execute('UPDATE users SET blocked = 1 WHERE user_id = ?', (user_id,))
                blocked_count += 1
    
    conn.commit()
    conn.close()
    return blocked_count

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_user(user.id)

    if user_data and user_data[4]:  # Если язык уже выбран
        lang = user_data[4]
        
        if lang == 'ru':
            text = (
                "🤖 Этот бот создан для *бесплатного трейда*\.\n\n"
                "Если у вас есть *полезный цифровой товар* или *группа в Telegram*, вы можете отправить нам информацию о нём прямо здесь\.\n\n"
                "Если ваш товар окажется *рабочим и качественным*, вы получите *валюту внутри бота*\. Размер вознаграждения зависит от того, *насколько ценным и полезным* будет ваш материал\.\n\n"
                "✅ *Допустимые форматы:*\n"
                "• пиар\-чаты\n"
                "• приватные или открытые группы\n"
                "• облачные хранилища с полезным контентом и др\.\n\n"
                "⚠️ *Отправка спама или мусора приведёт к бану во всех наших проектах\.*\n\n"
                "Нажмите кнопку ниже, чтобы отправить заявку и ознакомиться с инструкцией\."
            )
            button_text = "🚀 Начать трейд"
        else:
            text = (
                "🤖 This bot is created for *free trading*\.\n\n"
                "If you have a *useful digital item* or a *Telegram group*, you can submit it to us here\.\n\n"
                "If your submission is *working and of good quality*, you will receive *in\-bot currency*\. The amount depends on how *valuable and useful* your item is\.\n\n"
                "✅ *Acceptable formats:*\n"
                "• promotion chats\n"
                "• private or public groups\n"
                "• cloud storage with useful content, etc\.\n\n"
                "⚠️ *Sending spam or trash content will lead to a ban from all our projects\.*\n\n"
                "Click the button below to submit your request and read the instructions\."
            )
            button_text = "🚀 Start Trade"

        keyboard = [[InlineKeyboardButton(button_text, callback_data='start_trade')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        else:
            try:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
            except:
                await context.bot.send_message(chat_id=user.id, text=text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        
        return TRADE

    # Показываем выбор языка
    keyboard = [
        [InlineKeyboardButton("🇷🇺 Русский", callback_data='lang_ru')],
        [InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "🌐 Выберите язык / Choose language"
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except:
            await context.bot.send_message(chat_id=user.id, text=text, reply_markup=reply_markup)

    return LANGUAGE

async def show_language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🇷🇺 Русский", callback_data='set_lang_ru')],
        [InlineKeyboardButton("🇬🇧 English", callback_data='set_lang_en')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = "🌐 Выберите язык / Choose language"
    
    if update.message:
        msg = await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        try:
            msg = await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except:
            msg = await context.bot.send_message(chat_id=update.effective_user.id, text=text, reply_markup=reply_markup)
    
    context.user_data['lang_message_id'] = msg.message_id
    return LANGUAGE

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    lang = query.data.split('_')[-1]  # set_lang_ru → ru
    
    # Сохраняем выбор языка
    add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        lang=lang
    )
    
    # Удаляем сообщение с выбором языка
    try:
        await context.bot.delete_message(
            chat_id=query.message.chat_id,
            message_id=context.user_data['lang_message_id']
        )
    except:
        pass
    
    # Показываем главное меню
    if lang == 'ru':
        text = (
            "🤖 Этот бот создан для *бесплатного трейда*.\n\n"
            "Если у вас есть *полезный цифровой товар* или *группа в Telegram*, вы можете отправить нам информацию о нём прямо здесь.\n\n"
            "Если ваш товар окажется *рабочим и качественным*, вы получите *валюту внутри бота*. Размер вознаграждения зависит от того, *насколько ценным и полезным* будет ваш материал.\n\n"
            "✅ Допустимые форматы:\n"
            "• пиар-чаты\n"
            "• приватные или открытые группы\n"
            "• облачные хранилища с полезным контентом и др.\n\n"
            "⚠️ *Отправка спама или мусора приведёт к бану во всех наших проектах.*\n\n"
            "Нажмите кнопку ниже, чтобы отправить заявку и ознакомиться с инструкцией."
        )
        button_text = "🚀 Начать трейд"
    else:
        text = (
            "🤖 This bot is created for *free trading*.\n\n"
            "If you have a *useful digital item* or a *Telegram group*, you can submit it to us here.\n\n"
            "If your submission is *working and of good quality*, you will receive *in-bot currency*. The amount depends on how *valuable and useful* your item is.\n\n"
            "✅ Acceptable formats:\n"
            "• promotion chats\n"
            "• private or public groups\n"
            "• cloud storage with useful content, etc.\n\n"
            "⚠️ *Sending spam or trash content will lead to a ban from all our projects.*\n\n"
            "Click the button below to submit your request and read the instructions."
        )
        button_text = "🚀 Start Trade"
    
    keyboard = [[InlineKeyboardButton(button_text, callback_data='start_trade')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await context.bot.send_message(
        chat_id=user.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return TRADE

async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    lang = query.data.split('_')[1]  # Получаем 'ru' или 'en'
    
    # Сохраняем выбор языка
    add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        lang=lang
    )
    
    # Показываем главное меню с развернутыми текстами
    if lang == 'ru':
        text = (
            "🤖 Этот бот создан для *бесплатного трейда*\\.\n\n"
            "Если у вас есть *полезный цифровой товар* или *группа в Telegram*, вы можете отправить нам информацию о нём прямо здесь\\.\n\n"
            "Если ваш товар окажется *рабочим и качественным*, вы получите *валюту внутри бота*\\. Размер вознаграждения зависит от того, *насколько ценным и полезным* будет ваш материал\\.\n\n"
            "✅ *Допустимые форматы:*\n"
            "• пиар\\-чаты\n"
            "• приватные или открытые группы\n"
            "• облачные хранилища с полезным контентом и др\\.\n\n"
            "⚠️ *Отправка спама или мусора приведёт к бану во всех наших проектах\\.*\n\n"
            "Нажмите кнопку ниже, чтобы отправить заявку и ознакомиться с инструкцией\\."
        )
        button_text = "🚀 Начать трейд"
    else:
        text = (
            "🤖 This bot is created for *free trading*\\.\n\n"
            "If you have a *useful digital item* or a *Telegram group*, you can submit it to us here\\.\n\n"
            "If your submission is *working and of good quality*, you will receive *in\\-bot currency*\\. The amount depends on how *valuable and useful* your item is\\.\n\n"
            "✅ *Acceptable formats:*\n"
            "• promotion chats\n"
            "• private or public groups\n"
            "• cloud storage with useful content, etc\\.\n\n"
            "⚠️ *Sending spam or trash content will lead to a ban from all our projects\\.*\n\n"
            "Click the button below to submit your request and read the instructions\\."
        )
        button_text = "🚀 Start Trade"
    
    keyboard = [[InlineKeyboardButton(button_text, callback_data='start_trade')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        await context.bot.send_message(
            chat_id=user.id, 
            text=text, 
            reply_markup=reply_markup, 
            parse_mode='MarkdownV2'
        )
    
    return TRADE

async def start_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_data = get_user(query.from_user.id)
    lang = user_data[4]
    
    text = "📝 Пришлите сообщение в формате:\n🔗 Ссылка\n🆔 Ваш ID в Summer боте" if lang == 'ru' else "📝 Send message in format:\n🔗 Link\n🆔 Your Summer bot ID"
    await query.edit_message_text(text=text)
    return TRADE

async def handle_trade_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_data = get_user(user.id)
    lang = user_data[4]
    message_text = update.message.text

    lines = message_text.split('\n')
    if len(lines) != 2 or not lines[0].strip() or not lines[1].strip():
        error_text = (
            "❌ *Неверный формат.* Пришлите:\n🔗 *Ссылка*\n🆔 *ID*"
            if lang == 'ru'
            else "❌ *Invalid format.* Send:\n🔗 *Link*\n🆔 *ID*"
        )
        await update.message.reply_text(error_text, parse_mode="Markdown")
        return TRADE

    link = lines[0].strip()
    summer_id = lines[1].strip()
    request_id = add_request(user.id, link, summer_id)

    success_text = "✅ *Заявка отправлена!*" if lang == 'ru' else "✅ *Request submitted!*"
    await update.message.reply_text(success_text, parse_mode="Markdown")

    for admin_id in ADMIN_IDS:
        try:
            keyboard = [
                [
                    InlineKeyboardButton("❌ Отклонить", callback_data=f'reject_{request_id}'),
                    InlineKeyboardButton("✅ Принять", callback_data=f'accept_{request_id}')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            admin_text = (
                f"📩 *Новая заявка от пользователя:* @{user.username if user.username else 'N/A'}\n"
                f"🔗 *Ссылка:* `{link}`\n"
                f"🆔 *Айди:* `{summer_id}`"
            )

            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

    # Возвращаем пользователя в главное меню
    main_menu_text = (
            "🤖 Этот бот создан для *бесплатного трейда*.\n\n"
            "Если у вас есть *полезный цифровой товар* или *группа в Telegram*, вы можете отправить нам информацию о нём прямо здесь.\n\n"
            "Если ваш товар окажется *рабочим и качественным*, вы получите *валюту внутри бота*. Размер вознаграждения зависит от того, *насколько ценным и полезным* будет ваш материал.\n\n"
            "✅ Допустимые форматы:\n"
            "• пиар-чаты\n"
            "• приватные или открытые группы\n"
            "• облачные хранилища с полезным контентом и др.\n\n"
            "⚠️ *Отправка спама или мусора приведёт к бану во всех наших проектах.*\n\n"
            "Нажмите кнопку ниже, чтобы отправить заявку и ознакомиться с инструкцией."
        if lang == 'ru'
        else
            "🤖 This bot is created for *free trading*.\n\n"
            "If you have a *useful digital item* or a *Telegram group*, you can submit it to us here.\n\n"
            "If your submission is *working and of good quality*, you will receive *in-bot currency*. The amount depends on how *valuable and useful* your item is.\n\n"
            "✅ Acceptable formats:\n"
            "• promotion chats\n"
            "• private or public groups\n"
            "• cloud storage with useful content, etc.\n\n"
            "⚠️ *Sending spam or trash content will lead to a ban from all our projects.*\n\n"
            "Click the button below to submit your request and read the instructions."
    )

    keyboard = [[
        InlineKeyboardButton(
            "🚀 Начать трейд" if lang == 'ru' else "🚀 Start Trade",
            callback_data='start_trade'
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(main_menu_text, reply_markup=reply_markup, parse_mode="Markdown")

    return TRADE


async def handle_request_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"Error answering callback: {e}")
        return
    
    try:
        data = query.data
        if not data or '_' not in data:
            logger.error(f"Invalid callback data: {data}")
            return
            
        action, request_id = data.split('_', 1)
        request_id = int(request_id)
    except Exception as e:
        logger.error(f"Error parsing callback data: {e}")
        return
    
    try:
        request = get_request(request_id)
        if not request:
            logger.error(f"Request not found: {request_id}")
            return
            
        user_id = request[1]
        user_data = get_user(user_id)
        if not user_data:
            logger.error(f"User not found: {user_id}")
            return
            
        lang = user_data[4]
    except Exception as e:
        logger.error(f"Database error: {e}")
        return
    
    try:
        if action == 'accept':
            update_request_status(request_id, 'approved')
            user_text = "🎉 Ваша заявка одобрена!" if lang == 'ru' else "🎉 Request approved!"
            admin_text = f"✅ Заявка {request_id} одобрена"
        elif action == 'reject':
            update_request_status(request_id, 'rejected')
            user_text = "😞 Заявка отклонена." if lang == 'ru' else "😞 Request rejected."
            admin_text = f"❌ Заявка {request_id} отклонена"
        else:
            logger.error(f"Unknown action: {action}")
            return
            
        try:
            await context.bot.send_message(chat_id=user_id, text=user_text)
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
            
        try:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(admin_text)
        except Exception as e:
            logger.error(f"Failed to update admin message: {e}")
            
    except Exception as e:
        logger.error(f"Error processing request: {e}")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ У вас нет прав администратора.")
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("📨 Заявки", callback_data='admin_requests')],
        [InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text("👨‍💻 Админ меню:", reply_markup=reply_markup)
    else:
        try:
            await update.callback_query.edit_message_text("👨‍💻 Админ меню:", reply_markup=reply_markup)
        except:
            await context.bot.send_message(chat_id=user.id, text="👨‍💻 Админ меню:", reply_markup=reply_markup)
    
    return ADMIN_MAIN

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    today, yesterday, total = get_stats()
    text = (
        f"📊 Статистика\n\n"
        f"🤖 Всего пользователей: {total}\n"
        f"📅 Сегодня: {today}\n"
        f"📅 Вчера: {yesterday}"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data='admin_stats_refresh')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text=text, reply_markup=reply_markup)

async def admin_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    requests = get_pending_requests()
    text = "📨 Ожидающие заявки:\n"
    if not requests:
        text += "Нет заявок"
    else:
        for req in requests:
            request_id, created_at = req[0], req[1]
            date_str = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M')
            text += f"\n/request_{request_id} - {date_str}"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text=text, reply_markup=reply_markup)

async def admin_requests_navigate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    action = query.data.split('_')[-1]
    current_page = context.user_data.get('requests_page', 0)
    new_page = current_page + 1 if action == 'next' else current_page - 1
    
    requests = get_pending_requests(page=new_page)
    context.user_data['requests_page'] = new_page
    
    if not requests:
        text = "📨 Заявки ожидающие ответа:\n📭 Нет заявок"
    else:
        text = "📨 Заявки ожидающие ответа:\n"
        for req in requests:
            request_id = req[0]
            created_at = datetime.strptime(req[1], '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M')
            text += f"/request_{request_id} - ⏰ {created_at}\n"
    
    keyboard = []
    if new_page > 0:
        keyboard.append([InlineKeyboardButton("👈 Назад", callback_data='admin_requests_prev')])
    if len(requests) == 10:
        keyboard.append([InlineKeyboardButton("👉 Вперед", callback_data='admin_requests_next')])
    keyboard.append([InlineKeyboardButton("🔙 В меню", callback_data='admin_back')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=text, reply_markup=reply_markup)

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    text = "📢 Рассылка сообщений\n\nОтправьте сообщение, которое нужно разослать всем пользователям:"
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_back')],
        [InlineKeyboardButton("❌ Отмена", callback_data='admin_cancel_broadcast')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text=text, reply_markup=reply_markup)
    context.user_data['broadcast_state'] = True  # Флаг, что ожидается сообщение для рассылки

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    text = "📝 Отправьте сообщение для рассылки:"
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data='admin_back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text=text, reply_markup=reply_markup)
    return ADMIN_BROADCAST_CONFIRM

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get('broadcast_state'):
        return
    
    message = update.message
    broadcast_text = message.text
    
    # Получаем всех активных пользователей
    user_ids = get_all_users()
    total = len(user_ids)
    success = 0
    failed = 0
    
    # Отправляем сообщение каждому пользователю
    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=broadcast_text)
            success += 1
        except Exception as e:
            logger.error(f"Ошибка отправки пользователю {user_id}: {e}")
            failed += 1
            # Помечаем пользователя как заблокировавшего бота
            conn = sqlite3.connect('bot.db')
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET blocked = 1 WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
    
    # Отправляем отчет администратору
    result_text = (
        f"📢 Результаты рассылки:\n"
        f"✅ Успешно: {success}\n"
        f"❌ Не удалось: {failed}"
    )
    
    keyboard = [[InlineKeyboardButton("👨‍💻 В меню", callback_data='admin_back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(result_text, reply_markup=reply_markup)
    context.user_data['broadcast_state'] = False  # Сбрасываем флаг рассылки

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("📨 Заявки", callback_data='admin_requests')],
        [InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text="👨‍💻 Админ меню:", reply_markup=reply_markup)

async def admin_cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    context.user_data['broadcast_state'] = False
    await admin_back(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('❌ Действие отменено.')
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    # Обработчики админ-панели
    application.add_handler(CommandHandler('admin', admin))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern='^admin_stats$|^admin_stats_refresh$'))
    application.add_handler(CallbackQueryHandler(admin_requests, pattern='^admin_requests$'))
    application.add_handler(CallbackQueryHandler(admin_back, pattern='^admin_back$'))
    application.add_handler(CallbackQueryHandler(admin_broadcast, pattern='^admin_broadcast$'))
    application.add_handler(CallbackQueryHandler(admin_cancel_broadcast, pattern='^admin_cancel_broadcast$'))
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            LANGUAGE: [CallbackQueryHandler(language, pattern='^lang_(ru|en)$')],
            TRADE: [
                CallbackQueryHandler(start_trade, pattern='^start_trade$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trade_message)
            ],
            ADMIN_MAIN: [
                CallbackQueryHandler(admin_stats, pattern='^admin_stats$'),
                CallbackQueryHandler(admin_requests, pattern='^admin_requests$'),
                CallbackQueryHandler(admin_broadcast, pattern='^admin_broadcast$'),
            ],
            ADMIN_STATS: [
                CallbackQueryHandler(admin_stats, pattern='^admin_stats_refresh$'),
                CallbackQueryHandler(admin_back, pattern='^admin_back$'),
            ],
            ADMIN_REQUESTS: [
                CallbackQueryHandler(admin_requests_navigate, pattern='^admin_requests_'),
                CallbackQueryHandler(admin_back, pattern='^admin_back$'),
            ],
            ADMIN_BROADCAST: [
                CallbackQueryHandler(admin_broadcast_start, pattern='^admin_broadcast_start$'),
                CallbackQueryHandler(admin_back, pattern='^admin_back$'),
            ],
            ADMIN_BROADCAST_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send),
                CallbackQueryHandler(admin_back, pattern='^admin_back$'),
            ],
        },
        fallbacks=[CommandHandler('start', start)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('admin', admin))
    application.add_handler(CallbackQueryHandler(handle_request_decision, pattern='^(accept|reject)_[0-9]+$'))
    application.add_error_handler(error_handler)
    
    application.run_polling()

if __name__ == '__main__':
    main()
