import logging
import json
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ============================================================
# BURAYA TOKENI YAZ
TOKEN = "8580183780:AAGIWt2w5pld--No41FKAvPQKN1bQM21XWk"

# Xatırlatma saati (saat:dəqiqə) — istədiyin kimi dəyiş
REMINDER_HOUR   = 9   # səhər saatı
REMINDER_MINUTE = 0
# ============================================================

logging.basicConfig(level=logging.INFO)
TASKS_FILE = "tasks.json"

# ---------- Yardımçı funksiyalar ----------

def load_tasks():
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_tasks(data):
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_tasks(user_id):
    data = load_tasks()
    return data.get(str(user_id), [])

def set_user_tasks(user_id, tasks):
    data = load_tasks()
    data[str(user_id)] = tasks
    save_tasks(data)

def task_list_text(tasks):
    if not tasks:
        return "📭 Heç bir tapşırıq yoxdur."
    lines = []
    for i, t in enumerate(tasks):
        icon = "✅" if t["done"] else "⬜"
        lines.append(f"{icon} {i+1}. {t['text']}")
    done = sum(1 for t in tasks if t["done"])
    lines.append(f"\n📊 {done}/{len(tasks)} tamamlandı")
    return "\n".join(lines)

def task_keyboard(tasks):
    if not tasks:
        return None
    buttons = []
    for i, t in enumerate(tasks):
        icon = "✅" if t["done"] else "⬜"
        buttons.append([InlineKeyboardButton(
            f"{icon} {t['text'][:30]}",
            callback_data=f"toggle_{i}"
        )])
    buttons.append([
        InlineKeyboardButton("🗑 Hamısını sil", callback_data="clear_all"),
        InlineKeyboardButton("🗑 Tamamlanmışları sil", callback_data="clear_done"),
    ])
    return InlineKeyboardMarkup(buttons)

# ---------- Komandalar ----------

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Salam! Mən *Günlük Tapşırıq* botuyam.\n\n"
        "📌 *Komandalar:*\n"
        "/add — Yeni tapşırıq əlavə et\n"
        "/tasks — Tapşırıqlarına bax\n"
        "/settime — Xatırlatma saatını qur\n"
        "/help — Kömək\n\n"
        "Başlamaq üçün /add yaz! 🚀",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Necə istifadə etməli:*\n\n"
        "➕ /add — Tapşırıq əlavə et\n"
        "📋 /tasks — Siyahını gör, tamamla\n"
        "⏰ /settime — Xatırlatma saatını dəyiş\n\n"
        "Tapşırıq əlavə etmək üçün `/add Bazara get` kimi yaza bilərsən.",
        parse_mode="Markdown"
    )

async def add_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = " ".join(ctx.args).strip() if ctx.args else ""

    if not text:
        await update.message.reply_text("✍️ Tapşırığı yaz:\nMəs: `/add Bazara get`", parse_mode="Markdown")
        return

    tasks = get_user_tasks(user_id)
    tasks.append({"text": text, "done": False, "added": datetime.now().isoformat()})
    set_user_tasks(user_id, tasks)

    # Avtomatik xatırlatma qur — 1 saat sonra
    ctx.job_queue.run_once(
        remind_task,
        when=3600,
        data={"user_id": user_id, "task": text},
        name=f"remind_{user_id}_{len(tasks)}"
    )

    await update.message.reply_text(
        f"✅ *'{text}'* tapşırığı əlavə edildi!\n"
        f"⏰ 1 saat sonra xatırladacağam.",
        parse_mode="Markdown"
    )

async def show_tasks(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tasks = get_user_tasks(user_id)
    text = task_list_text(tasks)
    kb = task_keyboard(tasks)
    await update.message.reply_text(text, reply_markup=kb)

async def toggle_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("toggle_"):
        idx = int(data.split("_")[1])
        tasks = get_user_tasks(user_id)
        if 0 <= idx < len(tasks):
            tasks[idx]["done"] = not tasks[idx]["done"]
            set_user_tasks(user_id, tasks)

    elif data == "clear_done":
        tasks = get_user_tasks(user_id)
        tasks = [t for t in tasks if not t["done"]]
        set_user_tasks(user_id, tasks)

    elif data == "clear_all":
        set_user_tasks(user_id, [])
        tasks = []

    tasks = get_user_tasks(user_id)
    text = task_list_text(tasks)
    kb = task_keyboard(tasks)
    await query.edit_message_text(text, reply_markup=kb)

async def set_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "⏰ Xatırlatma saatını yaz:\nMəs: `/settime 08:30`",
            parse_mode="Markdown"
        )
        return
    try:
        hour, minute = map(int, ctx.args[0].split(":"))
        assert 0 <= hour <= 23 and 0 <= minute <= 59
    except:
        await update.message.reply_text("❌ Format səhvdir. Məs: `/settime 08:30`", parse_mode="Markdown")
        return

    user_id = update.effective_user.id
    # Köhnə işi sil
    current_jobs = ctx.job_queue.get_jobs_by_name(f"daily_{user_id}")
    for job in current_jobs:
        job.schedule_removal()

    # Yeni gündəlik iş qur
    ctx.job_queue.run_daily(
        daily_reminder,
        time=datetime.now().replace(hour=hour, minute=minute, second=0).time(),
        data={"user_id": user_id},
        name=f"daily_{user_id}"
    )

    await update.message.reply_text(
        f"✅ Hər gün saat *{hour:02d}:{minute:02d}*-də tapşırıqlarını xatırladacağam!",
        parse_mode="Markdown"
    )

# ---------- Xatırlatmalar ----------

async def remind_task(ctx: ContextTypes.DEFAULT_TYPE):
    job = ctx.job
    user_id = job.data["user_id"]
    task = job.data["task"]
    await ctx.bot.send_message(
        chat_id=user_id,
        text=f"⏰ *Xatırlatma!*\n\n📌 '{task}' tapşırığını tamamladın?\n\n/tasks — siyahına bax",
        parse_mode="Markdown"
    )

async def daily_reminder(ctx: ContextTypes.DEFAULT_TYPE):
    job = ctx.job
    user_id = job.data["user_id"]
    tasks = get_user_tasks(user_id)
    pending = [t for t in tasks if not t["done"]]

    if not pending:
        await ctx.bot.send_message(
            chat_id=user_id,
            text="🎉 *Əla!* Bu gün bütün tapşırıqlar tamamlanıb!\n\nYeni tapşırıq əlavə etmək üçün /add yaz.",
            parse_mode="Markdown"
        )
    else:
        text = f"🌅 *Günün xatırlatması!*\n\n{len(pending)} tapşırıq gözləyir:\n\n"
        for t in pending:
            text += f"⬜ {t['text']}\n"
        text += "\n/tasks — siyahına bax"
        await ctx.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")

# ---------- Əsas ----------

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("add", add_task))
    app.add_handler(CommandHandler("tasks", show_tasks))
    app.add_handler(CommandHandler("settime", set_time))
    app.add_handler(CallbackQueryHandler(toggle_task))

    print("✅ Bot işə düşdü!")
    app.run_polling()

if __name__ == "__main__":
    main()
