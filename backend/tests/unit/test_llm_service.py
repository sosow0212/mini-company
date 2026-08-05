"""프록시 service. 경계(LLM/Mongo)만 대체하고 나머지는 실제 객체를 쓴다.

블루프린트 §13이 이름으로 지정한 필수 테스트 4개가 여기 있다:
completion_uses_profile_of_requesting_employee
completion_records_llm_cost_entry_when_call_succeeds
completion_falls_back_to_secondary_profile_when_primary_fails
cost_is_calculated_from_pricing_table_not_from_provider_response
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from beanie import PydanticObjectId

from src.employees.exceptions import EmployeeNotFound
from src.ledger.constants import LedgerCategory, Period
from src.ledger.service import LedgerService
from src.llm.exceptions import (
    DailyCostLimitExceeded,
    LlmCallFailed,
    ProfileNotFound,
    ProviderNotConfigured,
)
from src.llm.gateway import LlmGateway
from src.llm.pricing import ModelPrice
from src.llm.profiles import LlmProfile
from src.llm.schemas import CompletionRequest, MessageRequest
from src.llm.service import LlmService
from src.tasks.constants import ActivityLevel
from src.tasks.service import TaskService
from tests.fakes.employee_repository import InMemoryEmployeeRepository
from tests.fakes.event_bus import RecordingEventBus
from tests.fakes.ledger_repository import InMemoryLedgerRepository
from tests.fakes.llm_provider import FakeLlmProvider
from tests.fakes.task_repository import InMemoryActivityRepository, InMemoryTaskRepository

_RATE = Decimal("1380")
_CHEAP = LlmProfile("cheap", "fake", "cheap-model", 0.2, 1_000)
_WRITER = LlmProfile("writer", "fake", "writer-model", 0.8, 4_000, fallback="cheap")
_PRICING = {
    "cheap-model": ModelPrice(Decimal("0.30"), Decimal("1.20")),
    "writer-model": ModelPrice(Decimal("3.00"), Decimal("15.00")),
}


class _Harness:
    """service와 그 협력자들을 한 번에 조립한다. 검증은 관찰 가능한 상태로 한다."""

    def __init__(
        self,
        *,
        provider: FakeLlmProvider,
        employees: InMemoryEmployeeRepository,
        pricing: dict[str, ModelPrice] | None = None,
        daily_limit: Decimal = Decimal(0),
        rate: Decimal = _RATE,
    ) -> None:
        self.provider = provider
        self.employees = employees
        self.ledger_repository = InMemoryLedgerRepository()
        self.activity_repository = InMemoryActivityRepository()
        task_repository = InMemoryTaskRepository()
        self.events = RecordingEventBus()
        self.ledger = LedgerService(self.ledger_repository, self.events)
        self.tasks = TaskService(task_repository, self.activity_repository, employees, self.events)
        self.gateway = LlmGateway(
            profiles={"cheap": _CHEAP, "writer": _WRITER},
            pricing=pricing if pricing is not None else _PRICING,
            providers={provider.name: provider},
            usd_krw_rate=rate,
            daily_cost_limit_krw=daily_limit,
        )
        self.service = LlmService(
            self.gateway, employees=employees, ledger=self.ledger, tasks=self.tasks
        )


def _harness(make_employee, *, profile: str = "cheap", **kwargs) -> tuple[_Harness, object]:
    employee = make_employee("작가 준", llm_profile=profile)
    employees = InMemoryEmployeeRepository([employee])
    harness = _Harness(
        provider=kwargs.pop("provider", FakeLlmProvider()), employees=employees, **kwargs
    )
    return harness, employee


def _request(employee_id: PydanticObjectId, task_id: PydanticObjectId | None = None):
    return CompletionRequest(
        employee_id=employee_id,
        task_id=task_id,
        messages=[MessageRequest(role="user", content="요약해줘")],
    )


# ─── 프로파일 해석 ─────────────────────────────────────────────


async def test_completion_uses_profile_of_requesting_employee(make_employee) -> None:
    """블루프린트 §13 필수 테스트.

    요청에는 model이 없다. 어떤 모델을 쓸지는 직원의 프로파일이 정한다(ADR-007).
    """
    harness, employee = _harness(make_employee, profile="writer")

    response = await harness.service.complete(_request(employee.id))

    assert harness.provider.called_models == ["writer-model"]
    assert response.profile == "writer"
    assert response.model == "writer-model"


async def test_completion_raises_employee_not_found_when_employee_is_unknown(
    make_employee,
) -> None:
    harness, _ = _harness(make_employee)

    with pytest.raises(EmployeeNotFound):
        await harness.service.complete(_request(PydanticObjectId()))


async def test_completion_raises_profile_not_found_when_employee_points_to_unknown_profile(
    make_employee,
) -> None:
    """부팅 시 카탈로그는 검증했지만 DB의 직원이 사라진 프로파일을 가리킬 수 있다."""
    harness, employee = _harness(make_employee, profile="ghost")

    with pytest.raises(ProfileNotFound):
        await harness.service.complete(_request(employee.id))


async def test_completion_raises_when_provider_key_is_missing(make_employee) -> None:
    harness, employee = _harness(make_employee, provider=FakeLlmProvider(configured=False))

    with pytest.raises(ProviderNotConfigured):
        await harness.service.complete(_request(employee.id))


# ─── 비용 기록 (ADR-002 / §8.5) ────────────────────────────────


async def test_completion_records_llm_cost_entry_when_call_succeeds(make_employee) -> None:
    """블루프린트 §13 필수 테스트. 워커가 비용 기록을 잊을 방법이 없어야 한다."""
    harness, employee = _harness(make_employee)

    await harness.service.complete(_request(employee.id))

    entries = await harness.ledger_repository.list(limit=10)
    assert len(entries) == 1
    assert entries[0].category is LedgerCategory.LLM_COST
    assert entries[0].employee_id == employee.id
    assert entries[0].amount > 0


async def test_recorded_cost_matches_the_returned_cost(make_employee) -> None:
    harness, employee = _harness(make_employee)

    response = await harness.service.complete(_request(employee.id))

    summary = await harness.ledger.summarize(Period.ALL)
    assert summary.totals[LedgerCategory.LLM_COST] == response.cost_krw


async def test_cost_entry_links_the_task_when_task_id_is_given(make_employee) -> None:
    harness, employee = _harness(make_employee)
    task_id = PydanticObjectId()

    await harness.service.complete(_request(employee.id, task_id))

    entries = await harness.ledger_repository.list(limit=10)
    assert entries[0].task_id == task_id


async def test_cost_is_calculated_from_pricing_table_not_from_provider_response(
    make_employee,
) -> None:
    """블루프린트 §13 필수 테스트.

    프로바이더는 토큰 사용량만 제공한다(LlmResult에 비용 필드가 없다). 같은 사용량에
    단가표만 바꾸면 비용이 그대로 따라 바뀌어야 한다 — 비용의 출처가 단가표라는 증거다.
    """
    # 같은 프로바이더(= 같은 usage), 단가만 10배
    cheap_table = {"cheap-model": ModelPrice(Decimal("0.30"), Decimal("1.20"))}
    pricey_table = {"cheap-model": ModelPrice(Decimal("3.00"), Decimal("12.00"))}

    cheap_harness, cheap_employee = _harness(make_employee, pricing=cheap_table)
    pricey_harness, pricey_employee = _harness(make_employee, pricing=pricey_table)

    cheap = await cheap_harness.service.complete(_request(cheap_employee.id))
    pricey = await pricey_harness.service.complete(_request(pricey_employee.id))

    assert Decimal(pricey.cost_krw) == Decimal(cheap.cost_krw) * 10


async def test_cost_follows_the_exchange_rate_setting(make_employee) -> None:
    base, base_employee = _harness(make_employee, rate=Decimal("1000"))
    doubled, doubled_employee = _harness(make_employee, rate=Decimal("2000"))

    base_response = await base.service.complete(_request(base_employee.id))
    doubled_response = await doubled.service.complete(_request(doubled_employee.id))

    assert Decimal(doubled_response.cost_krw) == Decimal(base_response.cost_krw) * 2


async def test_completion_fails_when_model_has_no_price(make_employee) -> None:
    """비용을 0으로 기록하는 것보다 실패가 낫다 — 원장 누락이 더 나쁘다."""
    harness, employee = _harness(make_employee, pricing={})

    with pytest.raises(LlmCallFailed, match="단가가 없습니다"):
        await harness.service.complete(_request(employee.id))


async def test_no_cost_is_recorded_when_the_call_fails(make_employee) -> None:
    harness, employee = _harness(
        make_employee, provider=FakeLlmProvider(fail_models={"cheap-model"})
    )

    with pytest.raises(LlmCallFailed):
        await harness.service.complete(_request(employee.id))

    assert await harness.ledger_repository.list(limit=10) == []


# ─── 폴백 (§8.5-4) ─────────────────────────────────────────────


async def test_completion_falls_back_to_secondary_profile_when_primary_fails(
    make_employee,
) -> None:
    """블루프린트 §13 필수 테스트."""
    harness, employee = _harness(
        make_employee,
        profile="writer",
        provider=FakeLlmProvider(fail_models={"writer-model"}),
    )

    response = await harness.service.complete(_request(employee.id))

    assert harness.provider.called_profiles == ["writer", "cheap"]
    assert response.profile == "cheap"


async def test_fallback_cost_is_priced_with_the_fallback_model(make_employee) -> None:
    """폴백했으면 실제로 호출한 모델의 단가로 기록해야 한다."""
    harness, employee = _harness(
        make_employee,
        profile="writer",
        provider=FakeLlmProvider(fail_models={"writer-model"}),
    )

    response = await harness.service.complete(_request(employee.id))

    entries = await harness.ledger_repository.list(limit=10)
    assert entries[0].memo is not None
    assert "cheap-model" in entries[0].memo
    assert Decimal(response.cost_krw) == entries[0].amount


async def test_fallback_records_a_warn_activity_when_task_is_given(make_employee) -> None:
    """폴백이 조용히 일어나면 관제실에서 품질 저하를 알 수 없다."""
    harness, employee = _harness(
        make_employee,
        profile="writer",
        provider=FakeLlmProvider(fail_models={"writer-model"}),
    )
    task = await harness.tasks.start_task(employee_id=employee.id, kind="write_post")

    await harness.service.complete(_request(employee.id, PydanticObjectId(task.id)))

    activities = await harness.activity_repository.list_by_employee(employee.id, limit=10)
    warnings = [a for a in activities if a.level is ActivityLevel.WARN]
    assert len(warnings) == 1
    assert "writer" in warnings[0].message and "cheap" in warnings[0].message


async def test_no_fallback_is_attempted_when_profile_has_none(make_employee) -> None:
    harness, employee = _harness(
        make_employee, profile="cheap", provider=FakeLlmProvider(fail_models={"cheap-model"})
    )

    with pytest.raises(LlmCallFailed):
        await harness.service.complete(_request(employee.id))

    assert harness.provider.called_profiles == ["cheap"]


# ─── 일일 비용 한도 ────────────────────────────────────────────


async def test_completion_is_rejected_when_daily_cost_limit_is_reached(make_employee) -> None:
    harness, employee = _harness(make_employee, daily_limit=Decimal("10"))
    await harness.ledger.record_entry(
        category=LedgerCategory.LLM_COST,
        amount=Decimal("10"),
        occurred_at=datetime.now(UTC),
    )

    with pytest.raises(DailyCostLimitExceeded):
        await harness.service.complete(_request(employee.id))

    assert harness.provider.calls == [], "한도 초과면 프로바이더를 호출하지 않아야 한다"


async def test_limit_of_zero_disables_the_check(make_employee) -> None:
    harness, employee = _harness(make_employee, daily_limit=Decimal(0))

    await harness.service.complete(_request(employee.id))

    assert len(harness.provider.calls) == 1
