from datetime import UTC, datetime
from decimal import Decimal

from beanie import PydanticObjectId

from src.ledger.constants import CATEGORY_UNITS, NET_SIGNS, LedgerCategory, Period
from src.ledger.domain import LedgerEntry, LedgerSummary
from src.ledger.exceptions import (
    CannotReverseReversal,
    EntryAlreadyReversed,
    LedgerEntryNotFound,
)
from src.ledger.period import resolve_period
from src.ledger.renderer import render
from src.ledger.repository import LedgerRepositoryProtocol
from src.ledger.schemas import LedgerEntryResponse, LedgerSummaryResponse
from src.realtime.bus import EventBus
from src.realtime.schemas import LedgerSummaryUpdated

_PLACEHOLDER_ROOT = "ledger"
_NET_KEY = "net"


class LedgerService:
    """비즈니스 로직. Beanie 쿼리 API가 이 파일에 등장하면 레이어가 무너진다."""

    def __init__(self, repository: LedgerRepositoryProtocol, events: EventBus) -> None:
        self._repository = repository
        self._events = events

    # ─── 기록 (워커 전용) ──────────────────────────────────────

    async def record_entry(
        self,
        *,
        category: LedgerCategory,
        amount: Decimal,
        occurred_at: datetime,
        employee_id: PydanticObjectId | None = None,
        task_id: PydanticObjectId | None = None,
        memo: str | None = None,
    ) -> LedgerEntryResponse:
        """발생한 사실만 남긴다. 계산은 하지 않는다(§7.1)."""
        entry = await self._repository.append(
            LedgerEntry(
                employee_id=employee_id,
                task_id=task_id,
                category=category,
                amount=amount,
                # 단위는 서버가 카테고리로 결정한다. 요청이 정하게 두면 같은 카테고리에
                # KRW와 count가 섞여 합계가 조용히 무의미해진다.
                unit=CATEGORY_UNITS[category],
                occurred_at=occurred_at,
                memo=memo,
            )
        )
        await self._publish_summary()
        return LedgerEntryResponse.from_domain(entry)

    async def reverse_entry(
        self,
        entry_id: PydanticObjectId,
        *,
        memo: str | None = None,
    ) -> LedgerEntryResponse:
        """정정은 UPDATE가 아니라 반대 부호의 새 엔트리다(ADR-003).

        금액을 요청에서 받지 않고 원본에서 파생시킨다 — 부호를 클라이언트가 정하면
        같은 금액으로 두 번 더해지는 실수를 막을 방법이 없다.
        """
        original = await self._repository.get(entry_id)
        if original is None:
            raise LedgerEntryNotFound
        if original.reverses_id is not None:
            raise CannotReverseReversal
        if await self._repository.find_reversal_of(entry_id) is not None:
            raise EntryAlreadyReversed

        reversal = await self._repository.append(
            LedgerEntry(
                employee_id=original.employee_id,
                task_id=original.task_id,
                category=original.category,
                amount=-original.amount,
                unit=original.unit,
                # 정정이 일어난 시점으로 기록한다. 원본 시점으로 넣으면 과거 집계가
                # 소급 변경되어 "그때 화면"을 재현할 수 없다.
                occurred_at=datetime.now(UTC),
                memo=memo,
                reverses_id=entry_id,
            )
        )
        await self._publish_summary()
        return LedgerEntryResponse.from_domain(reversal)

    # ─── 집계 (공개 조회) ──────────────────────────────────────

    async def summarize(
        self,
        period: Period,
        *,
        now: datetime | None = None,
    ) -> LedgerSummaryResponse:
        return LedgerSummaryResponse.from_domain(await self._summarize(period, now=now))

    async def render_summary(
        self,
        template: str,
        *,
        now: datetime | None = None,
    ) -> str:
        """LLM이 남긴 `{{ledger.*}}` 자리에 서버 집계값을 채운다(§7.3).

        알 수 없는 자리표시자나 치환 실패는 예외로 발행을 중단시킨다.
        """
        values: dict[str, str] = {}
        for period in Period:
            summary = await self._summarize(period, now=now)
            # 응답 DTO를 거쳐 숫자 표현 규칙을 한 곳(normalized_amount)에만 둔다.
            # 요약문과 API가 같은 값을 다르게 적으면 그게 곧 숫자 불신의 시작이다.
            values.update(_placeholder_values(LedgerSummaryResponse.from_domain(summary)))
        return render(template, values)

    async def _publish_summary(self) -> None:
        """원장이 바뀌면 화면 숫자도 바뀐다.

        기간은 스냅샷과 같은 MONTHLY로 고정한다 — 다른 기간을 보내면 프론트가 스냅샷으로
        그린 값을 엉뚱한 기간 값으로 덮는다. 기록마다 aggregate 1회가 추가되는 비용은
        "화면 숫자는 서버가 만든다"(ADR-002)를 지키는 대가다.
        """
        summary = await self._summarize(Period.MONTHLY, now=None)
        await self._events.publish(
            LedgerSummaryUpdated(data=LedgerSummaryResponse.from_domain(summary))
        )

    async def _summarize(self, period: Period, *, now: datetime | None) -> LedgerSummary:
        start, end = resolve_period(period, now or datetime.now(UTC))
        totals = await self._repository.sum_by_category(start=start, end=end)
        # 값이 없는 카테고리도 0으로 채운다. 프론트가 키 존재를 검사하지 않아도 되게.
        filled = {category: totals.get(category, Decimal(0)) for category in LedgerCategory}
        return LedgerSummary(
            period=period,
            start=start,
            end=end,
            totals=filled,
            net=_net_of(filled),
        )


def _net_of(totals: dict[LedgerCategory, Decimal]) -> Decimal:
    # count 단위 카테고리(VIEWS/SUBSCRIBERS)는 손익에 더할 수 없어 NET_SIGNS에 없다.
    return sum((totals[category] * sign for category, sign in NET_SIGNS.items()), Decimal(0))


def _placeholder_values(summary: LedgerSummaryResponse) -> dict[str, str]:
    prefix = f"{_PLACEHOLDER_ROOT}."
    suffix = f".{summary.period.value}"
    values = {
        f"{prefix}{category.value.lower()}{suffix}": total
        for category, total in summary.totals.items()
    }
    values[f"{prefix}{_NET_KEY}{suffix}"] = summary.net
    return values
