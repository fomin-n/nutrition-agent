from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class TelegramRequestContext:
    """Normalized, metadata-only context for one Telegram update."""

    update_id: int | None = None
    user_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    display_name: str | None = None
    user_language_code: str | None = None
    user_is_bot: bool | None = None
    chat_id: int | None = None
    chat_type: str | None = None
    chat_title: str | None = None
    chat_username: str | None = None
    chat_is_forum: bool | None = None
    message_id: int | None = None
    message_thread_id: int | None = None
    message_date: str | None = None
    media_group_id: str | None = None
    is_topic_message: bool | None = None

    @property
    def session_id(self) -> int | None:
        return self.chat_id

    @classmethod
    def from_update(cls, update: Any) -> TelegramRequestContext:
        user = getattr(update, "effective_user", None)
        chat = getattr(update, "effective_chat", None)
        message = getattr(update, "effective_message", None)
        return cls(
            update_id=_optional_int(getattr(update, "update_id", None)),
            user_id=_optional_int(getattr(user, "id", None)),
            username=_optional_str(getattr(user, "username", None)),
            first_name=_optional_str(getattr(user, "first_name", None)),
            last_name=_optional_str(getattr(user, "last_name", None)),
            display_name=_optional_str(getattr(user, "full_name", None)),
            user_language_code=_optional_str(getattr(user, "language_code", None)),
            user_is_bot=_optional_bool(getattr(user, "is_bot", None)),
            chat_id=_optional_int(getattr(chat, "id", None)),
            chat_type=_optional_str(getattr(chat, "type", None)),
            chat_title=_optional_str(getattr(chat, "title", None)),
            chat_username=_optional_str(getattr(chat, "username", None)),
            chat_is_forum=_optional_bool(getattr(chat, "is_forum", None)),
            message_id=_optional_int(getattr(message, "message_id", None)),
            message_thread_id=_optional_int(getattr(message, "message_thread_id", None)),
            message_date=_optional_datetime(getattr(message, "date", None)),
            media_group_id=_optional_str(getattr(message, "media_group_id", None)),
            is_topic_message=_optional_bool(getattr(message, "is_topic_message", None)),
        )

    def to_trace_metadata(self) -> dict[str, str | int | float | bool | None]:
        values: dict[str, str | int | bool | None] = {
            "telegram.update.id": self.update_id,
            "telegram.user.id": self.user_id,
            "telegram.user.username": self.username,
            "telegram.user.first_name": self.first_name,
            "telegram.user.last_name": self.last_name,
            "telegram.user.display_name": self.display_name,
            "telegram.user.language_code": self.user_language_code,
            "telegram.user.is_bot": self.user_is_bot,
            "telegram.chat.id": self.chat_id,
            "telegram.chat.type": self.chat_type,
            "telegram.chat.title": self.chat_title,
            "telegram.chat.username": self.chat_username,
            "telegram.chat.is_forum": self.chat_is_forum,
            "telegram.conversation.id": self.session_id,
            "telegram.message.id": self.message_id,
            "telegram.message.thread_id": self.message_thread_id,
            "telegram.message.date": self.message_date,
            "telegram.message.media_group_id": self.media_group_id,
            "telegram.message.is_topic_message": self.is_topic_message,
        }
        return {key: value for key, value in values.items() if value is not None}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return _optional_str(value)
