import asyncio
import logging
import tempfile
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.auth.service import AuthConfigurationError, AuthService
from app.bot.rate_limit import UsageLimitResult, UsageLimitService, get_usage_limit_service
from app.graph.graph import process_request
from app.i18n import detect_language, response_language
from app.llm.client import get_settings
from app.memory.service import MemoryService
from app.memory.service import get_memory_service as build_memory_service
from app.observability.request_context import TelegramRequestContext

LOGGER = logging.getLogger(__name__)
ACCESS_REQUIRED_MESSAGE = "Access required. Send /login <access_key>."
BANNED_MESSAGE = "This Telegram account cannot use the bot."
ACCESS_OPEN_MESSAGE = "Access is open. No access key is needed."
PRIVATE_CHAT_ONLY_MESSAGE = "Please message me in a private chat. Group chats are not supported yet."
ALBUM_REJECTED_MESSAGE = "Please send one standalone food photo instead of a photo album."
TEMPORARY_ERROR_MESSAGE = "Something went wrong while handling that update. Please try again."
TEMPORARY_ERROR_MESSAGE_RU = "При обработке сообщения произошла ошибка. Попробуйте еще раз."
IN_FLIGHT_MESSAGE = (
    "I’m still working on your previous request. Please wait for that answer before sending another one."
)


@lru_cache(maxsize=2)
def get_auth_service(*, require_secret: bool = True) -> AuthService:
    return AuthService.from_settings(require_secret=require_secret)


@lru_cache(maxsize=1)
def get_rate_limit_service() -> UsageLimitService:
    return get_usage_limit_service()


@lru_cache(maxsize=1)
def get_memory_service() -> MemoryService:
    return build_memory_service()


class _UserInFlightTracker:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._counts: dict[int, int] = {}

    async def try_acquire(self, user_id: int, *, limit: int) -> bool:
        if limit <= 0:
            return True
        async with self._lock:
            current = self._counts.get(user_id, 0)
            if current >= limit:
                return False
            self._counts[user_id] = current + 1
            return True

    async def release(self, user_id: int, *, limit: int) -> None:
        if limit <= 0:
            return
        async with self._lock:
            current = self._counts.get(user_id, 0)
            if current <= 1:
                self._counts.pop(user_id, None)
            else:
                self._counts[user_id] = current - 1


_USER_IN_FLIGHT = _UserInFlightTracker()


class _ExpiringKeySet:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, float] = OrderedDict()

    def add_if_new(self, key: str) -> bool:
        now = self._clock()
        self._prune(now)
        expires_at = self._entries.get(key)
        if expires_at is not None and expires_at > now:
            self._entries.move_to_end(key)
            return False
        self._entries[key] = now + self.ttl_seconds
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return True

    def _prune(self, now: float) -> None:
        expired = [key for key, expires_at in self._entries.items() if expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)


_ALBUM_REPLY_DEDUP = _ExpiringKeySet(ttl_seconds=120, max_entries=2048)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_private_chat(update):
        await _reply(update, _private_chat_only_message(update))
        return
    if _is_banned(update):
        await _reply(update, _banned_message(update))
        return
    if not _is_authorized(update):
        await _reply(update, _access_required_message(update))
        return
    await _reply(update, _start_message(update))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_private_chat(update):
        await _reply(update, _private_chat_only_message(update))
        return
    if _is_banned(update):
        await _reply(update, _banned_message(update))
        return
    if not _is_authorized(update):
        await _reply(update, _access_required_message(update))
        return
    await _reply(update, _help_message(update))


async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_private_chat(update):
        await _reply(update, _private_chat_only_message(update))
        return
    if _is_banned(update):
        await _reply(update, _banned_message(update))
        return
    await _reply(update, _privacy_message(update))


async def forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_private_chat(update):
        await _reply(update, _private_chat_only_message(update))
        return
    user = update.effective_user
    if user is None:
        await _reply(update, _not_authorized_message(update))
        return
    try:
        await asyncio.to_thread(get_memory_service().delete_user_data, user.id)
    except Exception as exc:
        LOGGER.error(
            "Failed to delete Telegram user memory user_id=%s chat_id=%s error_type=%s",
            user.id,
            getattr(update.effective_chat, "id", None),
            type(exc).__name__,
        )
        await _reply(update, _forget_failed_message(update))
        return
    await _reply(update, _forget_done_message(update))


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    request_context = TelegramRequestContext.from_update(update)
    error = getattr(context, "error", None)
    LOGGER.error(
        (
            "Unhandled Telegram update error update_id=%s user_id=%s chat_id=%s "
            "message_id=%s error_type=%s"
        ),
        request_context.update_id,
        request_context.user_id,
        request_context.chat_id,
        request_context.message_id,
        type(error).__name__ if error else None,
    )

    message = getattr(update, "effective_message", None)
    if message is None:
        return
    text = getattr(message, "text", None) or getattr(message, "caption", None)
    has_image = bool(getattr(message, "photo", None))
    try:
        await message.reply_text(
            _temporary_error_message_for_update(update, text=text, has_image=has_image)
        )
    except Exception as reply_error:
        LOGGER.warning(
            (
                "Failed to send Telegram error fallback update_id=%s user_id=%s "
                "chat_id=%s message_id=%s error_type=%s"
            ),
            request_context.update_id,
            request_context.user_id,
            request_context.chat_id,
            request_context.message_id,
            type(reply_error).__name__,
        )


async def login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = getattr(context, "args", [])
    should_delete_key_message = bool(args and args[0].strip())
    user = update.effective_user
    try:
        if not _is_private_chat(update):
            await _reply(update, _private_chat_only_message(update))
            return
        if user is None:
            await _reply(update, _access_required_message(update))
            return
        if _is_banned(update):
            await _reply(update, _banned_message(update))
            return
        if _access_mode() == "open":
            await _reply(update, _access_open_message(update))
            return

        if not args:
            await _reply(update, _access_required_message(update))
            return

        access_key = args[0].strip()
        if not access_key:
            await _reply(update, _access_required_message(update))
            return

        try:
            result = get_auth_service(require_secret=True).login(
                raw_key=access_key,
                telegram_user_id=user.id,
                username=user.username,
                display_name=user.full_name,
            )
        except AuthConfigurationError:
            LOGGER.error("Bot auth is not configured")
            await _reply(update, _auth_not_configured_message(update))
            return

        if result.ok:
            await _reply(update, _access_granted_message(update))
        else:
            await _reply(update, _invalid_access_key_message(update))
    finally:
        if should_delete_key_message:
            await _delete_login_message(update)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    if not _is_private_chat(update):
        return
    if _is_banned(update):
        await _reply(update, _banned_message(update))
        return
    if not _is_authorized(update):
        await _reply(update, _access_required_message(update))
        return
    async with _user_request_slot(update) as acquired:
        if not acquired:
            await _reply(update, _in_flight_message(update, text=message.text, has_image=False))
            return
        if not await _consume_usage_or_reply(context, update, text=message.text, has_image=False):
            return
        await _send_typing(update, context)
        await _process_and_reply(update, text=message.text)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.photo:
        return
    if not _is_private_chat(update):
        return
    if _is_banned(update):
        await _reply(update, _banned_message(update))
        return
    if not _is_authorized(update):
        await _reply(update, _access_required_message(update))
        return
    if _is_album_message(message):
        if _should_reply_to_album(message):
            await _reply(update, _album_rejected_message(update, text=message.caption))
        return
    size = getattr(message.photo[-1], "file_size", None)
    if isinstance(size, int) and size > getattr(get_settings(), "max_image_bytes", 10_000_000):
        await _reply(update, "Фото слишком большое. Пришлите уменьшенное фото." if _handler_language(update) == "ru" else "Photo is too large. Please send a smaller photo.")
        return
    async with _user_request_slot(update) as acquired:
        if not acquired:
            await _reply(update, _in_flight_message(update, text=message.caption, has_image=True))
            return
        if not await _consume_usage_or_reply(context, update, text=message.caption, has_image=True):
            return

        await _send_typing(update, context)
        photo = message.photo[-1]
        with tempfile.TemporaryDirectory(prefix="nutrition-agent-", dir=_temp_image_base_dir()) as temp_dir:
            image_path = Path(temp_dir) / f"{photo.file_unique_id}.jpg"
            telegram_file = await photo.get_file()
            await telegram_file.download_to_drive(custom_path=str(image_path))
            await _process_and_reply(update, text=message.caption, image_path=str(image_path))


@asynccontextmanager
async def _user_request_slot(update: Update) -> AsyncIterator[bool]:
    user = update.effective_user
    if user is None:
        yield False
        return
    limit = getattr(get_settings(), "bot_per_user_in_flight_limit", 1)
    acquired = await _USER_IN_FLIGHT.try_acquire(user.id, limit=limit)
    try:
        yield acquired
    finally:
        if acquired:
            await _USER_IN_FLIGHT.release(user.id, limit=limit)


async def _process_and_reply(update: Update, *, text: str | None, image_path: str | None = None) -> None:
    from collections.abc import Callable

    pending_memory: list[Callable[[], None]] = []
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
            defer_memory_write=pending_memory.append,
        )
    except Exception as exc:
        LOGGER.error(
            "Failed to process Telegram message user_id=%s chat_id=%s message_id=%s error_type=%s",
            request_context.user_id,
            request_context.chat_id,
            request_context.message_id,
            type(exc).__name__,
        )
        answer = _processing_error_message(update, text=text, has_image=image_path is not None)
    await _reply(update, answer)
    for write_memory in pending_memory:
        await asyncio.to_thread(write_memory)


async def _reply(update: Update, text: str) -> None:
    from app.bot.delivery import split_reply

    message = update.effective_message
    if message:
        for part in split_reply(text):
            await message.reply_text(part)


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
            type(exc).__name__,
        )


async def _consume_usage_or_reply(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    *,
    text: str | None,
    has_image: bool,
) -> bool:
    user = update.effective_user
    if user is None:
        return False
    try:
        result = await asyncio.to_thread(
            get_rate_limit_service().check_and_increment,
            user.id,
            has_image=has_image,
        )
    except Exception as exc:
        LOGGER.error(
            "Failed to verify request limits user_id=%s chat_id=%s error_type=%s",
            user.id,
            getattr(update.effective_chat, "id", None),
            type(exc).__name__,
        )
        await _reply(update, _rate_limit_unavailable_message_for_update(update, text=text, has_image=has_image))
        return False
    await _send_usage_admin_alert(context, result)
    if result.allowed:
        return True
    await _reply(update, _rate_limit_message(update, result.reason, text=text, has_image=has_image))
    return False


def _rate_limit_message(
    update: Update,
    reason: str,
    *,
    text: str | None,
    has_image: bool,
) -> str:
    language = _handler_language(update, text=text, has_image=has_image)
    if language == "ru":
        if reason == "user_minute_limit":
            return "Слишком много запросов подряд. Попробуйте снова примерно через минуту."
        if reason == "user_daily_photo_limit":
            return "Дневной лимит фото исчерпан. Можно отправить описание блюда текстом или попробовать фото завтра."
        if reason == "global_daily_limit":
            return "Сегодня бот уже на пределе нагрузки. Пожалуйста, попробуйте завтра."
        return (
            "Дневной лимит запросов исчерпан. Попробуйте завтра или попросите "
            "администратора увеличить лимит."
        )
    if reason == "user_minute_limit":
        return "Too many requests at once. Please slow down and try again in about a minute."
    if reason == "user_daily_photo_limit":
        return "Daily photo limit reached. You can still send text meal descriptions or try photos tomorrow."
    if reason == "global_daily_limit":
        return "The bot is at capacity today. Please come back tomorrow."
    return "Daily request limit reached. Please try again tomorrow or ask the administrator to raise it."


def _handler_language(
    update: Update,
    *,
    text: str | None = None,
    has_image: bool = False,
) -> str:
    language_code = getattr(update.effective_user, "language_code", None)
    if isinstance(language_code, str) and language_code.lower().startswith("ru"):
        return "ru"
    return response_language(detect_language(text, has_image=has_image))


def _start_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return (
            "Опишите блюдо текстом или отправьте одно фото еды, и я оценю калории, "
            "белки, жиры и углеводы с явными допущениями.\n\n"
            "Пример: 150 г риса, 120 г куриной грудки, салат, 1 ст. л. оливкового масла.\n\n"
            "Я не даю медицинских советов и небезопасных диет-планов. "
            "/privacy покажет, что хранится, а /forget удалит сохранённую память."
        )
    return (
        "Send a meal description or one food photo and I’ll estimate calories, protein, "
        "fat, and carbs with explicit assumptions.\n\n"
        "Example: 150g cooked rice, 120g chicken breast, salad, 1 tbsp olive oil.\n\n"
        "I don’t provide medical advice or unsafe diet plans. Use /privacy to see what "
        "is stored and /forget to delete saved memory."
    )


def _help_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return (
            "Примеры:\n"
            "• 150 г риса, 120 г куриной грудки, салат, 1 ст. л. оливкового масла\n"
            "• Фото тарелки с подписью: курица, картофель, салат из огурцов\n"
            "• Этикетка йогурта, порция 180 г\n\n"
            "Лучше всего указывать размеры порций."
        )
    return (
        "Examples:\n"
        "• 150g cooked rice, 120g chicken breast, salad, 1 tbsp olive oil\n"
        "• Photo of a plate with caption: chicken, potatoes, cucumber salad\n"
        "• Packaged yogurt label, 180g serving\n\n"
        "For best results include portion sizes."
    )


def _privacy_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return (
            "Я сохраняю недавние сообщения, краткую историю диалога и устойчивые "
            "пищевые предпочтения, чтобы лучше отвечать на уточнения. Счётчики "
            "использования хранятся отдельно для защиты от злоупотреблений. "
            "Запросы обрабатываются Telegram и OpenAI. Команда /forget удаляет память "
            "диалога, но не счётчики, резервные копии или записи внешних сервисов."
        )
    return (
        "I store recent messages, a compact conversation summary, and stable nutrition "
        "preferences so follow-up questions work better. Usage counters are kept "
        "separately for abuse and cost control. Use /forget to delete saved conversation "
        "memory, not usage counters, backups, or external-service records. "
        "Requests are processed by Telegram and OpenAI."
    )


def _forget_done_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Сохранённая память диалога удалена."
    return "Saved conversation memory deleted."


def _forget_failed_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Не удалось безопасно удалить память. Попробуйте позже."
    return "I couldn’t safely delete saved memory. Please try again later."


def _access_required_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Нужен доступ. Отправьте /login <access_key>."
    return ACCESS_REQUIRED_MESSAGE


def _banned_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Этот Telegram-аккаунт не может пользоваться ботом."
    return BANNED_MESSAGE


def _access_open_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Доступ открыт. Ключ не нужен."
    return ACCESS_OPEN_MESSAGE


def _private_chat_only_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Пожалуйста, напишите мне в личный чат. Групповые чаты пока не поддерживаются."
    return PRIVATE_CHAT_ONLY_MESSAGE


def _auth_not_configured_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Контроль доступа не настроен. Попросите администратора задать BOT_AUTH_SECRET."
    return "Access control is not configured. Ask the administrator to set BOT_AUTH_SECRET."


def _access_granted_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Доступ разрешён."
    return "Access granted."


def _invalid_access_key_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Ключ доступа неверный или истёк."
    return "Invalid or expired access key."


def _not_authorized_message(update: Update) -> str:
    if _handler_language(update) == "ru":
        return "Нет доступа. Отправьте /login <access_key>."
    return "Not authorized. Send /login <access_key>."


def _processing_error_message(update: Update, *, text: str | None, has_image: bool) -> str:
    if _handler_language(update, text=text, has_image=has_image) == "ru":
        return "Я не смог безопасно обработать запрос. Пришлите понятное описание блюда или фото еды."
    return "I couldn’t process that safely. Please try again with a clear meal description or food photo."


def _in_flight_message(update: Update, *, text: str | None, has_image: bool) -> str:
    if _handler_language(update, text=text, has_image=has_image) == "ru":
        return (
            "Я ещё обрабатываю предыдущий запрос. Дождитесь ответа, прежде чем отправлять следующий."
        )
    return IN_FLIGHT_MESSAGE


async def _send_usage_admin_alert(
    context: ContextTypes.DEFAULT_TYPE,
    result: UsageLimitResult,
) -> None:
    if result.admin_alert is None:
        return
    LOGGER.warning(
        "Telegram usage alert event=%s global_count=%s limit=%s",
        result.admin_alert,
        result.global_count,
        result.limit,
    )
    chat_id = getattr(get_settings(), "bot_admin_chat_id", None)
    if not chat_id:
        return
    message = (
        f"nutrition-agent usage alert: {result.admin_alert}; "
        f"global_count={result.global_count}; limit={result.limit}"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=message)
    except Exception:
        LOGGER.warning("Failed to send Telegram usage admin alert event=%s", result.admin_alert)


def _rate_limit_unavailable_message(*, text: str | None, has_image: bool) -> str:
    language = response_language(detect_language(text, has_image=has_image))
    if language == "ru":
        return "Не удалось безопасно проверить лимит запросов. Попробуйте позже."
    return "I couldn’t safely verify the request limit. Please try again later."


def _rate_limit_unavailable_message_for_update(
    update: Update,
    *,
    text: str | None,
    has_image: bool,
) -> str:
    language = _handler_language(update, text=text, has_image=has_image)
    if language == "ru":
        return "Не удалось безопасно проверить лимит запросов. Попробуйте позже."
    return "I couldn’t safely verify the request limit. Please try again later."


def _temporary_error_message(*, text: str | None, has_image: bool) -> str:
    language = response_language(detect_language(text, has_image=has_image))
    return TEMPORARY_ERROR_MESSAGE_RU if language == "ru" else TEMPORARY_ERROR_MESSAGE


def _temporary_error_message_for_update(
    update: Update,
    *,
    text: str | None,
    has_image: bool,
) -> str:
    language = _handler_language(update, text=text, has_image=has_image)
    return TEMPORARY_ERROR_MESSAGE_RU if language == "ru" else TEMPORARY_ERROR_MESSAGE


def _album_rejected_message(update: Update, *, text: str | None) -> str:
    language = _handler_language(update, text=text, has_image=True)
    if language == "ru":
        return "Пожалуйста, отправьте одну отдельную фотографию еды, а не альбом."
    return ALBUM_REJECTED_MESSAGE


def _temp_image_base_dir() -> str:
    path = Path(get_settings().temp_image_dir)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


async def _send_typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat:
        await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)


def _access_mode() -> str:
    return getattr(get_settings(), "bot_access_mode", "invite")


def _auth_service_for_access() -> AuthService:
    return get_auth_service(require_secret=_access_mode() == "invite")


def _is_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    return getattr(chat, "type", "private") == "private"


def _is_album_message(message: object) -> bool:
    return bool(getattr(message, "media_group_id", None))


def _should_reply_to_album(message: object) -> bool:
    media_group_id = getattr(message, "media_group_id", None)
    return bool(media_group_id and _ALBUM_REPLY_DEDUP.add_if_new(str(media_group_id)))


def _is_banned(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    try:
        return get_auth_service(require_secret=False).is_banned(user.id)
    except AuthConfigurationError:
        LOGGER.error("Bot ban list is not configured")
        return True


def _is_authorized(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    if _is_banned(update):
        return False
    if _access_mode() == "open":
        return True
    try:
        return _auth_service_for_access().is_authorized(user.id)
    except AuthConfigurationError:
        LOGGER.error("Bot auth is not configured")
        return False
