import os
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@JJewelryNhaTrang")
TZ_NAME = os.getenv("TZ", "Asia/Ho_Chi_Minh")
TZ = ZoneInfo(TZ_NAME)

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
WORKSHOPS_FILE = DATA_DIR / "workshops.json"
BOOKINGS_FILE = DATA_DIR / "bookings.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "welcome": "💎 Добро пожаловать в JJewerly Bot!\n\nЗдесь можно записаться на мастер-класс.",
}

def load_json(path: Path, default):
    if not path.exists():
        save_json(path, default)
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def workshops():
    return load_json(WORKSHOPS_FILE, [])

def bookings():
    return load_json(BOOKINGS_FILE, [])

def settings():
    return load_json(SETTINGS_FILE, DEFAULT_SETTINGS)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def main_menu(is_admin_user=False):
    rows = [
        ["🗓 Записаться на МК", "📋 Мои записи"],
        ["🔄 Перенести запись", "❌ Отменить запись"],
    ]
    if is_admin_user:
        rows.append(["⚙️ Админ-панель"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def admin_menu():
    return ReplyKeyboardMarkup(
        [
            ["➕ Добавить МК", "📋 Все записи"],
            ["📅 Расписание МК", "📣 Рассылка"],
            ["✏️ Изменить приветствие", "⬅️ В меню"],
        ],
        resize_keyboard=True,
    )

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning("Subscription check failed: %s", e)
        # Для быстрого теста не блокируем, если бот не админ канала или канал не настроен.
        return True

def active_workshops():
    now = datetime.now(TZ)
    items = []
    for w in workshops():
        try:
            dt = datetime.strptime(w["date"], "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
            if dt > now and int(w.get("places", 0)) > int(w.get("booked", 0)):
                items.append(w)
        except Exception:
            pass
    return items

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = settings().get("welcome", DEFAULT_SETTINGS["welcome"])
    await update.message.reply_text(text, reply_markup=main_menu(is_admin(update.effective_user.id)))

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    await update.message.reply_text("⚙️ Админ-панель", reply_markup=admin_menu())

async def show_workshops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_subscription(update, context):
        await update.message.reply_text(f"⚠️ Для записи нужно быть подписанным на канал {CHANNEL_USERNAME}")
        return
    items = active_workshops()
    if not items:
        await update.message.reply_text("Пока нет доступных мастер-классов.")
        return
    buttons = []
    for w in items:
        left = int(w.get("places", 0)) - int(w.get("booked", 0))
        buttons.append([InlineKeyboardButton(f"{w['title']} — {w['date']} / мест: {left}", callback_data=f"book:{w['id']}")])
    await update.message.reply_text("Выберите мастер-класс:", reply_markup=InlineKeyboardMarkup(buttons))

async def show_my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_bookings = [b for b in bookings() if b["user_id"] == uid and b["status"] == "active"]
    if not user_bookings:
        await update.message.reply_text("У вас нет активных записей.")
        return
    ws = {w["id"]: w for w in workshops()}
    text = "📋 Ваши записи:\n\n"
    for b in user_bookings:
        w = ws.get(b["workshop_id"], {})
        text += f"• {w.get('title','МК')} — {w.get('date','')}\nСтатус: {'✅ подтверждено' if b.get('confirmed') else '⏳ не подтверждено'}\n\n"
    await update.message.reply_text(text)

async def ask_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_bookings = [b for b in bookings() if b["user_id"] == uid and b["status"] == "active"]
    if not user_bookings:
        await update.message.reply_text("Нет активных записей для отмены.")
        return
    ws = {w["id"]: w for w in workshops()}
    buttons = []
    for b in user_bookings:
        w = ws.get(b["workshop_id"], {})
        buttons.append([InlineKeyboardButton(f"❌ {w.get('title','МК')} — {w.get('date','')}", callback_data=f"cancel:{b['id']}")])
    await update.message.reply_text("Выберите запись для отмены:", reply_markup=InlineKeyboardMarkup(buttons))

async def ask_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_bookings = [b for b in bookings() if b["user_id"] == uid and b["status"] == "active"]
    if not user_bookings:
        await update.message.reply_text("Нет активных записей для переноса.")
        return
    ws = {w["id"]: w for w in workshops()}
    buttons = []
    for b in user_bookings:
        w = ws.get(b["workshop_id"], {})
        buttons.append([InlineKeyboardButton(f"🔄 {w.get('title','МК')} — {w.get('date','')}", callback_data=f"transfer_from:{b['id']}")])
    await update.message.reply_text("Какую запись перенести?", reply_markup=InlineKeyboardMarkup(buttons))

async def all_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    bs = [b for b in bookings() if b["status"] == "active"]
    ws = {w["id"]: w for w in workshops()}
    if not bs:
        await update.message.reply_text("Активных записей нет.")
        return
    text = "📋 Все активные записи:\n\n"
    for b in bs:
        w = ws.get(b["workshop_id"], {})
        text += f"• {b.get('name')} @{b.get('username') or '-'} / {b.get('contact')}\nМК: {w.get('title')} — {w.get('date')}\nСтатус: {'✅' if b.get('confirmed') else '⏳'}\n\n"
    await update.message.reply_text(text)

async def schedule_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    items = workshops()
    if not items:
        await update.message.reply_text("Расписание пустое.")
        return
    text = "📅 Расписание МК:\n\n"
    for w in items:
        text += f"ID {w['id']}: {w['title']}\n{w['date']}, {w.get('duration')}, {w.get('price')}\nМест: {w.get('booked',0)}/{w.get('places',0)}\n{w.get('cafe','')}\n\n"
    await update.message.reply_text(text)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = q.from_user.id

    if data.startswith("book:"):
        wid = data.split(":", 1)[1]
        context.user_data["booking_wid"] = wid
        await q.message.reply_text(
            "Введите ваше имя:",
            reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True),
        )
        context.user_data["state"] = "await_name"
        return

    if data.startswith("confirm:"):
        bid = data.split(":", 1)[1]
        bs = bookings()
        for b in bs:
            if b["id"] == bid and b["user_id"] == uid:
                b["confirmed"] = True
        save_json(BOOKINGS_FILE, bs)
        await q.message.reply_text("✅ Участие подтверждено.")
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(admin_id, "✅ Пользователь подтвердил участие.")
        return

    if data.startswith("cancel:"):
        bid = data.split(":", 1)[1]
        bs = bookings()
        target = None
        for b in bs:
            if b["id"] == bid and (b["user_id"] == uid or is_admin(uid)):
                b["status"] = "cancelled"
                target = b
        if target:
            ws = workshops()
            for w in ws:
                if w["id"] == target["workshop_id"]:
                    w["booked"] = max(0, int(w.get("booked", 0)) - 1)
            save_json(WORKSHOPS_FILE, ws)
            save_json(BOOKINGS_FILE, bs)
            await q.message.reply_text("❌ Запись отменена.")
        return

    if data.startswith("transfer_from:"):
        bid = data.split(":", 1)[1]
        context.user_data["transfer_bid"] = bid
        items = active_workshops()
        buttons = []
        for w in items:
            buttons.append([InlineKeyboardButton(f"{w['title']} — {w['date']}", callback_data=f"transfer_to:{w['id']}")])
        await q.message.reply_text("Выберите новый МК:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith("transfer_to:"):
        new_wid = data.split(":", 1)[1]
        bid = context.user_data.get("transfer_bid")
        if not bid:
            return
        bs = bookings()
        old_wid = None
        for b in bs:
            if b["id"] == bid and b["user_id"] == uid:
                old_wid = b["workshop_id"]
                b["workshop_id"] = new_wid
                b["confirmed"] = False
        ws = workshops()
        for w in ws:
            if w["id"] == old_wid:
                w["booked"] = max(0, int(w.get("booked", 0)) - 1)
            if w["id"] == new_wid:
                w["booked"] = int(w.get("booked", 0)) + 1
        save_json(WORKSHOPS_FILE, ws)
        save_json(BOOKINGS_FILE, bs)
        await q.message.reply_text("🔄 Запись перенесена.")
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(admin_id, "🔄 Пользователь перенёс запись.")
        return

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id

    if text == "🗓 Записаться на МК":
        await show_workshops(update, context)
    elif text == "📋 Мои записи":
        await show_my_bookings(update, context)
    elif text == "❌ Отменить запись":
        await ask_cancel(update, context)
    elif text == "🔄 Перенести запись":
        await ask_transfer(update, context)
    elif text == "⚙️ Админ-панель" or text == "/admin":
        await admin(update, context)
    elif text == "⬅️ В меню":
        await start(update, context)
    elif is_admin(uid) and text == "📋 Все записи":
        await all_bookings(update, context)
    elif is_admin(uid) and text == "📅 Расписание МК":
        await schedule_list(update, context)
    elif is_admin(uid) and text == "➕ Добавить МК":
        context.user_data["state"] = "add_workshop"
        context.user_data["new_workshop"] = {}
        context.user_data["step"] = 1
        await update.message.reply_text("1/8 Название МК:")
    elif is_admin(uid) and text == "✏️ Изменить приветствие":
        context.user_data["state"] = "edit_welcome"
        await update.message.reply_text("Отправьте новый текст приветствия:")
    elif is_admin(uid) and text == "📣 Рассылка":
        context.user_data["state"] = "broadcast"
        await update.message.reply_text("Введите текст рассылки всем, кто записывался:")
    elif context.user_data.get("state") == "await_name":
        if text == "Отмена":
            context.user_data.clear()
            await start(update, context)
            return
        await finish_booking(update, context, text)
    elif is_admin(uid) and context.user_data.get("state") == "add_workshop":
        await add_workshop_step(update, context, text)
    elif is_admin(uid) and context.user_data.get("state") == "edit_welcome":
        s = settings()
        s["welcome"] = text
        save_json(SETTINGS_FILE, s)
        context.user_data.clear()
        await update.message.reply_text("✅ Приветствие обновлено.", reply_markup=admin_menu())
    elif is_admin(uid) and context.user_data.get("state") == "broadcast":
        await do_broadcast(update, context, text)
    else:
        await update.message.reply_text("Выберите действие в меню.", reply_markup=main_menu(is_admin(uid)))

async def finish_booking(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str):
    wid = context.user_data.get("booking_wid")
    ws = workshops()
    selected = None
    for w in ws:
        if w["id"] == wid:
            selected = w
            if int(w.get("booked", 0)) >= int(w.get("places", 0)):
                await update.message.reply_text("К сожалению, места уже закончились.")
                return
            w["booked"] = int(w.get("booked", 0)) + 1
    if not selected:
        await update.message.reply_text("МК не найден.")
        return
    user = update.effective_user
    b = {
        "id": str(int(datetime.now(TZ).timestamp() * 1000)),
        "user_id": user.id,
        "username": user.username,
        "contact": f"@{user.username}" if user.username else str(user.id),
        "name": name,
        "workshop_id": wid,
        "status": "active",
        "confirmed": False,
        "created_at": datetime.now(TZ).isoformat(),
        "reminder_24_sent": False,
        "reminder_1_sent": False,
    }
    bs = bookings()
    bs.append(b)
    save_json(WORKSHOPS_FILE, ws)
    save_json(BOOKINGS_FILE, bs)
    context.user_data.clear()

    await update.message.reply_text(
        f"✅ Запись создана!\n\nМК: {selected['title']}\nДата: {selected['date']}\nАдрес: {selected.get('cafe','')}\n{selected.get('maps','')}",
        reply_markup=main_menu(is_admin(user.id)),
    )
    for admin_id in ADMIN_IDS:
        await context.bot.send_message(
            admin_id,
            f"🔔 Новая запись\nИмя: {name}\nКонтакт: {b['contact']}\nМК: {selected['title']}\nДата: {selected['date']}",
        )

async def add_workshop_step(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    nw = context.user_data["new_workshop"]
    step = context.user_data["step"]
    prompts = {
        1: ("title", "2/8 Дата и время в формате 05.08.2026 12:00:"),
        2: ("date", "3/8 Длительность, например: 3 часа:"),
        3: ("duration", "4/8 Цена, например: 2500 ₽:"),
        4: ("price", "5/8 Количество мест:"),
        5: ("places", "6/8 Описание:"),
        6: ("description", "7/8 Название кафе:"),
        7: ("cafe", "8/8 Ссылка на Google Maps:"),
        8: ("maps", None),
    }
    key, next_prompt = prompts[step]
    nw[key] = text

    if step < 8:
        context.user_data["step"] = step + 1
        await update.message.reply_text(next_prompt)
    else:
        item = {
            "id": str(int(datetime.now(TZ).timestamp() * 1000)),
            "booked": 0,
            **nw,
        }
        try:
            int(item["places"])
            datetime.strptime(item["date"], "%d.%m.%Y %H:%M")
        except Exception:
            await update.message.reply_text("Ошибка формата даты или количества мест. Начните добавление заново.")
            context.user_data.clear()
            return
        ws = workshops()
        ws.append(item)
        save_json(WORKSHOPS_FILE, ws)
        context.user_data.clear()
        await update.message.reply_text("✅ МК добавлен.", reply_markup=admin_menu())

async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_ids = sorted(set(b["user_id"] for b in bookings()))
    sent = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(user_id, text)
            sent += 1
        except Exception:
            pass
    context.user_data.clear()
    await update.message.reply_text(f"✅ Рассылка отправлена. Получателей: {sent}", reply_markup=admin_menu())

async def reminders_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ)
    bs = bookings()
    ws = {w["id"]: w for w in workshops()}
    changed = False

    for b in bs:
        if b.get("status") != "active":
            continue
        w = ws.get(b["workshop_id"])
        if not w:
            continue
        try:
            dt = datetime.strptime(w["date"], "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
        except Exception:
            continue

        diff = dt - now
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Подтверждаю", callback_data=f"confirm:{b['id']}")],
            [InlineKeyboardButton("🔄 Перенести", callback_data=f"transfer_from:{b['id']}")],
            [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel:{b['id']}")],
        ])

        if timedelta(hours=23, minutes=30) <= diff <= timedelta(hours=24, minutes=30) and not b.get("reminder_24_sent"):
            await context.bot.send_message(
                b["user_id"],
                f"⏰ Напоминание за 24 часа\nМК: {w['title']}\nДата: {w['date']}\nАдрес: {w.get('cafe','')}\n{w.get('maps','')}",
                reply_markup=buttons,
            )
            b["reminder_24_sent"] = True
            changed = True

        if timedelta(minutes=30) <= diff <= timedelta(hours=1, minutes=30) and not b.get("reminder_1_sent"):
            await context.bot.send_message(
                b["user_id"],
                f"⏰ Напоминание за 1 час\nМК: {w['title']}\nАдрес: {w.get('cafe','')}\n{w.get('maps','')}",
                reply_markup=buttons,
            )
            b["reminder_1_sent"] = True
            changed = True

    if changed:
        save_json(BOOKINGS_FILE, bs)

def seed_files():
    if not WORKSHOPS_FILE.exists():
        save_json(WORKSHOPS_FILE, [])
    if not BOOKINGS_FILE.exists():
        save_json(BOOKINGS_FILE, [])
    if not SETTINGS_FILE.exists():
        save_json(SETTINGS_FILE, DEFAULT_SETTINGS)

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в переменных Railway")
    seed_files()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.job_queue.run_repeating(reminders_job, interval=1800, first=30)
    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()