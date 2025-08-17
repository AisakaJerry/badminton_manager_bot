import os
import asyncio
import logging
import re
from datetime import datetime
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
)

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# --- Configuration ---
# 从环境变量中获取 Bot Token
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set.")

# --- Conversation States ---
AWAIT_DATE, AWAIT_TIME, AWAIT_LOCATION, CONFIRM_DETAILS = range(4)

# --- Helper & Handler Functions ---
def format_booking_details(booking_data):
    return (
        f"**Event:** {booking_data.get('summary', 'Badminton Booking')}\n"
        f"**Location:** {booking_data.get('location', 'Not specified')}\n"
        f"**Time:** {booking_data.get('time', 'Not specified')}"
    )

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Hello! I'm your Badminton Calendar Bot. "
        "I can help you create a Google Calendar event. "
        "Send /create to begin."
    )
    return ConversationHandler.END

async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("User requested to create an event. Starting manual input flow.")
    context.user_data['booking'] = {}
    await update.message.reply_text(
        "Let's create a new event. First, please provide the event date (e.g., '2025-08-20'):"
    )
    return AWAIT_DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_date = update.message.text
    context.user_data['booking']['date'] = user_date
    logger.info(f"Received date from user: {user_date}")
    await update.message.reply_text(
        "Great. Now, please provide the event time (e.g., '19:00-21:00'):"
    )
    return AWAIT_TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_time = update.message.text
    context.user_data['booking']['time'] = user_time
    logger.info(f"Received time from user: {user_time}")
    await update.message.reply_text(
        "Thanks. Finally, please provide the location (e.g., 'ABC Badminton Hall, Court 3'):"
    )
    return AWAIT_LOCATION

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_location = update.message.text
    context.user_data['booking']['location'] = user_location
    logger.info(f"Received location from user: {user_location}")
    booking_details = context.user_data['booking']
    formatted_details = format_booking_details(booking_details)
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"I've collected the following details:\n\n{formatted_details}\n\n"
        f"Would you like to confirm this event?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return CONFIRM_DETAILS

async def confirm_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    booking_data = context.user_data.get('booking')
    if not booking_data:
        await query.edit_message_text("No booking data found. Please start over with /create.")
        return ConversationHandler.END
    logger.info(f"User confirmed event: {booking_data}")
    await query.edit_message_text(
        "✅ Confirmed! A Google Calendar event has been created.\n\n"
        "This conversation is now over. To create another event, use /create.",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ Canceled. The event was not created. "
        "This conversation is now over. To start again, use /create.",
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END
    
async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("I didn't understand that. Please use the buttons or /cancel to exit.")
    return ConversationHandler.END

# 创建 FastAPI 应用实例
app = FastAPI()
# 创建一个全局变量来存储 Application 实例
application_instance = None

@app.on_event("startup")
async def init_bot_app():
    """
    在 FastAPI 启动时初始化并设置 bot 的应用和处理器。
    """
    global application_instance
    application_instance = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("create", create_command)],
        states={
            AWAIT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            AWAIT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
            AWAIT_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_location)],
            CONFIRM_DETAILS: [
                CallbackQueryHandler(confirm_event, pattern="^confirm$"),
                CallbackQueryHandler(cancel_event, pattern="^cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_event)],
    )

    application_instance.add_handler(CommandHandler("start", start))
    application_instance.add_handler(conv_handler)
    # 调用 initialize() 方法来完成初始化
    await application_instance.initialize()


@app.post("/")
async def telegram_webhook(request: Request):
    global application_instance
    try:
        # 确保 application_instance 已被初始化
        if application_instance is None:
            raise RuntimeError("Application instance not initialized.")

        body = await request.json()
        update = Update.de_json(body, application_instance.bot)
        
        await application_instance.process_update(update)
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return {"status": "error", "message": f"Webhook processing failed: {e}"}, 500
    
    return {"status": "ok"}
