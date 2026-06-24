import logging
import sys

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.auth.service import AuthService
from app.bot.handlers import (
    handle_photo,
    handle_text,
    health,
    help_command,
    login,
    logout,
    start,
    whoami,
)
from app.llm.client import get_settings, reveal_secret
from app.observability.phoenix import configure_phoenix_tracing
from app.observability.trace_logging import configure_trace_log_correlation


def build_application() -> Application:
    settings = get_settings()
    configure_phoenix_tracing(settings)
    token = reveal_secret(settings.telegram_bot_token)
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing. Export it or put it into .env before running the bot."
        )
    AuthService.from_settings()

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("health", health))
    application.add_handler(CommandHandler("login", login))
    application.add_handler(CommandHandler("logout", logout))
    application.add_handler(CommandHandler("whoami", whoami))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return application


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
    try:
        application = build_application()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    application.run_polling(allowed_updates=["message"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
