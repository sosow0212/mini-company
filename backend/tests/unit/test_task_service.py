from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId

from src.employees.constants import EmployeeStatus
from src.employees.exceptions import EmployeeNotFound
from src.employees.repository import EmployeeRepositoryProtocol
from src.tasks.constants import ActivityLevel, TaskStatus
from src.tasks.exceptions import (
    EmployeeBusy,
    InvalidPaginationCursor,
    InvalidTaskTransition,
    TaskNotFound,
)
from src.tasks.repository import ActivityRepositoryProtocol, TaskRepositoryProtocol
from src.tasks.service import TaskService
from tests.fakes.employee_repository import InMemoryEmployeeRepository
from tests.fakes.event_bus import RecordingEventBus
from tests.fakes.task_repository import (
    InMemoryActivityRepository,
    InMemoryTaskRepository,
)

_BASE = datetime(2026, 2, 1, 9, 0, 0, tzinfo=UTC)


Repos = tuple[EmployeeRepositoryProtocol, TaskRepositoryProtocol, ActivityRepositoryProtocol]


def _service(
    *,
    employees=(),
    tasks=(),
    activities=(),
) -> tuple[TaskService, *Repos]:
    """service와 fake를 함께 돌려준다. 검증은 관찰 가능한 상태(반환값 + fake의 상태)로 한다."""
    employee_repo = InMemoryEmployeeRepository(list(employees))
    task_repo = InMemoryTaskRepository(list(tasks))
    activity_repo = InMemoryActivityRepository(list(activities))
    service = TaskService(task_repo, activity_repo, employee_repo, RecordingEventBus())
    return service, employee_repo, task_repo, activity_repo


async def test_start_task_creates_running_task_and_marks_employee_working(make_employee) -> None:
    employee = make_employee("노아")
    service, employee_repo, _, _ = _service(employees=[employee])
    before = datetime.now(UTC)

    task = await service.start_task(employee_id=employee.id, kind="collect_market_data")

    assert task.status is TaskStatus.RUNNING
    assert task.kind == "collect_market_data"
    assert task.started_at is not None and task.started_at >= before
    reloaded = await employee_repo.get(employee.id)
    assert reloaded is not None
    assert reloaded.status is EmployeeStatus.WORKING
    assert reloaded.current_task_id == PydanticObjectId(task.id)


async def test_start_task_raises_employee_not_found_when_employee_is_unknown() -> None:
    service, _, _, _ = _service()

    with pytest.raises(EmployeeNotFound):
        await service.start_task(employee_id=PydanticObjectId(), kind="collect_market_data")


async def test_start_task_raises_employee_busy_when_employee_already_has_a_task(
    make_employee,
) -> None:
    employee = make_employee(
        "바쁜 직원", status=EmployeeStatus.WORKING, current_task_id=PydanticObjectId()
    )
    service, _, _, _ = _service(employees=[employee])

    with pytest.raises(EmployeeBusy):
        await service.start_task(employee_id=employee.id, kind="collect_market_data")


async def test_finish_task_marks_task_succeeded_and_returns_employee_to_idle(
    make_employee, make_task
) -> None:
    task = make_task(status=TaskStatus.RUNNING, started_at=_BASE)
    employee = make_employee("노아", status=EmployeeStatus.WORKING, current_task_id=task.id)
    task = task.model_copy(update={"employee_id": employee.id})
    service, employee_repo, task_repo, _ = _service(employees=[employee], tasks=[task])

    finished = await service.finish_task(task.id, outcome=TaskStatus.SUCCEEDED, summary="수집 완료")

    assert finished.status is TaskStatus.SUCCEEDED
    assert finished.finished_at is not None
    assert finished.summary == "수집 완료"
    reloaded = await employee_repo.get(employee.id)
    assert reloaded is not None
    assert reloaded.status is EmployeeStatus.IDLE
    assert reloaded.current_task_id is None
    persisted = await task_repo.get(task.id)
    assert persisted is not None and persisted.status is TaskStatus.SUCCEEDED


async def test_finish_task_marks_employee_error_when_task_fails(make_employee, make_task) -> None:
    employee = make_employee("노아")
    task = make_task(employee.id, status=TaskStatus.RUNNING, started_at=_BASE)
    employee = employee.model_copy(
        update={"status": EmployeeStatus.WORKING, "current_task_id": task.id}
    )
    service, employee_repo, _, _ = _service(employees=[employee], tasks=[task])

    finished = await service.finish_task(
        task.id, outcome=TaskStatus.FAILED, error="외부 API 연결 실패"
    )

    assert finished.status is TaskStatus.FAILED
    assert finished.error == "외부 API 연결 실패"
    reloaded = await employee_repo.get(employee.id)
    assert reloaded is not None
    assert reloaded.status is EmployeeStatus.ERROR
    assert reloaded.current_task_id is None


async def test_finish_task_returns_employee_to_idle_when_task_is_cancelled(
    make_employee, make_task
) -> None:
    """취소는 실패가 아니다. ERROR로 두면 3D 씬에서 장애로 오독된다."""
    employee = make_employee("노아")
    task = make_task(employee.id, status=TaskStatus.RUNNING, started_at=_BASE)
    employee = employee.model_copy(
        update={"status": EmployeeStatus.WORKING, "current_task_id": task.id}
    )
    service, employee_repo, _, _ = _service(employees=[employee], tasks=[task])

    finished = await service.finish_task(task.id, outcome=TaskStatus.CANCELLED)

    assert finished.status is TaskStatus.CANCELLED
    reloaded = await employee_repo.get(employee.id)
    assert reloaded is not None
    assert reloaded.status is EmployeeStatus.IDLE
    assert reloaded.current_task_id is None


async def test_finish_task_raises_task_not_found_when_task_is_unknown() -> None:
    service, _, _, _ = _service()

    with pytest.raises(TaskNotFound):
        await service.finish_task(PydanticObjectId(), outcome=TaskStatus.SUCCEEDED)


async def test_finish_task_rejects_transition_when_task_is_already_finished(
    make_employee, make_task
) -> None:
    employee = make_employee("노아")
    task = make_task(
        employee.id,
        status=TaskStatus.SUCCEEDED,
        started_at=_BASE,
        finished_at=_BASE + timedelta(hours=1),
    )
    service, _, _, _ = _service(employees=[employee], tasks=[task])

    with pytest.raises(InvalidTaskTransition):
        await service.finish_task(task.id, outcome=TaskStatus.FAILED)


async def test_add_activity_appends_with_task_employee_and_server_timestamp(
    make_employee, make_task
) -> None:
    employee = make_employee("노아")
    task = make_task(employee.id, status=TaskStatus.RUNNING)
    service, _, _, activity_repo = _service(employees=[employee], tasks=[task])
    before = datetime.now(UTC)

    activity = await service.add_activity(
        task.id, level=ActivityLevel.WARN, message="중복 3건을 건너뛴다"
    )

    assert activity.employee_id == str(employee.id)
    assert activity.task_id == str(task.id)
    assert activity.level is ActivityLevel.WARN
    assert activity.occurred_at >= before
    persisted = await activity_repo.list_by_employee(employee.id, limit=10)
    assert [item.message for item in persisted] == ["중복 3건을 건너뛴다"]


async def test_add_activity_raises_task_not_found_when_task_is_unknown() -> None:
    service, _, _, _ = _service()

    with pytest.raises(TaskNotFound):
        await service.add_activity(PydanticObjectId(), level=ActivityLevel.INFO, message="메시지")


async def test_list_activities_returns_recent_first_and_paginates_with_cursor(
    make_employee, make_activity
) -> None:
    employee = make_employee("노아")
    oldest = make_activity(employee.id, message="첫째", occurred_at=_BASE)
    middle = make_activity(employee.id, message="둘째", occurred_at=_BASE + timedelta(minutes=1))
    newest = make_activity(employee.id, message="셋째", occurred_at=_BASE + timedelta(minutes=2))
    service, _, _, _ = _service(employees=[employee], activities=[oldest, middle, newest])

    first_page = await service.list_activities(employee.id, limit=2)

    assert [item.message for item in first_page.items] == ["셋째", "둘째"]
    assert first_page.next_cursor is not None

    second_page = await service.list_activities(employee.id, limit=2, cursor=first_page.next_cursor)

    assert [item.message for item in second_page.items] == ["첫째"]
    assert second_page.next_cursor is None


async def test_list_activities_raises_employee_not_found_when_employee_is_unknown() -> None:
    service, _, _, _ = _service()

    with pytest.raises(EmployeeNotFound):
        await service.list_activities(PydanticObjectId(), limit=20)


async def test_list_activities_raises_invalid_cursor_when_cursor_is_not_an_object_id(
    make_employee,
) -> None:
    employee = make_employee("노아")
    service, _, _, _ = _service(employees=[employee])

    with pytest.raises(InvalidPaginationCursor):
        await service.list_activities(employee.id, limit=20, cursor="not-an-object-id")


async def test_list_activities_raises_invalid_cursor_when_cursor_activity_does_not_exist(
    make_employee,
) -> None:
    employee = make_employee("노아")
    service, _, _, _ = _service(employees=[employee])

    with pytest.raises(InvalidPaginationCursor):
        await service.list_activities(employee.id, limit=20, cursor=str(PydanticObjectId()))


async def test_list_activities_raises_invalid_cursor_when_cursor_belongs_to_another_employee(
    make_employee, make_activity
) -> None:
    employee = make_employee("노아")
    other = make_employee("리아")
    foreign_activity = make_activity(other.id)
    service, _, _, _ = _service(employees=[employee, other], activities=[foreign_activity])

    with pytest.raises(InvalidPaginationCursor):
        await service.list_activities(employee.id, limit=20, cursor=str(foreign_activity.id))
