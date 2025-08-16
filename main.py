import os
import requests
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
)

# Set up basic logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Configuration ---
# Use environment variables for sensitive data in a production environment
BOT_TOKEN = os.environ.get("BOT_TOKEN")
EXTERNAL_SERVICE_URL = os.environ.get("EXTERNAL_SERVICE_URL")

# --- Conversation States ---
# We'll use these to manage the flow of the conversation
START_EVENT_CREATION, AWAIT_DATE, AWAIT_TIME, AWAIT_LOCATION, CONFIRM_DETAILS = range(5)


# --- Helper Functions ---
def format_booking_details(booking_data):
    """
    Formats the booking data into a readable string for the user.
    """
    return (
        f"**Event:** {booking_data.get('summary', 'Badminton Booking')}\n"
        f"**Location:** {booking_data.get('location', 'Not specified')}\n"
        f"**Time:** {booking_data.get('time', 'Not specified')}"
    )

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Sends a welcome message and starts the conversation.
    """
    await update.message.reply_text(
        "Hello! I'm your Badminton Calendar Bot. "
        "I can help you create a Google Calendar event. "
        "Send /create to begin."
    )
    return ConversationHandler.END


async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point for the conversation. Prompts the user for the event date.
    """
    logger.info("User requested to create an event. Starting manual input flow.")
    
    # Initialize user_data for the new event
    context.user_data['booking'] = {}

    await update.message.reply_text(
        "Let's create a new event. First, please provide the event date (e.g., '2025-08-20'):"
    )

    return AWAIT_DATE


async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles the date input from the user and prompts for the time.
    """
    user_date = update.message.text
    context.user_data['booking']['date'] = user_date
    logger.info(f"Received date from user: {user_date}")

    await update.message.reply_text(
        "Great. Now, please provide the event time (e.g., '19:00-21:00'):"
    )

    return AWAIT_TIME


async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles the time input from the user and prompts for the location.
    """
    user_time = update.message.text
    context.user_data['booking']['time'] = user_time
    logger.info(f"Received time from user: {user_time}")

    await update.message.reply_text(
        "Thanks. Finally, please provide the location (e.g., 'ABC Badminton Hall, Court 3'):"
    )

    return AWAIT_LOCATION


async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles the location input from the user and asks for confirmation.
    """
    user_location = update.message.text
    context.user_data['booking']['location'] = user_location
    logger.info(f"Received location from user: {user_location}")
    
    booking_details = context.user_data['booking']
    formatted_details = format_booking_details(booking_details)

    # Ask the user to confirm using inline keyboard buttons
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
    """
    Handles the user's confirmation. Creates the event and ends the conversation.
    """
    query = update.callback_query
    await query.answer()

    booking_data = context.user_data.get('booking')
    if not booking_data:
        await query.edit_message_text("No booking data found. Please start over with /create.")
        return ConversationHandler.END

    # Simulate sending the data to the external service
    logger.info(f"User confirmed event: {booking_data}")
    
    # You would insert your real Google Calendar API logic here
    # Example: create_google_calendar_event(booking_data)
    
    # Send a final success message
    await query.edit_message_text(
        "✅ Confirmed! A Google Calendar event has been created.\n\n"
        "This conversation is now over. To create another event, use /create.",
        parse_mode="Markdown"
    )

    context.user_data.clear()
    return ConversationHandler.END


async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handles the user's request to cancel. Ends the conversation.
    """
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
    """
    Catches messages that don't match any conversation states.
    """
    await update.message.reply_text("I didn't understand that. Please use the buttons or /cancel to exit.")
    return ConversationHandler.END

# The application object is now at the top level so gunicorn can find it.
application = Application.builder().token(BOT_TOKEN).build()

# Define and add all the handlers
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("create", create_command)],
    states={
        AWAIT_DATE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_date),
        ],
        AWAIT_TIME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_time),
        ],
        AWAIT_LOCATION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_location),
        ],
        CONFIRM_DETAILS: [
            CallbackQueryHandler(confirm_event, pattern="^confirm$"),
            CallbackQueryHandler(cancel_event, pattern="^cancel$"),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_event)],
)

application.add_handler(CommandHandler("start", start))
application.add_handler(conv_handler)

# The main function is now a simple entry point for gunicorn.
# It does not contain the bot's application logic.
def main() -> None:
    """
    This function is a simple entry point that will be called by gunicorn.
    It doesn't contain the bot's main application logic, which is now
    defined at the top level to be accessible by gunicorn.
    """
    logger.info("Gunicorn is starting the application...")
    
    # You will use `gunicorn main:application` to run the webhook.
    # The application.run_webhook(...) call is now managed by gunicorn
    # based on the `CMD` in your Dockerfile.
    
    # If running locally for testing, you might use:
    # application.run_polling()
    # but this is not for Cloud Run deployment.
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set. Please configure it.")
        return

    PORT = int(os.environ.get("PORT", 8080))
    URL = os.environ.get("URL")
    
    if not URL:
        logger.error("URL environment variable not set. Please configure it.")
        return

    # Set the webhook URL on Telegram. This happens when the container starts.
    application.bot.set_webhook(url=f"{URL}/telegram")
    logger.info("Webhook set. Application is ready to receive requests.")

# This __name__ check is important for gunicorn. It ensures the main() function
# is only called when the script is executed directly, not when it's imported
# by gunicorn.
if __name__ == "__main__":
    main()
