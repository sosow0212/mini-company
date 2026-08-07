"""반복 지시 — "매일 몇 시"가 실제로 그 시각에 한 번만 도는가.

시간 계산은 눈으로 검증하기 어렵고 하루에 한 번만 재현된다. 여기서 시각을 주입해
경계를 전부 확인한다(아직 이른 시각 / 창 안 / 창을 넘김 / 이미 오늘 실행함).
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from beanie import PydanticObjectId

from src.employees.constants import EmployeeStatus
from src.employees.exceptions import EmployeeNotFound
from src.schedules.domain import Schedule
from src.schedules.exceptions import ScheduleNotFound
from src.schedules.service import ScheduleService
from src.tasks.constants import TaskStatus
from src.tasks.service import TaskService
from tests.fakes.employee_repository import InMemoryEmployeeRepository
from tests.fakes.event_bus import RecordingEventBus
from tests.fakes.schedule_repository import InMemoryScheduleRepository
from tests.fakes.task_repository import InMemoryActivityRepository, InMemoryTaskRepository

_SEOUL = ZoneInfo("Asia/Seoul")
# 서울 기준 2026-08-07 11:00.
_ELEVEN = datetime(2026, 8, 7, 11, 0, tzinfo=_SEOUL)


def _build(employees, schedules=()):
    employee_repo = InMemoryEmployeeRepository(list(employees))
    task_repo = InMemoryTaskRepository()
    schedule_repo = InMemoryScheduleRepository(list(schedules))
    tasks = TaskService(task_repo, InMemoryActivityRepository(), employee_repo, RecordingEventBus())
    service = ScheduleService(schedule_repo, employee_repo, tasks, timezone="Asia/Seoul")
    return service, schedule_repo, task_repo


def _schedule(employee_id, *, hour=11, minute=0, enabled=True, last_run_at=None) -> Schedule:
    return Schedule(
        id=PydanticObjectId(),
        employee_id=employee_id,
        kind="collect_market_data",
        title="매일 시장 자료",
        hour=hour,
        minute=minute,
        enabled=enabled,
        last_run_at=last_run_at,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


# ─── 등록 ──────────────────────────────────────────────────────


async def test_create_rejects_unknown_employee() -> None:
    service, _, _ = _build([])

    with pytest.raises(EmployeeNotFound):
        await service.create(
            employee_id=PydanticObjectId(), kind="collect_market_data", hour=11, minute=0
        )


async def test_created_schedule_starts_enabled(make_employee) -> None:
    employee = make_employee("노아")
    service, _, _ = _build([employee])

    created = await service.create(
        employee_id=employee.id, kind="collect_market_data", hour=9, minute=30, title="아침 수집"
    )

    assert created.enabled is True
    assert (created.hour, created.minute) == (9, 30)
    assert created.last_run_at is None


async def test_disabled_schedule_can_be_re_enabled(make_employee) -> None:
    employee = make_employee("노아")
    schedule = _schedule(employee.id)
    service, _, _ = _build([employee], [schedule])

    off = await service.set_enabled(schedule.id, enabled=False)
    on = await service.set_enabled(schedule.id, enabled=True)

    assert off.enabled is False
    assert on.enabled is True


async def test_delete_raises_when_missing() -> None:
    service, _, _ = _build([])

    with pytest.raises(ScheduleNotFound):
        await service.delete(PydanticObjectId())


# ─── 언제 도는가 ────────────────────────────────────────────────


async def test_creates_a_queued_task_at_the_scheduled_time(make_employee) -> None:
    """작업을 만들 뿐 실행하지 않는다. 실행은 에이전트가 집어가서 한다."""
    employee = make_employee("노아")
    service, _, task_repo = _build([employee], [_schedule(employee.id)])

    created = await service.run_due(_ELEVEN)

    assert created == 1
    tasks = await task_repo.list()
    assert len(tasks) == 1
    assert tasks[0].status is TaskStatus.QUEUED
    assert tasks[0].title == "매일 시장 자료"


async def test_does_nothing_before_the_scheduled_time(make_employee) -> None:
    employee = make_employee("노아")
    service, _, task_repo = _build([employee], [_schedule(employee.id, hour=11)])

    created = await service.run_due(_ELEVEN - timedelta(minutes=1))

    assert created == 0
    assert await task_repo.list() == []


async def test_skips_when_the_catch_up_window_has_passed(make_employee) -> None:
    """백엔드가 몇 시간 꺼져 있다 켜져도 지난 스케줄을 몰아서 돌리지 않는다.

    새벽 작업이 오후에 도는 것보다 그날 건너뛰는 편이 예측 가능하다.
    """
    employee = make_employee("노아")
    service, _, task_repo = _build([employee], [_schedule(employee.id, hour=11)])

    created = await service.run_due(_ELEVEN + timedelta(hours=3))

    assert created == 0
    assert await task_repo.list() == []


async def test_runs_once_per_day_even_if_ticked_repeatedly(make_employee) -> None:
    """틱은 1분마다 온다. 창(30분) 안에서 매번 만들면 하루에 30개가 생긴다."""
    employee = make_employee("노아")
    service, _, task_repo = _build([employee], [_schedule(employee.id)])

    first = await service.run_due(_ELEVEN)
    second = await service.run_due(_ELEVEN + timedelta(minutes=1))
    third = await service.run_due(_ELEVEN + timedelta(minutes=5))

    assert (first, second, third) == (1, 0, 0)
    assert len(await task_repo.list()) == 1


async def test_runs_again_the_next_day(make_employee) -> None:
    employee = make_employee("노아")
    yesterday = (_ELEVEN - timedelta(days=1)).astimezone(UTC)
    service, _, task_repo = _build([employee], [_schedule(employee.id, last_run_at=yesterday)])

    created = await service.run_due(_ELEVEN)

    assert created == 1
    assert len(await task_repo.list()) == 1


async def test_disabled_schedule_never_runs(make_employee) -> None:
    employee = make_employee("노아")
    service, _, task_repo = _build([employee], [_schedule(employee.id, enabled=False)])

    assert await service.run_due(_ELEVEN) == 0
    assert await task_repo.list() == []


async def test_busy_employee_makes_the_run_skip_not_fail(make_employee) -> None:
    """앞 작업이 안 끝났으면 건너뛴다. 쌓아두면 직원 하나가 며칠치를 몰아 처리한다."""
    employee = make_employee(
        "노아", status=EmployeeStatus.WORKING, current_task_id=PydanticObjectId()
    )
    service, _, task_repo = _build([employee], [_schedule(employee.id)])

    created = await service.run_due(_ELEVEN)

    assert created == 0
    assert await task_repo.list() == []


async def test_timezone_is_local_not_utc(make_employee) -> None:
    """서울 11시는 UTC 02시다. UTC로 판단하면 등록한 시각과 9시간 어긋난다."""
    employee = make_employee("노아")
    service, _, _ = _build([employee], [_schedule(employee.id, hour=11)])

    # UTC 02:00 == 서울 11:00
    created = await service.run_due(datetime(2026, 8, 7, 2, 0, tzinfo=UTC))

    assert created == 1


async def test_second_replica_does_not_duplicate_the_task(make_employee) -> None:
    """replica 둘이 같은 틱에 같은 스케줄을 본다. 실행권을 먼저 가져간 쪽만 만든다."""
    employee = make_employee("노아")
    schedule = _schedule(employee.id)
    employee_repo = InMemoryEmployeeRepository([employee])
    schedule_repo = InMemoryScheduleRepository([schedule])
    task_repo = InMemoryTaskRepository()

    def _service() -> ScheduleService:
        tasks = TaskService(
            task_repo, InMemoryActivityRepository(), employee_repo, RecordingEventBus()
        )
        return ScheduleService(schedule_repo, employee_repo, tasks, timezone="Asia/Seoul")

    first = await _service().run_due(_ELEVEN)
    second = await _service().run_due(_ELEVEN)

    assert (first, second) == (1, 0)
    assert len(await task_repo.list()) == 1
