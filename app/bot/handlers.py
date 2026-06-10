import asyncio
import logging
import tempfile
from functools import lru_cache
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.auth.service import AuthConfigurationError, AuthService
from app.graph.graph import process_request

LOGGER = logging.getLogger(__name__)
ACCESS_REQUIRED_MESSAGE = "Access required. Send /login <access_key>."


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    return AuthService.from_settings()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply(update, ACCESS_REQUIRED_MESSAGE)
        return
    await _reply(
        update,
        (
            "Send a meal description or one food photo and I’ll estimate calories plus "
            "protein, fat, and carbs. I don’t provide medical advice, unsafe diet plans, "
            "or help with unrelated topics."
        ),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply(update, ACCESS_REQUIRED_MESSAGE)
        return
    await _reply(
        update,
        (
            "Examples:\n"
            "• 150g cooked rice, 120g chicken breast, salad, 1 tbsp olive oil\n"
            "• Photo of a plate with caption: chicken, potatoes, cucumber salad\n"
            "• Packaged yogurt label, 180g serving\n\n"
            "For best results include portion sizes."
        ),
    )


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _reply(update, ACCESS_REQUIRED_MESSAGE)
        return
    await _reply(update, "ok")


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        await _reply(update, ACCESS_REQUIRED_MESSAGE)
        return

    if not context.args:
        await _reply(update, ACCESS_REQUIRED_MESSAGE)
        return

    access_key = context.args[0].strip()
    if not access_key:
        await _reply(update, ACCESS_REQUIRED_MESSAGE)
        return

    try:
        result = get_auth_service().login(
            raw_key=access_key,
            telegram_user_id=user.id,
            username=user.username,
            display_name=user.full_name,
        )
    except AuthConfigurationError:
        LOGGER.exception("Bot auth is not configured")
        await _reply(update, "Access control is not configured. Ask the administrator to set BOT_AUTH_SECRET.")
        return

    if result.ok:
        await _reply(update, "Access granted.")
    else:
        await _reply(update, "Invalid or expired access key.")


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        await _reply(update, ACCESS_REQUIRED_MESSAGE)
        return
    try:
        get_auth_service().revoke_user(user.id)
    except AuthConfigurationError:
        LOGGER.exception("Bot auth is not configured")
    await _reply(update, "Logged out.")


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        await _reply(update, "Not authorized.")
        return
    if _is_authorized(update):
        await _reply(update, f"Authorized Telegram user ID: {user.id}")
    else:
        await _reply(update, "Not authorized. Send /login <access_key>.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    if not _is_authorized(update):
        await _reply(update, ACCESS_REQUIRED_MESSAGE)
        return
    await _send_typing(update, context)
    await _process_and_reply(update, text=message.text)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.photo:
        return
    if not _is_authorized(update):
        await _reply(update, ACCESS_REQUIRED_MESSAGE)
        return

    await _send_typing(update, context)
    photo = message.photo[-1]
    with tempfile.TemporaryDirectory(prefix="nutrition-agent-") as temp_dir:
        image_path = Path(temp_dir) / f"{photo.file_unique_id}.jpg"
        telegram_file = await photo.get_file()
        await telegram_file.download_to_drive(custom_path=str(image_path))
        await _process_and_reply(update, text=message.caption, image_path=str(image_path))


async def _process_and_reply(update: Update, *, text: str | None, image_path: str | None = None) -> None:
    try:
        answer = await asyncio.to_thread(process_request, text=text, image_path=image_path, source="telegram")
    except Exception:
        LOGGER.exception("Failed to process Telegram message")
        answer = "I couldn’t process that safely. Please try again with a clear meal description or food photo."
    await _reply(update, answer)


async def _reply(update: Update, text: str) -> None:
    message = update.effective_message
    if message:
        await message.reply_text(text)


async def _send_typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat:
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)


def _is_authorized(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    try:
        return get_auth_service().is_authorized(user.id)
    except AuthConfigurationError:
        LOGGER.exception("Bot auth is not configured")
        return False
