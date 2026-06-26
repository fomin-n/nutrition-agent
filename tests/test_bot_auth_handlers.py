import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.bot import handlers
from app.bot.rate_limit import UsageLimitResult


class FakeAuthService:
    def __init__(self, authorized: bool, *, login_ok: bool = True) -> None:
        self.authorized = authorized
        self.login_ok = login_ok
        self.revoked_users: list[int] = []
        self.login_keys: list[str] = []

    def is_authorized(self, telegram_user_id: int) -> bool:
        return self.authorized

    def login(
        self,
        *,
        raw_key: str,
        telegram_user_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ):
        self.login_keys.append(raw_key)
        self.authorized = self.login_ok
        return SimpleNamespace(ok=self.login_ok)

    def revoke_user(self, telegram_user_id: int) -> bool:
        self.revoked_users.append(telegram_user_id)
        self.authorized = False
        return True


class FakeRateLimitService:
    def __init__(self, result: UsageLimitResult | None = None) -> None:
        self.result = result or UsageLimitResult(allowed=True, reason="ok")
        self.user_ids: list[int] = []

    def check_and_increment(self, telegram_user_id: int) -> UsageLimitResult:
        self.user_ids.append(telegram_user_id)
        return self.result


class FakeMessage:
    def __init__(
        self,
        text: str | None = None,
        photo: list[object] | None = None,
        message_id: int | None = None,
        delete_raises: bool = False,
    ) -> None:
        self.text = text
        self.caption = None
        self.photo = photo or []
        self.message_id = message_id
        self.delete_raises = delete_raises
        self.deleted = False
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)

    async def delete(self) -> None:
        if self.delete_raises:
            raise RuntimeError("delete failed")
        self.deleted = True


class FakeBot:
    def __init__(self) -> None:
        self.actions: list[tuple[int, str]] = []

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        self.actions.append((chat_id, action))


class ExplodingPhoto:
    file_unique_id = "photo"

    async def get_file(self):
        raise AssertionError("unauthorized photo should not be downloaded")


def make_update(message: FakeMessage):
    return SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(id=1001, username="demo_user", full_name="Demo User"),
        effective_chat=SimpleNamespace(id=2001),
    )


@pytest.fixture(autouse=True)
def allow_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers, "get_rate_limit_service", lambda: FakeRateLimitService())


def test_unauthorized_text_does_not_call_agent_graph(monkeypatch) -> None:
    message = FakeMessage(text="200g rice and chicken")
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())

    monkeypatch.setattr(handlers, "get_auth_service", lambda: FakeAuthService(False))
    monkeypatch.setattr(
        handlers,
        "process_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("graph should not run")),
    )

    asyncio.run(handlers.handle_text(update, context))

    assert message.replies == [handlers.ACCESS_REQUIRED_MESSAGE]
    assert context.bot.actions == []


def test_unauthorized_photo_does_not_download_or_call_graph(monkeypatch) -> None:
    message = FakeMessage(photo=[ExplodingPhoto()])
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())

    monkeypatch.setattr(handlers, "get_auth_service", lambda: FakeAuthService(False))
    monkeypatch.setattr(
        handlers,
        "process_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("graph should not run")),
    )

    asyncio.run(handlers.handle_photo(update, context))

    assert message.replies == [handlers.ACCESS_REQUIRED_MESSAGE]
    assert context.bot.actions == []


def test_logout_revokes_current_user(monkeypatch) -> None:
    message = FakeMessage()
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    auth = FakeAuthService(True)
    monkeypatch.setattr(handlers, "get_auth_service", lambda: auth)

    asyncio.run(handlers.logout(update, context))

    assert auth.revoked_users == [1001]
    assert message.replies == ["Logged out."]


def test_authorized_text_passes_normalized_telegram_trace_metadata(monkeypatch) -> None:
    message = FakeMessage(text="100 g chicken", message_id=3001)
    message.message_thread_id = 77
    message.date = datetime(2026, 6, 24, 12, 30, tzinfo=UTC)
    message.media_group_id = None
    message.is_topic_message = True
    update = SimpleNamespace(
        update_id=4001,
        effective_message=message,
        effective_user=SimpleNamespace(
            id=1001,
            username="demo_user",
            first_name="Demo",
            last_name="Tester",
            full_name="Demo Tester",
            language_code="en",
            is_bot=False,
        ),
        effective_chat=SimpleNamespace(
            id=2001,
            type="supergroup",
            title="Nutrition QA",
            username=None,
            is_forum=True,
        ),
    )
    context = SimpleNamespace(bot=FakeBot())
    captured: dict[str, object] = {}

    def fake_process_request(**kwargs):
        captured.update(kwargs)
        return "Estimated."

    monkeypatch.setattr(handlers, "get_auth_service", lambda: FakeAuthService(True))
    monkeypatch.setattr(handlers, "process_request", fake_process_request)

    asyncio.run(handlers.handle_text(update, context))

    assert message.replies == ["Estimated."]
    assert captured["user_id"] == 1001
    assert captured["session_id"] == 2001
    assert captured["trace_metadata"] == {
        "telegram.update.id": 4001,
        "telegram.user.id": 1001,
        "telegram.user.username": "demo_user",
        "telegram.user.first_name": "Demo",
        "telegram.user.last_name": "Tester",
        "telegram.user.display_name": "Demo Tester",
        "telegram.user.language_code": "en",
        "telegram.user.is_bot": False,
        "telegram.chat.id": 2001,
        "telegram.chat.type": "supergroup",
        "telegram.chat.title": "Nutrition QA",
        "telegram.chat.is_forum": True,
        "telegram.conversation.id": 2001,
        "telegram.message.id": 3001,
        "telegram.message.thread_id": 77,
        "telegram.message.date": "2026-06-24T12:30:00+00:00",
        "telegram.message.is_topic_message": True,
    }


def test_login_deletes_access_key_message_after_success(monkeypatch) -> None:
    message = FakeMessage(text="/login raw-secret-key", message_id=3001)
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot(), args=["raw-secret-key"])
    auth = FakeAuthService(False, login_ok=True)
    monkeypatch.setattr(handlers, "get_auth_service", lambda: auth)

    asyncio.run(handlers.login(update, context))

    assert auth.login_keys == ["raw-secret-key"]
    assert message.replies == ["Access granted."]
    assert message.deleted


def test_login_deletes_access_key_message_after_failure(monkeypatch) -> None:
    message = FakeMessage(text="/login raw-secret-key", message_id=3001)
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot(), args=["raw-secret-key"])
    auth = FakeAuthService(False, login_ok=False)
    monkeypatch.setattr(handlers, "get_auth_service", lambda: auth)

    asyncio.run(handlers.login(update, context))

    assert message.replies == ["Invalid or expired access key."]
    assert message.deleted


def test_login_delete_failure_does_not_break_login(monkeypatch, caplog) -> None:
    message = FakeMessage(text="/login raw-secret-key", message_id=3001, delete_raises=True)
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot(), args=["raw-secret-key"])
    monkeypatch.setattr(handlers, "get_auth_service", lambda: FakeAuthService(False, login_ok=True))

    asyncio.run(handlers.login(update, context))

    assert message.replies == ["Access granted."]
    assert "Failed to delete login message" in caplog.text
    assert "raw-secret-key" not in caplog.text


def test_authorized_text_rate_limited_before_graph(monkeypatch) -> None:
    message = FakeMessage(text="Estimate calories for chicken")
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    limiter = FakeRateLimitService(
        UsageLimitResult(allowed=False, reason="user_daily_limit", limit=1)
    )
    monkeypatch.setattr(handlers, "get_auth_service", lambda: FakeAuthService(True))
    monkeypatch.setattr(handlers, "get_rate_limit_service", lambda: limiter)
    monkeypatch.setattr(
        handlers,
        "process_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("graph should not run")),
    )

    asyncio.run(handlers.handle_text(update, context))

    assert limiter.user_ids == [1001]
    assert message.replies == [
        "Daily request limit reached. Please try again tomorrow or ask the administrator to raise it."
    ]
    assert context.bot.actions == []


def test_russian_rate_limit_message_is_localized(monkeypatch) -> None:
    message = FakeMessage(text="Сколько калорий в яблоке?")
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    monkeypatch.setattr(handlers, "get_auth_service", lambda: FakeAuthService(True))
    monkeypatch.setattr(
        handlers,
        "get_rate_limit_service",
        lambda: FakeRateLimitService(
            UsageLimitResult(allowed=False, reason="user_daily_limit", limit=1)
        ),
    )

    asyncio.run(handlers.handle_text(update, context))

    assert message.replies == [
        "Дневной лимит запросов исчерпан. Попробуйте завтра или попросите "
        "администратора увеличить лимит."
    ]
    assert context.bot.actions == []


def test_rate_limited_photo_does_not_download_or_call_graph(monkeypatch) -> None:
    message = FakeMessage(photo=[ExplodingPhoto()])
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    monkeypatch.setattr(handlers, "get_auth_service", lambda: FakeAuthService(True))
    monkeypatch.setattr(
        handlers,
        "get_rate_limit_service",
        lambda: FakeRateLimitService(
            UsageLimitResult(allowed=False, reason="global_daily_limit", limit=1)
        ),
    )
    monkeypatch.setattr(
        handlers,
        "process_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("graph should not run")),
    )

    asyncio.run(handlers.handle_photo(update, context))

    assert message.replies == [
        "Daily request limit reached. Please try again tomorrow or ask the administrator to raise it."
    ]
    assert context.bot.actions == []
