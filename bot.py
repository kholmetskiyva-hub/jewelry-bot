"""
Telegram-бот для записи на мастер-классы по созданию украшений
Версия 3.0 — напоминания за 24ч и 1ч с подтверждением, адрес кафе
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
#  НАСТРОЙКИ
# ══════════════════════════════════════════
BOT_TOKEN         = "8559079528:AAEOXFQcqwMmAqi0H-b67vozQuhYsBa_mXc"
ADMIN_CHAT_ID     = 334195585
CHANNEL_USERNAME  = "@JJewelryNhaTrang"

BOOKINGS_FILE = "bookings.json"
CLASSES_FILE  = "classes.json"
SETTINGS_FILE = "settings.json"

DEFAULT_CLASSES = [
    {
        "id": 1,
        "title": "🌸 Цветочные серьги из полимерной глины",
        "date": "2026-07-05 12:00",
        "duration": "3 часа",
        "price": "2500 ₽",
        "spots": 8,
        "description": "Создадим нежные серьги с цветочным мотивом. Все материалы включены.",
        "venue_name": "Кафе Example",
        "venue_url": "https://maps.google.com/?q=Nha+Trang"
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
(CHOOSE_CLASS, GET_NAME, CONFIRM) = range(3)
EDIT_WELCOME = 10
(BROADCAST_TARGET, BROADCAST_SELECT_CLASS, BROADCAST_TEXT) = range(20, 23)
(MC_TITLE, MC_DATE, MC_DURATION, MC_PRICE, MC_SPOTS, MC_DESC, MC_VENUE_NAME, MC_VENUE_URL) = range(30, 38)
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
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
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

    if not await is_subscribed(context.bot, query.from_user.id):
        keyboard = [
            [InlineKeyboardButton("📢 Подписаться на канал", url=f"https://t.me/JJewelryNhaTrang")],
            [InlineKeyboardButton("✅ Я подписался — проверить", callback_data="book")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
        ]
        await query.edit_message_text(
            "🔒 *Доступ только для подписчиков*\n\n"
            "Подпишитесь на канал @JJewelryNhaTrang и нажмите «Я подписался».",
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
        spots = get_available_spots(mc["id"])
        # Скрываем МК если мест нет
        if spots <= 0:
            continue
        found = True
        venue_name = mc.get("venue_name", "")
        venue_line = f"📍 {venue_name}\n" if venue_name else ""
        text += (
            f"*{mc['title']}*\n"
            f"📆 {fmt_date(mc['date'])}\n"
            f"{venue_line}"
            f"⏱ {mc['duration']} | 💰 {mc['price']}\n"
            f"✅ Мест: {spots}\n\n"
        )
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
    # Проверяем актуальное кол-во мест
    spots_now = get_available_spots(class_id)
    if spots_now <= 0:
        await query.edit_message_text(
            f"😔 К сожалению, все места на *{mc['title']}* уже заняты.\n\n"
            f"Выберите другой мастер-класс:",
            parse_mode="Markdown"
        )
        return await show_classes(update, context)
    context.user_data["selected_class"] = mc
    keyboard = [
        [InlineKeyboardButton(f"✅ Записаться ({spots_now} мест)", callback_data="confirm_class")],
        [InlineKeyboardButton("◀️ Назад", callback_data="book")],
    ]
    venue_name = mc.get("venue_name", "")
    venue_url  = mc.get("venue_url", "")
    venue_line = f"📍 [{venue_name}]({venue_url})\n" if venue_name and venue_url else (f"📍 {venue_name}\n" if venue_name else "")
    await query.edit_message_text(
        f"*{mc['title']}*\n\n"
        f"📆 {fmt_date(mc['date'])}\n"
        f"{venue_line}"
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
    await query.edit_message_text("Введите ваше *имя:*", parse_mode="Markdown")
    return GET_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    mc = context.user_data["selected_class"]
    username = update.message.from_user.username
    contact = f"@{username}" if username else f"ID: {update.message.from_user.id}"
    context.user_data["contact"] = contact
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить запись", callback_data="final_confirm")],
        [InlineKeyboardButton("❌ Отмена", callback_data="main_menu")],
    ]
    venue_name = mc.get("venue_name", "")
    venue_url  = mc.get("venue_url", "")
    venue_line = f"📍 [{venue_name}]({venue_url})\n" if venue_name and venue_url else (f"📍 {venue_name}\n" if venue_name else "")
    await update.message.reply_text(
        f"📋 *Проверьте данные:*\n\n"
        f"👤 Имя: {context.user_data['name']}\n"
        f"📲 Контакт: {contact}\n"
        f"🎨 МК: {mc['title']}\n"
        f"📆 {fmt_date(mc['date'])}\n"
        f"{venue_line}"
        f"💰 {mc['price']}\n\n"
        f"Это ваш Telegram — всё верно?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CONFIRM



async def final_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mc = context.user_data["selected_class"]
    # Финальная проверка мест перед записью (защита от двойной записи)
    spots_final = get_available_spots(mc["id"])
    if spots_final <= 0:
        await query.edit_message_text(
            f"😔 К сожалению, места на *{mc['title']}* только что закончились.\n\n"
            f"Выберите другой мастер-класс:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 Выбрать другой МК", callback_data="book")
            ]]),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    bookings = load_bookings()
    contact = context.user_data.get("contact", f"@{query.from_user.username}" if query.from_user.username else f"ID:{query.from_user.id}")
    booking = {
        "id": len(bookings) + 1,
        "user_id": query.from_user.id,
        "username": query.from_user.username or "",
        "name": context.user_data["name"],
        "phone": contact,
        "class_id": mc["id"],
        "class_title": mc["title"],
        "class_date": mc["date"],
        "venue_name": mc.get("venue_name", ""),
        "venue_url": mc.get("venue_url", ""),
        "booked_at": datetime.now().isoformat(),
        "status": "confirmed",
        "reminder_24h_sent": False,
        "reminder_1h_sent": False,
        "confirmed_attendance": False,
    }
    bookings.append(booking)
    save_bookings(bookings)

    venue_name = mc.get("venue_name", "")
    venue_url  = mc.get("venue_url", "")
    venue_line = f"📍 [{venue_name}]({venue_url})\n" if venue_name and venue_url else (f"📍 {venue_name}\n" if venue_name else "")

    post_booking_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Записаться ещё на МК", callback_data="book")],
        [InlineKeyboardButton("🔄 Перенести запись", callback_data=f"user_move_{booking['id']}")],
        [InlineKeyboardButton("❌ Отменить запись", callback_data=f"user_cancel_{booking['id']}")],
    ])
    await query.edit_message_text(
        f"🎉 *Вы успешно записаны!*\n\n"
        f"🎨 {mc['title']}\n"
        f"📆 {fmt_date(mc['date'])}\n"
        f"{venue_line}"
        f"💰 {mc['price']}\n\n"
        f"За сутки пришлю напоминание. До встречи! 💎",
        reply_markup=post_booking_keyboard,
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
        venue_name = b.get("venue_name", "")
        venue_url  = b.get("venue_url", "")
        venue_line = f"📍 [{venue_name}]({venue_url})\n" if venue_name and venue_url else (f"📍 {venue_name}\n" if venue_name else "")
        text += f"🎨 {b['class_title']}\n📆 {fmt_date(b['class_date'])}\n{venue_line}\n"
        keyboard.insert(-1, [
            InlineKeyboardButton("🔄 Перенести", callback_data=f"user_move_{b['id']}"),
            InlineKeyboardButton("❌ Отменить", callback_data=f"user_cancel_{b['id']}"),
        ])
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
        "По вопросам: @вашusername",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════
#  ПОДТВЕРЖДЕНИЕ ПОСЕЩЕНИЯ (ответ на напоминание)
# ══════════════════════════════════════════
async def attendance_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь нажал «Подтверждаю ✅»"""
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[2])
    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    if not booking:
        await query.edit_message_text("Запись не найдена.")
        return

    booking["confirmed_attendance"] = True
    save_bookings(bookings)

    mc_date = fmt_date(booking["class_date"])
    venue_name = booking.get("venue_name", "")
    venue_url  = booking.get("venue_url", "")
    venue_line = f"📍 [{venue_name}]({venue_url})\n" if venue_name and venue_url else (f"📍 {venue_name}\n" if venue_name else "")

    await query.edit_message_text(
        f"✅ *Отлично! Ждём вас!*\n\n"
        f"🎨 {booking['class_title']}\n"
        f"📆 {mc_date}\n"
        f"{venue_line}"
        f"\nДо встречи! 💎",
        parse_mode="Markdown"
    )

    # Уведомляем админа
    try:
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"✅ *Подтверждение посещения*\n\n"
            f"👤 {booking['name']} (@{booking.get('username') or 'нет'})\n"
            f"📱 {booking['phone']}\n"
            f"🎨 {booking['class_title']}\n"
            f"📆 {mc_date}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")

async def attendance_reschedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь нажал «Перенести 🔄»"""
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[2])
    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    if not booking:
        await query.edit_message_text("Запись не найдена.")
        return

    # Показываем доступные МК для переноса
    classes = load_classes()
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
                callback_data=f"user_reschedule_{booking_id}_{mc['id']}"
            )])

    if not keyboard:
        await query.edit_message_text(
            "😔 К сожалению, сейчас нет доступных МК для переноса.\n"
            "Свяжитесь с организатором.",
            parse_mode="Markdown"
        )
        # Уведомляем админа
        try:
            await context.bot.send_message(
                ADMIN_CHAT_ID,
                f"🔄 *Запрос на перенос*\n\n"
                f"👤 {booking['name']} (@{booking.get('username') or 'нет'})\n"
                f"📱 {booking['phone']}\n"
                f"🎨 {booking['class_title']}\n"
                f"📆 {fmt_date(booking['class_date'])}\n\n"
                f"⚠️ Нет доступных МК — свяжитесь с клиентом вручную.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="main_menu")])
    await query.edit_message_text(
        "🔄 *Выберите мастер-класс для переноса:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def attendance_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь нажал «Отмена ❌» в напоминании"""
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[2])
    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    if not booking:
        await query.edit_message_text("Запись не найдена.")
        return

    booking["status"] = "cancelled"
    save_bookings(bookings)

    await query.edit_message_text(
        f"❌ *Ваша запись отменена.*\n\n"
        f"🎨 {booking['class_title']}\n"
        f"📆 {fmt_date(booking['class_date'])}\n\n"
        f"Будем рады видеть вас на следующих мастер-классах! 💎",
        parse_mode="Markdown"
    )

    # Уведомляем админа
    try:
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"❌ *Клиент отменил запись*\n\n"
            f"👤 {booking['name']} (@{booking.get('username') or 'нет'})\n"
            f"📱 {booking['phone']}\n"
            f"🎨 {booking['class_title']}\n"
            f"📆 {fmt_date(booking['class_date'])}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")


async def user_move_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перенос записи — вызывается кнопкой после успешной записи"""
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[2])
    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    if not booking or booking["status"] != "confirmed":
        await query.edit_message_text("Запись не найдена или уже отменена.")
        return

    classes = load_classes()
    keyboard = []
    for mc in classes:
        try:
            date = datetime.strptime(mc["date"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if date < datetime.now() or mc["id"] == booking["class_id"]:
            continue
        if get_available_spots(mc["id"]) > 0:
            keyboard.append([InlineKeyboardButton(
                f"{mc['title'][:30]} — {fmt_date(mc['date'])}",
                callback_data=f"user_reschedule_{booking_id}_{mc['id']}"
            )])

    if not keyboard:
        await query.edit_message_text(
            "😔 Сейчас нет доступных МК для переноса.\n"
            "Свяжитесь с организатором.",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                ADMIN_CHAT_ID,
                f"🔄 *Запрос на перенос*\n\n"
                f"👤 {booking['name']} ({booking.get('phone','')})\n"
                f"🎨 {booking['class_title']}\n"
                f"📆 {fmt_date(booking['class_date'])}\n\n"
                f"⚠️ Нет доступных МК — свяжитесь с клиентом.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="main_menu")])
    await query.edit_message_text(
        "🔄 *Выберите мастер-класс для переноса:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def user_cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена записи — вызывается кнопкой после успешной записи"""
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[2])
    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    if not booking or booking["status"] != "confirmed":
        await query.edit_message_text("Запись не найдена или уже отменена.")
        return

    # Показываем подтверждение отмены
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, отменить", callback_data=f"user_cancel_confirm_{booking_id}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="my_bookings")],
    ])
    await query.edit_message_text(
        f"❓ Вы уверены, что хотите отменить запись?\n\n"
        f"🎨 {booking['class_title']}\n"
        f"📆 {fmt_date(booking['class_date'])}",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def user_cancel_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение отмены записи пользователем"""
    query = update.callback_query
    await query.answer()
    booking_id = int(query.data.split("_")[3])
    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    if not booking:
        await query.edit_message_text("Запись не найдена.")
        return

    booking["status"] = "cancelled"
    save_bookings(bookings)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Записаться на другой МК", callback_data="book")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
    ])
    await query.edit_message_text(
        f"❌ *Запись отменена.*\n\n"
        f"🎨 {booking['class_title']}\n"
        f"📆 {fmt_date(booking['class_date'])}\n\n"
        f"Будем рады видеть вас на следующих мастер-классах! 💎",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    try:
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"❌ *Клиент отменил запись*\n\n"
            f"👤 {booking['name']} ({booking.get('phone','')})\n"
            f"🎨 {booking['class_title']}\n"
            f"📆 {fmt_date(booking['class_date'])}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")


async def user_reschedule_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пользователь выбрал новый МК для переноса"""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    booking_id  = int(parts[2])
    new_class_id = int(parts[3])

    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    classes = load_classes()
    new_mc = next((m for m in classes if m["id"] == new_class_id), None)

    if not booking or not new_mc:
        await query.edit_message_text("Ошибка. Попробуйте снова.")
        return

    old_title = booking["class_title"]
    old_date  = booking["class_date"]

    booking["class_id"]    = new_mc["id"]
    booking["class_title"] = new_mc["title"]
    booking["class_date"]  = new_mc["date"]
    booking["venue_name"]  = new_mc.get("venue_name", "")
    booking["venue_url"]   = new_mc.get("venue_url", "")
    booking["confirmed_attendance"] = False
    booking["reminder_24h_sent"]    = False
    booking["reminder_1h_sent"]     = False
    save_bookings(bookings)

    venue_name = new_mc.get("venue_name", "")
    venue_url  = new_mc.get("venue_url", "")
    venue_line = f"📍 [{venue_name}]({venue_url})\n" if venue_name and venue_url else ""

    await query.edit_message_text(
        f"✅ *Запись перенесена!*\n\n"
        f"Было: {old_title} — {fmt_date(old_date)}\n"
        f"Стало: {new_mc['title']} — {fmt_date(new_mc['date'])}\n"
        f"{venue_line}\n"
        f"Ждём вас! 💎",
        parse_mode="Markdown"
    )

    # Уведомляем админа
    try:
        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"🔄 *Клиент перенёс запись*\n\n"
            f"👤 {booking['name']} (@{booking.get('username') or 'нет'})\n"
            f"📱 {booking['phone']}\n"
            f"Было: {old_title} — {fmt_date(old_date)}\n"
            f"Стало: {new_mc['title']} — {fmt_date(new_mc['date'])}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")


# ══════════════════════════════════════════
#  НАПОМИНАНИЯ (запускаются каждые 30 минут)
# ══════════════════════════════════════════
def reminder_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения — используется в обоих напоминаниях"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтверждаю", callback_data=f"attend_confirm_{booking_id}")],
        [InlineKeyboardButton("🔄 Перенести на другой МК", callback_data=f"attend_reschedule_{booking_id}")],
        [InlineKeyboardButton("❌ Отмена записи", callback_data=f"attend_cancel_{booking_id}")],
    ])

async def send_reminders(app):
    bookings = load_bookings()
    changed = False

    for b in bookings:
        if b["status"] != "confirmed":
            continue
        try:
            class_date = datetime.strptime(b["class_date"], "%Y-%m-%d %H:%M")
        except Exception:
            continue

        diff_hours = (class_date - datetime.now()).total_seconds() / 3600
        venue_name = b.get("venue_name", "")
        venue_url  = b.get("venue_url", "")
        venue_line = f"📍 [{venue_name}]({venue_url})\n" if venue_name and venue_url else (f"📍 {venue_name}\n" if venue_name else "")

        # ── Напоминание за 24 часа ──────────────────────────────
        if 23 <= diff_hours <= 25 and not b.get("reminder_24h_sent"):
            try:
                await app.bot.send_message(
                    b["user_id"],
                    f"⏰ *Напоминание — завтра ваш мастер-класс!*\n\n"
                    f"🎨 {b['class_title']}\n"
                    f"📆 {fmt_date(b['class_date'])}\n"
                    f"{venue_line}\n"
                    f"Пожалуйста, подтвердите участие:",
                    reply_markup=reminder_keyboard(b["id"]),
                    parse_mode="Markdown"
                )
                b["reminder_24h_sent"] = True
                changed = True
                logger.info(f"Напоминание 24ч отправлено: {b['name']}")
            except Exception as e:
                logger.error(f"Ошибка напоминания 24ч: {e}")

        # ── Напоминание за 1 час ────────────────────────────────
        if 0.5 <= diff_hours <= 1.5 and not b.get("reminder_1h_sent"):
            try:
                await app.bot.send_message(
                    b["user_id"],
                    f"🔔 *Через час начинается мастер-класс!*\n\n"
                    f"🎨 {b['class_title']}\n"
                    f"📆 {fmt_date(b['class_date'])}\n"
                    f"{venue_line}\n"
                    f"Выезжайте заранее! Подтвердите участие:",
                    reply_markup=reminder_keyboard(b["id"]),
                    parse_mode="Markdown"
                )
                b["reminder_1h_sent"] = True
                changed = True
                logger.info(f"Напоминание 1ч отправлено: {b['name']}")
            except Exception as e:
                logger.error(f"Ошибка напоминания 1ч: {e}")

    if changed:
        save_bookings(bookings)


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


async def admin_welcome_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    settings = load_settings()
    await query.edit_message_text(
        f"✏️ *Текущее приветствие:*\n\n{settings['welcome_message']}\n\nОтправьте новый текст:",
        parse_mode="Markdown"
    )
    return EDIT_WELCOME

async def admin_welcome_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings = load_settings()
    settings["welcome_message"] = update.message.text
    save_settings(settings)
    await update.message.reply_text("✅ Приветствие обновлено!", reply_markup=back_to_admin())
    return ConversationHandler.END


async def admin_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bookings = [b for b in load_bookings() if b["status"] == "confirmed"]
    if not bookings:
        await query.edit_message_text("Нет активных записей.", reply_markup=back_to_admin())
        return
    text = "📋 *Все активные записи:*\n\n"
    for b in bookings:
        confirmed = "✅" if b.get("confirmed_attendance") else "⏳"
        text += (
            f"#{b['id']} {b['name']} | {b['phone']}\n"
            f"   🎨 {b['class_title']}\n"
            f"   📆 {fmt_date(b['class_date'])}\n"
            f"   {confirmed} Посещение подтверждено\n\n"
        )
    if len(text) > 4000:
        text = text[:4000] + "\n\n_(показаны не все)_"
    await query.edit_message_text(text, reply_markup=back_to_admin(), parse_mode="Markdown")


async def admin_cancel_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
    booking_id = int(query.data.split("_")[2])
    bookings = load_bookings()
    booking = next((b for b in bookings if b["id"] == booking_id), None)
    if not booking:
        await query.edit_message_text("Запись не найдена.", reply_markup=back_to_admin())
        return
    booking["status"] = "cancelled"
    save_bookings(bookings)
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


async def admin_reschedule_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
        if get_available_spots(mc["id"]) > 0:
            keyboard.append([InlineKeyboardButton(
                f"{mc['title'][:30]} — {fmt_date(mc['date'])}",
                callback_data=f"reschedule_to_{mc['id']}"
            )])
    if not keyboard:
        await query.edit_message_text("Нет доступных МК для переноса.", reply_markup=back_to_admin())
        return
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_reschedule_list")])
    await query.edit_message_text(
        f"🔄 Перенести запись #{booking_id} на:",
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
        await query.edit_message_text("Ошибка.", reply_markup=back_to_admin())
        return
    old_title = booking["class_title"]
    old_date  = booking["class_date"]
    booking["class_id"]    = new_mc["id"]
    booking["class_title"] = new_mc["title"]
    booking["class_date"]  = new_mc["date"]
    booking["venue_name"]  = new_mc.get("venue_name", "")
    booking["venue_url"]   = new_mc.get("venue_url", "")
    booking["confirmed_attendance"] = False
    booking["reminder_24h_sent"]    = False
    booking["reminder_1h_sent"]     = False
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


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
    context.user_data["broadcast_target"] = query.data
    await query.edit_message_text("✏️ Введите текст сообщения для рассылки:", parse_mode="Markdown")
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


# ══════════════════════════════════════════
#  РАСПИСАНИЕ МК
# ══════════════════════════════════════════
async def admin_classes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
    await query.edit_message_text(f"Удалить «{mc['title']}»?", reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_delete_mc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    class_id = int(query.data.split("_")[3])
    classes = [m for m in load_classes() if m["id"] != class_id]
    save_classes(classes)
    await query.edit_message_text("🗑 Мастер-класс удалён.", reply_markup=back_to_admin())


# ── Добавление МК (теперь 8 шагов — добавили название и адрес кафе) ──
async def admin_add_mc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_mc"] = {}
    await query.edit_message_text(
        "➕ *Новый мастер-класс*\n\nШаг 1/8: Введите *название* МК:",
        parse_mode="Markdown"
    )
    return MC_TITLE

async def mc_get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_mc"]["title"] = update.message.text
    await update.message.reply_text(
        "Шаг 2/8: Введите *дату и время* в формате ДД.ММ.ГГГГ ЧЧ:ММ\nНапример: `05.08.2026 12:00`",
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
    await update.message.reply_text("Шаг 3/8: Введите *длительность* (например: `3 часа`):", parse_mode="Markdown")
    return MC_DURATION

async def mc_get_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_mc"]["duration"] = update.message.text
    await update.message.reply_text("Шаг 4/8: Введите *цену* (например: `2500 ₽`):", parse_mode="Markdown")
    return MC_PRICE

async def mc_get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_mc"]["price"] = update.message.text
    await update.message.reply_text("Шаг 5/8: Сколько *мест* на МК? (число):", parse_mode="Markdown")
    return MC_SPOTS

async def mc_get_spots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["new_mc"]["spots"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите число, например: `8`", parse_mode="Markdown")
        return MC_SPOTS
    await update.message.reply_text("Шаг 6/8: Введите *описание* МК:", parse_mode="Markdown")
    return MC_DESC

async def mc_get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_mc"]["description"] = update.message.text
    await update.message.reply_text(
        "Шаг 7/8: Введите *название кафе/места проведения*:\n"
        "Например: `Кафе Море`",
        parse_mode="Markdown"
    )
    return MC_VENUE_NAME

async def mc_get_venue_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_mc"]["venue_name"] = update.message.text.strip()
    await update.message.reply_text(
        "Шаг 8/8: Вставьте *ссылку на Google Maps* для этого места:\n\n"
        "Как получить ссылку:\n"
        "1. Откройте Google Maps\n"
        "2. Найдите место\n"
        "3. Нажмите «Поделиться» → скопируйте ссылку\n\n"
        "Вставьте ссылку:",
        parse_mode="Markdown"
    )
    return MC_VENUE_URL

async def mc_get_venue_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text(
            "❌ Ссылка должна начинаться с http или https.\nПопробуйте снова:",
            parse_mode="Markdown"
        )
        return MC_VENUE_URL

    new_mc = context.user_data["new_mc"]
    new_mc["venue_url"] = url
    new_mc["id"] = next_mc_id()
    classes = load_classes()
    classes.append(new_mc)
    save_classes(classes)

    venue_name = new_mc.get("venue_name", "")
    venue_url  = new_mc.get("venue_url", "")

    await update.message.reply_text(
        f"✅ *Мастер-класс добавлен!*\n\n"
        f"*{new_mc['title']}*\n"
        f"📆 {fmt_date(new_mc['date'])}\n"
        f"📍 [{venue_name}]({venue_url})\n"
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
    "venue_name":  "Название кафе",
    "venue_url":   "Ссылка на Google Maps",
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
    hints = {
        "date": " (формат: ДД.ММ.ГГГГ ЧЧ:ММ)",
        "venue_url": "\n\nВставьте ссылку из Google Maps (начинается с https://)",
    }
    hint = hints.get(field, "")
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
        await update.message.reply_text("Ошибка.", reply_markup=back_to_admin())
        return ConversationHandler.END
    if field == "date":
        try:
            dt = datetime.strptime(value, "%d.%m.%Y %H:%M")
            value = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            await update.message.reply_text("❌ Неверный формат даты.", parse_mode="Markdown")
            return EDIT_MC_VALUE
    if field == "spots":
        try:
            value = int(value)
        except ValueError:
            await update.message.reply_text("❌ Введите целое число.")
            return EDIT_MC_VALUE
    if field == "venue_url" and not value.startswith("http"):
        await update.message.reply_text("❌ Ссылка должна начинаться с https://")
        return EDIT_MC_VALUE
    mc[field] = value
    save_classes(classes)
    await update.message.reply_text(
        f"✅ Поле *{FIELD_LABELS.get(field, field)}* обновлено!",
        reply_markup=back_to_admin(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Отменено.", reply_markup=back_to_admin())
    return ConversationHandler.END


# ══════════════════════════════════════════
#  КОМАНДЫ ПОСТОЯННОГО МЕНЮ
# ══════════════════════════════════════════
async def cmd_book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /book — Записаться на МК"""
    settings = load_settings()
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
        spots = get_available_spots(mc["id"])
        if spots <= 0:
            continue
        found = True
        venue_name = mc.get("venue_name", "")
        venue_line = f"📍 {venue_name}\n" if venue_name else ""
        text += (
            f"*{mc['title']}*\n"
            f"📆 {fmt_date(mc['date'])}\n"
            f"{venue_line}"
            f"⏱ {mc['duration']} | 💰 {mc['price']}\n"
            f"✅ Мест: {spots}\n\n"
        )
        keyboard.append([InlineKeyboardButton(
            mc["title"][:40], callback_data=f"select_{mc['id']}"
        )])
    if not found:
        text = "😔 Пока нет доступных мастер-классов. Следите за обновлениями!"
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def cmd_mybookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /mybookings — Мои записи"""
    user_id = update.effective_user.id
    bookings = [b for b in load_bookings() if b["user_id"] == user_id and b["status"] == "confirmed"]
    keyboard = [[InlineKeyboardButton("📅 Записаться на МК", callback_data="book")]]
    if not bookings:
        await update.message.reply_text(
            "У вас пока нет активных записей.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    text = "📋 *Ваши записи:*\n\n"
    for b in bookings:
        venue_name = b.get("venue_name", "")
        venue_url  = b.get("venue_url", "")
        venue_line = f"📍 [{venue_name}]({venue_url})\n" if venue_name and venue_url else (f"📍 {venue_name}\n" if venue_name else "")
        text += f"🎨 {b['class_title']}\n📆 {fmt_date(b['class_date'])}\n{venue_line}\n"
        keyboard.insert(0, [
            InlineKeyboardButton("🔄 Перенести", callback_data=f"user_move_{b['id']}"),
            InlineKeyboardButton("❌ Отменить",  callback_data=f"user_cancel_{b['id']}"),
        ])
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def cmd_move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /move — Перенести запись"""
    user_id = update.effective_user.id
    bookings = [b for b in load_bookings() if b["user_id"] == user_id and b["status"] == "confirmed"]
    if not bookings:
        await update.message.reply_text(
            "У вас нет активных записей для переноса.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 Записаться на МК", callback_data="book")
            ]])
        )
        return
    keyboard = [
        [InlineKeyboardButton(
            f"🔄 {b['class_title'][:35]} — {fmt_date(b['class_date'])}",
            callback_data=f"user_move_{b['id']}"
        )]
        for b in bookings
    ]
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    await update.message.reply_text(
        "🔄 *Какую запись перенести?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel — Отменить запись"""
    user_id = update.effective_user.id
    bookings = [b for b in load_bookings() if b["user_id"] == user_id and b["status"] == "confirmed"]
    if not bookings:
        await update.message.reply_text(
            "У вас нет активных записей для отмены.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 Записаться на МК", callback_data="book")
            ]])
        )
        return
    keyboard = [
        [InlineKeyboardButton(
            f"❌ {b['class_title'][:35]} — {fmt_date(b['class_date'])}",
            callback_data=f"user_cancel_{b['id']}"
        )]
        for b in bookings
    ]
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    await update.message.reply_text(
        "❌ *Какую запись отменить?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════
def main():
    async def post_init(application: Application) -> None:
        """Устанавливает постоянное меню команд в Telegram"""
        await application.bot.set_my_commands([
            ("book",       "📅 Записаться на МК"),
            ("mybookings", "📋 Мои записи"),
            ("move",       "🔄 Перенести запись"),
            ("cancel",     "❌ Отменить запись"),
        ])

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    client_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_classes, pattern="^book$")],
        states={
            CHOOSE_CLASS: [
                CallbackQueryHandler(select_class,  pattern="^select_"),
                CallbackQueryHandler(ask_name,      pattern="^confirm_class$"),
                CallbackQueryHandler(show_classes,  pattern="^book$"),
            ],
            GET_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            CONFIRM:   [CallbackQueryHandler(final_confirm, pattern="^final_confirm$")],
        },
        fallbacks=[
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"),
            CommandHandler("cancel", cancel_conv),
        ],
    )

    welcome_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_welcome_start, pattern="^admin_welcome$")],
        states={EDIT_WELCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_welcome_save)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")],
        states={
            BROADCAST_TARGET: [CallbackQueryHandler(broadcast_target_chosen, pattern="^broadcast_")],
            BROADCAST_TEXT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    add_mc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_mc_start, pattern="^admin_add_mc$")],
        states={
            MC_TITLE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_title)],
            MC_DATE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_date)],
            MC_DURATION:   [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_duration)],
            MC_PRICE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_price)],
            MC_SPOTS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_spots)],
            MC_DESC:       [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_desc)],
            MC_VENUE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_venue_name)],
            MC_VENUE_URL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, mc_get_venue_url)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    edit_mc_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_mc, pattern="^admin_edit_mc_")],
        states={
            EDIT_MC_FIELD: [CallbackQueryHandler(edit_mc_field_chosen, pattern="^edit_field_")],
            EDIT_MC_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_mc_value_save)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("admin",      admin_panel_cmd))
    app.add_handler(CommandHandler("book",       cmd_book))
    app.add_handler(CommandHandler("mybookings", cmd_mybookings))
    app.add_handler(CommandHandler("move",       cmd_move))
    app.add_handler(CommandHandler("cancel",     cmd_cancel))
    app.add_handler(client_conv)
    app.add_handler(welcome_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(add_mc_conv)
    app.add_handler(edit_mc_conv)
    app.add_handler(CallbackQueryHandler(admin_panel,             pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_bookings,          pattern="^admin_bookings$"))
    app.add_handler(CallbackQueryHandler(admin_classes,           pattern="^admin_classes$"))
    app.add_handler(CallbackQueryHandler(admin_cancel_list,       pattern="^admin_cancel_list$"))
    app.add_handler(CallbackQueryHandler(do_cancel,               pattern="^do_cancel_"))
    app.add_handler(CallbackQueryHandler(admin_reschedule_list,   pattern="^admin_reschedule_list$"))
    app.add_handler(CallbackQueryHandler(reschedule_pick_booking, pattern="^reschedule_pick_"))
    app.add_handler(CallbackQueryHandler(reschedule_to_class,     pattern="^reschedule_to_"))
    app.add_handler(CallbackQueryHandler(admin_delete_mc,         pattern="^admin_delete_mc_"))
    app.add_handler(CallbackQueryHandler(confirm_delete_mc,       pattern="^confirm_delete_mc_"))
    app.add_handler(CallbackQueryHandler(my_bookings,             pattern="^my_bookings$"))
    app.add_handler(CallbackQueryHandler(help_callback,           pattern="^help$"))
    app.add_handler(CallbackQueryHandler(main_menu_callback,      pattern="^main_menu$"))
    # Подтверждение/перенос от пользователя
    app.add_handler(CallbackQueryHandler(attendance_confirm,       pattern="^attend_confirm_"))
    app.add_handler(CallbackQueryHandler(attendance_reschedule,    pattern="^attend_reschedule_"))
    app.add_handler(CallbackQueryHandler(attendance_cancel,        pattern="^attend_cancel_"))
    app.add_handler(CallbackQueryHandler(user_reschedule_confirm,  pattern="^user_reschedule_"))
    app.add_handler(CallbackQueryHandler(user_move_booking,        pattern="^user_move_"))
    app.add_handler(CallbackQueryHandler(user_cancel_booking,      pattern="^user_cancel_[0-9]+$"))
    app.add_handler(CallbackQueryHandler(user_cancel_confirm,      pattern="^user_cancel_confirm_"))

    # Напоминания каждые 30 минут
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, "interval", minutes=30, args=[app])
    scheduler.start()

    print("✅ Бот v3.1 запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
