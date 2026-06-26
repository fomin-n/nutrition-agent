import asyncio
import logging
import tempfile
from functools import lru_cache
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.auth.service import AuthConfigurationError, AuthService
from app.bot.rate_limit import UsageLimitService, get_usage_limit_service
from app.graph.graph import process_request
from app.i18n import detect_language, response_language
from app.observability.request_context import TelegramRequestContext

LOGGER = logging.getLogger(__name__)
ACCESS_REQUIRED_MESSAGE = "Access required. Send /login <access_key>."


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    return AuthService.from_settings()


@lru_cache(maxsize=1)
def get_rate_limit_service() -> UsageLimitService:
    return get_usage_limit_service()


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
    args = getattr(context, "args", [])
    should_delete_key_message = bool(args and args[0].strip())
    user = update.effective_user
    try:
        if user is None:
            await _reply(update, ACCESS_REQUIRED_MESSAGE)
            return

        if not args:
            await _reply(update, ACCESS_REQUIRED_MESSAGE)
            return

        access_key = args[0].strip()
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
            await _reply(
                update,
                "Access control is not configured. Ask the administrator to set BOT_AUTH_SECRET.",
            )
            return

        if result.ok:
            await _reply(update, "Access granted.")
        else:
            await _reply(update, "Invalid or expired access key.")
    finally:
        if should_delete_key_message:
            await _delete_login_message(update)


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
    if not await _consume_usage_or_reply(update, text=message.text, has_image=False):
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
    if not await _consume_usage_or_reply(update, text=message.caption, has_image=True):
        return

    await _send_typing(update, context)
    photo = message.photo[-1]
    with tempfile.TemporaryDirectory(prefix="nutrition-agent-") as temp_dir:
        image_path = Path(temp_dir) / f"{photo.file_unique_id}.jpg"
        telegram_file = await photo.get_file()
        await telegram_file.download_to_drive(custom_path=str(image_path))
        await _process_and_reply(update, text=message.caption, image_path=str(image_path))


async def _process_and_reply(update: Update, *, text: str | None, image_path: str | None = None) -> None:
    request_context = TelegramRequestContext.from_update(update)
    try:
        answer = await asyncio.to_thread(
            process_request,
            text=text,
            image_path=image_path,
            source="telegram",
            user_id=request_context.user_id,
            session_id=request_context.session_id,
            trace_metadata=request_context.to_trace_metadata(),
        )
    except Exception:
        LOGGER.exception(
            "Failed to process Telegram message user_id=%s chat_id=%s message_id=%s",
            request_context.user_id,
            request_context.chat_id,
            request_context.message_id,
        )
        answer = "I couldn’t process that safely. Please try again with a clear meal description or food photo."
    await _reply(update, answer)


async def _reply(update: Update, text: str) -> None:
    message = update.effective_message
    if message:
        await message.reply_text(text)


async def _delete_login_message(update: Update) -> None:
    message = update.effective_message
    if message is None:
        return
    delete = getattr(message, "delete", None)
    if delete is None:
        return
    try:
        await delete()
    except Exception as exc:
        user_id = getattr(update.effective_user, "id", None)
        chat_id = getattr(update.effective_chat, "id", None)
        message_id = getattr(message, "message_id", None)
        LOGGER.warning(
            "Failed to delete login message user_id=%s chat_id=%s message_id=%s: %s",
            user_id,
            chat_id,
            message_id,
            exc,
        )


async def _consume_usage_or_reply(update: Update, *, text: str | None, has_image: bool) -> bool:
    user = update.effective_user
    if user is None:
        return False
    try:
        result = await asyncio.to_thread(get_rate_limit_service().check_and_increment, user.id)
    except Exception:
        LOGGER.exception(
            "Failed to verify request limits user_id=%s chat_id=%s",
            user.id,
            getattr(update.effective_chat, "id", None),
        )
        await _reply(update, _rate_limit_unavailable_message(text=text, has_image=has_image))
        return False
    if result.allowed:
        return True
    await _reply(update, _rate_limit_message(text=text, has_image=has_image))
    return False


def _rate_limit_message(*, text: str | None, has_image: bool) -> str:
    language = response_language(detect_language(text, has_image=has_image))
    if language == "ru":
        return (
            "Дневной лимит запросов исчерпан. Попробуйте завтра или попросите "
            "администратора увеличить лимит."
        )
    return "Daily request limit reached. Please try again tomorrow or ask the administrator to raise it."


def _rate_limit_unavailable_message(*, text: str | None, has_image: bool) -> str:
    language = response_language(detect_language(text, has_image=has_image))
    if language == "ru":
        return "Не удалось безопасно проверить лимит запросов. Попробуйте позже."
    return "I couldn’t safely verify the request limit. Please try again later."


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
