import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from math import ceil
from pathlib import Path
from typing import Literal

from app.llm.client import get_settings

LimitReason = Literal[
    "ok",
    "disabled",
    "user_daily_limit",
    "global_daily_limit",
    "user_minute_limit",
    "user_daily_photo_limit",
]
AdminUsageAlert = Literal["global_warning", "global_exhausted"]


@dataclass(frozen=True)
class UsageLimitConfig:
    daily_user_request_limit: int = 100
    daily_global_request_limit: int = 1000
    per_minute_user_request_limit: int = 6
    daily_user_photo_limit: int = 25
    global_warning_ratio: float = 0.8


@dataclass(frozen=True)
class UsageLimitResult:
    allowed: bool
    reason: LimitReason
    user_count: int = 0
    global_count: int = 0
    minute_count: int = 0
    photo_count: int = 0
    limit: int | None = None
    admin_alert: AdminUsageAlert | None = None


class UsageLimitService:
    def __init__(self, db_path: str | Path, config: UsageLimitConfig | None = None) -> None:
        self.db_path = Path(db_path)
        self.config = config or UsageLimitConfig()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._harden_permissions()

    @classmethod
    def from_settings(cls) -> "UsageLimitService":
        settings = get_settings()
        db_path = settings.usage_db_path or str(Path(settings.auth_db_path).with_name("usage.sqlite3"))
        return cls(
            db_path,
            UsageLimitConfig(
                daily_user_request_limit=settings.bot_daily_user_request_limit,
                daily_global_request_limit=settings.bot_daily_global_request_limit,
                per_minute_user_request_limit=settings.bot_user_burst_request_limit_per_minute,
                daily_user_photo_limit=settings.bot_daily_user_photo_limit,
                global_warning_ratio=settings.bot_global_usage_warning_ratio,
            ),
        )

    def check_and_increment(
        self,
        telegram_user_id: int,
        *,
        has_image: bool = False,
        now: datetime | None = None,
    ) -> UsageLimitResult:
        user_limit = self.config.daily_user_request_limit
        global_limit = self.config.daily_global_request_limit
        minute_limit = self.config.per_minute_user_request_limit
        photo_limit = self.config.daily_user_photo_limit
        if user_limit <= 0 and global_limit <= 0 and minute_limit <= 0 and photo_limit <= 0:
            return UsageLimitResult(allowed=True, reason="disabled")

        current_time = now or datetime.now(UTC)
        day = current_time.date().isoformat()
        minute = current_time.strftime("%Y-%m-%dT%H:%MZ")
        updated_at = current_time.isoformat(timespec="seconds")
        user_key = str(telegram_user_id)

        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user_count = self._count(conn, day=day, scope="user", key=user_key)
            global_count = self._count(conn, day=day, scope="global", key="all")
            minute_count = self._count(conn, day=minute, scope="user_minute", key=user_key)
            photo_count = self._count(conn, day=day, scope="user_photo", key=user_key)

            if minute_limit > 0 and minute_count >= minute_limit:
                return UsageLimitResult(
                    allowed=False,
                    reason="user_minute_limit",
                    user_count=user_count,
                    global_count=global_count,
                    minute_count=minute_count,
                    photo_count=photo_count,
                    limit=minute_limit,
                )

            if user_limit > 0 and user_count >= user_limit:
                return UsageLimitResult(
                    allowed=False,
                    reason="user_daily_limit",
                    user_count=user_count,
                    global_count=global_count,
                    minute_count=minute_count,
                    photo_count=photo_count,
                    limit=user_limit,
                )
            if has_image and photo_limit > 0 and photo_count >= photo_limit:
                return UsageLimitResult(
                    allowed=False,
                    reason="user_daily_photo_limit",
                    user_count=user_count,
                    global_count=global_count,
                    minute_count=minute_count,
                    photo_count=photo_count,
                    limit=photo_limit,
                )
            if global_limit > 0 and global_count >= global_limit:
                reserved_admin_alert = self._reserve_notification(
                    conn,
                    day=day,
                    event="global_exhausted",
                    updated_at=updated_at,
                )
                return UsageLimitResult(
                    allowed=False,
                    reason="global_daily_limit",
                    user_count=user_count,
                    global_count=global_count,
                    minute_count=minute_count,
                    photo_count=photo_count,
                    limit=global_limit,
                    admin_alert="global_exhausted" if reserved_admin_alert else None,
                )

            if minute_limit > 0:
                minute_count = self._increment(
                    conn,
                    day=minute,
                    scope="user_minute",
                    key=user_key,
                    updated_at=updated_at,
                )
            if user_limit > 0:
                user_count = self._increment(
                    conn,
                    day=day,
                    scope="user",
                    key=user_key,
                    updated_at=updated_at,
                )
            if has_image and photo_limit > 0:
                photo_count = self._increment(
                    conn,
                    day=day,
                    scope="user_photo",
                    key=user_key,
                    updated_at=updated_at,
                )
            if global_limit > 0:
                global_count = self._increment(
                    conn,
                    day=day,
                    scope="global",
                    key="all",
                    updated_at=updated_at,
                )

            admin_alert: AdminUsageAlert | None = None
            warning_threshold = _warning_threshold(global_limit, self.config.global_warning_ratio)
            should_warn = bool(global_limit > 0 and warning_threshold and global_count >= warning_threshold)
            if should_warn and self._reserve_notification(
                conn,
                day=day,
                event="global_warning",
                updated_at=updated_at,
            ):
                admin_alert = "global_warning"
            if global_limit > 0 and global_count >= global_limit and self._reserve_notification(
                conn,
                day=day,
                event="global_exhausted",
                updated_at=updated_at,
            ):
                admin_alert = "global_exhausted"

            return UsageLimitResult(
                allowed=True,
                reason="ok",
                user_count=user_count,
                global_count=global_count,
                minute_count=minute_count,
                photo_count=photo_count,
                admin_alert=admin_alert,
            )

    def _count(self, conn: sqlite3.Connection, *, day: str, scope: str, key: str) -> int:
        row = conn.execute(
            """
            SELECT request_count
            FROM usage_counters
            WHERE day = ? AND scope = ? AND key = ?
            """,
            (day, scope, key),
        ).fetchone()
        return int(row["request_count"]) if row else 0

    def _increment(
        self,
        conn: sqlite3.Connection,
        *,
        day: str,
        scope: str,
        key: str,
        updated_at: str,
    ) -> int:
        conn.execute(
            """
            INSERT INTO usage_counters (day, scope, key, request_count, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(day, scope, key) DO UPDATE SET
                request_count = usage_counters.request_count + 1,
                updated_at = excluded.updated_at
            """,
            (day, scope, key, updated_at),
        )
        return self._count(conn, day=day, scope=scope, key=key)

    def _reserve_notification(
        self,
        conn: sqlite3.Connection,
        *,
        day: str,
        event: str,
        updated_at: str,
    ) -> bool:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO usage_notifications (day, event, sent_at)
            VALUES (?, ?, ?)
            """,
            (day, event, updated_at),
        )
        return cursor.rowcount > 0

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as conn, conn:
            yield conn

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            self._migrate_usage_counters_if_needed(conn)
            self._create_schema(conn)

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS usage_counters (
                day TEXT NOT NULL,
                scope TEXT NOT NULL,
                key TEXT NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (day, scope, key)
            );

            CREATE TABLE IF NOT EXISTS usage_notifications (
                day TEXT NOT NULL,
                event TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (day, event)
            );
            """
        )

    def _migrate_usage_counters_if_needed(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'usage_counters'
            """
        ).fetchone()
        if not row or "CHECK(scope IN" not in str(row["sql"]):
            return
        conn.execute("ALTER TABLE usage_counters RENAME TO usage_counters_old")
        self._create_schema(conn)
        conn.execute(
            """
            INSERT INTO usage_counters (day, scope, key, request_count, updated_at)
            SELECT day, scope, key, request_count, updated_at
            FROM usage_counters_old
            """
        )
        conn.execute("DROP TABLE usage_counters_old")

    def _harden_permissions(self) -> None:
        try:
            self.db_path.parent.chmod(0o700)
            self.db_path.chmod(0o600)
        except OSError:
            pass


@lru_cache(maxsize=1)
def get_usage_limit_service() -> UsageLimitService:
    return UsageLimitService.from_settings()


def _warning_threshold(limit: int, ratio: float) -> int | None:
    if limit <= 0 or ratio <= 0:
        return None
    return max(1, min(limit, ceil(limit * ratio)))
