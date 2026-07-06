import sqlite3

import pytest

from app.auth.service import AuthConfigurationError, AuthService


def test_key_generation_stores_digest_not_raw_key(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3", "test-secret")
    created = service.create_key(label="demo-user")

    with sqlite3.connect(tmp_path / "auth.sqlite3") as conn:
        row = conn.execute("SELECT key_digest FROM access_keys WHERE id = ?", (created.key_id,)).fetchone()

    assert row is not None
    assert row[0] != created.raw_key
    assert created.raw_key.encode("utf-8") not in (tmp_path / "auth.sqlite3").read_bytes()


def test_auth_db_uses_wal_and_connection_pragmas(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3", "test-secret")

    with service._connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_valid_login_authorizes_user(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3", "test-secret")
    created = service.create_key(label="demo-user")

    result = service.login(
        raw_key=created.raw_key,
        telegram_user_id=1001,
        username="demo_user",
        display_name="Demo User",
    )

    assert result.ok
    assert service.is_authorized(1001)

    with sqlite3.connect(tmp_path / "auth.sqlite3") as conn:
        row = conn.execute(
            "SELECT used_by_user_id FROM access_keys WHERE id = ?",
            (created.key_id,),
        ).fetchone()
    assert row == (1001,)


def test_reused_one_time_key_fails(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3", "test-secret")
    created = service.create_key(label="demo-user")

    first = service.login(raw_key=created.raw_key, telegram_user_id=1001)
    second = service.login(raw_key=created.raw_key, telegram_user_id=1002)

    assert first.ok
    assert not second.ok
    assert second.reason == "used"
    assert not service.is_authorized(1002)


def test_failed_login_releases_write_lock(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3", "test-secret")

    result = service.login(raw_key="not-a-real-key", telegram_user_id=1001)

    assert not result.ok
    with sqlite3.connect(tmp_path / "auth.sqlite3", timeout=0.1) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.rollback()


def test_revoke_user_revokes_access(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3", "test-secret")
    created = service.create_key(label="demo-user")
    service.login(raw_key=created.raw_key, telegram_user_id=1001)

    assert service.revoke_user(1001)
    assert not service.is_authorized(1001)


def test_ban_unban_and_list_users_persist_without_auth_secret(tmp_path) -> None:
    db_path = tmp_path / "auth.sqlite3"
    service = AuthService(db_path)

    service.ban_user(1001, username="demo", display_name="Demo User", reason="abuse")

    reloaded = AuthService(db_path)
    assert reloaded.is_banned(1001)
    rows = reloaded.list_banned_users()
    assert len(rows) == 1
    assert rows[0]["telegram_user_id"] == 1001
    assert rows[0]["username"] == "demo"
    assert rows[0]["display_name"] == "Demo User"
    assert rows[0]["reason"] == "abuse"

    assert reloaded.unban_user(1001)
    assert not reloaded.is_banned(1001)


def test_access_key_operations_require_secret(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3")

    with pytest.raises(AuthConfigurationError):
        service.create_key(label="demo")

    with pytest.raises(AuthConfigurationError):
        service.login(raw_key="key", telegram_user_id=1001)
