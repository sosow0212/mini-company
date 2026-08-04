"""기간 경계 계산. 순수 함수라 시계를 고정해 경계를 직접 찍는다."""

from datetime import UTC, datetime

from src.ledger.constants import Period
from src.ledger.period import resolve_period


def test_all_period_has_no_boundaries() -> None:
    assert resolve_period(Period.ALL, datetime(2026, 8, 4, 12, tzinfo=UTC)) == (None, None)


def test_daily_period_covers_one_day_from_midnight() -> None:
    start, end = resolve_period(Period.DAILY, datetime(2026, 8, 4, 15, 30, 5, tzinfo=UTC))

    assert start == datetime(2026, 8, 4, tzinfo=UTC)
    assert end == datetime(2026, 8, 5, tzinfo=UTC)


def test_monthly_period_covers_one_month_from_first_day() -> None:
    start, end = resolve_period(Period.MONTHLY, datetime(2026, 8, 4, 15, tzinfo=UTC))

    assert start == datetime(2026, 8, 1, tzinfo=UTC)
    assert end == datetime(2026, 9, 1, tzinfo=UTC)


def test_monthly_period_rolls_over_to_next_year_in_december() -> None:
    start, end = resolve_period(Period.MONTHLY, datetime(2026, 12, 31, 23, 59, tzinfo=UTC))

    assert start == datetime(2026, 12, 1, tzinfo=UTC)
    assert end == datetime(2027, 1, 1, tzinfo=UTC)


def test_monthly_period_handles_february_in_leap_year() -> None:
    start, end = resolve_period(Period.MONTHLY, datetime(2028, 2, 29, 12, tzinfo=UTC))

    assert start == datetime(2028, 2, 1, tzinfo=UTC)
    assert end == datetime(2028, 3, 1, tzinfo=UTC)


def test_boundaries_are_half_open_so_days_do_not_overlap() -> None:
    _, first_end = resolve_period(Period.DAILY, datetime(2026, 8, 4, 1, tzinfo=UTC))
    second_start, _ = resolve_period(Period.DAILY, datetime(2026, 8, 5, 1, tzinfo=UTC))

    assert first_end == second_start
