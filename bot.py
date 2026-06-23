"""
Telegram-бот для записи на мастер-классы по созданию украшений
Версия 2.0 — с полной админ-панелью

Установка:
    pip install python-telegram-bot==20.7 apscheduler

Запуск:
    python masterclass_bot_v2.py
"""

import logging
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ══════════════════════════════════════════
#  НАСТРОЙКИ — заполните перед запуском
# ══════════════════════════════════════════
BOT_TOKEN    = "8559079528:AAEOXFQcqwMmAqi0H-b67vozQuhYsBa_mXc"   # Получить у @BotFather
ADMIN_CHAT_ID = 334195585          # Ваш Telegram ID (узнать у @userinfobot)
CHANNEL_USERNAME = "@JJewelryNhaTrang"  # Канал для проверки подписки

# Файлы хранения данных (создаются автоматически)
BOOKINGS_FILE  = "bookings.json"
CLASSES_FILE   = "classes.json"
SETTINGS_FILE  = "settings.json"

# ══════════════════════════════════════════
#  НАЧАЛЬНЫЕ МАСТЕР-КЛАССЫ
#  (загружаются только при первом запуске)
# ══════════════════════════════════════════
DEFAULT_CLASSES = [
    {
        "id": 1,
        "title": "🌸 Цветочные серьги из полимерной глины",
        "date": "2026-07-05 12:00",
        "duration": "3 часа",
        "price": "2500 ₽",
        "spots": 8,
        "description": "Создадим нежные серьги с цветочным мотивом. Все материалы включены."
    },
    {
        "id": 2,
        "title": "💎 Кольца из серебряной проволоки",
        "date": "2026-07-12 14:00",
        "duration": "2.5 часа",
        "price": "3000 ₽",
        "spots": 6,
        "description": "Техника wire wrapping. Научитесь делать изящные кольца с камнями."
    },
    {
        "id": 3,
        "title": "🌿 Кулоны с природными элементами",
        "date": "2026-07-19 11:00",
        "duration": "3 часа",
        "price": "2800 ₽",
        "spots": 10,
        "description": "Создадим кулоны с сухоцветами и смолой. Уникальные украшения из природы."
    },
]

DEFAULT_SETTINGS = {
    "welcome_message": (
        "👋 Добро пожаловать!\n\n"
        "Я помогу вам записаться на мастер-класс по созданию украшений.\n\n"
        "Выберите действие:"
    )
}

# ══════════════════════════════════════════
#  СОСТОЯНИЯ ДИАЛОГОВ
# ══════════════════════════════════════════
# Запись клиента
(CHOOSE_CLASS, GET_NAME, GET_PHONE, CONFIRM) = range(4)

# Админ: приветствие
EDIT_WELCOME = 10

# Админ: рассылка
(BROADCAST_TARGET, BROADCAST_SELECT_CLASS, BROADCAST_TEXT) = range(20, 23)

# Админ: новый мастер-класс
(MC_TITLE, MC_DATE, MC_DURATION, MC_PRICE, MC_SPOTS, MC_DESC) = range(30, 36)

# Админ: редактирование поля МК
(EDIT_MC_CHOOSE, EDIT_MC_FIELD, EDIT_MC_VALUE) = range(40, 43)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════
#  РАБОТА С ДАННЫМИ
# ══════════════════════════════════════════
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    data = default() if callable(default) else default
    save_json(path, data)
    return data

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_classes():    return load_json(CLASSES_FILE, DEFAULT_CLASSES)
def save_classes(d):   save_json(CLASSES_FILE, d)
def load_bookings():   return load_json(BOOKINGS_FILE, [])
def save_bookings(d):  save_json(BOOKINGS_FILE, d)
def load_settings():   return load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
def save_settings(d):  save_json(SETTINGS_FILE, d)

def get_available_spots(class_id):
    bookings = load_bookings()
    booked = sum(1 for b in bookings if b["class_id"] == class_id and b["status"] == "confirmed")
    mc = next((m for m in load_classes() if m["id"] == class_id), None)
    return (mc["spots"] - booked) if mc else 0

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_CHAT_ID

async def is_subscribed(bot, user_id: int) -> bool:
    """Проверяет подписку пользователя на канал CHANNEL_USERNAME."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        # Если бот не добавлен в канал как администратор — пропускаем проверку
        return True

def fmt_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M").strftime("%d.%m.%Y в %H:%M")
    except Exception:
        return date_str

def next_mc_id():
    classes = load_classes()
    return max((m["id"] for m in classes), default=0) + 1


# ══════════════════════════════════════════
#  КЛИЕНТСКАЯ ЧАСТЬ
# ══════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = load_settings()
    keyboard = [
        [InlineKeyboardButton("📅 Записаться на мастер-класс", callback_data="book")],
        [InlineKeyboardButton("📋 Мои записи", callback_data="my_bookings")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    if is_admin(update.effective_user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])

    await update.message.reply_text(
        settings["welcome_message"],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    settings = load_settings()
    keyboard = [
        [InlineKeyboardButton("📅 Записаться на мастер-класс", callback_data="book")],
        [InlineKeyboardButton("📋 Мои записи", callback_data="my_bookings")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    if is_admin(query.from_user.id):
        keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    await query.edit_message_text(
        settings["welcome_message"],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def show_classes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # ── Проверка подписки на канал ──
    if not await is_subscribed(context.bot, query.from_user.id):
        keyboard = [
            [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/JJewelryNhaTrang")],
            [InlineKeyboardButton("✅ Я подписался — проверить", callback_data="book")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ]
        await query.edit_message_text(
            "🔒 *Доступ только для подписчиков*\n\n"
            "Чтобы записаться на мастер-класс, необходимо подписаться на наш канал:\n"
            "📢 @JJewelryNhaTrang\n\n"
            "После подписки нажмите кнопку «Я подписался».",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    classes = load_classes()
    keyboard = []
    text = "📅 *Доступные мастер-классы:*\n\n"
    found = False
    for mc in classes:
        try:
            date = datetime.strptime(mc["date"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if date < datetime.now():
            continue
        found = True
        spots = get_available_spots(mc["id"])
        spots_text = f"✅ Мест: {spots}" if spots > 0 else "❌ Мест нет"
        text += (
            f"*{mc['title']}*\n"
            f"📆 {fmt_date(mc['date'])}\n"
            f"⏱ {mc['duration']} | 💰 {mc['price']}\n"
            f"{spots_text}\n\n"
        )
        if spots > 0:
            keyboard.append([InlineKeyboardButton(
                mc["title"][:40], callback_data=f"select_{mc['id']}"
            )])
    if not found:
        text = "😔 Пока нет доступных мастер-классов. Следите за обновлениями!"
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return CHOOSE_CLASS

async def select_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    class_id = int(query.data.split("_")[1])
    classes = load_classes()
    mc = next((m for m in classes if m["id"] == class_id), None)
    if not mc:
        await query.edit_message_text("Мастер-класс не найден.")
        return ConversationHandler.END
    context.user_data["selected_class"] = mc
    keyboard = [
        [InlineKeyboardButton("✅ Записаться", callback_data="confirm_class")],
        [InlineKeyboardButton("◀️ Назад", callback_data="book")],
    ]
    await query.edit_message_text(
        f"*{mc['title']}*\n\n"
        f"📆 {fmt_date(mc['date'])}\n"
        f"⏱ Длительность: {mc['duration']}\n"
        f"💰 Стоимость: {mc['price']}\n\n"
        f"ℹ️ {mc['description']}\n\n"
        f"Свободных мест: {get_available_spots(class_id)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CHOOSE_CLASS

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите ваше *имя и фамилию:*", parse_mode="Markdown")
    return GET_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("📱 Введите ваш *номер телефона:*", parse_mode="Markdown")
    return GET_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    mc = context.user_data["selected_class"]
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить запись", callback_data="final_confirm")],
        [InlineKeyboardButton("❌ Отмена", callback_data="main_menu")],
    ]
    await update.message.reply_text(
        f"📋 *Проверьте данные:*\n\n"
        f"👤 Имя: {context.user_data['name']}\n"
        f"📱 Телефон: {context.user_data['phone']}\n"
        f"🎨 МК: {mc['title']}\n"
        f"📆 {fmt_date(mc['date'])}\n"
        f"💰 {mc['price']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CONFIRM

async def final_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mc = context.user_data["selected_class"]
    bookings = load_bookings()
    booking = {
        "id": len(bookings) + 1,
        "user_id": query.from_user.id,
        "username": query.from_user.username or "",
        "name": context.user_data["name"],
        "phone": context.user_data["phone"],
        "class_id": mc["id"],
        "class_title": mc["title"],
        "class_date": mc["date"],
        "booked_at": datetime.now().isoformat(),
        "status": "confirmed"
    }
    bookings.append(booking)
    save_bookings(bookings)

    await query.edit_message_text(
        f"🎉 *Вы успешно записаны!*\n\n"
        f"🎨 {mc['title']}\n"
        f"📆 {fmt_date(mc['date'])}\n"
        f"💰 {mc['price']}\n\n"
        f"За день до мастер-класса пришлю напоминание. До встречи! 💎",
        parse_mode="Markdown"
    )
    await context.bot.send_message(
        ADMIN_CHAT_ID,
        f"🔔 *Новая запись №{booking['id']}*\n\n"
        f"👤 {booking['name']}\n"
        f"📱 {booking['phone']}\n"
        f"🎨 {mc['title']}\n"
        f"📆 {fmt_date(mc['date'])}\n"
        f"🆔 @{query.from_user.username or 'нет username'}",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    bookings = [b for b in load_bookings() if b["user_id"] == user_id and b["status"] == "confirmed"]
    keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
    if not bookings:
        await query.edit_message_text("У вас пока нет активных записей.", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    text = "📋 *Ваши записи:*\n\n"
    for b in bookings:
        text += f"🎨 {b['class_title']}\n📆 {fmt_date(b['class_date'])}\n\n"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]]
    await query.edit_message_text(
        "❓ *Помощь*\n\n"
        "Этот бот позволяет записаться на мастер-классы по созданию украшений.\n\n"
        "📅 *Записаться* — выбрать мастер-класс и оставить заявку\n"
        "📋 *Мои записи* — посмотреть ваши бронирования\n\n"
        "По вопросам: @ваш_username",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════
#  АДМИН-ПАНЕЛЬ
# ══════════════════════════════════════════
def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить приветствие",    callback_data="admin_welcome")],
        [InlineKeyboardButton("📋 Все записи",              callback_data="admin_bookings")],
        [InlineKeyboardButton("❌ Отменить запись",          callback_data="admin_cancel_list")],
        [InlineKeyboardButton("🔄 Перенести запись",         callback_data="admin_reschedule_list")],
        [InlineKeyboardButton("📣 Рассылка",                callback_data="admin_broadcast")],
        [InlineKeyboardButton("🗓 Расписание МК",           callback_data="admin_classes")],
        [InlineKeyboardButton("🏠 Главное меню",            callback_data="main_menu")],
    ])

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Нет доступа", show_alert=True)
        return
    await query.edit_message_text("⚙️ *Админ-панель*\n\nВыберите действие:", reply_markup=admin_keyboard(), parse_mode="Markdown")

async def admin_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    await update.message.reply_text("⚙️ *Админ-панель*\n\nВыберите действие:", reply_markup=admin_keyboard(), parse_mode="Markdown")

def back_to_admin():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад в панель", callback_data="admin_panel")]])


# ── Приветственное сообщение ──────────────
async def admin_welcome_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    settings = load_settings()
    await query.edit_message_text(
        f"✏️ *Текущее приветствие:*\n\n{settings['welcome_message']}\n\n"
        "Отправьте новый текст приветствия (или /cancel для отмены):",
        parse_mode="Markdown"
    )
    return EDIT_WELCOME

async def admin_welcome_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = load_settings()
    settings["welcome_message"] = update.message.text
    save_settings(settings)
    await update.message.reply_text(
        "✅ Приветствие обновлено!",
        reply_markup=back_to_admin()
    )
    return ConversationHandler.END


# ── Все записи ────────────────────────────
async def admin_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    bookings = [b for b in load_bookings() if b["status"] == "confirmed"]
    if not bookings:
        await query.edit_message_text("Нет активных записей.", reply_markup=back_to_admin())
        return
    text = "📋 *Все активные записи:*\n\n"
    for b in bookings:
        text += (
            f"#{b['id']} {b['name']} | {b['phone']}\n"
            f"   🎨 {b['class_title']}\n"
            f"   📆 {fmt_date(b['class_date'])}\n\n"
        )
    # Разбиваем если слишком длинно
    if len(text) > 4000:
        text = text[:4000] + "\n\n_(показаны не все)_"
    await query.edit_message_text(text, reply_markup=back_to_admin(), parse_mode="Markdown")


# ── Отмена записи ────────────────────────
async def admin_cancel_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    bookings = [b for b in load_bookings() if b["status"] == "confirmed"]
    if not bookings:
        await query.edit_message_text("Нет активных записей.", reply_markup=back_to_admin())
        return
    keyboard = [
        [InlineKeyboardButton(
            f"#{b['id']} {b['name']} — {b['class_title'][:25]}",
            callback_data=f"do_cancel_{b['id']}"
        )]
        for b in bookings
    ]
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    await query.edit_message_text(
        "❌ *Выберите запись для отмены:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def do_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    booking_id = int(query.data.split("_")[2])
    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    if not booking:
        await query.edit_message_text("Запись не найдена.", reply_markup=back_to_admin())
        return
    booking["status"] = "cancelled"
    save_bookings(bookings)
    # Уведомляем клиента
    try:
        await context.bot.send_message(
            booking["user_id"],
            f"❌ *Ваша запись отменена*\n\n"
            f"🎨 {booking['class_title']}\n"
            f"📆 {fmt_date(booking['class_date'])}\n\n"
            f"Для вопросов свяжитесь с организатором.",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await query.edit_message_text(
        f"✅ Запись #{booking_id} ({booking['name']}) отменена. Клиент уведомлён.",
        reply_markup=back_to_admin()
    )


# ── Перенос записи ───────────────────────
async def admin_reschedule_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    bookings = [b for b in load_bookings() if b["status"] == "confirmed"]
    if not bookings:
        await query.edit_message_text("Нет активных записей.", reply_markup=back_to_admin())
        return
    keyboard = [
        [InlineKeyboardButton(
            f"#{b['id']} {b['name']} — {b['class_title'][:25]}",
            callback_data=f"reschedule_pick_{b['id']}"
        )]
        for b in bookings
    ]
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    await query.edit_message_text(
        "🔄 *Выберите запись для переноса:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def reschedule_pick_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[2])
    context.user_data["reschedule_booking_id"] = booking_id
    classes = load_classes()
    booking = next((b for b in load_bookings() if b["id"] == booking_id), None)
    keyboard = []
    for mc in classes:
        try:
            date = datetime.strptime(mc["date"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if date < datetime.now() or mc["id"] == booking["class_id"]:
            continue
        spots = get_available_spots(mc["id"])
        if spots > 0:
            keyboard.append([InlineKeyboardButton(
                f"{mc['title'][:30]} — {fmt_date(mc['date'])}",
                callback_data=f"reschedule_to_{mc['id']}"
            )])
    if not keyboard:
        await query.edit_message_text("Нет доступных МК для переноса.", reply_markup=back_to_admin())
        return
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_reschedule_list")])
    await query.edit_message_text(
        f"🔄 Перенести запись #{booking_id} на:\n_(выберите новый мастер-класс)_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def reschedule_to_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    new_class_id = int(query.data.split("_")[2])
    booking_id = context.user_data.get("reschedule_booking_id")
    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    classes = load_classes()
    new_mc = next((m for m in classes if m["id"] == new_class_id), None)
    if not booking or not new_mc:
        await query.edit_message_text("Ошибка. Попробуйте снова.", reply_markup=back_to_admin())
        return
    old_title = booking["class_title"]
    old_date  = booking["class_date"]
    booking["class_id"]    = new_mc["id"]
    booking["class_title"] = new_mc["title"]
    booking["class_date"]  = new_mc["date"]
    save_bookings(bookings)
    try:
        await context.bot.send_message(
            booking["user_id"],
            f"🔄 *Ваша запись перенесена*\n\n"
            f"Было: {old_title} — {fmt_date(old_date)}\n"
            f"Стало: {new_mc['title']} — {fmt_date(new_mc['date'])}\n\n"
            f"Ждём вас! 💎",
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await query.edit_message_text(
        f"✅ Запись #{booking_id} перенесена на «{new_mc['title']}». Клиент уведомлён.",
        reply_markup=back_to_admin()
    )


# ── Рассылка ─────────────────────────────
async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    classes = load_classes()
    keyboard = [[InlineKeyboardButton("📣 Всем пользователям бота", callback_data="broadcast_all")]]
    for mc in classes:
        try:
            date = datetime.strptime(mc["date"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if date >= datetime.now():
            keyboard.append([InlineKeyboardButton(
                f"Записаны на: {mc['title'][:35]}",
                callback_data=f"broadcast_class_{mc['id']}"
            )])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    await query.edit_message_text(
        "📣 *Рассылка*\n\nКому отправить сообщение?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BROADCAST_TARGET

async def broadcast_target_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target = query.data  # "broadcast_all" или "broadcast_class_ID"
    context.user_data["broadcast_target"] = target
    await query.edit_message_text(
        "✏️ Введите текст сообщения для рассылки\n_(или /cancel для отмены)_:",
        parse_mode="Markdown"
    )
    return BROADCAST_TEXT

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    target = context.user_data.get("broadcast_target", "broadcast_all")
    bookings = load_bookings()

    if target == "broadcast_all":
        user_ids = list({b["user_id"] for b in bookings if b["status"] == "confirmed"})
        label = "всем пользователям"
    else:
        class_id = int(target.split("_")[2])
        user_ids = list({b["user_id"] for b in bookings if b["class_id"] == class_id and b["status"] == "confirmed"})
        mc = next((m for m in load_classes() if m["id"] == class_id), None)
        label = f"записанным на «{mc['title'] if mc else class_id}»"

    sent = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(uid, text)
            sent += 1
        except Exception:
            pass

    await update.message.reply_text(
        f"✅ Рассылка завершена!\nОтправлено {sent} из {len(user_ids)} ({label}).",
        reply_markup=back_to_admin()
    )
    return ConversationHandler.END


# ── Расписание мастер-классов ─────────────
async def admin_classes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    classes = load_classes()
    keyboard = [[InlineKeyboardButton("➕ Добавить мастер-класс", callback_data="admin_add_mc")]]
    for mc in classes:
        keyboard.append([InlineKeyboardButton(
            f"✏️ {mc['title'][:35]} — {fmt_date(mc['date'])}",
            callback_data=f"admin_edit_mc_{mc['id']}"
        )])
        keyboard.append([InlineKeyboardButton(
            f"🗑 Удалить: {mc['title'][:30]}",
            callback_data=f"admin_delete_mc_{mc['id']}"
        )])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    await query.edit_message_text(
        "🗓 *Расписание мастер-классов*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def admin_delete_mc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    class_id = int(query.data.split("_")[3])
    classes = load_classes()
    mc = next((m for m in classes if m["id"] == class_id), None)
    if not mc:
        await query.edit_message_text("МК не найден.", reply_markup=back_to_admin())
        return
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_mc_{class_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data="admin_classes")],
    ]
    await query.edit_message_text(
        f"Удалить «{mc['title']}»?\n\n⚠️ Все записи на этот МК будут сохранены в архиве.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confirm_delete_mc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    class_id = int(query.data.split("_")[3])
    classes = load_classes()
    classes = [m for m in classes if m["id"] != class_id]
    save_classes(classes)
    await query.edit_message_text("🗑 Мастер-класс удалён.", reply_markup=back_to_admin())


# ── Добавление МК ────────────────────────
async def admin_add_mc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_mc"] = {}
    await query.edit_message_text(
        "➕ *Новый мастер-класс*\n\nШаг 1/6: Введите *название* МК:",
        parse_mode="Markdown"
    )
    return MC_TITLE

async def mc_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_mc"]["title"] = update.message.text
    await update.message.reply_text(
        "Шаг 2/6: Введите *дату и время* в формате ДД.ММ.ГГГГ ЧЧ:ММ\nНапример: `05.08.2026 12:00`",
        parse_mode="Markdown"
    )
    return MC_DATE

async def mc_get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        dt = datetime.strptime(update.message.text.strip(), "%d.%m.%Y %H:%M")
        context.user_data["new_mc"]["date"] = dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Введите как: `05.08.2026 12:00`", parse_mode="Markdown")
        return MC_DATE
    await update.message.reply_text("Шаг 3/6: Введите *длительность* (например: `3 часа`):", parse_mode="Markdown")
    return MC_DURATION

async def mc_get_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_mc"]["duration"] = update.message.text
    await update.message.reply_text("Шаг 4/6: Введите *цену* (например: `2500 ₽`):", parse_mode="Markdown")
    return MC_PRICE

async def mc_get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_mc"]["price"] = update.message.text
    await update.message.reply_text("Шаг 5/6: Сколько *мест* на МК? (число):", parse_mode="Markdown")
    return MC_SPOTS

async def mc_get_spots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["new_mc"]["spots"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите число, например: `8`", parse_mode="Markdown")
        return MC_SPOTS
    await update.message.reply_text("Шаг 6/6: Введите *описание* МК:", parse_mode="Markdown")
    return MC_DESC

async def mc_get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_mc = context.user_data["new_mc"]
    new_mc["description"] = update.message.text
    new_mc["id"] = next_mc_id()
    classes = load_classes()
    classes.append(new_mc)
    save_classes(classes)
    await update.message.reply_text(
        f"✅ Мастер-класс добавлен!\n\n"
        f"*{new_mc['title']}*\n"
        f"📆 {fmt_date(new_mc['date'])}\n"
        f"⏱ {new_mc['duration']} | 💰 {new_mc['price']}\n"
        f"👥 Мест: {new_mc['spots']}",
        reply_markup=back_to_admin(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── Редактирование МК ────────────────────
FIELD_LABELS = {
    "title":       "Название",
    "date":        "Дата (ДД.ММ.ГГГГ ЧЧ:ММ)",
    "duration":    "Длительность",
    "price":       "Цена",
    "spots":       "Количество мест",
    "description": "Описание",
}

async def admin_edit_mc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    class_id = int(query.data.split("_")[3])
    classes = load_classes()
    mc = next((m for m in classes if m["id"] == class_id), None)
    if not mc:
        await query.edit_message_text("МК не найден.", reply_markup=back_to_admin())
        return ConversationHandler.END
    context.user_data["editing_mc_id"] = class_id
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"edit_field_{field}")]
        for field, label in FIELD_LABELS.items()
    ]
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_classes")])
    await query.edit_message_text(
        f"✏️ *Редактирование: {mc['title']}*\n\nЧто изменить?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return EDIT_MC_FIELD

async def edit_mc_field_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.split("_")[2]
    context.user_data["editing_field"] = field
    label = FIELD_LABELS.get(field, field)
    hint = " (формат: ДД.ММ.ГГГГ ЧЧ:ММ)" if field == "date" else ""
    await query.edit_message_text(
        f"Введите новое значение для *{label}*{hint}:",
        parse_mode="Markdown"
    )
    return EDIT_MC_VALUE

async def edit_mc_value_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field    = context.user_data.get("editing_field")
    class_id = context.user_data.get("editing_mc_id")
    value    = update.message.text.strip()
    classes  = load_classes()
    mc = next((m for m in classes if m["id"] == class_id), None)
    if not mc or not field:
        await update.message.reply_text("Ошибка. Попробуйте снова.", reply_markup=back_to_admin())
        return ConversationHandler.END

    if field == "date":
        try:
            dt = datetime.strptime(value, "%d.%m.%Y %H:%M")
            value = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            await update.message.reply_text("❌ Неверный формат даты. Попробуйте: `05.08.2026 12:00`", parse_mode="Markdown")
            return EDIT_MC_VALUE
    if field == "spots":
        try:
            value = int(value)
        except ValueError:
            await update.message.reply_text("❌ Введите целое число.")
            return EDIT_MC_VALUE

    mc[field] = value
    save_classes(classes)
    await update.message.reply_text(
        f"✅ Поле *{FIELD_LABELS.get(field, field)}* обновлено!",
        reply_markup=back_to_admin(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ══════════════════════════════════════════
#  НАПОМИНАНИЯ
# ══════════════════════════════════════════
async def send_reminders(app):
    bookings = load_bookings()
    for b in bookings:
        if b["status"] != "confirmed":
            continue
        try:
            class_date = datetime.strptime(b["class_date"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        diff = (class_date - datetime.now()).total_seconds() / 3600
        if 23 <= diff <= 25:
            try:
                await app.bot.send_message(
                    b["user_id"],
                    f"⏰ *Напоминание!*\n\n"
                    f"Завтра у вас мастер-класс:\n"
                    f"🎨 {b['class_title']}\n"
                    f"📆 {fmt_date(b['class_date'])}\n\n"
                    f"До встречи! 💎",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка напоминания: {e}")

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.", reply_markup=back_to_admin())
    return ConversationHandler.END


# ══════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Запись клиента
    client_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_classes, pattern="^book$")],
        states={
            CHOOSE_CLASS: [
                CallbackQueryHandler(select_class,  pattern="^select_"),
                CallbackQueryHandler(ask_name,      pattern="^confirm_class$"),
                CallbackQueryHandler(show_classes,  pattern="^book$"),
            ],
            GET_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            GET_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            CONFIRM:   [CallbackQueryHandler(final_confirm, pattern="^final_confirm$")],
        },
        fallbacks=[
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
            CommandHandler("cancel", cancel_conv),
        ],
    )

    # Изменение приветствия
    welcome_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_welcome_start, pattern="^admin_welcome$")],
        states={
            EDIT_WELCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_welcome_save)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    # Рассылка
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")],
        states={
            BROADCAST_TARGET: [CallbackQueryHandler(broadcast_target_chosen, pattern="^broadcast_")],
            BROADCAST_TEXT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    # Добавление МК
    add_mc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_mc_start, pattern="^admin_add_mc$")],
        states={
            MC_TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_title)],
            MC_DATE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_date)],
            MC_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_duration)],
            MC_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_price)],
            MC_SPOTS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_spots)],
            MC_DESC:     [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_desc)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    # Редактирование МК
    edit_mc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_mc, pattern="^admin_edit_mc_")],
        states={
            EDIT_MC_FIELD: [CallbackQueryHandler(edit_mc_field_chosen, pattern="^edit_field_")],
            EDIT_MC_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_mc_value_save)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    # Регистрация хэндлеров
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("admin",  admin_panel_cmd))
    app.add_handler(client_conv)
    app.add_handler(welcome_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(add_mc_conv)
    app.add_handler(edit_mc_conv)
    app.add_handler(CallbackQueryHandler(admin_panel,           pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_bookings,        pattern="^admin_bookings$"))
    app.add_handler(CallbackQueryHandler(admin_classes,         pattern="^admin_classes$"))
    app.add_handler(CallbackQueryHandler(admin_cancel_list,     pattern="^admin_cancel_list$"))
    app.add_handler(CallbackQueryHandler(do_cancel,             pattern="^do_cancel_"))
    app.add_handler(CallbackQueryHandler(admin_reschedule_list, pattern="^admin_reschedule_list$"))
    app.add_handler(CallbackQueryHandler(reschedule_pick_booking, pattern="^reschedule_pick_"))
    app.add_handler(CallbackQueryHandler(reschedule_to_class,   pattern="^reschedule_to_"))
    app.add_handler(CallbackQueryHandler(admin_delete_mc,       pattern="^admin_delete_mc_"))
    app.add_handler(CallbackQueryHandler(confirm_delete_mc,     pattern="^confirm_delete_mc_"))
    app.add_handler(CallbackQueryHandler(my_bookings,           pattern="^my_bookings$"))
    app.add_handler(CallbackQueryHandler(help_callback,         pattern="^help$"))
    app.add_handler(CallbackQueryHandler(main_menu_callback,    pattern="^main_menu$"))

    # Напоминания — каждый час
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, "interval", hours=1, args=[app])
    scheduler.start()

    print("✅ Бот v2.0 запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
