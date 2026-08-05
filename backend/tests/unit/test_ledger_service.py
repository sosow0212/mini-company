"""service 단위 테스트. fake repository를 쓰므로 DB가 필요 없다.

블루프린트 §13이 이름으로 지정한 필수 테스트가 여기 있다:
summary_reflects_reversal_entry_when_entry_is_reversed
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from beanie import PydanticObjectId

from src.ledger.constants import LedgerCategory, Period
from src.ledger.domain import LedgerEntry
from src.ledger.exceptions import (
    CannotReverseReversal,
    EntryAlreadyReversed,
    LedgerEntryNotFound,
    UnknownPlaceholder,
)
from src.ledger.service import LedgerService
from tests.fakes.event_bus import RecordingEventBus
from tests.fakes.ledger_repository import InMemoryLedgerRepository

_NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)
_LAST_MONTH = datetime(2026, 7, 15, 12, tzinfo=UTC)


def _service(*entries: LedgerEntry) -> tuple[LedgerService, InMemoryLedgerRepository]:
    repository = InMemoryLedgerRepository(list(entries))
    return LedgerService(repository, RecordingEventBus()), repository


async def _record(
    service: LedgerService,
    category: LedgerCategory,
    amount: str,
    *,
    occurred_at: datetime = _NOW,
) -> str:
    recorded = await service.record_entry(
        category=category, amount=Decimal(amount), occurred_at=occurred_at
    )
    return recorded.id


# ─── 기록 ──────────────────────────────────────────────────────


async def test_record_entry_fills_unit_from_category_so_requests_cannot_mix_units() -> None:
    service, _ = _service()

    revenue = await service.record_entry(
        category=LedgerCategory.REVENUE, amount=Decimal("82860000"), occurred_at=_NOW
    )
    views = await service.record_entry(
        category=LedgerCategory.VIEWS, amount=Decimal("1200"), occurred_at=_NOW
    )

    assert revenue.unit == "KRW"
    assert views.unit == "count"


async def test_record_entry_serializes_amount_as_string() -> None:
    service, _ = _service()

    recorded = await service.record_entry(
        category=LedgerCategory.REVENUE, amount=Decimal("82860000.55"), occurred_at=_NOW
    )

    assert recorded.amount == "82860000.55"
    assert isinstance(recorded.amount, str)


# ─── 집계 ──────────────────────────────────────────────────────


async def test_summary_sums_entries_of_the_same_category() -> None:
    service, _ = _service()
    await _record(service, LedgerCategory.REVENUE, "1000")
    await _record(service, LedgerCategory.REVENUE, "2000")

    summary = await service.summarize(Period.MONTHLY, now=_NOW)

    assert summary.totals[LedgerCategory.REVENUE] == "3000"


async def test_summary_fills_missing_categories_with_zero() -> None:
    service, _ = _service()

    summary = await service.summarize(Period.MONTHLY, now=_NOW)

    assert set(summary.totals) == set(LedgerCategory)
    assert all(total == "0" for total in summary.totals.values())
    assert summary.net == "0"


async def test_summary_net_subtracts_costs_from_revenue() -> None:
    service, _ = _service()
    await _record(service, LedgerCategory.REVENUE, "10000")
    await _record(service, LedgerCategory.COST, "3000")
    await _record(service, LedgerCategory.LLM_COST, "500")

    summary = await service.summarize(Period.MONTHLY, now=_NOW)

    assert summary.net == "6500"


async def test_summary_net_excludes_count_categories() -> None:
    """VIEWS/SUBSCRIBERS는 count 단위라 손익에 더할 수 없다."""
    service, _ = _service()
    await _record(service, LedgerCategory.REVENUE, "10000")
    await _record(service, LedgerCategory.VIEWS, "999999")
    await _record(service, LedgerCategory.SUBSCRIBERS, "5000")

    summary = await service.summarize(Period.MONTHLY, now=_NOW)

    assert summary.net == "10000"


async def test_summary_keeps_decimal_precision_when_summing_small_amounts() -> None:
    """LLM 비용은 소액이 대량 누적되므로 float 오차가 실제로 문제가 된다."""
    service, _ = _service()
    for _ in range(3):
        await _record(service, LedgerCategory.LLM_COST, "0.1")

    summary = await service.summarize(Period.MONTHLY, now=_NOW)

    assert summary.totals[LedgerCategory.LLM_COST] == "0.3"


async def test_summary_excludes_entries_outside_the_period() -> None:
    service, _ = _service()
    await _record(service, LedgerCategory.REVENUE, "1000", occurred_at=_NOW)
    await _record(service, LedgerCategory.REVENUE, "9999", occurred_at=_LAST_MONTH)

    monthly = await service.summarize(Period.MONTHLY, now=_NOW)
    all_time = await service.summarize(Period.ALL, now=_NOW)

    assert monthly.totals[LedgerCategory.REVENUE] == "1000"
    assert all_time.totals[LedgerCategory.REVENUE] == "10999"


async def test_all_period_summary_has_no_boundaries() -> None:
    service, _ = _service()

    summary = await service.summarize(Period.ALL, now=_NOW)

    assert summary.start is None
    assert summary.end is None


# ─── 역분개 (ADR-003) ──────────────────────────────────────────


async def test_summary_reflects_reversal_entry_when_entry_is_reversed() -> None:
    """블루프린트 §13 필수 테스트.

    정정은 UPDATE가 아니라 반대 부호의 새 엔트리이고, 집계는 별도 처리 없이
    그 합계에 자동 반영되어야 한다.
    """
    service, repository = _service()
    entry_id = await _record(service, LedgerCategory.REVENUE, "82860000")

    await service.reverse_entry(PydanticObjectId(entry_id), memo="중복 정산 취소")

    summary = await service.summarize(Period.ALL, now=_NOW)
    assert summary.totals[LedgerCategory.REVENUE] == "0"
    # 원본이 지워지지 않고 두 건이 남아야 감사 가능하다.
    assert len(await repository.list(limit=10)) == 2


async def test_reverse_entry_records_opposite_amount_derived_from_original() -> None:
    service, _ = _service()
    entry_id = await _record(service, LedgerCategory.REVENUE, "82860000")

    reversal = await service.reverse_entry(PydanticObjectId(entry_id))

    assert reversal.amount == "-82860000"
    assert reversal.category is LedgerCategory.REVENUE
    assert reversal.unit == "KRW"
    assert reversal.reverses_id == entry_id


async def test_reverse_entry_does_not_modify_the_original() -> None:
    service, repository = _service()
    entry_id = await _record(service, LedgerCategory.REVENUE, "82860000")

    await service.reverse_entry(PydanticObjectId(entry_id))

    original = await repository.get(PydanticObjectId(entry_id))
    assert original is not None
    assert original.amount == Decimal("82860000")
    assert original.reverses_id is None


async def test_reverse_entry_raises_not_found_when_entry_is_unknown() -> None:
    service, _ = _service()

    with pytest.raises(LedgerEntryNotFound):
        await service.reverse_entry(PydanticObjectId())


async def test_reverse_entry_rejects_second_reversal_of_the_same_entry() -> None:
    """두 번 역분개하면 합계가 원본만큼 어긋난다."""
    service, _ = _service()
    entry_id = await _record(service, LedgerCategory.REVENUE, "82860000")
    await service.reverse_entry(PydanticObjectId(entry_id))

    with pytest.raises(EntryAlreadyReversed):
        await service.reverse_entry(PydanticObjectId(entry_id))


async def test_reverse_entry_rejects_reversing_a_reversal() -> None:
    service, _ = _service()
    entry_id = await _record(service, LedgerCategory.REVENUE, "82860000")
    reversal = await service.reverse_entry(PydanticObjectId(entry_id))

    with pytest.raises(CannotReverseReversal):
        await service.reverse_entry(PydanticObjectId(reversal.id))


async def test_reversal_is_recorded_at_correction_time_not_original_time() -> None:
    """원본 시점으로 넣으면 과거 집계가 소급 변경되어 '그때 화면'을 재현할 수 없다."""
    service, _ = _service()
    entry_id = await _record(service, LedgerCategory.REVENUE, "1000", occurred_at=_LAST_MONTH)

    reversal = await service.reverse_entry(PydanticObjectId(entry_id))

    assert reversal.occurred_at > _LAST_MONTH


# ─── 렌더링 (§7.3) ─────────────────────────────────────────────


async def test_render_summary_substitutes_server_computed_values() -> None:
    service, _ = _service()
    await _record(service, LedgerCategory.REVENUE, "10000")
    await _record(service, LedgerCategory.COST, "3000")

    rendered = await service.render_summary(
        "매출 {{ledger.revenue.monthly}}, 순손익 {{ledger.net.monthly}}", now=_NOW
    )

    assert rendered == "매출 10000, 순손익 7000"


async def test_render_summary_exposes_all_periods() -> None:
    service, _ = _service()
    await _record(service, LedgerCategory.REVENUE, "1000", occurred_at=_NOW)
    await _record(service, LedgerCategory.REVENUE, "500", occurred_at=_LAST_MONTH)

    rendered = await service.render_summary(
        "{{ledger.revenue.daily}}/{{ledger.revenue.monthly}}/{{ledger.revenue.all}}", now=_NOW
    )

    assert rendered == "1000/1000/1500"


async def test_render_summary_raises_when_placeholder_is_unknown() -> None:
    service, _ = _service()

    with pytest.raises(UnknownPlaceholder):
        await service.render_summary("{{ledger.revenue.weekly}}", now=_NOW)
