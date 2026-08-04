"""LLM 프록시의 비즈니스 로직.

흐름(§8.5):
  1. 직원 조회 → `employee.llm_profile`
  2. 카탈로그에서 프로파일 해석
  3. 일일 비용 한도 확인
  4. 프로바이더 호출 (실패 시 fallback 1홉, Activity에 WARN)
  5. 사용량 수신 → 자체 단가표로 비용 계산
  6. `LedgerEntry(category=LLM_COST)` 기록
  7. 응답 반환

6번이 자동이라는 게 이 구조의 값어치다. 워커 구현자가 비용 기록을 잊을 방법이 없다.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from beanie import PydanticObjectId

from src.employees.exceptions import EmployeeNotFound
from src.employees.repository import EmployeeRepositoryProtocol
from src.ledger.constants import LedgerCategory, Period
from src.ledger.schemas import normalized_amount
from src.ledger.service import LedgerService
from src.llm.exceptions import (
    DailyCostLimitExceeded,
    LlmCallFailed,
    ProfileNotFound,
    ProviderNotConfigured,
)
from src.llm.gateway import LlmGateway
from src.llm.pricing import calculate_cost_krw
from src.llm.profiles import LlmProfile
from src.llm.providers.base import LlmResult, Message
from src.llm.schemas import CompletionRequest, CompletionResponse
from src.tasks.constants import ActivityLevel
from src.tasks.service import TaskService

logger = logging.getLogger(__name__)


class LlmService:
    def __init__(
        self,
        gateway: LlmGateway,
        *,
        employees: EmployeeRepositoryProtocol,
        ledger: LedgerService,
        tasks: TaskService,
    ) -> None:
        self._gateway = gateway
        self._employees = employees
        self._ledger = ledger
        self._tasks = tasks

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        employee = await self._employees.get(request.employee_id)
        if employee is None:
            raise EmployeeNotFound

        profile = self._resolve_profile(employee.llm_profile)
        await self._reject_if_over_daily_limit()

        messages = [Message(role=m.role, content=m.content) for m in request.messages]
        used_profile, result = await self._call_with_fallback(
            profile, messages, task_id=request.task_id
        )

        cost_krw = self._cost_of(used_profile, result)
        await self._record_cost(
            cost_krw,
            employee_id=request.employee_id,
            task_id=request.task_id,
            profile=used_profile,
        )
        return CompletionResponse.of(
            result, profile=used_profile, cost_krw=normalized_amount(cost_krw)
        )

    def _resolve_profile(self, name: str) -> LlmProfile:
        profile = self._gateway.profiles.get(name)
        if profile is None:
            # 부팅 시 카탈로그는 검증했지만, DB의 직원이 없는 프로파일을 가리킬 수 있다.
            raise ProfileNotFound
        return profile

    async def _reject_if_over_daily_limit(self) -> None:
        limit = self._gateway.daily_cost_limit_krw
        if limit <= 0:
            return
        summary = await self._ledger.summarize(Period.DAILY)
        spent = Decimal(summary.totals[LedgerCategory.LLM_COST])
        if spent >= limit:
            logger.warning("LLM 일일 비용 한도 초과: spent=%s limit=%s", spent, limit)
            raise DailyCostLimitExceeded

    async def _call_with_fallback(
        self,
        profile: LlmProfile,
        messages: list[Message],
        *,
        task_id: PydanticObjectId | None,
    ) -> tuple[LlmProfile, LlmResult]:
        try:
            return profile, await self._call(profile, messages)
        except (LlmCallFailed, ProviderNotConfigured) as exc:
            if profile.fallback is None:
                raise
            fallback = self._resolve_profile(profile.fallback)
            # 폴백은 조용히 일어나면 안 된다. 관제실에서 보이게 남긴다.
            await self._warn_fallback(task_id, primary=profile, fallback=fallback, reason=exc)
            return fallback, await self._call(fallback, messages)

    async def _call(self, profile: LlmProfile, messages: list[Message]) -> LlmResult:
        provider = self._gateway.providers.get(profile.provider)
        if provider is None or not provider.is_configured():
            raise ProviderNotConfigured
        return await provider.complete(profile, messages)

    def _cost_of(self, profile: LlmProfile, result: LlmResult) -> Decimal:
        price = self._gateway.pricing.get(profile.model)
        if price is None:
            # 부팅 검증이 막아야 하는 경로다. 여기까지 왔다면 비용을 0으로 기록하는 대신
            # 실패시킨다 — 원장에서 LLM 비용이 누락되는 것이 더 나쁘다.
            raise LlmCallFailed(f"모델 '{profile.model}'의 단가가 없습니다")
        return calculate_cost_krw(price, result.usage, usd_krw_rate=self._gateway.usd_krw_rate)

    async def _record_cost(
        self,
        cost_krw: Decimal,
        *,
        employee_id: PydanticObjectId,
        task_id: PydanticObjectId | None,
        profile: LlmProfile,
    ) -> None:
        await self._ledger.record_entry(
            category=LedgerCategory.LLM_COST,
            amount=cost_krw,
            occurred_at=datetime.now(UTC),
            employee_id=employee_id,
            task_id=task_id,
            memo=f"{profile.provider}/{profile.model} ({profile.name})",
        )

    async def _warn_fallback(
        self,
        task_id: PydanticObjectId | None,
        *,
        primary: LlmProfile,
        fallback: LlmProfile,
        reason: Exception,
    ) -> None:
        message = f"{primary.name} 프로파일 호출 실패로 {fallback.name}으로 대체했습니다"
        logger.warning("%s: %s", message, type(reason).__name__)
        if task_id is None:
            return
        # 활동 로그는 작업에 매달린다. task_id가 없는 호출은 로그로만 남는다.
        await self._tasks.add_activity(task_id, level=ActivityLevel.WARN, message=message)
