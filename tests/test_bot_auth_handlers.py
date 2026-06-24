import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from app.bot import handlers


class FakeAuthService:
    def __init__(self, authorized: bool) -> None:
        self.authorized = authorized
        self.revoked_users: list[int] = []

    def is_authorized(self, telegram_user_id: int) -> bool:
        return self.authorized

    def revoke_user(self, telegram_user_id: int) -> bool:
        self.revoked_users.append(telegram_user_id)
        self.authorized = False
        return True


class FakeMessage:
    def __init__(
        self,
        text: str | None = None,
        photo: list[object] | None = None,
        message_id: int | None = None,
    ) -> None:
        self.text = text
        self.caption = None
        self.photo = photo or []
        self.message_id = message_id
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


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
