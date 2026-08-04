"""기간 경계 계산. I/O 없는 순수 함수.

`now`를 인자로 받는 이유: 시계는 경계다. service가 주입하면 월·일 경계 테스트를
고정 시각으로 검증할 수 있다.

기준 타임존은 UTC다. "오늘 매출"을 KST로 봐야 하면 설정 가능한 타임존이 필요하지만,
블루프린트에 명시가 없어 지금은 UTC로 고정하고 이 한계를 여기 적어둔다.
"""

from datetime import UTC, datetime, timedelta

from src.ledger.constants import Period


def resolve_period(period: Period, now: datetime) -> tuple[datetime | None, datetime | None]:
    """[start, end) 반경계 구간을 돌려준다. ALL은 경계가 없어 (None, None)."""
    if period is Period.ALL:
        return None, None

    moment = now.astimezone(UTC)
    if period is Period.DAILY:
        start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)

    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, _next_month(start)


def _next_month(start: datetime) -> datetime:
    if start.month == 12:
        return start.replace(year=start.year + 1, month=1)
    return start.replace(month=start.month + 1)
