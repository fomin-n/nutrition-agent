from pydantic import SecretStr

from app.bot import handlers, telegram_bot
from app.llm.client import Settings


def test_build_application_registers_global_error_handler(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: Settings(
            telegram_bot_token=SecretStr("123456:TEST"),
            bot_auth_secret=SecretStr("test-secret"),
        ),
    )
    monkeypatch.setattr(telegram_bot, "configure_phoenix_tracing", lambda _settings: None)
    monkeypatch.setattr(
        telegram_bot.AuthService,
        "from_settings",
        classmethod(lambda cls: object()),
    )

    application = telegram_bot.build_application()

    assert handlers.handle_error in application.error_handlers
