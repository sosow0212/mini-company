from datetime import datetime
from decimal import Decimal

from beanie import PydanticObjectId
from pydantic import Field

from src.ledger.constants import LedgerCategory, Period
from src.ledger.domain import LedgerEntry, LedgerSummary
from src.schemas import ApiModel

_MEMO_MAX_LENGTH = 500


class RecordEntryRequest(ApiModel):
    """워커가 보내는 원시 트랜잭션.

    `unit`이 없는 것이 핵심이다 — 단위는 카테고리가 결정하고 서버가 채운다.
    `amount`는 문자열로 보낸다(JSON number를 거치면 float 오차가 섞인다).
    """

    category: LedgerCategory
    amount: Decimal
    occurred_at: datetime
    employee_id: PydanticObjectId | None = None
    task_id: PydanticObjectId | None = None
    memo: str | None = Field(default=None, max_length=_MEMO_MAX_LENGTH)


class ReverseEntryRequest(ApiModel):
    """역분개 요청. 금액을 받지 않는다 — 서버가 원본의 반대 부호로 계산한다."""

    memo: str | None = Field(default=None, max_length=_MEMO_MAX_LENGTH)


class LedgerEntryResponse(ApiModel):
    id: str
    category: LedgerCategory
    # 금액은 문자열로 내린다. JS number로 변환되면 정밀도가 손실된다.
    amount: str
    unit: str
    occurred_at: datetime
    employee_id: str | None
    task_id: str | None
    memo: str | None
    reverses_id: str | None

    @classmethod
    def from_domain(cls, entry: LedgerEntry) -> "LedgerEntryResponse":
        if entry.id is None:
            raise ValueError("저장되지 않은 엔트리는 응답으로 내릴 수 없다")
        return cls(
            id=str(entry.id),
            category=entry.category,
            amount=str(entry.amount),
            unit=entry.unit,
            occurred_at=entry.occurred_at,
            employee_id=str(entry.employee_id) if entry.employee_id else None,
            task_id=str(entry.task_id) if entry.task_id else None,
            memo=entry.memo,
            reverses_id=str(entry.reverses_id) if entry.reverses_id else None,
        )


class LedgerSummaryResponse(ApiModel):
    period: Period
    start: datetime | None
    end: datetime | None
    totals: dict[LedgerCategory, str]
    net: str

    @classmethod
    def from_domain(cls, summary: LedgerSummary) -> "LedgerSummaryResponse":
        return cls(
            period=summary.period,
            start=summary.start,
            end=summary.end,
            totals={
                category: normalized_amount(total) for category, total in summary.totals.items()
            },
            net=normalized_amount(summary.net),
        )


def normalized_amount(amount: Decimal) -> str:
    """같은 값이 항상 같은 문자열이 되게 한다.

    `str(Decimal)`은 산술이 남긴 scale을 그대로 노출한다 — 역분개 한 번으로 같은 0이
    "0"에서 "0.00"으로 바뀌고, 문자열을 그대로 렌더링하는 프론트의 표시가 흔들린다
    (ADR-006). `normalize()`만 쓰면 큰 수가 지수 표기(8.286E+7)가 되므로 `:f`로 되돌린다.
    """
    return f"{amount.normalize():f}"
