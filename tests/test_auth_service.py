import sqlite3

from app.auth.service import AuthService


def test_key_generation_stores_digest_not_raw_key(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3", "test-secret")
    created = service.create_key(label="demo-user")

    with sqlite3.connect(tmp_path / "auth.sqlite3") as conn:
        row = conn.execute("SELECT key_digest FROM access_keys WHERE id = ?", (created.key_id,)).fetchone()

    assert row is not None
    assert row[0] != created.raw_key
    assert created.raw_key.encode("utf-8") not in (tmp_path / "auth.sqlite3").read_bytes()


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


def test_reused_one_time_key_fails(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3", "test-secret")
    created = service.create_key(label="demo-user")

    first = service.login(raw_key=created.raw_key, telegram_user_id=1001)
    second = service.login(raw_key=created.raw_key, telegram_user_id=1002)

    assert first.ok
    assert not second.ok
    assert second.reason == "used"
    assert not service.is_authorized(1002)


def test_logout_revokes_access(tmp_path) -> None:
    service = AuthService(tmp_path / "auth.sqlite3", "test-secret")
    created = service.create_key(label="demo-user")
    service.login(raw_key=created.raw_key, telegram_user_id=1001)

    assert service.revoke_user(1001)
    assert not service.is_authorized(1001)
