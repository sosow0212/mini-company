"""원장(LedgerEntry) 애그리거트 — 화면에 나오는 모든 수치의 유일한 원천.

워커는 발생한 사실(원시 트랜잭션)만 기록하고, 합계는 서버가 aggregate로 만든다.
LLM도 워커도 숫자를 타이핑하지 않는다(ADR-002). append-only이므로 정정은 UPDATE가
아니라 반대 부호의 새 엔트리이고, 그래서 과거 화면을 그대로 재현할 수 있다(ADR-003).

공개/내부 라우터를 두 APIRouter로 분리한다. 내부 라우터가 실제로 잠기는 지점은
main.py의 include_router다(블루프린트 §5).
"""

from beanie import PydanticObjectId
from fastapi import APIRouter, status

from src.ledger.constants import Period
from src.ledger.dependencies import LedgerServiceDep
from src.ledger.schemas import (
    LedgerEntryResponse,
    LedgerSummaryResponse,
    RecordEntryRequest,
    ReverseEntryRequest,
)

public_router = APIRouter(prefix="/ledger", tags=["ledger"])
internal_router = APIRouter(prefix="/ledger", tags=["internal-ledger"])


@public_router.get("/summary")
async def get_summary(
    service: LedgerServiceDep,
    period: Period = Period.MONTHLY,
) -> LedgerSummaryResponse:
    return await service.summarize(period)


@internal_router.post("/entries", status_code=status.HTTP_201_CREATED)
async def record_entry(
    request: RecordEntryRequest,
    service: LedgerServiceDep,
) -> LedgerEntryResponse:
    return await service.record_entry(
        category=request.category,
        amount=request.amount,
        occurred_at=request.occurred_at,
        employee_id=request.employee_id,
        task_id=request.task_id,
        memo=request.memo,
    )


@internal_router.post("/entries/{entry_id}/reversal", status_code=status.HTTP_201_CREATED)
async def reverse_entry(
    entry_id: PydanticObjectId,
    request: ReverseEntryRequest,
    service: LedgerServiceDep,
) -> LedgerEntryResponse:
    """별도 엔드포인트로 둔 이유: 금액을 받지 않기 때문에 요청 스키마가 다르다."""
    return await service.reverse_entry(entry_id, memo=request.memo)
