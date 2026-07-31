import os
import logging
from fastapi import FastAPI, Request, Response
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
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
# Shared secret between us and Telegram. Registered via set_webhook(secret_token=...)
# and echoed back by Telegram in the X-Telegram-Bot-Api-Secret-Token header on every
# update, so we can reject forged requests to the (public) webhook endpoint.
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")

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
    application_instance.add_handler(CommandHandler("remember", bot_handlers.remember_command))
    # Runs in its own group so it observes every photo (for media-group tracking) without
    # interfering with the conversation handler's own photo handling in the default group.
    application_instance.add_handler(bot_handlers.media_group_handler, group=1)
    application_instance.add_handler(bot_handlers.conv_handler)
    
    # It is crucial to call initialize() to finalize the setup of the application instance.
    await application_instance.initialize()

    # Re-assert the webhook on every startup. Regenerating the bot token in BotFather
    # wipes the webhook on Telegram's side, so registering it here means a redeploy is
    # all that's needed to restore delivery after a token rotation.
    if WEBHOOK_URL:
        await application_instance.bot.set_webhook(
            url=WEBHOOK_URL,
            secret_token=WEBHOOK_SECRET or None,
        )
        logger.info(
            "Webhook registered: %s (secret_token %s)",
            WEBHOOK_URL,
            "enabled" if WEBHOOK_SECRET else "DISABLED",
        )
    else:
        logger.warning("WEBHOOK_URL not set; skipping webhook registration.")


@app.post("/")
async def telegram_webhook(request: Request):
    global application_instance
    # Reject forged updates: the endpoint is public, so only accept requests whose
    # secret-token header matches what we registered with Telegram.
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        logger.warning("Rejected webhook request with missing/invalid secret token.")
        return Response(status_code=403)
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
