from datetime import datetime
from decimal import Decimal
from typing import Protocol

import pymongo
from beanie import PydanticObjectId

from src.ledger.constants import LedgerCategory
from src.ledger.domain import LedgerEntry
from src.ledger.models import LedgerEntryDocument

_RECENT_FIRST = [("occurred_at", pymongo.DESCENDING), ("_id", pymongo.DESCENDING)]


class LedgerRepositoryProtocol(Protocol):
    """append-only 경계. 갱신·삭제 메서드가 의도적으로 없다(ADR-003).

    "없으면 예외"를 판단하지 않고 None을 반환한다.
    """

    async def get(self, entry_id: PydanticObjectId) -> LedgerEntry | None: ...

    async def append(self, entry: LedgerEntry) -> LedgerEntry: ...

    async def find_reversal_of(self, entry_id: PydanticObjectId) -> LedgerEntry | None: ...

    async def list(
        self,
        *,
        category: LedgerCategory | None = None,
        limit: int,
    ) -> list[LedgerEntry]: ...

    async def sum_by_category(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> dict[LedgerCategory, Decimal]: ...


class LedgerRepository:
    """Beanie 쿼리는 이 파일에만 등장한다."""

    async def get(self, entry_id: PydanticObjectId) -> LedgerEntry | None:
        document = await LedgerEntryDocument.get(entry_id)
        return _to_domain(document) if document is not None else None

    async def append(self, entry: LedgerEntry) -> LedgerEntry:
        # save()가 아니라 insert()만 쓴다 — UPDATE 경로를 물리적으로 열지 않는다.
        document = _to_document(entry)
        await document.insert()
        return _to_domain(document)

    async def find_reversal_of(self, entry_id: PydanticObjectId) -> LedgerEntry | None:
        document = await LedgerEntryDocument.find_one(LedgerEntryDocument.reverses_id == entry_id)
        return _to_domain(document) if document is not None else None

    async def list(
        self,
        *,
        category: LedgerCategory | None = None,
        limit: int,
    ) -> list[LedgerEntry]:
        conditions = []
        if category is not None:
            conditions.append(LedgerEntryDocument.category == category)
        documents = (
            await LedgerEntryDocument.find(*conditions).sort(_RECENT_FIRST).limit(limit).to_list()
        )
        return [_to_domain(document) for document in documents]

    async def sum_by_category(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> dict[LedgerCategory, Decimal]:
        """$sum은 Decimal128 위에서 수행되므로 0.1을 세 번 더해도 오차가 없다.

        역분개는 반대 부호 엔트리라서, 별도 처리 없이 이 합계에 자동 반영된다.
        """
        pipeline: list[dict[str, object]] = []
        window = _occurred_at_window(start, end)
        if window:
            pipeline.append({"$match": {"occurred_at": window}})
        pipeline.append({"$group": {"_id": "$category", "total": {"$sum": "$amount"}}})

        rows = await LedgerEntryDocument.aggregate(pipeline).to_list()
        return {
            LedgerCategory(row["_id"]): _to_decimal(row["total"])
            for row in rows
            if row["_id"] is not None
        }


def _occurred_at_window(start: datetime | None, end: datetime | None) -> dict[str, datetime]:
    window: dict[str, datetime] = {}
    if start is not None:
        window["$gte"] = start
    if end is not None:
        window["$lt"] = end
    return window


def _to_decimal(value: object) -> Decimal:
    # $sum 결과는 Decimal128로 돌아온다. 도메인 경계에서 Decimal로 바꾼다.
    to_decimal = getattr(value, "to_decimal", None)
    return to_decimal() if to_decimal is not None else Decimal(str(value))


def _to_domain(document: LedgerEntryDocument) -> LedgerEntry:
    return LedgerEntry(
        id=document.id,
        employee_id=document.employee_id,
        task_id=document.task_id,
        category=document.category,
        amount=document.amount,
        unit=document.unit,
        occurred_at=document.occurred_at,
        memo=document.memo,
        reverses_id=document.reverses_id,
    )


def _to_document(entry: LedgerEntry) -> LedgerEntryDocument:
    return LedgerEntryDocument(
        id=entry.id,
        employee_id=entry.employee_id,
        task_id=entry.task_id,
        category=entry.category,
        amount=entry.amount,
        unit=entry.unit,
        occurred_at=entry.occurred_at,
        memo=entry.memo,
        reverses_id=entry.reverses_id,
    )
