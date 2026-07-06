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
            daily_user_request_limit=10,
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


def test_usage_counter_prune_removes_old_rows_but_keeps_current_day(tmp_path) -> None:
    service = UsageLimitService(
        tmp_path / "usage.sqlite3",
        UsageLimitConfig(
            daily_user_request_limit=10,
            daily_global_request_limit=10,
            per_minute_user_request_limit=10,
            daily_user_photo_limit=10,
        ),
    )
    old_time = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
    recent_time = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)
    current_time = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

    assert service.check_and_increment(1001, has_image=True, now=old_time).allowed
    assert service.check_and_increment(1002, has_image=True, now=recent_time).allowed
    assert service.check_and_increment(1003, has_image=True, now=current_time).allowed

    with service._connection() as conn:
        conn.execute(
            """
            INSERT INTO usage_counters (day, scope, key, request_count, updated_at)
            VALUES ('2026-07-06', 'user', 'stale-current-day', 1, '2026-06-01T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO usage_counters (day, scope, key, request_count, updated_at)
            VALUES ('2026-07-06T08:00Z', 'user_minute', 'stale-current-minute', 1, '2026-06-01T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO usage_notifications (day, event, sent_at)
            VALUES ('2026-06-20', 'global_warning', '2026-06-20T12:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO usage_notifications (day, event, sent_at)
            VALUES ('2026-07-06', 'global_warning', '2026-06-01T00:00:00+00:00')
            """
        )

    deleted = service.prune_older_than(7, now=current_time)

    assert deleted == 5
    with service._connection() as conn:
        counter_rows = list(
            conn.execute("SELECT day, scope, key FROM usage_counters ORDER BY day, scope, key")
        )
        notification_rows = list(
            conn.execute("SELECT day, event FROM usage_notifications ORDER BY day, event")
        )

    assert ("2026-06-20", "global", "all") not in [
        (row["day"], row["scope"], row["key"]) for row in counter_rows
    ]
    assert ("2026-07-04", "global", "all") in [
        (row["day"], row["scope"], row["key"]) for row in counter_rows
    ]
    assert ("2026-07-06", "user", "stale-current-day") in [
        (row["day"], row["scope"], row["key"]) for row in counter_rows
    ]
    assert ("2026-07-06T08:00Z", "user_minute", "stale-current-minute") in [
        (row["day"], row["scope"], row["key"]) for row in counter_rows
    ]
    assert [(row["day"], row["event"]) for row in notification_rows] == [
        ("2026-07-06", "global_warning")
    ]


def test_usage_counter_prune_disabled(tmp_path) -> None:
    service = UsageLimitService(tmp_path / "usage.sqlite3")
    assert service.check_and_increment(
        1001,
        now=datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
    ).allowed

    assert service.prune_older_than(0, now=datetime(2026, 7, 6, 12, 0, tzinfo=UTC)) == 0

    with service._connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM usage_counters").fetchone()[0] > 0
