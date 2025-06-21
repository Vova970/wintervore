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
import threading
import time

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния
LANGUAGE, TRADE, ADMIN_MAIN, ADMIN_STATS, ADMIN_REQUESTS, ADMIN_BROADCAST, ADMIN_BROADCAST_CONFIRM = range(7)

# Настройки
ADMIN_IDS = [8126533622]  # Замените на ваш ID
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or '7715353196:AAEvyhRGpqFrUrL_eC9HMozwn9IdyIWwBM4'
DB_FILE = 'bot_database.db'
BROADCAST_LOCK = threading.Lock()

class Database:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Database, cls).__new__(cls)
                    cls._instance._initialize_db()
        return cls._instance

    def _initialize_db(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            lang TEXT DEFAULT 'ru',
            blocked INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            summer_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS broadcast_history (
            broadcast_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            message_text TEXT,
            total_users INTEGER,
            success_count INTEGER,
            failed_count INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        
        self.conn.commit()

    def get_user(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return cursor.fetchone()

    def add_user(self, user_id, username, first_name, last_name, lang):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, lang) 
        VALUES (?, ?, ?, ?, ?)''', (user_id, username, first_name, last_name, lang))
        self.conn.commit()

    def update_user_lang(self, user_id, lang):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE users SET lang = ? WHERE user_id = ?', (lang, user_id))
        self.conn.commit()

    def add_request(self, user_id, link, summer_id):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT INTO requests (user_id, link, summer_id) 
        VALUES (?, ?, ?)''', (user_id, link, summer_id))
        request_id = cursor.lastrowid
        self.conn.commit()
        return request_id

    def get_pending_requests(self, page=0, per_page=10):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT r.request_id, r.created_at, u.user_id, u.username 
        FROM requests r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.status = 'pending'
        ORDER BY r.created_at DESC
        LIMIT ? OFFSET ?''', (per_page, page * per_page))
        return cursor.fetchall()

    def get_request(self, request_id):
        cursor = self.conn.cursor()
        cursor.execute('''SELECT r.*, u.username 
        FROM requests r
        JOIN users u ON r.user_id = u.user_id
        WHERE r.request_id = ?''', (request_id,))
        return cursor.fetchone()

    def update_request_status(self, request_id, status):
        cursor = self.conn.cursor()
        cursor.execute('UPDATE requests SET status = ? WHERE request_id = ?', (status, request_id))
        self.conn.commit()

    def get_stats(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''SELECT COUNT(*) FROM users 
        WHERE date(created_at) = date('now') AND blocked = 0''')
        today = cursor.fetchone()[0]
        
        cursor.execute('''SELECT COUNT(*) FROM users 
        WHERE date(created_at) = date('now', '-1 day') AND blocked = 0''')
        yesterday = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE blocked = 0')
        total = cursor.fetchone()[0]
        
        return today, yesterday, total

    def get_all_active_users(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE blocked = 0')
        return [row[0] for row in cursor.fetchall()]

    def mark_blocked_users(self, user_ids):
        cursor = self.conn.cursor()
        cursor.executemany('UPDATE users SET blocked = 1 WHERE user_id = ?', [(uid,) for uid in user_ids])
        self.conn.commit()
        return cursor.rowcount

    def add_broadcast_record(self, admin_id, message_text, total_users, success_count, failed_count):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT INTO broadcast_history 
        (admin_id, message_text, total_users, success_count, failed_count)
        VALUES (?, ?, ?, ?, ?)''', (admin_id, message_text, total_users, success_count, failed_count))
        self.conn.commit()
        return cursor.lastrowid

    def close(self):
        self.conn.close()

# Инициализация базы данных
db = Database()

async def send_message_safe(bot, chat_id, text, parse_mode=None, reply_markup=None):
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
        return False

def get_main_menu_text(lang):
    if lang == 'ru':
        return (
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
    else:
        return (
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = db.get_user(user.id)

    if user_data and user_data['lang']:
        lang = user_data['lang']
        
        text = get_main_menu_text(lang)
        button_text = "🚀 Начать трейд" if lang == 'ru' else "🚀 Start Trade"
        
        keyboard = [[InlineKeyboardButton(button_text, callback_data='start_trade')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        else:
            try:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')
            except:
                await send_message_safe(context.bot, user.id, text, reply_markup=reply_markup, parse_mode='MarkdownV2')
        
        return TRADE

    keyboard = [
        [InlineKeyboardButton("🇷🇺 Русский", callback_data='lang_ru')],
        [InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "🌐 Выберите язык / Choose language"
    if update.message:
        msg = await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        try:
            msg = await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        except:
            msg = await send_message_safe(context.bot, user.id, text, reply_markup=reply_markup)

    context.user_data['lang_message_id'] = msg.message_id
    return LANGUAGE

async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    lang = query.data.split('_')[1]
    
    db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        lang=lang
    )
    
    text = get_main_menu_text(lang)
    button_text = "🚀 Начать трейд" if lang == 'ru' else "🚀 Start Trade"
    
    keyboard = [[InlineKeyboardButton(button_text, callback_data='start_trade')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='MarkdownV2')
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        await send_message_safe(
            context.bot, 
            user.id, 
            text, 
            reply_markup=reply_markup, 
            parse_mode='MarkdownV2'
        )
    
    return TRADE

async def start_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_data = db.get_user(query.from_user.id)
    lang = user_data['lang']
    
    text = "📝 Пришлите сообщение в формате:\n🔗 Ссылка\n🆔 Ваш ID в Summer боте" if lang == 'ru' else "📝 Send message in format:\n🔗 Link\n🆔 Your Summer bot ID"
    await query.edit_message_text(text=text)
    return TRADE

async def handle_trade_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_data = db.get_user(user.id)
    lang = user_data['lang']
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
    request_id = db.add_request(user.id, link, summer_id)

    success_text = "✅ *Заявка отправлена!*" if lang == 'ru' else "✅ *Request submitted!*"
    await update.message.reply_text(success_text, parse_mode="Markdown")

    admin_text = (
        f"📩 *Новая заявка от пользователя:* @{user.username if user.username else 'N/A'}\n"
        f"🔗 *Ссылка:* `{link}`\n"
        f"🆔 *Айди:* `{summer_id}`"
    )

    keyboard = [
        [
            InlineKeyboardButton("❌ Отклонить", callback_data=f'reject_{request_id}'),
            InlineKeyboardButton("✅ Принять", callback_data=f'accept_{request_id}')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    for admin_id in ADMIN_IDS:
        await send_message_safe(
            context.bot,
            admin_id,
            admin_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    text = get_main_menu_text(lang)
    keyboard = [[
        InlineKeyboardButton(
            "🚀 Начать трейд" if lang == 'ru' else "🚀 Start Trade",
            callback_data='start_trade'
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="MarkdownV2")

    return TRADE

async def handle_request_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    try:
        action, request_id = query.data.split('_', 1)
        request_id = int(request_id)
    except Exception as e:
        logger.error(f"Error parsing callback data: {e}")
        return
    
    request = db.get_request(request_id)
    if not request:
        logger.error(f"Request not found: {request_id}")
        return
        
    user_id = request['user_id']
    user_data = db.get_user(user_id)
    if not user_data:
        logger.error(f"User not found: {user_id}")
        return
        
    lang = user_data['lang']
    
    if action == 'accept':
        db.update_request_status(request_id, 'approved')
        user_text = "🎉 Ваша заявка одобрена!" if lang == 'ru' else "🎉 Request approved!"
        admin_text = f"✅ Заявка {request_id} одобрена"
    elif action == 'reject':
        db.update_request_status(request_id, 'rejected')
        user_text = "😞 Заявка отклонена." if lang == 'ru' else "😞 Request rejected."
        admin_text = f"❌ Заявка {request_id} отклонена"
    else:
        logger.error(f"Unknown action: {action}")
        return
        
    await send_message_safe(context.bot, user_id, user_text)
    
    try:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(admin_text)
    except Exception as e:
        logger.error(f"Failed to update admin message: {e}")

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ У вас нет прав администратора.")
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("📨 Заявки", callback_data='admin_requests')],
        [InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast')],
        [InlineKeyboardButton("🔄 Проверить блокировки", callback_data='admin_check_blocks')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text("👨‍💻 Админ меню:", reply_markup=reply_markup)
    else:
        try:
            await update.callback_query.edit_message_text("👨‍💻 Админ меню:", reply_markup=reply_markup)
        except:
            await send_message_safe(context.bot, user.id, "👨‍💻 Админ меню:", reply_markup=reply_markup)
    
    return ADMIN_MAIN

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    today, yesterday, total = db.get_stats()
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
    
    requests = db.get_pending_requests()
    text = "📨 Ожидающие заявки:\n"
    if not requests:
        text += "Нет заявок"
    else:
        for req in requests:
            request_id, created_at = req['request_id'], req['created_at']
            date_str = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M')
            text += f"\n/request_{request_id} - {date_str}"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]]
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
    return ADMIN_BROADCAST

async def admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message
    context.user_data['broadcast_message'] = message.text
    
    user_count = len(db.get_all_active_users())
    text = (
        f"📢 Подтверждение рассылки\n\n"
        f"Сообщение:\n{message.text}\n\n"
        f"Будет отправлено: {user_count} пользователям\n\n"
        f"Подтверждаете?"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, отправить", callback_data='broadcast_confirm_yes'),
            InlineKeyboardButton("❌ Нет, отменить", callback_data='broadcast_confirm_no')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(text, reply_markup=reply_markup)
    return ADMIN_BROADCAST_CONFIRM

async def admin_broadcast_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if not BROADCAST_LOCK.acquire(blocking=False):
        await query.edit_message_text("⏳ Рассылка уже выполняется, пожалуйста, подождите...")
        return
    
    try:
        broadcast_text = context.user_data['broadcast_message']
        user_ids = db.get_all_active_users()
        total_users = len(user_ids)
        success = 0
        failed = 0
        blocked_users = []

        await query.edit_message_text(f"⏳ Начата рассылка сообщения для {total_users} пользователей...")

        for i, user_id in enumerate(user_ids):
            if i % 20 == 0 and i > 0:
                time.sleep(1)
            
            try:
                await context.bot.send_message(chat_id=user_id, text=broadcast_text)
                success += 1
            except Exception as e:
                if "bot was blocked by the user" in str(e).lower():
                    blocked_users.append(user_id)
                failed += 1

        if blocked_users:
            db.mark_blocked_users(blocked_users)

        db.add_broadcast_record(
            admin_id=query.from_user.id,
            message_text=broadcast_text,
            total_users=total_users,
            success_count=success,
            failed_count=failed
        )

        result_text = (
            f"📢 Результаты рассылки:\n"
            f"✅ Успешно: {success}\n"
            f"❌ Не удалось: {failed}\n"
            f"🚫 Заблокировавших пользователей: {len(blocked_users)}"
        )
        
        keyboard = [[InlineKeyboardButton("👨‍💻 В меню", callback_data='admin_back')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(result_text, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"Ошибка при рассылке: {e}")
        await query.edit_message_text(f"❌ Произошла ошибка при рассылке: {str(e)}")
    finally:
        BROADCAST_LOCK.release()
        return ADMIN_MAIN

async def admin_check_blocks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("⏳ Проверяю заблокировавших пользователей...")
    
    user_ids = db.get_all_active_users()
    blocked_users = []
    
    for user_id in user_ids:
        try:
            await context.bot.send_chat_action(chat_id=user_id, action='typing')
        except Exception as e:
            if "bot was blocked by the user" in str(e).lower():
                blocked_users.append(user_id)
    
    if blocked_users:
        db.mark_blocked_users(blocked_users)
        text = f"🔍 Найдено {len(blocked_users)} заблокировавших пользователей"
    else:
        text = "✅ Все пользователи активны"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='admin_back')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup)

async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("📨 Заявки", callback_data='admin_requests')],
        [InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast')],
        [InlineKeyboardButton("🔄 Проверить блокировки", callback_data='admin_check_blocks')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text="👨‍💻 Админ меню:", reply_markup=reply_markup)
    return ADMIN_MAIN

async def admin_cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if 'broadcast_message' in context.user_data:
        del context.user_data['broadcast_message']
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("📨 Заявки", callback_data='admin_requests')],
        [InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast')],
        [InlineKeyboardButton("🔄 Проверить блокировки", callback_data='admin_check_blocks')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text="👨‍💻 Админ меню:", reply_markup=reply_markup)
    return ADMIN_MAIN

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('❌ Действие отменено.')
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and update.effective_user:
        await send_message_safe(
            context.bot,
            update.effective_user.id,
            "⚠️ Произошла ошибка. Пожалуйста, попробуйте еще раз."
        )

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            LANGUAGE: [CallbackQueryHandler(language, pattern='^lang_(ru|en)$')],
            TRADE: [
                CallbackQueryHandler(start_trade, pattern='^start_trade$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_trade_message)
            ],
            ADMIN_MAIN: [
                CallbackQueryHandler(admin_stats, pattern='^admin_stats$|^admin_stats_refresh$'),
                CallbackQueryHandler(admin_requests, pattern='^admin_requests$'),
                CallbackQueryHandler(admin_broadcast, pattern='^admin_broadcast$'),
                CallbackQueryHandler(admin_check_blocks, pattern='^admin_check_blocks$'),
                CallbackQueryHandler(admin_back, pattern='^admin_back$')
            ],
            ADMIN_BROADCAST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_confirm),
                CallbackQueryHandler(admin_back, pattern='^admin_back$'),
                CallbackQueryHandler(admin_cancel_broadcast, pattern='^admin_cancel_broadcast$')
            ],
            ADMIN_BROADCAST_CONFIRM: [
                CallbackQueryHandler(admin_broadcast_execute, pattern='^broadcast_confirm_yes$'),
                CallbackQueryHandler(admin_back, pattern='^broadcast_confirm_no$|^admin_back$')
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('admin', admin))
    application.add_handler(CallbackQueryHandler(handle_request_decision, pattern='^(accept|reject)_[0-9]+$'))
    application.add_error_handler(error_handler)
    
    application.run_polling()

if __name__ == '__main__':
    try:
        main()
    finally:
        db.close()
