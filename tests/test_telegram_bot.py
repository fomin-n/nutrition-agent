from pydantic import SecretStr

from app.bot import handlers, telegram_bot
from app.llm.client import Settings


def test_settings_default_access_mode_is_open(monkeypatch) -> None:
    monkeypatch.delenv("BOT_ACCESS_MODE", raising=False)

    assert Settings(_env_file=None).bot_access_mode == "open"


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


def test_build_application_prunes_memory_when_retention_enabled(monkeypatch) -> None:
    pruned: list[int] = []
    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: Settings(
            telegram_bot_token=SecretStr("123456:TEST"),
            bot_auth_secret=SecretStr("test-secret"),
            memory_retention_days=14,
        ),
    )
    monkeypatch.setattr(telegram_bot, "configure_phoenix_tracing", lambda _settings: None)
    monkeypatch.setattr(
        telegram_bot.AuthService,
        "from_settings",
        classmethod(lambda cls, **kwargs: object()),
    )
    monkeypatch.setattr(
        telegram_bot,
        "get_memory_service",
        lambda: type("FakeMemory", (), {"prune_older_than": lambda self, days: pruned.append(days) or 2})(),
    )

    telegram_bot.build_application()

    assert pruned == [14]
