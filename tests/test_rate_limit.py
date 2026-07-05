from datetime import UTC, datetime

from app.bot.rate_limit import UsageLimitConfig, UsageLimitService


def test_user_daily_limit_blocks_after_threshold(tmp_path) -> None:
    service = UsageLimitService(
        tmp_path / "usage.sqlite3",
        UsageLimitConfig(daily_user_request_limit=2, daily_global_request_limit=0),
    )
    now = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)

    first = service.check_and_increment(1001, now=now)
    second = service.check_and_increment(1001, now=now)
    third = service.check_and_increment(1001, now=now)

    assert first.allowed
    assert second.allowed
    assert not third.allowed
    assert third.reason == "user_daily_limit"
    assert third.user_count == 2


def test_usage_db_uses_wal_and_connection_pragmas(tmp_path) -> None:
    service = UsageLimitService(tmp_path / "usage.sqlite3")

    with service._connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_global_daily_limit_blocks_across_users(tmp_path) -> None:
    service = UsageLimitService(
        tmp_path / "usage.sqlite3",
        UsageLimitConfig(daily_user_request_limit=0, daily_global_request_limit=2),
    )
    now = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)

    assert service.check_and_increment(1001, now=now).allowed
    assert service.check_and_increment(1002, now=now).allowed
    blocked = service.check_and_increment(1003, now=now)

    assert not blocked.allowed
    assert blocked.reason == "global_daily_limit"
    assert blocked.global_count == 2


def test_zero_limits_disable_usage_counter(tmp_path) -> None:
    service = UsageLimitService(
        tmp_path / "usage.sqlite3",
        UsageLimitConfig(
            daily_user_request_limit=0,
            daily_global_request_limit=0,
            per_minute_user_request_limit=0,
            daily_user_photo_limit=0,
        ),
    )

    result = service.check_and_increment(1001)

    assert result.allowed
    assert result.reason == "disabled"


def test_usage_counts_reset_by_utc_day(tmp_path) -> None:
    service = UsageLimitService(
        tmp_path / "usage.sqlite3",
        UsageLimitConfig(daily_user_request_limit=1, daily_global_request_limit=0),
    )

    assert service.check_and_increment(
        1001,
        now=datetime(2026, 6, 26, 23, 59, tzinfo=UTC),
    ).allowed
    assert service.check_and_increment(
        1001,
        now=datetime(2026, 6, 27, 0, 0, tzinfo=UTC),
    ).allowed


def test_user_minute_burst_limit_blocks_within_same_minute(tmp_path) -> None:
    service = UsageLimitService(
        tmp_path / "usage.sqlite3",
        UsageLimitConfig(
            daily_user_request_limit=0,
            daily_global_request_limit=0,
            per_minute_user_request_limit=2,
            daily_user_photo_limit=0,
        ),
    )
    now = datetime(2026, 6, 26, 12, 0, 30, tzinfo=UTC)

    assert service.check_and_increment(1001, now=now).allowed
    assert service.check_and_increment(1001, now=now).allowed
    blocked = service.check_and_increment(1001, now=now)

    assert not blocked.allowed
    assert blocked.reason == "user_minute_limit"
    assert blocked.minute_count == 2
    assert service.check_and_increment(
        1001,
        now=datetime(2026, 6, 26, 12, 1, 0, tzinfo=UTC),
    ).allowed


def test_daily_photo_limit_only_counts_photo_requests(tmp_path) -> None:
    service = UsageLimitService(
        tmp_path / "usage.sqlite3",
        UsageLimitConfig(
            daily_user_request_limit=0,
            daily_global_request_limit=0,
            per_minute_user_request_limit=0,
            daily_user_photo_limit=1,
        ),
    )
    now = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)

    assert service.check_and_increment(1001, has_image=False, now=now).allowed
    assert service.check_and_increment(1001, has_image=True, now=now).allowed
    blocked = service.check_and_increment(1001, has_image=True, now=now)

    assert not blocked.allowed
    assert blocked.reason == "user_daily_photo_limit"
    assert blocked.photo_count == 1


def test_global_usage_warning_and_exhaustion_alert_once_per_day(tmp_path) -> None:
    service = UsageLimitService(
        tmp_path / "usage.sqlite3",
        UsageLimitConfig(
            daily_user_request_limit=0,
            daily_global_request_limit=3,
            per_minute_user_request_limit=0,
            daily_user_photo_limit=0,
            global_warning_ratio=0.8,
        ),
    )
    now = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)

    first = service.check_and_increment(1001, now=now)
    second = service.check_and_increment(1002, now=now)
    third = service.check_and_increment(1003, now=now)
    blocked = service.check_and_increment(1004, now=now)
    blocked_again = service.check_and_increment(1005, now=now)

    assert first.admin_alert is None
    assert second.admin_alert is None
    assert third.admin_alert == "global_exhausted"
    assert not blocked.allowed
    assert blocked.reason == "global_daily_limit"
    assert blocked.admin_alert is None
    assert not blocked_again.allowed
    assert blocked_again.admin_alert is None


def test_usage_counter_migrates_old_scope_check_schema(tmp_path) -> None:
    db_path = tmp_path / "usage.sqlite3"
    service = UsageLimitService(
        db_path,
        UsageLimitConfig(
            daily_user_request_limit=1,
            daily_global_request_limit=0,
            per_minute_user_request_limit=0,
            daily_user_photo_limit=0,
        ),
    )
    assert service.check_and_increment(1001).allowed

    with service._connection() as conn:
        conn.execute("ALTER TABLE usage_counters RENAME TO usage_counters_current")
        conn.executescript(
            """
            CREATE TABLE usage_counters (
                day TEXT NOT NULL,
                scope TEXT NOT NULL CHECK(scope IN ('user', 'global')),
                key TEXT NOT NULL,
                request_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (day, scope, key)
            );
            INSERT INTO usage_counters
            SELECT day, scope, key, request_count, updated_at
            FROM usage_counters_current;
            DROP TABLE usage_counters_current;
            """
        )

    migrated = UsageLimitService(
        db_path,
        UsageLimitConfig(
            daily_user_request_limit=0,
            daily_global_request_limit=0,
            per_minute_user_request_limit=1,
            daily_user_photo_limit=0,
        ),
    )

    assert migrated.check_and_increment(1001).allowed
