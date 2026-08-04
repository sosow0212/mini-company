"""지속성 표현. 이 파일 밖으로 나가지 않는다 — repository가 도메인 모델로 변환한다."""

from datetime import datetime
from typing import ClassVar

import pymongo
from beanie import DecimalAnnotation, Document, PydanticObjectId
from pymongo import IndexModel

from src.ledger.constants import LedgerCategory


class LedgerEntryDocument(Document):
    employee_id: PydanticObjectId | None = None
    task_id: PydanticObjectId | None = None
    category: LedgerCategory
    amount: DecimalAnnotation
    unit: str
    occurred_at: datetime
    memo: str | None = None
    reverses_id: PydanticObjectId | None = None

    class Settings:
        name = "ledger_entries"
        indexes: ClassVar[list[IndexModel | str]] = [
            IndexModel(
                [("category", pymongo.ASCENDING), ("occurred_at", pymongo.DESCENDING)],
                name="category_recent",
            ),
            IndexModel(
                [("reverses_id", pymongo.ASCENDING)],
                name="uq_reverses",
                unique=True,
                partialFilterExpression={"reverses_id": {"$type": "objectId"}},
            ),
        ]
