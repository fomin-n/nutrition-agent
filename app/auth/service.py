import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.llm.client import get_settings, reveal_secret


class AuthConfigurationError(RuntimeError):
    """Raised when auth cannot operate because required secrets are missing."""


@dataclass(frozen=True)
class CreatedAccessKey:
    key_id: str
    raw_key: str
    label: str | None
    expires_at: str | None


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    reason: str
    key_id: str | None = None


class AuthService:
    def __init__(self, db_path: str | Path, secret: str) -> None:
        if not secret:
            raise AuthConfigurationError("BOT_AUTH_SECRET is required for bot access control")
        self.db_path = Path(db_path)
        self.secret = secret.encode("utf-8")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._harden_permissions()

    @classmethod
    def from_settings(cls) -> "AuthService":
        settings = get_settings()
        secret = reveal_secret(settings.bot_auth_secret)
        if not secret:
            raise AuthConfigurationError(
                "BOT_AUTH_SECRET is missing. Set it in .env or the service environment."
            )
        return cls(settings.auth_db_path, secret)

    def create_key(self, *, label: str | None = None, expires_at: str | None = None) -> CreatedAccessKey:
        raw_key = secrets.token_urlsafe(32)
        key_id = uuid4().hex
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO access_keys (id, label, key_digest, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key_id, label, self.digest_key(raw_key), now, expires_at),
            )
        return CreatedAccessKey(key_id=key_id, raw_key=raw_key, label=label, expires_at=expires_at)

    def list_keys(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT id, label, created_at, expires_at, used_at, used_by_user_id, revoked_at
                    FROM access_keys
                    ORDER BY created_at DESC
                    """
                )
            )

    def revoke_key(self, key_id: str) -> bool:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE access_keys SET revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
                (now, key_id),
            )
            return cursor.rowcount > 0

    def login(
        self,
        *,
        raw_key: str,
        telegram_user_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ) -> LoginResult:
        digest = self.digest_key(raw_key)
        now = _now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, expires_at, used_at, revoked_at
                FROM access_keys
                WHERE key_digest = ?
                """,
                (digest,),
            ).fetchone()
            if row is None:
                return LoginResult(ok=False, reason="invalid")
            if row["revoked_at"]:
                return LoginResult(ok=False, reason="revoked", key_id=row["id"])
            if row["used_at"]:
                return LoginResult(ok=False, reason="used", key_id=row["id"])
            if row["expires_at"] and row["expires_at"] < now:
                return LoginResult(ok=False, reason="expired", key_id=row["id"])

            conn.execute(
                """
                UPDATE access_keys
                SET used_at = ?, used_by_user_id = ?
                WHERE id = ?
                """,
                (now, telegram_user_id, row["id"]),
            )
            conn.execute(
                """
                INSERT INTO authorized_users
                    (telegram_user_id, username, display_name, authorized_at, revoked_at)
                VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    username = excluded.username,
                    display_name = excluded.display_name,
                    authorized_at = excluded.authorized_at,
                    revoked_at = NULL
                """,
                (telegram_user_id, username, display_name, now),
            )
            return LoginResult(ok=True, reason="ok", key_id=row["id"])

    def is_authorized(self, telegram_user_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM authorized_users
                WHERE telegram_user_id = ? AND revoked_at IS NULL
                """,
                (telegram_user_id,),
            ).fetchone()
            return row is not None

    def revoke_user(self, telegram_user_id: int) -> bool:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE authorized_users
                SET revoked_at = ?
                WHERE telegram_user_id = ? AND revoked_at IS NULL
                """,
                (now, telegram_user_id),
            )
            return cursor.rowcount > 0

    def list_users(self) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return list(
                conn.execute(
                    """
                    SELECT telegram_user_id, username, display_name, authorized_at, revoked_at
                    FROM authorized_users
                    ORDER BY authorized_at DESC
                    """
                )
            )

    def digest_key(self, raw_key: str) -> str:
        return hmac.new(self.secret, raw_key.encode("utf-8"), sha256).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS access_keys (
                    id TEXT PRIMARY KEY,
                    label TEXT,
                    key_digest TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    used_at TEXT,
                    used_by_user_id INTEGER,
                    revoked_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_access_keys_digest
                    ON access_keys(key_digest);

                CREATE TABLE IF NOT EXISTS authorized_users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    display_name TEXT,
                    authorized_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                """
            )

    def _harden_permissions(self) -> None:
        try:
            self.db_path.parent.chmod(0o700)
            self.db_path.chmod(0o600)
        except OSError:
            pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
