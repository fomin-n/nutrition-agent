import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.llm.client import get_settings

LimitReason = Literal["ok", "disabled", "user_daily_limit", "global_daily_limit"]


@dataclass(frozen=True)
class UsageLimitConfig:
    daily_user_request_limit: int = 100
    daily_global_request_limit: int = 1000


@dataclass(frozen=True)
class UsageLimitResult:
    allowed: bool
    reason: LimitReason
    user_count: int = 0
    global_count: int = 0
    limit: int | None = None


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
            ),
        )

    def check_and_increment(
        self,
        telegram_user_id: int,
        *,
        now: datetime | None = None,
    ) -> UsageLimitResult:
        user_limit = self.config.daily_user_request_limit
        global_limit = self.config.daily_global_request_limit
        if user_limit <= 0 and global_limit <= 0:
            return UsageLimitResult(allowed=True, reason="disabled")

        current_time = now or datetime.now(UTC)
        day = current_time.date().isoformat()
        updated_at = current_time.isoformat(timespec="seconds")
        user_key = str(telegram_user_id)

        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user_count = self._count(conn, day=day, scope="user", key=user_key)
            global_count = self._count(conn, day=day, scope="global", key="all")

            if user_limit > 0 and user_count >= user_limit:
                return UsageLimitResult(
                    allowed=False,
                    reason="user_daily_limit",
                    user_count=user_count,
                    global_count=global_count,
                    limit=user_limit,
                )
            if global_limit > 0 and global_count >= global_limit:
                return UsageLimitResult(
                    allowed=False,
                    reason="global_daily_limit",
                    user_count=user_count,
                    global_count=global_count,
                    limit=global_limit,
                )

            user_count = self._increment(conn, day=day, scope="user", key=user_key, updated_at=updated_at)
            global_count = self._increment(
                conn,
                day=day,
                scope="global",
                key="all",
                updated_at=updated_at,
            )
            return UsageLimitResult(
                allowed=True,
                reason="ok",
                user_count=user_count,
                global_count=global_count,
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

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as conn, conn:
            yield conn

    def _init_db(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS usage_counters (
                    day TEXT NOT NULL,
                    scope TEXT NOT NULL CHECK(scope IN ('user', 'global')),
                    key TEXT NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (day, scope, key)
                );
                """
            )

    def _harden_permissions(self) -> None:
        try:
            self.db_path.parent.chmod(0o700)
            self.db_path.chmod(0o600)
        except OSError:
            pass


@lru_cache(maxsize=1)
def get_usage_limit_service() -> UsageLimitService:
    return UsageLimitService.from_settings()
