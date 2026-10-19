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
import gemini_client
import memory_store
import media_group_store
import pending_booking_store

# Use a separate logger for this module
logger = logging.getLogger(__name__)

# --- Configuration ---
MAX_CAPACITY = os.environ.get("MAX_CAPACITY", "6")

# --- Conversation States ---
AWAIT_MODE, AWAIT_IMAGE, AWAIT_DATE, AWAIT_TIME, AWAIT_LOCATION, AWAIT_BOOKER_NAME = range(6)

# --- Media Group Tracking ---
# Telegram sends each photo in a multi-photo message ("album") as a separate update sharing
# a media_group_id. If a user later replies to just one of them, that reply only carries that
# single message. media_group_store (backed by Firestore, since Cloud Run instances are
# stateless and don't share memory) lets us recover the other photos in the same album.
def _get_album_file_ids(chat_id: int, message_with_photo) -> list[str]:
    """Returns the file_ids of every photo in the same album as message_with_photo, in send order."""
    if not message_with_photo.media_group_id:
        return [message_with_photo.photo[-1].file_id]

    file_ids = media_group_store.get_file_ids(chat_id, message_with_photo.media_group_id)
    self_file_id = message_with_photo.photo[-1].file_id
    if self_file_id not in file_ids:
        file_ids.append(self_file_id)
    return file_ids

async def track_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Records every photo sent as part of an album, so a later reply can recover all of them."""
    message = update.message
    if not message or not message.photo or not message.media_group_id:
        return
    media_group_store.add_photo(
        update.effective_chat.id, message.media_group_id, message.message_id, message.photo[-1].file_id
    )

media_group_handler = MessageHandler(filters.PHOTO, track_media_group)

# --- Helper & Handler Functions ---
def format_booking_details(booking_data):
    return (
        f"**Event:** Badminton Booking\n"
        f"**Date:** {booking_data.get('date', 'Not specified')}\n"
        f"**Time:** {booking_data.get('time', 'Not specified')}\n"
        f"**Location:** {booking_data.get('location', 'Not specified')}\n"
        f"**Booked by:** {booking_data.get('booker_name', 'Not specified')}"
    )

async def send_confirmation_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, intro: str) -> int:
    """
    Persists the collected booking to Firestore and shows Confirm/Cancel buttons carrying its id.
    Ends the conversation: the buttons are handled by the standalone confirm/cancel handlers below,
    which work on any Cloud Run instance and for any member of the chat.
    """
    booking_id = pending_booking_store.save(
        chat_id=update.effective_chat.id,
        user_id=update.effective_user.id,
        booking=context.user_data['booking'],
        messages_to_delete=context.user_data['messages_to_delete'],
    )
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm:{booking_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{booking_id}")]
    ]
    await update.message.reply_text(
        f"{intro}\n\n{format_booking_details(context.user_data['booking'])}\n\n"
        f"Would you like to confirm this event?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    context.user_data.clear()
    return ConversationHandler.END

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
    if not update.message:
        return ConversationHandler.END
        
    await update.message.reply_text(
        "Hello! I'm your Badminton Calendar Bot. "
        "I can help you create a Google Calendar event. "
        "Send /create to begin."
    )
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message explaining how to use the bot."""
    if not update.message:
        return
        
    help_text = (
        "This bot helps you create Google Calendar events for badminton bookings.\n\n"
        "Here are the available commands:\n"
        "/start - Starts the bot and shows welcome message.\n"
        "/create - Begins the step-by-step process to create a new event.\n"
        "/cancel - Cancels the current event creation process.\n"
        "/help - Displays this help message.\n"
        "/check_badminton_session - Checks for all badminton sessions in the next 7 days.\n"
        "/remember <fact> - Remembers a fact (e.g. court nicknames, regular bookers) to help "
        "the bot read future booking screenshots in this chat."
    )
    await update.message.reply_text(help_text)

async def remember_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /remember command, storing a fact for this chat."""
    if not update.message:
        return

    fact = " ".join(context.args) if context.args else ""
    if not fact:
        await update.message.reply_text(
            "Please provide something to remember, e.g. '/remember each badminton slot lasts 1 hour'."
        )
        return

    memory_store.remember(update.effective_chat.id, fact)
    logger.info(f"Stored memory for chat {update.effective_chat.id}: {fact}")
    await update.message.reply_text(f"Got it, I'll remember: \"{fact}\"")

async def check_badminton_session_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /check_badminton_session command.
    Checks the Google Calendar for upcoming events in the next 14 days.
    """
    if not update.message:
        return
        
    logger.info("User requested to check for upcoming badminton sessions.")
    
    events = calendar_api.check_upcoming_events(days=14)
    
    if events:
        response_text = "Here are the upcoming badminton sessions in the next 14 days:\n\n"
        for e in events:
            attendee_list = ", ".join(e['attendees']) if e['attendees'] else "No attendees specified"
            response_text += (
                f"- **{e['summary']}**\n"
                f"  📅 Date: {e['start'].split('T')[0]}\n"
                f"  ⏰ Time: {e['start'].split('T')[1][:5]} - {e['end'].split('T')[1][:5]}\n"
                f"  📍 Location: {e['location']}\n"
                f"  👥 Attendees: {attendee_list}\n\n"
            )
    else:
        response_text = "There are no upcoming badminton sessions in the next 7 days."
        
    await update.message.reply_text(response_text, parse_mode="Markdown")


async def create_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("User requested to create an event. Checking for image attachment.")
    
    # Store the initial trigger message ID to preserve it
    context.user_data['initial_message_id'] = update.message.message_id
    # Initialize list for messages that should be deleted (excluding the initial trigger)
    context.user_data['messages_to_delete'] = []
    
    # Check if the message is a reply to a photo
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        # Store the quoted image ID to preserve it too
        context.user_data['quoted_image_id'] = update.message.reply_to_message.message_id
        return await process_photo(update, context)
    else:
        # Fallback to the standard menu if no image is found
        keyboard = [
            [InlineKeyboardButton("Upload Image", callback_data="upload_image")],
            [InlineKeyboardButton("Manual Input", callback_data="manual_input")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        bot_message = await update.message.reply_text(
            "How would you like to create your event?",
            reply_markup=reply_markup
        )
        context.user_data['messages_to_delete'].append(bot_message.message_id)

        return AWAIT_MODE

async def start_manual_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    await delete_messages(context, update.effective_chat.id, context.user_data.get('messages_to_delete', []))

    bot_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Let's create a new event. First, please provide the event date (e.g., 'YYYY-MM-DD'):\n\n"
             "Type /cancel to exit."
    )
    context.user_data['messages_to_delete'] = [bot_message.message_id]
    
    return AWAIT_DATE

async def start_image_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    await delete_messages(context, update.effective_chat.id, context.user_data.get('messages_to_delete', []))
    
    bot_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Please upload an image of your booking confirmation. The bot will automatically extract the details.\n\n"
             "Type /cancel to exit."
    )
    context.user_data['messages_to_delete'] = [bot_message.message_id]

    return AWAIT_IMAGE

async def process_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # If this is from a reply, the message object is different
    message_with_photo = update.message.reply_to_message if update.message.reply_to_message else update.message
    
    if not message_with_photo or not message_with_photo.photo:
        return AWAIT_IMAGE
    
    # Only add user input messages to delete list, NOT the quoted image or initial command
    # The quoted image and initial command should be preserved as they are the trigger messages
    if not update.message.reply_to_message:
        # This means the photo was uploaded directly (not quoted), so we can add it to delete list
        context.user_data['messages_to_delete'].append(message_with_photo.message_id)
    
    chat_id = update.effective_chat.id
    file_ids = _get_album_file_ids(chat_id, message_with_photo)
    MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB

    images_data = []
    for file_id in file_ids:
        telegram_file = await context.bot.get_file(file_id)

        if telegram_file.file_size > MAX_IMAGE_SIZE:
            bot_message = await update.message.reply_text(
                "One of the uploaded images is too large (max 5MB allowed). Please upload smaller images or use manual input."
            )
            context.user_data['messages_to_delete'].append(bot_message.message_id)
            return AWAIT_IMAGE

        images_data.append(await telegram_file.download_as_bytearray())

    try:
        memories = memory_store.get_memories(chat_id)
        booking_details = await gemini_client.extract_booking_info(images_data, memories)

        if not booking_details:
            bot_message = await update.message.reply_text("Could not extract booking details from the image. Please try again with a clearer image or use manual input.")
            context.user_data['messages_to_delete'].append(bot_message.message_id)
            return AWAIT_IMAGE
            
        context.user_data['booking'] = booking_details
        return await send_confirmation_prompt(
            update, context, "I've extracted the following details from your image:"
        )
    except Exception as e:
        logger.error(f"Error processing photo with Gemini API: {e}")
        bot_message = await update.message.reply_text(
            "An error occurred while processing the image. Please try again or use manual input.\n\n"
            "Type /cancel to exit."
        )
        context.user_data['messages_to_delete'].append(bot_message.message_id)
        return AWAIT_IMAGE


async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_date = update.message.text
    if not user_date:
        return AWAIT_DATE
        
    # Add user input message to delete list
    context.user_data['messages_to_delete'].append(update.message.message_id)

    try:
        datetime.strptime(user_date, '%Y-%m-%d')
        if 'booking' not in context.user_data:
            context.user_data['booking'] = {}
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
    if not user_time:
        return AWAIT_TIME
        
    context.user_data['messages_to_delete'].append(update.message.message_id)
    
    time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$')
    if time_pattern.match(user_time):
        if 'booking' not in context.user_data:
            context.user_data['booking'] = {}
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
    if not user_location:
        return AWAIT_LOCATION
        
    context.user_data['messages_to_delete'].append(update.message.message_id)
    
    if 'booking' not in context.user_data:
        context.user_data['booking'] = {}
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
    if not user_name:
        return AWAIT_BOOKER_NAME
        
    context.user_data['messages_to_delete'].append(update.message.message_id)
    
    if 'booking' not in context.user_data:
        context.user_data['booking'] = {}
    context.user_data['booking']['booker_name'] = user_name
    logger.info(f"Received booker name from user: {user_name}")

    return await send_confirmation_prompt(update, context, "I've collected the following details:")

async def remove_buttons(query) -> None:
    """Strips the inline keyboard from a stale prompt; ignores failures (e.g. the message was already deleted)."""
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logger.warning(f"Could not remove stale buttons: {e}")

async def confirm_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    booking_id = query.data.split(":", 1)[1]
    chat_id = update.effective_chat.id

    pending = pending_booking_store.pop(booking_id)
    if not pending:
        # Already confirmed/canceled (e.g. a double-click), or the prompt predates this store.
        await query.answer("This booking was already handled. Use /create to start over.", show_alert=True)
        await remove_buttons(query)
        return
    await query.answer()

    booking_data = pending['booking']
    logger.info(f"User {update.effective_user.id} confirmed event: {booking_data}")
    
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
        
        # Delete conversation messages (including this prompt) before sending the final confirmation.
        # This preserves the initial trigger message (command or quoted image)
        await delete_messages(context, chat_id, pending['messages_to_delete'] + [query.message.message_id])
        
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

async def cancel_booking_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    booking_id = query.data.split(":", 1)[1]
    chat_id = update.effective_chat.id

    pending = pending_booking_store.pop(booking_id)
    if not pending:
        await query.answer("This booking was already handled. Use /create to start over.", show_alert=True)
        await remove_buttons(query)
        return
    await query.answer()
    logger.info(f"User {update.effective_user.id} canceled pending booking {booking_id}")

    # Delete conversation messages (including this prompt) before sending the final cancellation message.
    # This preserves the initial trigger message
    await delete_messages(context, chat_id, pending['messages_to_delete'] + [query.message.message_id])
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "❌ Canceled. The event was not created. "
            "This conversation is now over. To start again, use /create."
        ),
        parse_mode="Markdown"
    )

async def cancel_event(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/cancel while the /create conversation is still collecting details."""
    chat_id = update.effective_chat.id

    # Add the cancel command message to delete list
    if update.message:
        context.user_data.setdefault('messages_to_delete', []).append(update.message.message_id)
    
    # Delete conversation messages when a command is used to cancel
    # This preserves the initial trigger message
    await delete_messages(context, chat_id, context.user_data.get('messages_to_delete', []))

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "❌ Canceled. The event was not created. "
            "This conversation is now over. To start again, use /create."
        )
    )
    
    context.user_data.clear()
    return ConversationHandler.END

async def expired_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Catch-all for button clicks no other handler took, e.g. the Upload/Manual menu after the
    instance holding that conversation scaled down, someone else's menu in a group, or buttons
    from before persistent bookings. Answering the query stops Telegram's loading spinner instead
    of leaving the button stuck. The buttons are left in place since they may still be live for
    the user who started that /create.
    """
    query = update.callback_query
    logger.warning(
        f"Unhandled button click data={query.data!r} user={update.effective_user.id} chat={update.effective_chat.id}"
    )
    await query.answer(
        "This session has expired or belongs to someone else. Please start your own with /create.",
        show_alert=True,
    )

confirm_handler = CallbackQueryHandler(confirm_event, pattern="^confirm:")
cancel_button_handler = CallbackQueryHandler(cancel_booking_button, pattern="^cancel:")
expired_button_handler = CallbackQueryHandler(expired_button)

async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message:
        return ConversationHandler.END
        
    await update.message.reply_text("I didn't understand that. Please use the buttons or /cancel to exit.")
    return ConversationHandler.END

# Define the conversation handler here
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("create", create_command)],
    states={
        AWAIT_MODE: [
            CallbackQueryHandler(start_image_upload, pattern="^upload_image$"),
            CallbackQueryHandler(start_manual_input, pattern="^manual_input$"),
        ],
        AWAIT_IMAGE: [
            MessageHandler(filters.PHOTO & ~filters.COMMAND, process_photo),
            CommandHandler("cancel", cancel_event),
        ],
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
    },
    fallbacks=[CommandHandler("cancel", cancel_event)],
)
