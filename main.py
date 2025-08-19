import os
import logging
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application
import bot_handlers

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set.")


# Create FastAPI app instance
app = FastAPI()
# Create a global variable to store the Application instance
application_instance = None

@app.on_event("startup")
async def init_bot_app():
    """
    Initializes the bot's application and handlers when FastAPI starts up.
    """
    global application_instance
    application_instance = Application.builder().token(BOT_TOKEN).build()
    
    # Add all handlers from the separate bot_handlers module
    from telegram.ext import CommandHandler
    application_instance.add_handler(CommandHandler("help", bot_handlers.help_command))
    application_instance.add_handler(CommandHandler("start", bot_handlers.start_command))
    application_instance.add_handler(CommandHandler("check_badminton_session", bot_handlers.check_badminton_session_command))
    application_instance.add_handler(bot_handlers.conv_handler)
    
    # It is crucial to call initialize() to finalize the setup of the application instance.
    await application_instance.initialize()


@app.post("/")
async def telegram_webhook(request: Request):
    global application_instance
    try:
        if application_instance is None:
            raise RuntimeError("Application instance not initialized.")

        body = await request.json()
        update = Update.de_json(body, application_instance.bot)
        
        await application_instance.process_update(update)
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return {"status": "error", "message": f"Webhook processing failed: {e}"}, 500
    
    return {"status": "ok"}
