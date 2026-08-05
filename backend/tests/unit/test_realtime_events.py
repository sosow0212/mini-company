"""service가 실제로 이벤트를 발행하는가.

Phase 5의 값어치는 "상태가 바뀌면 화면이 안다"는 것이다. 상태 전이 코드와 발행 코드가
갈라지면 화면이 조용히 멈추므로, 전이가 있는 곳마다 발행을 확인한다.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from beanie import PydanticObjectId

from src.employees.constants import EmployeeStatus
from src.ledger.constants import LedgerCategory
from src.ledger.service import LedgerService
from src.tasks.constants import ActivityLevel, TaskStatus
from src.tasks.exceptions import EmployeeBusy
from src.tasks.service import TaskService
from tests.fakes.employee_repository import InMemoryEmployeeRepository
from tests.fakes.event_bus import RecordingEventBus
from tests.fakes.ledger_repository import InMemoryLedgerRepository
from tests.fakes.task_repository import InMemoryActivityRepository, InMemoryTaskRepository

_NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _tasks(*employees) -> tuple[TaskService, RecordingEventBus]:
    bus = RecordingEventBus()
    service = TaskService(
        InMemoryTaskRepository(),
        InMemoryActivityRepository(),
        InMemoryEmployeeRepository(list(employees)),
        bus,
    )
    return service, bus


def _ledger() -> tuple[LedgerService, RecordingEventBus]:
    bus = RecordingEventBus()
    return LedgerService(InMemoryLedgerRepository(), bus), bus


# ─── 직원 상태 (아바타 색) ─────────────────────────────────────


async def test_start_task_publishes_employee_status_changed(make_employee) -> None:
    employee = make_employee("노아")
    service, bus = _tasks(employee)

    task = await service.start_task(employee_id=employee.id, kind="collect")

    events = bus.of_type("employee.status_changed")
    assert len(events) == 1
    assert events[0].data.employee_id == str(employee.id)
    assert events[0].data.status is EmployeeStatus.WORKING
    assert events[0].data.current_task_id == task.id


async def test_finish_task_publishes_status_back_to_idle(make_employee) -> None:
    employee = make_employee("노아")
    service, bus = _tasks(employee)
    task = await service.start_task(employee_id=employee.id, kind="collect")

    await service.finish_task(PydanticObjectId(task.id), outcome=TaskStatus.SUCCEEDED)

    events = bus.of_type("employee.status_changed")
    assert [e.data.status for e in events] == [EmployeeStatus.WORKING, EmployeeStatus.IDLE]
    assert events[-1].data.current_task_id is None


async def test_failed_task_publishes_error_status(make_employee) -> None:
    employee = make_employee("노아")
    service, bus = _tasks(employee)
    task = await service.start_task(employee_id=employee.id, kind="collect")

    await service.finish_task(PydanticObjectId(task.id), outcome=TaskStatus.FAILED)

    assert bus.of_type("employee.status_changed")[-1].data.status is EmployeeStatus.ERROR


async def test_no_status_event_when_start_task_fails(make_employee) -> None:
    """상태가 바뀌지 않았는데 이벤트가 나가면 화면이 DB보다 앞서간다."""
    employee = make_employee("바쁜 직원", current_task_id=PydanticObjectId())
    service, bus = _tasks(employee)

    with pytest.raises(EmployeeBusy):
        await service.start_task(employee_id=employee.id, kind="collect")

    assert bus.published == []


# ─── 활동 (말풍선) ─────────────────────────────────────────────


async def test_add_activity_publishes_activity_created(make_employee) -> None:
    employee = make_employee("노아")
    service, bus = _tasks(employee)
    task = await service.start_task(employee_id=employee.id, kind="collect")

    await service.add_activity(
        PydanticObjectId(task.id), level=ActivityLevel.INFO, message="수집 준비 완료"
    )

    events = bus.of_type("activity.created")
    assert len(events) == 1
    assert events[0].data.message == "수집 준비 완료"
    assert events[0].data.employee_id == str(employee.id)
    assert events[0].data.task_id == task.id


# ─── 원장 (숫자 패널) ──────────────────────────────────────────


async def test_record_entry_publishes_ledger_summary(make_employee) -> None:
    service, bus = _ledger()

    await service.record_entry(
        category=LedgerCategory.REVENUE, amount=Decimal("1000"), occurred_at=_NOW
    )

    events = bus.of_type("ledger.summary_updated")
    assert len(events) == 1
    assert events[0].data.totals[LedgerCategory.REVENUE] == "1000"


async def test_published_summary_carries_server_computed_net() -> None:
    """프론트가 계산하지 않는다 — net도 서버가 넣어 보낸다(ADR-006)."""
    service, bus = _ledger()

    await service.record_entry(
        category=LedgerCategory.REVENUE, amount=Decimal("10000"), occurred_at=_NOW
    )
    await service.record_entry(
        category=LedgerCategory.COST, amount=Decimal("3000"), occurred_at=_NOW
    )

    assert bus.of_type("ledger.summary_updated")[-1].data.net == "7000"


async def test_reversal_publishes_the_corrected_summary() -> None:
    service, bus = _ledger()
    entry = await service.record_entry(
        category=LedgerCategory.REVENUE, amount=Decimal("1000"), occurred_at=_NOW
    )

    await service.reverse_entry(PydanticObjectId(entry.id))

    assert bus.of_type("ledger.summary_updated")[-1].data.totals[LedgerCategory.REVENUE] == "0"


async def test_published_summary_uses_monthly_period_like_the_snapshot() -> None:
    """스냅샷과 기간이 다르면 이벤트가 화면 값을 엉뚱한 기간으로 덮는다."""
    service, bus = _ledger()

    await service.record_entry(
        category=LedgerCategory.REVENUE, amount=Decimal("1000"), occurred_at=_NOW
    )

    assert bus.of_type("ledger.summary_updated")[0].data.period.value == "monthly"
