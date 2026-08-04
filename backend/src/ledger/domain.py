"""도메인 모델. 지속성 기술(Beanie)을 모른다.

금액은 순수 `Decimal`이다. `Decimal128` 변환은 repository 경계에서만 일어난다 —
도메인과 service가 bson 타입을 다루면 계산 중 어디서 정밀도가 깨지는지 추적할 수 없다.
"""

from datetime import datetime
from decimal import Decimal

from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict

from src.ledger.constants import LedgerCategory, Period


class LedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: PydanticObjectId | None = None
    employee_id: PydanticObjectId | None = None
    task_id: PydanticObjectId | None = None
    category: LedgerCategory
    amount: Decimal
    unit: str
    occurred_at: datetime
    memo: str | None = None
    # 이 엔트리가 정정(역분개)하는 원본. 회계의 역분개와 같다.
    reverses_id: PydanticObjectId | None = None


class LedgerSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    period: Period
    # ALL 기간은 경계가 없다.
    start: datetime | None
    end: datetime | None
    # 값이 없는 카테고리도 0으로 채워 내린다. 프론트가 키 존재를 확인하지 않아도 되게.
    totals: dict[LedgerCategory, Decimal]
    net: Decimal
