import os
import logging
import re
from datetime import datetime
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
import google_calendar_event_creator as calendar_api

# Use a separate logger for this module
logger = logging.getLogger(__name__)

# --- Configuration ---
MAX_CAPACITY = os.environ.get("MAX_CAPACITY", "6")

# --- Conversation States ---
AWAIT_DATE, AWAIT_TIME, AWAIT_LOCATION, AWAIT_BOOKER_NAME, CONFIRM_DETAILS = range(5)

# --- Helper & Handler Functions ---
def format_booking_details(booking_data):
    return (
        f"**Event:** {booking_data.get('summary', 'Badminton Booking')}\n"
        f"**Location:** {booking_data.get('location', 'Not specified')}\n"
        f"**Time:** {booking_data.get('time', 'Not specified')}\n"
        f"**Booked by:** {booking_data.get('booker_name', 'Not specified')}"
    )

async def delete_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_ids: list[int]):
    """
    Deletes a list of messages from the chat.
    """
    for msg_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.warning(f"Could not delete message {msg_id}. Bot might not have admin permissions: {e}")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Hello! I'm your Badminton Calendar Bot. "
        "I can help you create a Google Calendar event. "
        "Send /create to begin."
    )
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message explaining how to use the bot."""
    help_text = (
        "This bot helps you create Google Calendar events for badminton bookings.\n\n"
        "Here are the available commands:\n"
        "/start - Starts the bot and shows welcome message.\n"
        "/create - Begins the step-by-step process to create a new event.\n"
        "/cancel - Cancels the current event creation process.\n"
        "/help - Displays this help message.\n"
        "/check_badminton_session - Checks for all badminton sessions in the next 7 days."
    )
    await update.message.reply_text(help_text)

async def check_badminton_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /check_badminton_session command.
    Checks the Google Calendar for upcoming events in the next 7 days.
    """
    logger.info("User requested to check for upcoming badminton sessions.")
    
    events = calendar_api.check_upcoming_events(days=7)
    
    if events:
        def format_event_datetime(dt_str):
            try:
                dt = datetime.fromisoformat(dt_str)
                return dt.strftime('%Y-%m-%d %H:%M')
            except Exception:
                return dt_str  # fallback to original if parsing fails

        event_list = "\n".join([
            f"- **{e['summary']}** on {format_event_datetime(e['start'])} at {e['location']}"
            for e in events
        ])
        response_text = f"Here are the upcoming badminton sessions in the next 7 days:\n\n{event_list}"
    else:
        response_text = "There are no upcoming badminton sessions in the next 7 days."
        
    await update.message.reply_text(response_text, parse_mode="Markdown")


async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("User requested to create an event. Starting manual input flow.")
    context.user_data['booking'] = {}
    
    # Start collecting message IDs
    context.user_data['messages_to_delete'] = [update.message.message_id]
    
    bot_message = await update.message.reply_text(
        "Let's create a new event. First, please provide the event date (e.g., 'YYYY-MM-DD'):\n\n"
        "Type /cancel to exit."
    )
    context.user_data['messages_to_delete'].append(bot_message.message_id)
    
    return AWAIT_DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_date = update.message.text
    context.user_data['messages_to_delete'].append(update.message.message_id)

    try:
        datetime.strptime(user_date, '%Y-%m-%d')
        context.user_data['booking']['date'] = user_date
        logger.info(f"Received date from user: {user_date}")
        bot_message = await update.message.reply_text(
            "Great. Now, please provide the event time (e.g., 'HH:MM-HH:MM'):\n\n"
            "Type /cancel to exit."
        )
        context.user_data['messages_to_delete'].append(bot_message.message_id)
        return AWAIT_TIME
    except ValueError:
        bot_message = await update.message.reply_text(
            "Invalid date format. Please use YYYY-MM-DD, for example '2025-08-20'."
        )
        context.user_data['messages_to_delete'].append(bot_message.message_id)
        return AWAIT_DATE

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_time = update.message.text
    context.user_data['messages_to_delete'].append(update.message.message_id)
    
    time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$')
    if time_pattern.match(user_time):
        context.user_data['booking']['time'] = user_time
        logger.info(f"Received time from user: {user_time}")
        bot_message = await update.message.reply_text(
            "Thanks. Now, please provide the location (e.g., 'ABC Badminton Hall, Court 3'):\n\n"
            "Type /cancel to exit."
        )
        context.user_data['messages_to_delete'].append(bot_message.message_id)
        return AWAIT_LOCATION
    else:
        bot_message = await update.message.reply_text(
            "Invalid time format. Please use HH:MM-HH:MM, for example '19:00-21:00'."
        )
        context.user_data['messages_to_delete'].append(bot_message.message_id)
        return AWAIT_TIME

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_location = update.message.text
    context.user_data['messages_to_delete'].append(update.message.message_id)
    
    context.user_data['booking']['location'] = user_location
    logger.info(f"Received location from user: {user_location}")
    bot_message = await update.message.reply_text(
        "Who booked the court? Please provide a name:\n\n"
        "Type /cancel to exit."
    )
    context.user_data['messages_to_delete'].append(bot_message.message_id)
    return AWAIT_BOOKER_NAME

async def get_booker_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_name = update.message.text
    context.user_data['messages_to_delete'].append(update.message.message_id)
    
    context.user_data['booking']['booker_name'] = user_name
    logger.info(f"Received booker name from user: {user_name}")
    
    booking_details = context.user_data['booking']
    formatted_details = format_booking_details(booking_details)
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    bot_message = await update.message.reply_text(
        f"I've collected the following details:\n\n{formatted_details}\n\n"
        f"Would you like to confirm this event?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    context.user_data['messages_to_delete'].append(bot_message.message_id)
    
    return CONFIRM_DETAILS

async def confirm_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    booking_data = context.user_data.get('booking')
    
    chat_id = update.effective_chat.id
    
    if not booking_data:
        # If no booking data, clean up and send a final message
        await delete_messages(context, chat_id, context.user_data.get('messages_to_delete', []))
        await context.bot.send_message(
            chat_id=chat_id,
            text="No booking data found. Please start over with /create."
        )
        context.user_data.clear()
        return ConversationHandler.END

    logger.info(f"User confirmed event: {booking_data}")
    
    date = booking_data.get('date')
    time = booking_data.get('time')
    location = booking_data.get('location')
    booker_name = booking_data.get('booker_name')
        
    summary = f"Badminton Booking by {booker_name}" if booker_name else "Badminton Booking"
    
    description_lines = []
    if MAX_CAPACITY:
        description_lines.append(f"MAX={MAX_CAPACITY}")
    if booker_name:
        description_lines.append(f"Court booked by {booker_name}. Location: {location}")
    else:
        description_lines.append(f"Location: {location}")
    description = "\n".join(description_lines)

    try:
        event_link = calendar_api.create_calendar_event(
            date=date,
            time_range=time,
            location=location,
            description=description
        )
        
        # Delete messages before sending the final confirmation
        await delete_messages(context, chat_id, context.user_data['messages_to_delete'])
        
        if event_link:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ Confirmed! A Google Calendar event has been created.\n\n"
                    f"**Event Link:** {event_link}\n\n"
                    "This conversation is now over. To create another event, use /create."
                ),
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ Failed to create a calendar event. Please check the logs or try again later."
                ),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error calling calendar API: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ An unexpected error occurred while creating the calendar event. Please try again later."
            ),
            parse_mode="Markdown"
        )

    context.user_data.clear()
    return ConversationHandler.END

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    
    # Check if this is a button click or a command message
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        # Delete messages before sending the final cancellation message
        await delete_messages(context, chat_id, context.user_data.get('messages_to_delete', []))
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ Canceled. The event was not created. "
                "This conversation is now over. To start again, use /create."
            ),
            parse_mode="Markdown"
        )
    else:
        # Delete messages when a command is used to cancel
        context.user_data['messages_to_delete'].append(update.message.message_id)
        
        await delete_messages(context, chat_id, context.user_data.get('messages_to_delete'))

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ Canceled. The event was not created. "
                "This conversation is now over. To start again, use /create."
            )
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("I didn't understand that. Please use the buttons or /cancel to exit.")
    return ConversationHandler.END

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("create", create_command)],
    states={
        AWAIT_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_date),
            CommandHandler("cancel", cancel_event),
        ],
        AWAIT_TIME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_time),
            CommandHandler("cancel", cancel_event),
        ],
        AWAIT_LOCATION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_location),
            CommandHandler("cancel", cancel_event),
        ],
        AWAIT_BOOKER_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_booker_name),
            CommandHandler("cancel", cancel_event),
        ],
        CONFIRM_DETAILS: [
            CallbackQueryHandler(confirm_event, pattern="^confirm$"),
            CallbackQueryHandler(cancel_event, pattern="^cancel$"),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_event)],
)
