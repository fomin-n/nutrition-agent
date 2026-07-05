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
        classmethod(lambda cls, **kwargs: object()),
    )

    application = telegram_bot.build_application()

    assert handlers.handle_error in application.error_handlers


def test_build_application_open_mode_does_not_require_auth_secret(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: Settings(
            telegram_bot_token=SecretStr("123456:TEST"),
            bot_access_mode="open",
        ),
    )
    monkeypatch.setattr(telegram_bot, "configure_phoenix_tracing", lambda _settings: None)
    monkeypatch.setattr(
        telegram_bot.AuthService,
        "from_settings",
        classmethod(lambda cls, *, require_secret=True: calls.append(require_secret) or object()),
    )

    telegram_bot.build_application()

    assert calls == [False]


def test_build_application_invite_mode_requires_auth_secret(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: Settings(
            telegram_bot_token=SecretStr("123456:TEST"),
            bot_access_mode="invite",
            bot_auth_secret=SecretStr("test-secret"),
        ),
    )
    monkeypatch.setattr(telegram_bot, "configure_phoenix_tracing", lambda _settings: None)
    monkeypatch.setattr(
        telegram_bot.AuthService,
        "from_settings",
        classmethod(lambda cls, *, require_secret=True: calls.append(require_secret) or object()),
    )

    telegram_bot.build_application()

    assert calls == [True]
