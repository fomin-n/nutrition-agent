import asyncio
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
    def __init__(self, text: str | None = None, photo: list[object] | None = None) -> None:
        self.text = text
        self.caption = None
        self.photo = photo or []
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
