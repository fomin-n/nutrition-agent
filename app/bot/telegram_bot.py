import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.auth.service import AuthService
from app.bot.handlers import (
    forget,
    handle_error,
    handle_photo,
    handle_text,
    help_command,
    login,
    privacy,
    start,
)
from app.bot.health_server import start_health_server
from app.bot.rate_limit import get_usage_limit_service
from app.llm.client import get_settings, reveal_secret
from app.memory.service import get_memory_service
from app.observability.phoenix import configure_phoenix_tracing
from app.observability.trace_logging import configure_trace_log_correlation

LOGGER = logging.getLogger(__name__)


def build_application() -> Application:
    settings = get_settings()
    configure_phoenix_tracing(settings)
    token = reveal_secret(settings.telegram_bot_token)
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing. Export it or put it into .env before running the bot."
        )
    AuthService.from_settings(require_secret=settings.bot_access_mode == "invite")
    _prune_memory_if_configured(settings.memory_retention_days)
    _prune_usage_if_configured(settings.usage_counter_retention_days)

    application = (
        Application.builder()
        .token(token)
        .concurrent_updates(settings.bot_concurrent_updates)
        .build()
    )
    LOGGER.info(
        "Configured Telegram update concurrency concurrent_updates=%s",
        settings.bot_concurrent_updates,
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("privacy", privacy))
    application.add_handler(CommandHandler("forget", forget))
    application.add_handler(CommandHandler("login", login))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, handle_photo))
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text)
    )
    application.add_error_handler(handle_error)
    return application


def configure_default_executor(max_workers: int) -> ThreadPoolExecutor:
    executor = ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="nutrition-agent",
    )
    loop = _get_or_create_event_loop()
    loop.set_default_executor(executor)
    LOGGER.info(
        "Configured default asyncio executor thread_workers=%s",
        max_workers,
    )
    return executor


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def _prune_memory_if_configured(retention_days: int) -> None:
    if retention_days <= 0:
        return
    try:
        deleted = get_memory_service().prune_older_than(retention_days)
    except Exception:
        LOGGER.exception("Failed to prune old memory rows")
        return
    LOGGER.info("Pruned old memory rows retention_days=%s deleted=%s", retention_days, deleted)


def _prune_usage_if_configured(retention_days: int) -> None:
    if retention_days <= 0:
        return
    try:
        deleted = get_usage_limit_service().prune_older_than(retention_days)
    except Exception:
        LOGGER.exception("Failed to prune old usage counter rows")
        return
    LOGGER.info("Pruned old usage counter rows retention_days=%s deleted=%s", retention_days, deleted)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)s %(name)s "
            "trace_id=%(trace_id)s span_id=%(span_id)s: %(message)s"
        ),
    )
    configure_trace_log_correlation()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = get_settings()
    health_server = None
    executor: ThreadPoolExecutor | None = None
    try:
        executor = configure_default_executor(settings.bot_concurrent_updates)
        application = build_application()
        health_server = start_health_server(settings)
    except RuntimeError as exc:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        print(str(exc), file=sys.stderr)
        return 2
    try:
        application.run_polling(allowed_updates=["message"])
    finally:
        if health_server is not None:
            health_server.stop()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
