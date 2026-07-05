import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bot import handlers
from app.bot.rate_limit import UsageLimitResult


class FakeAuthService:
    def __init__(self, authorized: bool, *, login_ok: bool = True, banned: bool = False) -> None:
        self.authorized = authorized
        self.login_ok = login_ok
        self.banned = banned
        self.revoked_users: list[int] = []
        self.login_keys: list[str] = []

    def is_authorized(self, telegram_user_id: int) -> bool:
        return self.authorized

    def is_banned(self, telegram_user_id: int) -> bool:
        return self.banned

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
        self.has_image_values: list[bool] = []

    def check_and_increment(self, telegram_user_id: int, *, has_image: bool = False) -> UsageLimitResult:
        self.user_ids.append(telegram_user_id)
        self.has_image_values.append(has_image)
        return self.result


class FakeMessage:
    def __init__(
        self,
        text: str | None = None,
        photo: list[object] | None = None,
        message_id: int | None = None,
        delete_raises: bool = False,
        reply_raises: bool = False,
        media_group_id: str | None = None,
    ) -> None:
        self.text = text
        self.caption = None
        self.photo = photo or []
        self.message_id = message_id
        self.media_group_id = media_group_id
        self.delete_raises = delete_raises
        self.reply_raises = reply_raises
        self.deleted = False
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        if self.reply_raises:
            raise RuntimeError("reply failed")
        self.replies.append(text)

    async def delete(self) -> None:
        if self.delete_raises:
            raise RuntimeError("delete failed")
        self.deleted = True


class FakeBot:
    def __init__(self) -> None:
        self.actions: list[tuple[int, str]] = []
        self.messages: list[tuple[int | str, str]] = []

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        self.actions.append((chat_id, action))

    async def send_message(self, *, chat_id: int | str, text: str) -> None:
        self.messages.append((chat_id, text))


class ExplodingPhoto:
    file_unique_id = "photo"

    async def get_file(self):
        raise AssertionError("unauthorized photo should not be downloaded")


class FakeTelegramFile:
    def __init__(self) -> None:
        self.download_paths: list[Path] = []

    async def download_to_drive(self, *, custom_path: str) -> None:
        path = Path(custom_path)
        self.download_paths.append(path)
        path.write_bytes(b"fake image")


class DownloadablePhoto:
    file_unique_id = "configured-photo"

    def __init__(self, telegram_file: FakeTelegramFile) -> None:
        self.telegram_file = telegram_file

    async def get_file(self) -> FakeTelegramFile:
        return self.telegram_file


def make_update(message: FakeMessage):
    return SimpleNamespace(
        effective_message=message,
        effective_user=SimpleNamespace(
            id=1001,
            username="demo_user",
            full_name="Demo User",
            language_code="en",
        ),
        effective_chat=SimpleNamespace(id=2001, type="private"),
    )


@pytest.fixture(autouse=True)
def allow_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers, "get_rate_limit_service", lambda: FakeRateLimitService())


def test_unauthorized_text_does_not_call_agent_graph(monkeypatch) -> None:
    message = FakeMessage(text="200g rice and chicken")
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())

    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(False))
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

    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(False))
    monkeypatch.setattr(
        handlers,
        "process_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("graph should not run")),
    )

    asyncio.run(handlers.handle_photo(update, context))

    assert message.replies == [handlers.ACCESS_REQUIRED_MESSAGE]
    assert context.bot.actions == []


def test_open_mode_text_allows_user_without_access_key(monkeypatch) -> None:
    message = FakeMessage(text="100 g chicken", message_id=3001)
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    captured: dict[str, object] = {}

    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(bot_access_mode="open"))
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(False))

    def fake_process_request(**kwargs):
        captured.update(kwargs)
        return "Estimated."

    monkeypatch.setattr(handlers, "process_request", fake_process_request)

    asyncio.run(handlers.handle_text(update, context))

    assert message.replies == ["Estimated."]
    assert captured["text"] == "100 g chicken"


def test_banned_user_is_refused_before_quota_or_graph(monkeypatch) -> None:
    message = FakeMessage(text="100 g chicken")
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    limiter = FakeRateLimitService()

    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True, banned=True))
    monkeypatch.setattr(handlers, "get_rate_limit_service", lambda: limiter)
    monkeypatch.setattr(
        handlers,
        "process_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("graph should not run")),
    )

    asyncio.run(handlers.handle_text(update, context))

    assert message.replies == [handlers.BANNED_MESSAGE]
    assert limiter.user_ids == []
    assert context.bot.actions == []


def test_logout_revokes_current_user(monkeypatch) -> None:
    message = FakeMessage()
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    auth = FakeAuthService(True)
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: auth)

    asyncio.run(handlers.logout(update, context))

    assert auth.revoked_users == [1001]
    assert message.replies == ["Logged out."]


def test_open_mode_logout_is_noop(monkeypatch) -> None:
    message = FakeMessage()
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    auth = FakeAuthService(False)
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(bot_access_mode="open"))
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: auth)

    asyncio.run(handlers.logout(update, context))

    assert auth.revoked_users == []
    assert message.replies == [handlers.OPEN_LOGOUT_MESSAGE]


def test_russian_start_message_in_open_mode(monkeypatch) -> None:
    message = FakeMessage(text="/start")
    update = make_update(message)
    update.effective_user.language_code = "ru"
    context = SimpleNamespace(bot=FakeBot())
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(bot_access_mode="open"))
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(False))

    asyncio.run(handlers.start(update, context))

    assert "Опишите блюдо" in message.replies[0]
    assert "/privacy" in message.replies[0]
    assert "/forget" in message.replies[0]


def test_privacy_message_is_available_without_invite_auth(monkeypatch) -> None:
    message = FakeMessage(text="/privacy")
    update = make_update(message)
    update.effective_user.language_code = "ru"
    context = SimpleNamespace(bot=FakeBot())
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(False))

    asyncio.run(handlers.privacy(update, context))

    assert "недавние сообщения" in message.replies[0]
    assert "/forget" in message.replies[0]


def test_open_mode_login_replies_no_key_needed_and_deletes_message(monkeypatch) -> None:
    message = FakeMessage(text="/login raw-secret-key", message_id=3001)
    update = make_update(message)
    update.effective_user.language_code = "ru"
    context = SimpleNamespace(bot=FakeBot(), args=["raw-secret-key"])
    auth = FakeAuthService(False)
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(bot_access_mode="open"))
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: auth)

    asyncio.run(handlers.login(update, context))

    assert auth.login_keys == []
    assert message.replies == ["Доступ открыт. Ключ не нужен."]
    assert message.deleted


def test_open_mode_whoami_is_localized(monkeypatch) -> None:
    message = FakeMessage(text="/whoami")
    update = make_update(message)
    update.effective_user.language_code = "ru"
    context = SimpleNamespace(bot=FakeBot())
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(bot_access_mode="open"))
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(False))

    asyncio.run(handlers.whoami(update, context))

    assert "Режим доступа: open" in message.replies[0]
    assert "Статус: разрешён" in message.replies[0]


def test_authorized_text_passes_normalized_telegram_trace_metadata(monkeypatch) -> None:
    message = FakeMessage(text="100 g chicken", message_id=3001)
    message.message_thread_id = None
    message.date = datetime(2026, 6, 24, 12, 30, tzinfo=UTC)
    message.media_group_id = None
    message.is_topic_message = False
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
            type="private",
            title=None,
            username=None,
            is_forum=False,
        ),
    )
    context = SimpleNamespace(bot=FakeBot())
    captured: dict[str, object] = {}

    def fake_process_request(**kwargs):
        captured.update(kwargs)
        return "Estimated."

    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))
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
        "telegram.chat.type": "private",
        "telegram.chat.is_forum": False,
        "telegram.conversation.id": 2001,
        "telegram.message.id": 3001,
        "telegram.message.date": "2026-06-24T12:30:00+00:00",
        "telegram.message.is_topic_message": False,
    }


def test_login_deletes_access_key_message_after_success(monkeypatch) -> None:
    message = FakeMessage(text="/login raw-secret-key", message_id=3001)
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot(), args=["raw-secret-key"])
    auth = FakeAuthService(False, login_ok=True)
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: auth)

    asyncio.run(handlers.login(update, context))

    assert auth.login_keys == ["raw-secret-key"]
    assert message.replies == ["Access granted."]
    assert message.deleted


def test_login_deletes_access_key_message_after_failure(monkeypatch) -> None:
    message = FakeMessage(text="/login raw-secret-key", message_id=3001)
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot(), args=["raw-secret-key"])
    auth = FakeAuthService(False, login_ok=False)
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: auth)

    asyncio.run(handlers.login(update, context))

    assert message.replies == ["Invalid or expired access key."]
    assert message.deleted


def test_login_delete_failure_does_not_break_login(monkeypatch, caplog) -> None:
    message = FakeMessage(text="/login raw-secret-key", message_id=3001, delete_raises=True)
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot(), args=["raw-secret-key"])
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(False, login_ok=True))

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
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))
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
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))
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
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))
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

    assert message.replies == ["The bot is at capacity today. Please come back tomorrow."]
    assert context.bot.actions == []


def test_photo_limit_message_does_not_download(monkeypatch) -> None:
    message = FakeMessage(photo=[ExplodingPhoto()])
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))
    monkeypatch.setattr(
        handlers,
        "get_rate_limit_service",
        lambda: FakeRateLimitService(
            UsageLimitResult(allowed=False, reason="user_daily_photo_limit", limit=1)
        ),
    )

    asyncio.run(handlers.handle_photo(update, context))

    assert message.replies == [
        "Daily photo limit reached. You can still send text meal descriptions or try photos tomorrow."
    ]
    assert context.bot.actions == []


def test_album_photo_is_rejected_before_quota_or_download(monkeypatch) -> None:
    message = FakeMessage(photo=[ExplodingPhoto()], media_group_id="album-1")
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    limiter = FakeRateLimitService()
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))
    monkeypatch.setattr(handlers, "get_rate_limit_service", lambda: limiter)

    asyncio.run(handlers.handle_photo(update, context))

    assert message.replies == [handlers.ALBUM_REJECTED_MESSAGE]
    assert limiter.user_ids == []
    assert context.bot.actions == []


def test_group_text_message_is_ignored_before_quota_or_graph(monkeypatch) -> None:
    message = FakeMessage(text="100 g chicken")
    update = make_update(message)
    update.effective_chat.type = "group"
    context = SimpleNamespace(bot=FakeBot())
    limiter = FakeRateLimitService()
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))
    monkeypatch.setattr(handlers, "get_rate_limit_service", lambda: limiter)
    monkeypatch.setattr(
        handlers,
        "process_request",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("graph should not run")),
    )

    asyncio.run(handlers.handle_text(update, context))

    assert message.replies == []
    assert limiter.user_ids == []
    assert context.bot.actions == []


def test_group_command_gets_private_chat_restriction(monkeypatch) -> None:
    message = FakeMessage(text="/start")
    update = make_update(message)
    update.effective_chat.type = "supergroup"
    context = SimpleNamespace(bot=FakeBot())
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))

    asyncio.run(handlers.start(update, context))

    assert message.replies == [handlers.PRIVATE_CHAT_ONLY_MESSAGE]


def test_global_usage_alert_sends_admin_message(monkeypatch, caplog) -> None:
    message = FakeMessage(text="100 g chicken")
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))
    monkeypatch.setattr(
        handlers,
        "get_rate_limit_service",
        lambda: FakeRateLimitService(
            UsageLimitResult(
                allowed=True,
                reason="ok",
                global_count=8,
                limit=10,
                admin_alert="global_warning",
            )
        ),
    )
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(bot_admin_chat_id="999"))
    monkeypatch.setattr(handlers, "process_request", lambda **kwargs: "Estimated.")

    asyncio.run(handlers.handle_text(update, context))

    assert message.replies == ["Estimated."]
    assert context.bot.messages == [
        ("999", "nutrition-agent usage alert: global_warning; global_count=8; limit=10")
    ]
    assert "Telegram usage alert event=global_warning" in caplog.text


def test_authorized_photo_uses_configured_temp_image_dir(monkeypatch, tmp_path) -> None:
    telegram_file = FakeTelegramFile()
    message = FakeMessage(photo=[DownloadablePhoto(telegram_file)], message_id=3001)
    message.caption = "100g apple"
    update = make_update(message)
    context = SimpleNamespace(bot=FakeBot())
    configured_base = tmp_path / "configured-images"
    captured: dict[str, object] = {}

    def fake_process_request(**kwargs):
        captured.update(kwargs)
        return "Estimated."

    monkeypatch.setattr(handlers, "get_auth_service", lambda **_: FakeAuthService(True))
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(temp_image_dir=str(configured_base)))
    monkeypatch.setattr(handlers, "process_request", fake_process_request)

    asyncio.run(handlers.handle_photo(update, context))

    assert message.replies == ["Estimated."]
    assert configured_base.exists()
    assert len(telegram_file.download_paths) == 1
    downloaded_path = telegram_file.download_paths[0]
    assert configured_base in downloaded_path.parents
    assert captured["image_path"] == str(downloaded_path)
    assert not downloaded_path.exists()
    assert not downloaded_path.parent.exists()


def test_global_error_handler_replies_without_logging_raw_message(caplog) -> None:
    message = FakeMessage(text="/login raw-secret-key", message_id=3001)
    update = make_update(message)
    update.update_id = 4001
    context = SimpleNamespace(error=RuntimeError("raw-secret-key"))

    asyncio.run(handlers.handle_error(update, context))

    assert message.replies == [handlers.TEMPORARY_ERROR_MESSAGE]
    assert "Unhandled Telegram update error" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "raw-secret-key" not in caplog.text


def test_global_error_handler_localizes_russian_fallback() -> None:
    message = FakeMessage(text="Сколько калорий в яблоке?", message_id=3001)
    update = make_update(message)
    context = SimpleNamespace(error=TimeoutError("timeout"))

    asyncio.run(handlers.handle_error(update, context))

    assert message.replies == [handlers.TEMPORARY_ERROR_MESSAGE_RU]


def test_global_error_handler_swallows_reply_failure(caplog) -> None:
    message = FakeMessage(text="100 g chicken", message_id=3001, reply_raises=True)
    update = make_update(message)
    context = SimpleNamespace(error=TimeoutError("update failed"))

    asyncio.run(handlers.handle_error(update, context))

    assert "Unhandled Telegram update error" in caplog.text
    assert "Failed to send Telegram error fallback" in caplog.text
    assert "update failed" not in caplog.text
    assert "100 g chicken" not in caplog.text
