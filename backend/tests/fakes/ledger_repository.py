from datetime import datetime
from decimal import Decimal

from beanie import PydanticObjectId

from src.ledger.constants import LedgerCategory
from src.ledger.domain import LedgerEntry


class InMemoryLedgerRepository:
    """LedgerRepository의 경계 대체물. append-only 동작까지 흉내낸다.

    실제 Mongo 구현과 갈라지면 테스트가 거짓말을 하므로,
    tests/integration의 계약 스위트를 두 구현에 동일하게 돌린다.
    """

    def __init__(self, entries: list[LedgerEntry] | None = None) -> None:
        self._by_id: dict[PydanticObjectId, LedgerEntry] = {}
        for entry in entries or []:
            self._by_id[_require_id(entry)] = entry

    async def get(self, entry_id: PydanticObjectId) -> LedgerEntry | None:
        return self._by_id.get(entry_id)

    async def append(self, entry: LedgerEntry) -> LedgerEntry:
        stored = (
            entry if entry.id is not None else entry.model_copy(update={"id": PydanticObjectId()})
        )
        self._by_id[_require_id(stored)] = stored
        return stored

    async def find_reversal_of(self, entry_id: PydanticObjectId) -> LedgerEntry | None:
        return next(
            (entry for entry in self._by_id.values() if entry.reverses_id == entry_id),
            None,
        )

    async def list(
        self,
        *,
        category: LedgerCategory | None = None,
        limit: int,
    ) -> list[LedgerEntry]:
        matched = [
            entry
            for entry in self._by_id.values()
            if category is None or entry.category == category
        ]
        matched.sort(key=lambda entry: (entry.occurred_at, entry.id), reverse=True)
        return matched[:limit]

    async def sum_by_category(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> dict[LedgerCategory, Decimal]:
        totals: dict[LedgerCategory, Decimal] = {}
        for entry in self._by_id.values():
            if start is not None and entry.occurred_at < start:
                continue
            if end is not None and entry.occurred_at >= end:
                continue
            totals[entry.category] = totals.get(entry.category, Decimal(0)) + entry.amount
        return totals


def _require_id(entry: LedgerEntry) -> PydanticObjectId:
    if entry.id is None:
        raise ValueError("저장된 엔트리에는 id가 있어야 한다")
    return entry.id
