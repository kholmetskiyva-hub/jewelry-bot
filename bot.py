"""
Telegram-бот для записи на мастер-классы по украшениям
Версия 4.0 — чистая архитектура без ConversationHandler
"""

import logging
import json
import os
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    BotCommandScopeDefault, BotCommandScopeChat
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ══════════════════════════════════════════
#  НАСТРОЙКИ
# ══════════════════════════════════════════
BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
MAIN_ADMIN_ID    = 334195585
CHANNEL_USERNAME = "@JJewelryNhaTrang"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════
#  ХРАНЕНИЕ ДАННЫХ (Railway Volume /app/data)
# ══════════════════════════════════════════
DATA_DIR = "/app/data"
try:
    os.makedirs(DATA_DIR, exist_ok=True)
    _t = os.path.join(DATA_DIR, ".test")
    open(_t, "w").close(); os.remove(_t)
except Exception:
    DATA_DIR = "/tmp/bot_data"
    os.makedirs(DATA_DIR, exist_ok=True)
    logger.warning("⚠️ /app/data недоступна — используется /tmp/bot_data (данные не сохранятся!)")

BOOKINGS_FILE = os.path.join(DATA_DIR, "bookings.json")
CLASSES_FILE  = os.path.join(DATA_DIR, "classes.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

DEFAULT_CLASSES = [
    {
        "id": 1,
        "title": "🌸 Цветочные серьги из полимерной глины",
        "date": "2026-07-10 12:00",
        "duration": "3 часа",
        "price": "2500 ₽",
        "spots": 8,
        "description": "Создадим нежные серьги с цветочным мотивом. Все материалы включены.",
        "venue_name": "Кафе Example",
        "venue_url": "https://maps.google.com/?q=Nha+Trang"
    }
]

DEFAULT_SETTINGS = {
    "welcome_message": (
        "👋 Добро пожаловать!\n\n"
        "Я помогу вам записаться на мастер-класс по созданию украшений 💎\n\n"
        "Выберите действие:"
    ),
    "new_user_greeting": "👋 Привет, {name}! Рада видеть тебя впервые!\n\n",
    "admins": [],
    "known_users": []
}

def safe_text(value, fallback="Выберите действие:"):
    """Telegram не принимает пустые сообщения."""
    if value is None:
        return fallback
    value = str(value)
    if not value.strip():
        return fallback
    return value


def _load(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    data = default() if callable(default) else default
    _save(path, data)
    return data

def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_classes():    return _load(CLASSES_FILE,  lambda: list(DEFAULT_CLASSES))
def save_classes(d):   _save(CLASSES_FILE, d)
def load_bookings():   return _load(BOOKINGS_FILE, [])
def save_bookings(d):  _save(BOOKINGS_FILE, d)
def load_settings():   return _load(SETTINGS_FILE, dict(DEFAULT_SETTINGS))
def save_settings(d):  _save(SETTINGS_FILE, d)

# ══════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════
def get_admins():
    return [MAIN_ADMIN_ID] + load_settings().get("admins", [])

def is_admin(uid: int) -> bool:
    return uid in get_admins()

def fmt_date(s: str) -> str:
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M").strftime("%d.%m.%Y в %H:%M")
    except Exception:
        return s

def free_spots(class_id: int) -> int:
    mc = next((m for m in load_classes() if m["id"] == class_id), None)
    if not mc:
        return 0
    taken = sum(1 for b in load_bookings()
                if b["class_id"] == class_id and b["status"] == "confirmed")
    return mc["spots"] - taken

def next_mc_id() -> int:
    classes = load_classes()
    return max((m["id"] for m in classes), default=0) + 1

def next_booking_id() -> int:
    bookings = load_bookings()
    return max((b["id"] for b in bookings), default=0) + 1

async def is_subscribed(bot, uid: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=uid)
        return m.status in ("member", "administrator", "creator")
    except Exception:
        return True  # не блокируем если канал недоступен

# ══════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════
def kb_main(uid: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📅 Записаться на МК",  callback_data="book")],
        [InlineKeyboardButton("📋 Мои записи",        callback_data="my_bookings")],
        [InlineKeyboardButton("❓ Помощь",             callback_data="help")],
    ]
    if is_admin(uid):
        rows.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)

def kb_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Все записи",          callback_data="adm:bookings")],
        [InlineKeyboardButton("📅 Расписание МК",       callback_data="adm:classes")],
        [InlineKeyboardButton("❌ Отменить запись",     callback_data="adm:cancel_list")],
        [InlineKeyboardButton("🔄 Перенести запись",    callback_data="adm:move_list")],
        [InlineKeyboardButton("📣 Рассылка",            callback_data="adm:broadcast")],
        [InlineKeyboardButton("✏️ Приветствие",         callback_data="adm:settings")],
        [InlineKeyboardButton("👤 Администраторы",      callback_data="adm:admins")],
        [InlineKeyboardButton("🏠 Главное меню",        callback_data="main_menu")],
    ])

def kb_back_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад в админ-панель", callback_data="admin_panel")]
    ])

def kb_back_main(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
    ])

# ══════════════════════════════════════════
#  СОСТОЯНИЯ (хранятся в context.user_data)
# ══════════════════════════════════════════
# user_data["state"] — текущее ожидаемое действие пользователя
# user_data["draft"] — временные данные при создании/редактировании

def set_state(context: ContextTypes.DEFAULT_TYPE, state: str | None):
    if state is None:
        context.user_data.pop("state", None)
    else:
        context.user_data["state"] = state

def get_state(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return context.user_data.get("state")

# ══════════════════════════════════════════
#  /start
# ══════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_state(context, None)
    uid  = update.effective_user.id
    name = update.effective_user.first_name or "друг"
    s    = load_settings()

    known = s.setdefault("known_users", [])
    welcome = safe_text(s.get("welcome_message"), DEFAULT_SETTINGS["welcome_message"])
    greeting_tpl = s.get("new_user_greeting", "")

    if uid not in known:
        known.append(uid)
        save_settings(s)
        greeting = greeting_tpl.replace("{name}", name) if greeting_tpl else ""
        text = safe_text(greeting + welcome, DEFAULT_SETTINGS["welcome_message"])
    else:
        text = safe_text(welcome, DEFAULT_SETTINGS["welcome_message"])

    await update.message.reply_text(text, reply_markup=kb_main(uid), parse_mode="Markdown")

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_state(context, None)
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    await update.message.reply_text(
        "⚙️ *Админ-панель*\n\nВыберите действие:",
        reply_markup=kb_admin(),
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════
#  ГЛАВНЫЙ ДИСПЕТЧЕР CALLBACK
# ══════════════════════════════════════════
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data
    uid  = q.from_user.id
    logger.info("🔘 CALLBACK from %s: %s", uid, data)
    await q.answer()

    # ── Главное меню ──────────────────────────────────────
    if data == "main_menu":
        set_state(context, None)
        s = load_settings()
        await q.edit_message_text(
            safe_text(s.get("welcome_message"), "Выберите действие:"),
            reply_markup=kb_main(uid),
            parse_mode="Markdown"
        )

    elif data == "admin_panel":
        if not is_admin(uid):
            await q.edit_message_text("⛔ Нет доступа.", reply_markup=kb_back_main(uid))
            return
        set_state(context, None)
        await q.edit_message_text(
            "⚙️ *Админ-панель*\n\nВыберите действие:",
            reply_markup=kb_admin(),
            parse_mode="Markdown"
        )

    # ── Помощь ────────────────────────────────────────────
    elif data == "help":
        await q.edit_message_text(
            "❓ *Помощь*\n\n"
            "• /start — главное меню\n"
            "• Записаться → выберите МК → введите имя и телефон\n"
            "• Мои записи → просмотр и отмена своих записей\n\n"
            "По вопросам пишите организатору.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")
            ]]),
            parse_mode="Markdown"
        )

    # ── Запись на МК ─────────────────────────────────────
    elif data == "book":
        await show_classes(q, context, uid)

    elif data.startswith("select_"):
        class_id = int(data.split("_", 1)[1])
        await show_class_detail(q, context, uid, class_id)

    elif data.startswith("confirm_class_"):
        class_id = int(data.split("_", 2)[2])
        mc = next((m for m in load_classes() if m["id"] == class_id), None)
        if not mc or free_spots(class_id) <= 0:
            await q.edit_message_text("😔 Мест уже нет. Выберите другой МК.",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("📅 К списку МК", callback_data="book")
                                      ]]))
            return
        context.user_data["draft"] = {"class_id": class_id, "class_title": mc["title"],
                                       "class_date": mc["date"]}
        set_state(context, "booking_name")
        await q.edit_message_text(
            "✏️ Введите ваше *имя:*",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="book")
            ]]),
            parse_mode="Markdown"
        )

    # ── Мои записи ───────────────────────────────────────
    elif data == "my_bookings":
        await show_my_bookings(q, context, uid)

    elif data.startswith("user_cancel_confirm_"):
        bid = int(data.split("_", 3)[3])
        await user_cancel_booking(q, context, uid, bid)

    elif data.startswith("user_cancel_ask_"):
        bid = int(data.split("_", 3)[3])
        b = next((x for x in load_bookings() if x["id"] == bid and x["user_id"] == uid), None)
        if not b:
            await q.edit_message_text("Запись не найдена.", reply_markup=kb_back_main(uid))
            return
        await q.edit_message_text(
            f"❓ Отменить запись на *{b['class_title']}* ({fmt_date(b['class_date'])})?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, отменить", callback_data=f"user_cancel_confirm_{bid}")],
                [InlineKeyboardButton("◀️ Назад",        callback_data="my_bookings")],
            ]),
            parse_mode="Markdown"
        )

    # ── Посещение (из напоминаний) ────────────────────────
    elif data.startswith("attend_yes_"):
        bid = int(data.split("_", 2)[2])
        bookings = load_bookings()
        for b in bookings:
            if b["id"] == bid:
                b["confirmed_attendance"] = True
                break
        save_bookings(bookings)
        await q.edit_message_text("✅ Отлично! Ждём вас на мастер-классе!")

    elif data.startswith("attend_no_"):
        bid = int(data.split("_", 2)[2])
        await q.edit_message_text(
            "Жаль! Хотите перенести или отменить запись?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Перенести", callback_data=f"user_move_from_{bid}")],
                [InlineKeyboardButton("❌ Отменить",  callback_data=f"user_cancel_ask_{bid}")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ])
        )

    elif data.startswith("user_move_from_"):
        bid = int(data.split("_", 3)[3])
        await show_classes_for_move(q, context, uid, bid)

    elif data.startswith("user_move_to_"):
        parts = data.split("_", 3)  # user_move_to_BOOKINGID_CLASSID
        _, _, _, rest = data.split("_", 3)
        b_id, c_id = map(int, rest.split("_"))
        await user_move_booking(q, context, uid, b_id, c_id)

    # ── АДМИН-ПАНЕЛЬ ─────────────────────────────────────
    elif data.startswith("adm:"):
        if not is_admin(uid):
            await q.edit_message_text("⛔ Нет доступа.", reply_markup=kb_back_main(uid))
            return
        cmd = data[4:]
        await dispatch_admin(q, context, uid, cmd)

    else:
        logger.warning(f"Unhandled callback: {data!r}")

# ══════════════════════════════════════════
#  КЛИЕНТСКИЙ ПОТОК: ЗАПИСАТЬСЯ
# ══════════════════════════════════════════
async def show_classes(q, context, uid):
    if not await is_subscribed(context.bot, uid):
        await q.edit_message_text(
            "🔒 *Доступ только для подписчиков*\n\n"
            f"Подпишитесь на {CHANNEL_USERNAME} и нажмите «Я подписался».",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Подписаться", url=f"https://t.me/JJewelryNhaTrang")],
                [InlineKeyboardButton("✅ Я подписался", callback_data="book")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ]),
            parse_mode="Markdown"
        )
        return

    classes = load_classes()
    rows = []
    text = "📅 *Доступные мастер-классы:*\n\n"
    found = False
    for mc in classes:
        try:
            dt = datetime.strptime(mc["date"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if dt < datetime.now():
            continue
        spots = free_spots(mc["id"])
        if spots <= 0:
            continue
        found = True
        venue = mc.get("venue_name", "")
        text += (
            f"*{mc['title']}*\n"
            f"📆 {fmt_date(mc['date'])}"
            + (f"  📍 {venue}" if venue else "") + "\n"
            f"⏱ {mc['duration']}  💰 {mc['price']}  ✅ мест: {spots}\n\n"
        )
        rows.append([InlineKeyboardButton(mc["title"][:40], callback_data=f"select_{mc['id']}")])

    if not found:
        text = "😔 Пока нет доступных МК. Следите за обновлениями!"
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])

    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def show_class_detail(q, context, uid, class_id):
    mc = next((m for m in load_classes() if m["id"] == class_id), None)
    if not mc:
        await q.edit_message_text("МК не найден.", reply_markup=kb_back_main(uid))
        return
    spots = free_spots(class_id)
    if spots <= 0:
        await q.edit_message_text(
            f"😔 На *{mc['title']}* мест нет.\n\nВыберите другой МК.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📅 К списку МК", callback_data="book")
            ]]),
            parse_mode="Markdown"
        )
        return

    venue_name = mc.get("venue_name", "")
    venue_url  = mc.get("venue_url", "")
    venue_line = ""
    if venue_name and venue_url:
        venue_line = f"📍 [{venue_name}]({venue_url})\n"
    elif venue_name:
        venue_line = f"📍 {venue_name}\n"

    text = (
        f"*{mc['title']}*\n\n"
        f"📆 {fmt_date(mc['date'])}\n"
        f"{venue_line}"
        f"⏱ {mc['duration']}\n"
        f"💰 {mc['price']}\n"
        f"✅ Свободных мест: {spots}\n\n"
        f"ℹ️ {mc['description']}"
    )
    rows = [
        [InlineKeyboardButton(f"✅ Записаться ({spots} мест)", callback_data=f"confirm_class_{class_id}")],
        [InlineKeyboardButton("◀️ Назад к списку",             callback_data="book")],
        [InlineKeyboardButton("🏠 Главное меню",               callback_data="main_menu")],
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def show_my_bookings(q, context, uid):
    bookings = [b for b in load_bookings()
                if b["user_id"] == uid and b["status"] == "confirmed"]
    if not bookings:
        await q.edit_message_text(
            "📋 У вас нет активных записей.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Записаться на МК", callback_data="book")],
                [InlineKeyboardButton("🏠 Главное меню",     callback_data="main_menu")],
            ])
        )
        return

    text = "📋 *Ваши записи:*\n\n"
    rows = []
    for b in bookings:
        text += f"• *{b['class_title']}*\n  📆 {fmt_date(b['class_date'])}\n\n"
        rows.append([InlineKeyboardButton(
            f"❌ Отменить: {b['class_title'][:25]}", callback_data=f"user_cancel_ask_{b['id']}"
        )])
    rows.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

async def user_cancel_booking(q, context, uid, bid):
    bookings = load_bookings()
    b = next((x for x in bookings if x["id"] == bid and x["user_id"] == uid), None)
    if not b:
        await q.edit_message_text("Запись не найдена.", reply_markup=kb_back_main(uid))
        return
    b["status"] = "cancelled"
    save_bookings(bookings)
    # Уведомляем главного админа
    try:
        await q.get_bot().send_message(
            MAIN_ADMIN_ID,
            f"❌ Клиент отменил запись\n\n"
            f"👤 {b['name']} ({b.get('contact','')})\n"
            f"🎨 {b['class_title']}\n"
            f"📆 {fmt_date(b['class_date'])}"
        )
    except Exception:
        pass
    await q.edit_message_text(
        f"✅ Запись на *{b['class_title']}* отменена.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Записаться на МК", callback_data="book")],
            [InlineKeyboardButton("🏠 Главное меню",     callback_data="main_menu")],
        ]),
        parse_mode="Markdown"
    )

async def show_classes_for_move(q, context, uid, booking_id):
    classes = load_classes()
    rows = []
    for mc in classes:
        try:
            dt = datetime.strptime(mc["date"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if dt < datetime.now():
            continue
        spots = free_spots(mc["id"])
        if spots <= 0:
            continue
        rows.append([InlineKeyboardButton(
            f"{mc['title'][:30]} — {fmt_date(mc['date'])}",
            callback_data=f"user_move_to_{booking_id}_{mc['id']}"
        )])
    if not rows:
        await q.edit_message_text("😔 Нет доступных МК для переноса.",
                                  reply_markup=kb_back_main(uid))
        return
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="my_bookings")])
    await q.edit_message_text(
        "🔄 Выберите МК, на который перенести запись:",
        reply_markup=InlineKeyboardMarkup(rows)
    )

async def user_move_booking(q, context, uid, booking_id, new_class_id):
    bookings = load_bookings()
    b = next((x for x in bookings if x["id"] == booking_id and x["user_id"] == uid), None)
    mc = next((m for m in load_classes() if m["id"] == new_class_id), None)
    if not b or not mc or free_spots(new_class_id) <= 0:
        await q.edit_message_text("Ошибка. Попробуйте снова.", reply_markup=kb_back_main(uid))
        return
    b["class_id"]    = new_class_id
    b["class_title"] = mc["title"]
    b["class_date"]  = mc["date"]
    b["confirmed_attendance"] = False
    save_bookings(bookings)
    try:
        await q.get_bot().send_message(
            MAIN_ADMIN_ID,
            f"🔄 Клиент перенёс запись\n\n"
            f"👤 {b['name']} ({b.get('contact','')})\n"
            f"🎨 Новый МК: {mc['title']}\n"
            f"📆 {fmt_date(mc['date'])}"
        )
    except Exception:
        pass
    await q.edit_message_text(
        f"✅ Запись перенесена на *{mc['title']}*\n📆 {fmt_date(mc['date'])}",
        reply_markup=kb_back_main(uid),
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════
#  ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ
# ══════════════════════════════════════════
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = get_state(context)
    uid   = update.effective_user.id
    text  = update.message.text.strip()
    logger.info("💬 TEXT from %s | state=%s | text=%r", uid, state, text)

    if state == "booking_name":
        context.user_data["draft"]["name"] = text
        set_state(context, "booking_phone")
        await update.message.reply_text(
            "📱 Введите ваш *номер телефона:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="book")
            ]])
        )

    elif state == "booking_phone":
        draft = context.user_data.get("draft", {})
        draft["phone"] = text
        name     = draft.get("name", "")
        class_id = draft.get("class_id")
        mc_title = draft.get("class_title", "")
        mc_date  = draft.get("class_date", "")
        username = update.effective_user.username
        contact  = f"@{username}" if username else f"ID {uid}"

        # Проверяем ещё раз
        if not class_id or free_spots(class_id) <= 0:
            set_state(context, None)
            await update.message.reply_text(
                "😔 К сожалению, места закончились. Выберите другой МК.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📅 К списку МК", callback_data="book")
                ]])
            )
            return

        booking = {
            "id":         next_booking_id(),
            "user_id":    uid,
            "name":       name,
            "phone":      text,
            "contact":    contact,
            "class_id":   class_id,
            "class_title": mc_title,
            "class_date": mc_date,
            "status":     "confirmed",
            "confirmed_attendance": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        bookings = load_bookings()
        bookings.append(booking)
        save_bookings(bookings)
        set_state(context, None)
        context.user_data.pop("draft", None)

        # Уведомление администратора
        try:
            await context.bot.send_message(
                MAIN_ADMIN_ID,
                f"🎉 *Новая запись #{booking['id']}*\n\n"
                f"👤 {name} ({contact})\n"
                f"📱 {text}\n"
                f"🎨 {mc_title}\n"
                f"📆 {fmt_date(mc_date)}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        await update.message.reply_text(
            f"✅ *Запись подтверждена!*\n\n"
            f"🎨 {mc_title}\n"
            f"📆 {fmt_date(mc_date)}\n\n"
            f"Ждём вас! По вопросам пишите организатору.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Мои записи",  callback_data="my_bookings")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")],
            ])
        )

    # ── Состояния admin-wizard ──────────────────────────
    elif state and state.startswith("adm_"):
        await admin_wizard_step(update, context, uid, state, text)

    else:
        # Нет активного состояния — показываем меню
        s = load_settings()
        await update.message.reply_text(
            safe_text(s.get("welcome_message"), "Выберите действие:"),
            reply_markup=kb_main(uid),
            parse_mode="Markdown"
        )

# ══════════════════════════════════════════
#  АДМИН-ПАНЕЛЬ: ДИСПЕТЧЕР
# ══════════════════════════════════════════
async def dispatch_admin(q, context, uid, cmd):
    # ── Все записи ────────────────────────────────────────
    if cmd == "bookings":
        bookings = [b for b in load_bookings() if b["status"] == "confirmed"]
        if not bookings:
            await q.edit_message_text("Нет активных записей.", reply_markup=kb_back_admin())
            return
        text = "📋 *Все активные записи:*\n\n"
        for b in bookings:
            text += (
                f"#{b['id']} *{b['name']}* | {b.get('phone','—')}\n"
                f"   🎨 {b['class_title']}\n"
                f"   📆 {fmt_date(b['class_date'])}\n\n"
            )
            if len(text) > 3800:
                text += "_(показаны не все)_"
                break
        await q.edit_message_text(text, reply_markup=kb_back_admin(), parse_mode="Markdown")

    # ── Расписание МК ────────────────────────────────────
    elif cmd == "classes":
        await admin_show_classes(q, context, uid)

    elif cmd.startswith("class_edit_"):
        class_id = int(cmd.split("_", 2)[2])
        await admin_class_menu(q, context, uid, class_id)

    elif cmd.startswith("class_delete_confirm_"):
        class_id = int(cmd.split("_", 3)[3])
        await q.edit_message_text(
            "❓ Удалить этот МК? Все записи на него останутся в базе.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"adm:class_delete_{class_id}")],
                [InlineKeyboardButton("◀️ Назад",       callback_data=f"adm:class_edit_{class_id}")],
            ])
        )

    elif cmd.startswith("class_delete_"):
        class_id = int(cmd.split("_", 2)[2])
        classes = [m for m in load_classes() if m["id"] != class_id]
        save_classes(classes)
        await q.edit_message_text("✅ МК удалён.", reply_markup=kb_back_admin())

    elif cmd == "add_mc":
        context.user_data["draft"] = {}
        set_state(context, "adm_mc_title")
        await q.edit_message_text(
            "➕ *Новый МК — шаг 1/8*\n\nВведите *название:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="adm:classes")
            ]])
        )

    elif cmd.startswith("edit_field_"):
        # edit_field_CLASSID_FIELDNAME
        parts = cmd.split("_", 3)
        class_id = int(parts[2])
        field    = parts[3]
        context.user_data["draft"] = {"edit_class_id": class_id, "edit_field": field}
        labels = {
            "title": "название", "date": "дату (ГГГГ-ММ-ДД ЧЧ:ММ)", "duration": "длительность",
            "price": "стоимость", "spots": "число мест (число)", "description": "описание",
            "venue_name": "название площадки", "venue_url": "ссылку на карту",
        }
        set_state(context, "adm_edit_value")
        await q.edit_message_text(
            f"✏️ Введите новое *{labels.get(field, field)}:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data=f"adm:class_edit_{class_id}")
            ]])
        )

    # ── Отмена записи (adminом) ───────────────────────────
    elif cmd == "cancel_list":
        bookings = [b for b in load_bookings() if b["status"] == "confirmed"]
        if not bookings:
            await q.edit_message_text("Нет записей для отмены.", reply_markup=kb_back_admin())
            return
        rows = [[InlineKeyboardButton(
            f"#{b['id']} {b['name']} — {b['class_title'][:20]}",
            callback_data=f"adm:cancel_ask_{b['id']}"
        )] for b in bookings]
        rows.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
        await q.edit_message_text("❌ Выберите запись для отмены:",
                                  reply_markup=InlineKeyboardMarkup(rows))

    elif cmd.startswith("cancel_ask_"):
        bid = int(cmd.split("_", 2)[2])
        b = next((x for x in load_bookings() if x["id"] == bid), None)
        if not b:
            await q.edit_message_text("Запись не найдена.", reply_markup=kb_back_admin())
            return
        await q.edit_message_text(
            f"❓ Отменить запись #{bid}?\n\n"
            f"👤 {b['name']} | 🎨 {b['class_title']}\n"
            f"📆 {fmt_date(b['class_date'])}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, отменить", callback_data=f"adm:cancel_do_{bid}")],
                [InlineKeyboardButton("◀️ Назад",        callback_data="adm:cancel_list")],
            ])
        )

    elif cmd.startswith("cancel_do_"):
        bid = int(cmd.split("_", 2)[2])
        bookings = load_bookings()
        b = next((x for x in bookings if x["id"] == bid), None)
        if not b:
            await q.edit_message_text("Запись не найдена.", reply_markup=kb_back_admin())
            return
        b["status"] = "cancelled"
        save_bookings(bookings)
        try:
            await q.get_bot().send_message(
                b["user_id"],
                f"❌ *Ваша запись отменена организатором*\n\n"
                f"🎨 {b['class_title']}\n"
                f"📆 {fmt_date(b['class_date'])}\n\n"
                "По вопросам свяжитесь с организатором.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await q.edit_message_text(
            f"✅ Запись #{bid} отменена. Клиент уведомлён.",
            reply_markup=kb_back_admin()
        )

    # ── Перенос записи (admin) ────────────────────────────
    elif cmd == "move_list":
        bookings = [b for b in load_bookings() if b["status"] == "confirmed"]
        if not bookings:
            await q.edit_message_text("Нет записей.", reply_markup=kb_back_admin())
            return
        rows = [[InlineKeyboardButton(
            f"#{b['id']} {b['name']} — {b['class_title'][:20]}",
            callback_data=f"adm:move_pick_{b['id']}"
        )] for b in bookings]
        rows.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
        await q.edit_message_text("🔄 Выберите запись для переноса:",
                                  reply_markup=InlineKeyboardMarkup(rows))

    elif cmd.startswith("move_pick_"):
        bid = int(cmd.split("_", 2)[2])
        classes = load_classes()
        rows = []
        for mc in classes:
            try:
                dt = datetime.strptime(mc["date"], "%Y-%m-%d %H:%M")
            except Exception:
                continue
            if dt < datetime.now() or free_spots(mc["id"]) <= 0:
                continue
            rows.append([InlineKeyboardButton(
                f"{mc['title'][:25]} — {fmt_date(mc['date'])}",
                callback_data=f"adm:move_do_{bid}_{mc['id']}"
            )])
        if not rows:
            await q.edit_message_text("Нет доступных МК.", reply_markup=kb_back_admin())
            return
        rows.append([InlineKeyboardButton("◀️ Назад", callback_data="adm:move_list")])
        await q.edit_message_text("Выберите МК для переноса:",
                                  reply_markup=InlineKeyboardMarkup(rows))

    elif cmd.startswith("move_do_"):
        _, _, bid_s, cid_s = cmd.split("_", 3)
        bid, cid = int(bid_s), int(cid_s)
        bookings = load_bookings()
        b  = next((x for x in bookings if x["id"] == bid), None)
        mc = next((m for m in load_classes() if m["id"] == cid), None)
        if not b or not mc:
            await q.edit_message_text("Ошибка.", reply_markup=kb_back_admin())
            return
        b["class_id"]    = cid
        b["class_title"] = mc["title"]
        b["class_date"]  = mc["date"]
        b["confirmed_attendance"] = False
        save_bookings(bookings)
        try:
            await q.get_bot().send_message(
                b["user_id"],
                f"🔄 *Ваша запись перенесена*\n\n"
                f"🎨 {mc['title']}\n"
                f"📆 {fmt_date(mc['date'])}",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await q.edit_message_text(
            f"✅ Запись #{bid} перенесена на {mc['title']}.",
            reply_markup=kb_back_admin()
        )

    # ── Рассылка ─────────────────────────────────────────
    elif cmd == "broadcast":
        context.user_data["draft"] = {"broadcast_target": "all"}
        set_state(context, "adm_broadcast_text")
        await q.edit_message_text(
            "📣 *Рассылка всем пользователям*\n\nВведите текст сообщения:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="admin_panel")
            ]])
        )

    # ── Настройки (приветствие) ───────────────────────────
    elif cmd == "settings":
        s = load_settings()
        await q.edit_message_text(
            f"✏️ *Настройки приветствия*\n\n"
            f"*Текущее приветствие:*\n{safe_text(s.get("welcome_message"), DEFAULT_SETTINGS["welcome_message"])}\n\n"
            f"*Для новых пользователей:*\n{s.get('new_user_greeting','')}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Изменить приветствие", callback_data="adm:edit_welcome")],
                [InlineKeyboardButton("✏️ Для новых пользователей", callback_data="adm:edit_greeting")],
                [InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")],
            ]),
            parse_mode="Markdown"
        )

    elif cmd == "edit_welcome":
        set_state(context, "adm_edit_welcome")
        await q.edit_message_text(
            "✏️ Введите новое *главное приветствие:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="adm:settings")
            ]])
        )

    elif cmd == "edit_greeting":
        set_state(context, "adm_edit_greeting")
        await q.edit_message_text(
            "✏️ Введите приветствие для *новых пользователей*\n"
            "(используйте {name} для имени):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="adm:settings")
            ]])
        )

    # ── Администраторы ────────────────────────────────────
    elif cmd == "admins":
        await admin_show_admins(q, context, uid)

    elif cmd == "add_admin":
        set_state(context, "adm_add_admin")
        await q.edit_message_text(
            "👤 Введите Telegram ID нового администратора\n"
            "(число, например: 123456789):",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="adm:admins")
            ]])
        )

    elif cmd.startswith("remove_admin_"):
        admin_id = int(cmd.split("_", 2)[2])
        if admin_id == MAIN_ADMIN_ID:
            await q.edit_message_text("⛔ Нельзя удалить главного администратора.",
                                      reply_markup=kb_back_admin())
            return
        s = load_settings()
        s["admins"] = [a for a in s.get("admins", []) if a != admin_id]
        save_settings(s)
        await q.edit_message_text(
            f"✅ Администратор {admin_id} удалён.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ К администраторам", callback_data="adm:admins")
            ]])
        )

    else:
        logger.warning(f"Unknown admin command: {cmd!r}")
        await q.edit_message_text("Неизвестная команда.", reply_markup=kb_back_admin())

# ══════════════════════════════════════════
#  ADMIN: Расписание МК
# ══════════════════════════════════════════
async def admin_show_classes(q, context, uid):
    classes = load_classes()
    if not classes:
        await q.edit_message_text(
            "Нет мастер-классов.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить МК", callback_data="adm:add_mc")],
                [InlineKeyboardButton("◀️ Назад",       callback_data="admin_panel")],
            ])
        )
        return
    rows = []
    for mc in classes:
        spots = free_spots(mc["id"])
        rows.append([InlineKeyboardButton(
            f"{mc['title'][:30]} | {fmt_date(mc['date'])} | мест:{spots}",
            callback_data=f"adm:class_edit_{mc['id']}"
        )])
    rows.append([InlineKeyboardButton("➕ Добавить МК", callback_data="adm:add_mc")])
    rows.append([InlineKeyboardButton("◀️ Назад",       callback_data="admin_panel")])
    await q.edit_message_text("📅 *Расписание МК:*", reply_markup=InlineKeyboardMarkup(rows),
                              parse_mode="Markdown")

async def admin_class_menu(q, context, uid, class_id):
    mc = next((m for m in load_classes() if m["id"] == class_id), None)
    if not mc:
        await q.edit_message_text("МК не найден.", reply_markup=kb_back_admin())
        return
    spots = free_spots(class_id)
    text = (
        f"📅 *{mc['title']}*\n\n"
        f"📆 {fmt_date(mc['date'])}\n"
        f"⏱ {mc['duration']}  💰 {mc['price']}\n"
        f"✅ Мест: {mc['spots']} (свободно: {spots})\n"
        f"📍 {mc.get('venue_name','—')}\n\n"
        f"ℹ️ {mc['description']}"
    )
    fields = [
        ("Название",  "title"), ("Дата",      "date"),
        ("Длит-сть",  "duration"), ("Цена",   "price"),
        ("Мест всего","spots"), ("Описание",   "description"),
        ("Площадка",  "venue_name"), ("Карта", "venue_url"),
    ]
    rows = [[InlineKeyboardButton(
        f"✏️ {label}", callback_data=f"adm:edit_field_{class_id}_{key}"
    )] for label, key in fields]
    rows.append([InlineKeyboardButton("🗑 Удалить МК",
                                      callback_data=f"adm:class_delete_confirm_{class_id}")])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="adm:classes")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

# ══════════════════════════════════════════
#  ADMIN: Список администраторов
# ══════════════════════════════════════════
async def admin_show_admins(q, context, uid):
    s      = load_settings()
    admins = [MAIN_ADMIN_ID] + s.get("admins", [])
    text   = "👤 *Администраторы:*\n\n"
    rows   = []
    for a in admins:
        label = f"{'★ ' if a == MAIN_ADMIN_ID else ''}ID: {a}"
        text += f"• {label}\n"
        if a != MAIN_ADMIN_ID:
            rows.append([InlineKeyboardButton(
                f"❌ Удалить {a}", callback_data=f"adm:remove_admin_{a}"
            )])
    rows.append([InlineKeyboardButton("➕ Добавить администратора", callback_data="adm:add_admin")])
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="admin_panel")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")

# ══════════════════════════════════════════
#  ADMIN WIZARD: ввод текста
# ══════════════════════════════════════════
MC_STEPS = [
    ("adm_mc_title",      "название",          "title",      None),
    ("adm_mc_date",       "дату (ГГГГ-ММ-ДД ЧЧ:ММ)", "date", "adm_mc_title"),
    ("adm_mc_duration",   "длительность",      "duration",   "adm_mc_date"),
    ("adm_mc_price",      "стоимость",         "price",      "adm_mc_duration"),
    ("adm_mc_spots",      "число мест",        "spots",      "adm_mc_price"),
    ("adm_mc_desc",       "описание",          "description","adm_mc_spots"),
    ("adm_mc_venue_name", "название площадки", "venue_name", "adm_mc_desc"),
    ("adm_mc_venue_url",  "ссылку на карту",   "venue_url",  "adm_mc_venue_name"),
]
MC_STATE_KEYS = {s: (label, key, prev) for s, label, key, prev in MC_STEPS}
MC_STATES     = [s for s, *_ in MC_STEPS]

async def admin_wizard_step(update, context, uid, state, text):
    # ── Добавление МК ─────────────────────────────────────
    if state in MC_STATE_KEYS:
        label, key, prev = MC_STATE_KEYS[state]
        draft = context.user_data.setdefault("draft", {})

        # Валидация spots
        if key == "spots":
            if not text.isdigit():
                await update.message.reply_text(
                    "⚠️ Введите число мест (только цифры):",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Отмена", callback_data="adm:classes")
                    ]])
                )
                return
            draft[key] = int(text)
        else:
            draft[key] = text

        idx = MC_STATES.index(state)
        if idx + 1 < len(MC_STEPS):
            next_state, next_label, *_ = MC_STEPS[idx + 1]
            set_state(context, next_state)
            step = idx + 2
            await update.message.reply_text(
                f"➕ *Новый МК — шаг {step}/{len(MC_STEPS)}*\n\nВведите *{next_label}:*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data="adm:classes")
                ]])
            )
        else:
            # Все поля собраны — сохраняем
            classes = load_classes()
            new_mc = {
                "id":          next_mc_id(),
                "title":       draft.get("title", ""),
                "date":        draft.get("date", ""),
                "duration":    draft.get("duration", ""),
                "price":       draft.get("price", ""),
                "spots":       draft.get("spots", 0),
                "description": draft.get("description", ""),
                "venue_name":  draft.get("venue_name", ""),
                "venue_url":   draft.get("venue_url", ""),
            }
            classes.append(new_mc)
            save_classes(classes)
            set_state(context, None)
            context.user_data.pop("draft", None)
            await update.message.reply_text(
                f"✅ *МК добавлен!*\n\n"
                f"*{new_mc['title']}*\n"
                f"📆 {fmt_date(new_mc['date'])}\n"
                f"💰 {new_mc['price']}  ✅ мест: {new_mc['spots']}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📅 Расписание МК", callback_data="adm:classes")],
                    [InlineKeyboardButton("◀️ Админ-панель",  callback_data="admin_panel")],
                ])
            )

    # ── Редактирование поля МК ────────────────────────────
    elif state == "adm_edit_value":
        draft    = context.user_data.get("draft", {})
        class_id = draft.get("edit_class_id")
        field    = draft.get("edit_field")
        classes  = load_classes()
        mc = next((m for m in classes if m["id"] == class_id), None)
        if not mc:
            set_state(context, None)
            await update.message.reply_text("МК не найден.", reply_markup=kb_back_main(uid))
            return
        if field == "spots":
            if not text.isdigit():
                await update.message.reply_text("Введите число:", reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data=f"adm:class_edit_{class_id}")
                ]]))
                return
            mc[field] = int(text)
        else:
            mc[field] = text
        save_classes(classes)
        set_state(context, None)
        context.user_data.pop("draft", None)
        await update.message.reply_text(
            f"✅ Поле обновлено.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 К МК", callback_data=f"adm:class_edit_{class_id}")],
                [InlineKeyboardButton("◀️ Расписание",   callback_data="adm:classes")],
            ])
        )

    # ── Рассылка ──────────────────────────────────────────
    elif state == "adm_broadcast_text":
        s       = load_settings()
        users   = s.get("known_users", [])
        ok, fail = 0, 0
        for user_id in users:
            try:
                await context.bot.send_message(user_id, text, parse_mode="Markdown")
                ok += 1
            except Exception:
                fail += 1
        set_state(context, None)
        await update.message.reply_text(
            f"✅ Рассылка завершена: {ok} доставлено, {fail} ошибок.",
            reply_markup=kb_back_admin()
        )

    # ── Приветствие ───────────────────────────────────────
    elif state == "adm_edit_welcome":
        s = load_settings()
        s["welcome_message"] = text
        save_settings(s)
        set_state(context, None)
        await update.message.reply_text(
            "✅ Главное приветствие обновлено.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Настройки", callback_data="adm:settings")
            ]])
        )

    elif state == "adm_edit_greeting":
        s = load_settings()
        s["new_user_greeting"] = text
        save_settings(s)
        set_state(context, None)
        await update.message.reply_text(
            "✅ Приветствие для новых пользователей обновлено.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Настройки", callback_data="adm:settings")
            ]])
        )

    # ── Добавить администратора ───────────────────────────
    elif state == "adm_add_admin":
        if not text.lstrip("-").isdigit():
            await update.message.reply_text(
                "⚠️ Введите корректный Telegram ID (только цифры):",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Отмена", callback_data="adm:admins")
                ]])
            )
            return
        new_id = int(text)
        s = load_settings()
        if new_id not in s.get("admins", []) and new_id != MAIN_ADMIN_ID:
            s.setdefault("admins", []).append(new_id)
            save_settings(s)
        set_state(context, None)
        await update.message.reply_text(
            f"✅ Администратор {new_id} добавлен.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Администраторы", callback_data="adm:admins")
            ]])
        )

    else:
        set_state(context, None)
        await update.message.reply_text("Неизвестное состояние. Начните заново.",
                                        reply_markup=kb_main(uid))

# ══════════════════════════════════════════
#  НАПОМИНАНИЯ
# ══════════════════════════════════════════
async def send_reminders(app):
    now     = datetime.now()
    bookings = [b for b in load_bookings() if b["status"] == "confirmed"]
    for b in bookings:
        try:
            dt = datetime.strptime(b["class_date"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        diff = (dt - now).total_seconds() / 3600
        bid  = b["id"]

        # За 24 часа
        if 23.5 <= diff <= 24.5 and not b.get("reminded_24"):
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Приду",        callback_data=f"attend_yes_{bid}")],
                [InlineKeyboardButton("🔄 Перенести",   callback_data=f"user_move_from_{bid}")],
                [InlineKeyboardButton("❌ Отменить",    callback_data=f"user_cancel_ask_{bid}")],
            ])
            try:
                await app.bot.send_message(
                    b["user_id"],
                    f"⏰ *Напоминание — завтра мастер-класс!*\n\n"
                    f"🎨 {b['class_title']}\n"
                    f"📆 {fmt_date(b['class_date'])}\n\n"
                    "Вы придёте?",
                    parse_mode="Markdown",
                    reply_markup=kb
                )
                b["reminded_24"] = True
            except Exception as e:
                logger.error(f"Reminder 24h error {bid}: {e}")

        # За 1 час
        if 0.5 <= diff <= 1.5 and not b.get("reminded_1"):
            try:
                await app.bot.send_message(
                    b["user_id"],
                    f"⏰ *Через час начинается мастер-класс!*\n\n"
                    f"🎨 {b['class_title']}\n"
                    f"📆 {fmt_date(b['class_date'])}\n\n"
                    "До встречи! 🎉",
                    parse_mode="Markdown"
                )
                b["reminded_1"] = True
            except Exception as e:
                logger.error(f"Reminder 1h error {bid}: {e}")

    # Сохраняем флаги напоминаний
    all_bookings = load_bookings()
    reminded_map = {b["id"]: b for b in bookings}
    for b in all_bookings:
        if b["id"] in reminded_map:
            b.update({
                "reminded_24": reminded_map[b["id"]].get("reminded_24", b.get("reminded_24")),
                "reminded_1":  reminded_map[b["id"]].get("reminded_1",  b.get("reminded_1")),
            })
    save_bookings(all_bookings)

# ══════════════════════════════════════════
#  ERROR HANDLER
# ══════════════════════════════════════════
async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}", exc_info=context.error)

# ══════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в переменных Railway")

    async def post_init(app: Application):
        user_cmds = [
            ("start",       "🏠 Главное меню"),
        ]
        admin_cmds = user_cmds + [("admin", "⚙️ Админ-панель")]
        await app.bot.set_my_commands(user_cmds, scope=BotCommandScopeDefault())
        for aid in get_admins():
            try:
                await app.bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=aid))
            except Exception:
                pass

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_error_handler(on_error)

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))

    # Один глобальный обработчик всех callback
    app.add_handler(CallbackQueryHandler(on_callback))

    # Один глобальный обработчик текстовых сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    # Напоминания каждые 30 минут
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, "interval", minutes=30, args=[app])
    scheduler.start()

    logger.info("✅ Бот v4.0 запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
