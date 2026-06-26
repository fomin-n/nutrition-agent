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
        UsageLimitConfig(daily_user_request_limit=0, daily_global_request_limit=0),
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
