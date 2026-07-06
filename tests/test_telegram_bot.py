import pytest
from pydantic import SecretStr

from app.bot import handlers, telegram_bot
from app.llm.client import Settings


@pytest.fixture(autouse=True)
def disable_usage_prune(monkeypatch) -> None:
    monkeypatch.setattr(telegram_bot, "_prune_usage_if_configured", lambda _days: None)


def test_settings_default_access_mode_is_open(monkeypatch) -> None:
    monkeypatch.delenv("BOT_ACCESS_MODE", raising=False)

    assert Settings(_env_file=None).bot_access_mode == "open"


def test_settings_default_concurrency_is_bounded(monkeypatch) -> None:
    monkeypatch.delenv("BOT_CONCURRENT_UPDATES", raising=False)
    monkeypatch.delenv("BOT_PER_USER_IN_FLIGHT_LIMIT", raising=False)

    settings = Settings(_env_file=None)

    assert settings.bot_concurrent_updates == 8
    assert settings.bot_per_user_in_flight_limit == 1


def test_settings_default_usage_counter_retention_is_bounded(monkeypatch) -> None:
    monkeypatch.delenv("USAGE_COUNTER_RETENTION_DAYS", raising=False)

    assert Settings(_env_file=None).usage_counter_retention_days == 7


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
    assert application.concurrent_updates == 8


def test_build_application_uses_configured_concurrent_updates(monkeypatch) -> None:
    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: Settings(
            telegram_bot_token=SecretStr("123456:TEST"),
            bot_auth_secret=SecretStr("test-secret"),
            bot_concurrent_updates=1,
        ),
    )
    monkeypatch.setattr(telegram_bot, "configure_phoenix_tracing", lambda _settings: None)
    monkeypatch.setattr(
        telegram_bot.AuthService,
        "from_settings",
        classmethod(lambda cls, **kwargs: object()),
    )

    application = telegram_bot.build_application()

    assert application.concurrent_updates == 1


def test_configure_default_executor_uses_configured_workers(monkeypatch) -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self.executor = None

        def set_default_executor(self, executor) -> None:
            self.executor = executor

    fake_loop = FakeLoop()
    monkeypatch.setattr(telegram_bot, "_get_or_create_event_loop", lambda: fake_loop)

    executor = telegram_bot.configure_default_executor(3)
    try:
        assert fake_loop.executor is executor
        assert executor._max_workers == 3
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


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


def test_build_application_prunes_usage_when_retention_enabled(monkeypatch) -> None:
    pruned: list[int] = []
    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: Settings(
            telegram_bot_token=SecretStr("123456:TEST"),
            bot_auth_secret=SecretStr("test-secret"),
            usage_counter_retention_days=9,
        ),
    )
    monkeypatch.setattr(telegram_bot, "_prune_usage_if_configured", lambda days: pruned.append(days))
    monkeypatch.setattr(telegram_bot, "configure_phoenix_tracing", lambda _settings: None)
    monkeypatch.setattr(
        telegram_bot.AuthService,
        "from_settings",
        classmethod(lambda cls, **kwargs: object()),
    )

    telegram_bot.build_application()

    assert pruned == [9]
