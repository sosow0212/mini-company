"""Repository 계약 스위트.

같은 테스트를 InMemory fake와 실제 Mongo 양쪽에 돌린다. 특히 이 도메인에서는
Decimal128 왕복과 $sum 정밀도가 fake의 순수 Decimal 연산과 일치해야 한다 —
갈라지면 원장 숫자가 조용히 틀어진다.

베이스 클래스는 이름이 Test로 시작하지 않아 pytest가 직접 수집하지 않는다.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from src.ledger.constants import CATEGORY_UNITS, LedgerCategory
from src.ledger.domain import LedgerEntry
from src.ledger.repository import LedgerRepository, LedgerRepositoryProtocol
from tests.fakes.ledger_repository import InMemoryLedgerRepository

_JULY = datetime(2026, 7, 15, 12, tzinfo=UTC)
_AUGUST = datetime(2026, 8, 4, 12, tzinfo=UTC)


def _entry(
    category: LedgerCategory,
    amount: str,
    *,
    occurred_at: datetime = _AUGUST,
    reverses_id: PydanticObjectId | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        category=category,
        amount=Decimal(amount),
        unit=CATEGORY_UNITS[category],
        occurred_at=occurred_at,
        reverses_id=reverses_id,
    )


class LedgerRepositoryContract:
    async def test_get_returns_none_when_entry_does_not_exist(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        assert await repository.get(PydanticObjectId()) is None

    async def test_append_assigns_id_and_preserves_amount(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        appended = await repository.append(_entry(LedgerCategory.REVENUE, "82860000.55"))

        assert appended.id is not None
        reloaded = await repository.get(appended.id)
        assert reloaded is not None
        assert reloaded.amount == Decimal("82860000.55")

    async def test_amount_survives_round_trip_as_decimal_not_float(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        appended = await repository.append(_entry(LedgerCategory.LLM_COST, "0.0000001"))

        reloaded = await repository.get(appended.id)
        assert reloaded is not None
        assert isinstance(reloaded.amount, Decimal)
        assert reloaded.amount == Decimal("0.0000001")

    async def test_sum_by_category_groups_totals(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        await repository.append(_entry(LedgerCategory.REVENUE, "1000"))
        await repository.append(_entry(LedgerCategory.REVENUE, "2000"))
        await repository.append(_entry(LedgerCategory.COST, "500"))

        totals = await repository.sum_by_category(start=None, end=None)

        assert totals[LedgerCategory.REVENUE] == Decimal("3000")
        assert totals[LedgerCategory.COST] == Decimal("500")

    async def test_sum_by_category_keeps_precision_for_small_amounts(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        """0.1을 세 번 더해 0.3이어야 한다. float면 0.30000000000000004가 된다."""
        for _ in range(3):
            await repository.append(_entry(LedgerCategory.LLM_COST, "0.1"))

        totals = await repository.sum_by_category(start=None, end=None)

        assert totals[LedgerCategory.LLM_COST] == Decimal("0.3")

    async def test_sum_by_category_nets_out_opposite_signs(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        original = await repository.append(_entry(LedgerCategory.REVENUE, "82860000"))
        await repository.append(
            _entry(LedgerCategory.REVENUE, "-82860000", reverses_id=original.id)
        )

        totals = await repository.sum_by_category(start=None, end=None)

        assert totals[LedgerCategory.REVENUE] == Decimal("0")

    async def test_sum_by_category_respects_the_window(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        await repository.append(_entry(LedgerCategory.REVENUE, "1000", occurred_at=_AUGUST))
        await repository.append(_entry(LedgerCategory.REVENUE, "9999", occurred_at=_JULY))

        august = await repository.sum_by_category(
            start=datetime(2026, 8, 1, tzinfo=UTC), end=datetime(2026, 9, 1, tzinfo=UTC)
        )

        assert august[LedgerCategory.REVENUE] == Decimal("1000")

    async def test_sum_by_category_excludes_the_end_boundary(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        """반경계 [start, end)라서 경계 시각 엔트리는 다음 기간에 속한다."""
        boundary = datetime(2026, 9, 1, tzinfo=UTC)
        await repository.append(_entry(LedgerCategory.REVENUE, "1000", occurred_at=boundary))

        august = await repository.sum_by_category(
            start=datetime(2026, 8, 1, tzinfo=UTC), end=boundary
        )

        assert LedgerCategory.REVENUE not in august

    async def test_sum_by_category_returns_empty_when_no_entries_match(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        assert await repository.sum_by_category(start=None, end=None) == {}

    async def test_find_reversal_of_returns_none_when_entry_is_not_reversed(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        original = await repository.append(_entry(LedgerCategory.REVENUE, "1000"))

        assert await repository.find_reversal_of(original.id) is None

    async def test_find_reversal_of_returns_the_reversing_entry(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        original = await repository.append(_entry(LedgerCategory.REVENUE, "1000"))
        reversal = await repository.append(
            _entry(LedgerCategory.REVENUE, "-1000", reverses_id=original.id)
        )

        found = await repository.find_reversal_of(original.id)

        assert found is not None
        assert found.id == reversal.id

    async def test_list_returns_entries_most_recent_first(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        await repository.append(_entry(LedgerCategory.REVENUE, "1000", occurred_at=_JULY))
        await repository.append(_entry(LedgerCategory.REVENUE, "2000", occurred_at=_AUGUST))

        entries = await repository.list(limit=10)

        assert [str(entry.amount) for entry in entries] == ["2000", "1000"]

    async def test_list_filters_by_category(self, repository: LedgerRepositoryProtocol) -> None:
        await repository.append(_entry(LedgerCategory.REVENUE, "1000"))
        await repository.append(_entry(LedgerCategory.COST, "500"))

        entries = await repository.list(category=LedgerCategory.COST, limit=10)

        assert [entry.category for entry in entries] == [LedgerCategory.COST]

    async def test_list_applies_limit(self, repository: LedgerRepositoryProtocol) -> None:
        for _ in range(3):
            await repository.append(_entry(LedgerCategory.REVENUE, "1000"))

        assert len(await repository.list(limit=2)) == 2


class TestInMemoryLedgerRepository(LedgerRepositoryContract):
    @pytest.fixture
    def repository(self) -> LedgerRepositoryProtocol:
        return InMemoryLedgerRepository()


class TestMongoLedgerRepository(LedgerRepositoryContract):
    @pytest.fixture
    def repository(self, mongo_repository_ready: None) -> LedgerRepositoryProtocol:
        return LedgerRepository()

    async def test_amount_is_stored_as_decimal128_not_double(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        """BSON 타입까지 확인한다. double로 저장되면 합계에 오차가 섞인다."""
        from bson import Decimal128

        from src.ledger.models import LedgerEntryDocument

        appended = await repository.append(_entry(LedgerCategory.REVENUE, "82860000.55"))

        raw = await LedgerEntryDocument.get_pymongo_collection().find_one({"_id": appended.id})
        assert raw is not None
        assert isinstance(raw["amount"], Decimal128)

    async def test_second_reversal_of_the_same_entry_is_rejected_by_unique_index(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        """DB 제약은 실제 구현에만 있는 2차 방어선이라 계약에 넣지 않는다."""
        original = await repository.append(_entry(LedgerCategory.REVENUE, "1000"))
        await repository.append(_entry(LedgerCategory.REVENUE, "-1000", reverses_id=original.id))

        with pytest.raises(DuplicateKeyError):
            await repository.append(
                _entry(LedgerCategory.REVENUE, "-1000", reverses_id=original.id)
            )

    async def test_entries_without_reversal_are_not_blocked_by_the_sparse_index(
        self, repository: LedgerRepositoryProtocol
    ) -> None:
        """sparse가 아니면 reverses_id=null 두 건째부터 unique 위반이 난다."""
        await repository.append(_entry(LedgerCategory.REVENUE, "1000"))
        await repository.append(_entry(LedgerCategory.REVENUE, "2000"))

        assert len(await repository.list(limit=10)) == 2
