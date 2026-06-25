"""
JJewelry Bot — рабочая версия на обычных текстовых кнопках.
Причина: inline-кнопки в Telegram не доходили до бота как callback.
Эта версия не зависит от callback для основного меню.
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", os.getenv("ADMIN_IDS", "334195585").split(",")[0]))
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@JJewelryNhaTrang")

DATA_DIR = Path("/app/data")
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    test = DATA_DIR / ".test"
    test.write_text("ok", encoding="utf-8")
    test.unlink()
except Exception:
    DATA_DIR = Path("/tmp/bot_data")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

BOOKINGS_FILE = DATA_DIR / "bookings.json"
CLASSES_FILE = DATA_DIR / "classes.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "welcome_message": "👋 Добро пожаловать!\n\nЯ помогу записаться на мастер-класс по украшениям 💎",
    "admins": [],
    "known_users": [],
}

DEFAULT_CLASSES = [
    {
        "id": 1,
        "title": "🌸 Цветочные серьги из полимерной глины",
        "date": "2026-07-10 12:00",
        "duration": "3 часа",
        "price": "2500 ₽",
        "spots": 8,
        "description": "Создадим нежные серьги. Все материалы включены.",
        "venue_name": "Кафе Example",
        "venue_url": "https://maps.google.com/?q=Nha+Trang",
    }
]


def safe_text(value, fallback="Выберите действие:"):
    if value is None:
        return fallback
    value = str(value)
    return value if value.strip() else fallback


def load_json(path: Path, default):
    if not path.exists():
        save_json(path, default)
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.exception("JSON load error %s: %s", path, e)
        save_json(path, default)
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_settings():
    return load_json(SETTINGS_FILE, dict(DEFAULT_SETTINGS))


def save_settings(data):
    save_json(SETTINGS_FILE, data)


def load_classes():
    return load_json(CLASSES_FILE, list(DEFAULT_CLASSES))


def save_classes(data):
    save_json(CLASSES_FILE, data)


def load_bookings():
    return load_json(BOOKINGS_FILE, [])


def save_bookings(data):
    save_json(BOOKINGS_FILE, data)


def get_admins():
    s = load_settings()
    return [MAIN_ADMIN_ID] + [int(x) for x in s.get("admins", []) if str(x).isdigit()]


def is_admin(uid: int) -> bool:
    return uid in get_admins()


def fmt_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").strftime("%d.%m.%Y в %H:%M")
    except Exception:
        return value


def parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def free_spots(class_id: int) -> int:
    mc = next((m for m in load_classes() if int(m["id"]) == int(class_id)), None)
    if not mc:
        return 0
    taken = sum(
        1 for b in load_bookings()
        if int(b.get("class_id", 0)) == int(class_id) and b.get("status") == "confirmed"
    )
    return int(mc.get("spots", 0)) - taken


def active_classes():
    now = datetime.now()
    result = []
    for mc in load_classes():
        try:
            if parse_date(mc["date"]) >= now and free_spots(mc["id"]) > 0:
                result.append(mc)
        except Exception:
            pass
    return result


def next_id(items):
    return max([int(x.get("id", 0)) for x in items], default=0) + 1


def main_keyboard(uid: int):
    rows = [
        ["📅 Записаться на МК", "📋 Мои записи"],
        ["❓ Помощь"],
    ]
    if is_admin(uid):
        rows.append(["⚙️ Админ-панель"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def admin_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📋 Все записи", "📅 Расписание МК"],
            ["➕ Добавить МК", "❌ Отменить запись"],
            ["🔄 Перенести запись", "📣 Рассылка"],
            ["✏️ Приветствие", "👤 Администраторы"],
            ["🏠 Главное меню"],
        ],
        resize_keyboard=True,
    )


def cancel_keyboard():
    return ReplyKeyboardMarkup([["❌ Отмена"], ["🏠 Главное меню"]], resize_keyboard=True)


def set_state(context, state):
    if state is None:
        context.user_data.pop("state", None)
    else:
        context.user_data["state"] = state


def get_state(context):
    return context.user_data.get("state")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_state(context, None)
    uid = update.effective_user.id
    s = load_settings()
    known = s.setdefault("known_users", [])
    if uid not in known:
        known.append(uid)
        save_settings(s)

    await update.message.reply_text(
        safe_text(s.get("welcome_message"), DEFAULT_SETTINGS["welcome_message"]),
        reply_markup=main_keyboard(uid),
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_state(context, None)
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    await update.message.reply_text("⚙️ Админ-панель\n\nВыберите действие:", reply_markup=admin_keyboard())


async def check_subscription(context, uid: int) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, uid)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        # Для теста не блокируем, если бот не админ канала.
        return True


async def show_classes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not await check_subscription(context, uid):
        await update.message.reply_text(f"🔒 Для записи подпишитесь на канал {CHANNEL_USERNAME}")
        return

    classes = active_classes()
    if not classes:
        await update.message.reply_text("😔 Пока нет доступных мастер-классов.", reply_markup=main_keyboard(uid))
        return

    rows = []
    text = "📅 Доступные мастер-классы:\n\n"

    for mc in classes:
        spots = free_spots(mc["id"])
        label = f"МК #{mc['id']} — {mc['title'][:25]}"
        rows.append([label])
        text += (
            f"{label}\n"
            f"📆 {fmt_date(mc['date'])}\n"
            f"⏱ {mc.get('duration','')}, 💰 {mc.get('price','')}, мест: {spots}\n\n"
        )

    rows.append(["🏠 Главное меню"])

    await update.message.reply_text(
        text + "Нажмите кнопку нужного МК ниже.",
        reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True),
    )


async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE, class_id: int):
    mc = next((m for m in load_classes() if int(m["id"]) == int(class_id)), None)
    if not mc or free_spots(class_id) <= 0:
        await update.message.reply_text("😔 Мест уже нет или МК не найден.", reply_markup=main_keyboard(update.effective_user.id))
        return

    context.user_data["draft"] = {
        "class_id": int(class_id),
        "class_title": mc["title"],
        "class_date": mc["date"],
    }
    set_state(context, "booking_name")

    await update.message.reply_text(
        f"Вы выбрали:\n\n🎨 {mc['title']}\n📆 {fmt_date(mc['date'])}\n\nВведите ваше имя:",
        reply_markup=cancel_keyboard(),
    )


async def show_my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bookings = [
        b for b in load_bookings()
        if int(b.get("user_id", 0)) == uid and b.get("status") == "confirmed"
    ]

    if not bookings:
        await update.message.reply_text("📋 У вас нет активных записей.", reply_markup=main_keyboard(uid))
        return

    text = "📋 Ваши записи:\n\n"
    rows = []

    for b in bookings:
        text += f"#{b['id']} — {b['class_title']}\n📆 {fmt_date(b['class_date'])}\n\n"
        rows.append([f"Отменить запись #{b['id']}"])

    rows.append(["🏠 Главное меню"])

    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True))


async def admin_all_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bookings = [b for b in load_bookings() if b.get("status") == "confirmed"]
    if not bookings:
        await update.message.reply_text("Активных записей нет.", reply_markup=admin_keyboard())
        return

    text = "📋 Все активные записи:\n\n"
    for b in bookings:
        text += (
            f"#{b['id']} {b.get('name','')} | {b.get('phone','')}\n"
            f"TG: {b.get('contact','')}\n"
            f"🎨 {b.get('class_title','')}\n"
            f"📆 {fmt_date(b.get('class_date',''))}\n\n"
        )
        if len(text) > 3500:
            text += "Показаны не все записи."
            break

    await update.message.reply_text(text, reply_markup=admin_keyboard())


async def admin_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    classes = load_classes()
    if not classes:
        await update.message.reply_text("Расписание пустое.", reply_markup=admin_keyboard())
        return

    text = "📅 Расписание МК:\n\n"
    rows = []

    for mc in classes:
        text += (
            f"ID {mc['id']}: {mc['title']}\n"
            f"📆 {fmt_date(mc['date'])}\n"
            f"⏱ {mc.get('duration','')}, 💰 {mc.get('price','')}\n"
            f"Мест: {free_spots(mc['id'])}/{mc.get('spots',0)}\n"
            f"📍 {mc.get('venue_name','')}\n\n"
        )
        rows.append([f"Удалить МК #{mc['id']}"])

    rows.append(["➕ Добавить МК"])
    rows.append(["⚙️ Админ-панель"])

    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True))


async def ask_cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bookings = [b for b in load_bookings() if b.get("status") == "confirmed"]
    if not bookings:
        await update.message.reply_text("Нет записей для отмены.", reply_markup=admin_keyboard())
        return

    rows = [[f"Отменить запись #{b['id']}"] for b in bookings]
    rows.append(["⚙️ Админ-панель"])

    await update.message.reply_text("Выберите запись для отмены:", reply_markup=ReplyKeyboardMarkup(rows, resize_keyboard=True))


async def cancel_booking(update: Update, context: ContextTypes.DEFAULT_TYPE, booking_id: int):
    uid = update.effective_user.id
    bookings = load_bookings()
    target = None

    for b in bookings:
        if int(b.get("id", 0)) == int(booking_id):
            if is_admin(uid) or int(b.get("user_id", 0)) == uid:
                b["status"] = "cancelled"
                target = b
                break

    if not target:
        await update.message.reply_text("Запись не найдена.", reply_markup=main_keyboard(uid))
        return

    save_bookings(bookings)

    await update.message.reply_text(f"✅ Запись #{booking_id} отменена.", reply_markup=main_keyboard(uid))

    if is_admin(uid) and target.get("user_id") != uid:
        try:
            await context.bot.send_message(
                target["user_id"],
                f"❌ Ваша запись отменена организатором:\n{target['class_title']}\n{fmt_date(target['class_date'])}",
            )
        except Exception:
            pass


async def delete_class(update: Update, context: ContextTypes.DEFAULT_TYPE, class_id: int):
    if not is_admin(update.effective_user.id):
        return

    classes = [m for m in load_classes() if int(m["id"]) != int(class_id)]
    save_classes(classes)

    await update.message.reply_text(f"✅ МК #{class_id} удалён.", reply_markup=admin_keyboard())


async def start_add_class(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["draft"] = {}
    set_state(context, "add_title")
    await update.message.reply_text("➕ Новый МК\n\n1/8 Введите название:", reply_markup=cancel_keyboard())


async def continue_add_class(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    steps = {
        "add_title": ("title", "add_date", "2/8 Введите дату в формате 2026-07-10 12:00:"),
        "add_date": ("date", "add_duration", "3/8 Введите длительность, например 3 часа:"),
        "add_duration": ("duration", "add_price", "4/8 Введите цену, например 2500 ₽:"),
        "add_price": ("price", "add_spots", "5/8 Введите количество мест цифрой:"),
        "add_spots": ("spots", "add_description", "6/8 Введите описание:"),
        "add_description": ("description", "add_venue_name", "7/8 Введите название кафе/места:"),
        "add_venue_name": ("venue_name", "add_venue_url", "8/8 Введите ссылку на Google Maps:"),
        "add_venue_url": ("venue_url", None, None),
    }

    state = get_state(context)
    field, next_state, prompt = steps[state]
    draft = context.user_data.setdefault("draft", {})

    if field == "date":
        try:
            parse_date(text)
        except Exception:
            await update.message.reply_text("⚠️ Неверный формат. Пример: 2026-07-10 12:00")
            return

    if field == "spots":
        if not text.isdigit():
            await update.message.reply_text("⚠️ Введите число мест цифрами.")
            return
        draft[field] = int(text)
    else:
        draft[field] = text

    if next_state:
        set_state(context, next_state)
        await update.message.reply_text(prompt, reply_markup=cancel_keyboard())
        return

    classes = load_classes()
    new_mc = {
        "id": next_id(classes),
        "title": draft.get("title", ""),
        "date": draft.get("date", ""),
        "duration": draft.get("duration", ""),
        "price": draft.get("price", ""),
        "spots": draft.get("spots", 0),
        "description": draft.get("description", ""),
        "venue_name": draft.get("venue_name", ""),
        "venue_url": draft.get("venue_url", ""),
    }
    classes.append(new_mc)
    save_classes(classes)

    context.user_data.pop("draft", None)
    set_state(context, None)

    await update.message.reply_text(
        f"✅ МК добавлен!\n\nID {new_mc['id']}: {new_mc['title']}\n📆 {fmt_date(new_mc['date'])}",
        reply_markup=admin_keyboard(),
    )


async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_state(context, "broadcast")
    await update.message.reply_text("📣 Введите текст рассылки:", reply_markup=cancel_keyboard())


async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    s = load_settings()
    users = set(s.get("known_users", []))
    for b in load_bookings():
        users.add(b.get("user_id"))

    ok = 0
    fail = 0

    for uid in users:
        try:
            await context.bot.send_message(int(uid), text)
            ok += 1
        except Exception:
            fail += 1

    set_state(context, None)
    await update.message.reply_text(f"✅ Рассылка завершена: {ok} доставлено, {fail} ошибок.", reply_markup=admin_keyboard())


async def start_edit_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    set_state(context, "edit_welcome")
    await update.message.reply_text("✏️ Введите новый текст приветствия:", reply_markup=cancel_keyboard())


async def save_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    s = load_settings()
    s["welcome_message"] = safe_text(text, DEFAULT_SETTINGS["welcome_message"])
    save_settings(s)
    set_state(context, None)
    await update.message.reply_text("✅ Приветствие обновлено.", reply_markup=admin_keyboard())


async def show_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    admins = get_admins()
    text = "👤 Администраторы:\n\n" + "\n".join([f"• {a}" for a in admins])
    await update.message.reply_text(text, reply_markup=admin_keyboard())


async def reminders_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    bookings = load_bookings()
    changed = False

    for b in bookings:
        if b.get("status") != "confirmed":
            continue

        try:
            dt = parse_date(b["class_date"])
        except Exception:
            continue

        diff = dt - now

        if timedelta(hours=23, minutes=30) <= diff <= timedelta(hours=24, minutes=30) and not b.get("reminded_24"):
            try:
                await context.bot.send_message(
                    b["user_id"],
                    f"⏰ Напоминание за 24 часа\n\n🎨 {b['class_title']}\n📆 {fmt_date(b['class_date'])}",
                )
                b["reminded_24"] = True
                changed = True
            except Exception:
                pass

        if timedelta(minutes=30) <= diff <= timedelta(hours=1, minutes=30) and not b.get("reminded_1"):
            try:
                await context.bot.send_message(
                    b["user_id"],
                    f"⏰ Через 1 час мастер-класс\n\n🎨 {b['class_title']}\n📆 {fmt_date(b['class_date'])}",
                )
                b["reminded_1"] = True
                changed = True
            except Exception:
                pass

    if changed:
        save_bookings(bookings)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    state = get_state(context)

    logger.info("TEXT from %s | state=%s | text=%r", uid, state, text)

    if text in ("❌ Отмена", "🏠 Главное меню"):
        set_state(context, None)
        context.user_data.pop("draft", None)
        await update.message.reply_text("Главное меню:", reply_markup=main_keyboard(uid))
        return

    if text == "⚙️ Админ-панель":
        await cmd_admin(update, context)
        return

    if state == "booking_name":
        context.user_data.setdefault("draft", {})["name"] = text
        set_state(context, "booking_phone")
        await update.message.reply_text("📱 Введите номер телефона:", reply_markup=cancel_keyboard())
        return

    if state == "booking_phone":
        draft = context.user_data.get("draft", {})
        class_id = draft.get("class_id")

        if not class_id or free_spots(class_id) <= 0:
            set_state(context, None)
            context.user_data.pop("draft", None)
            await update.message.reply_text("😔 Места закончились или МК не найден.", reply_markup=main_keyboard(uid))
            return

        user = update.effective_user
        booking = {
            "id": next_id(load_bookings()),
            "user_id": uid,
            "name": draft.get("name", ""),
            "phone": text,
            "contact": f"@{user.username}" if user.username else f"ID {uid}",
            "class_id": class_id,
            "class_title": draft.get("class_title", ""),
            "class_date": draft.get("class_date", ""),
            "status": "confirmed",
            "confirmed_attendance": False,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

        bookings = load_bookings()
        bookings.append(booking)
        save_bookings(bookings)

        set_state(context, None)
        context.user_data.pop("draft", None)

        await update.message.reply_text(
            f"✅ Запись подтверждена!\n\n🎨 {booking['class_title']}\n📆 {fmt_date(booking['class_date'])}",
            reply_markup=main_keyboard(uid),
        )

        try:
            await context.bot.send_message(
                MAIN_ADMIN_ID,
                f"🎉 Новая запись #{booking['id']}\n\n"
                f"👤 {booking['name']} ({booking['contact']})\n"
                f"📱 {booking['phone']}\n"
                f"🎨 {booking['class_title']}\n"
                f"📆 {fmt_date(booking['class_date'])}",
            )
        except Exception:
            pass
        return

    if state in ("add_title", "add_date", "add_duration", "add_price", "add_spots", "add_description", "add_venue_name", "add_venue_url"):
        await continue_add_class(update, context, text)
        return

    if state == "broadcast":
        await send_broadcast(update, context, text)
        return

    if state == "edit_welcome":
        await save_welcome(update, context, text)
        return

    if text == "📅 Записаться на МК":
        await show_classes(update, context)
        return

    if text.startswith("МК #"):
        try:
            class_id = int(text.split("МК #", 1)[1].split(" ", 1)[0])
            await start_booking(update, context, class_id)
        except Exception:
            await update.message.reply_text("Не смог определить МК. Нажмите «Записаться на МК» заново.")
        return

    if text == "📋 Мои записи":
        await show_my_bookings(update, context)
        return

    if text.startswith("Отменить запись #"):
        try:
            booking_id = int(text.split("#", 1)[1])
            await cancel_booking(update, context, booking_id)
        except Exception:
            await update.message.reply_text("Не смог определить запись.")
        return

    if text == "❓ Помощь":
        await update.message.reply_text("Помощь:\n/start — главное меню\n/admin — админ-панель", reply_markup=main_keyboard(uid))
        return

    if is_admin(uid):
        if text == "📋 Все записи":
            await admin_all_bookings(update, context)
            return
        if text == "📅 Расписание МК":
            await admin_schedule(update, context)
            return
        if text == "➕ Добавить МК":
            await start_add_class(update, context)
            return
        if text == "❌ Отменить запись":
            await ask_cancel_admin(update, context)
            return
        if text == "🔄 Перенести запись":
            await update.message.reply_text("Перенос пока делаем через отмену и новую запись.", reply_markup=admin_keyboard())
            return
        if text == "📣 Рассылка":
            await start_broadcast(update, context)
            return
        if text == "✏️ Приветствие":
            await start_edit_welcome(update, context)
            return
        if text == "👤 Администраторы":
            await show_admins(update, context)
            return
        if text.startswith("Удалить МК #"):
            try:
                class_id = int(text.split("#", 1)[1])
                await delete_class(update, context, class_id)
            except Exception:
                await update.message.reply_text("Не смог определить МК.")
            return

    await update.message.reply_text("Выберите действие:", reply_markup=main_keyboard(uid))


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    logger.info("CALLBACK from %s: %s", q.from_user.id, q.data)
    await q.message.reply_text("Эта версия работает через обычные кнопки меню. Используйте кнопки снизу.")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update %s caused error: %s", update, context.error, exc_info=context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в переменных Railway")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    app.job_queue.run_repeating(reminders_job, interval=1800, first=30)

    logger.info("✅ Бот запущен. Версия TEXT BUTTONS.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
