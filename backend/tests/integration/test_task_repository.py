"""Task/Activity repository 계약 스위트.

같은 테스트를 InMemory fake와 실제 Mongo 양쪽에 돌린다(test_employee_repository.py와 같은 규칙).
베이스 클래스는 이름이 Test로 시작하지 않아 pytest가 직접 수집하지 않는다.

주의: Mongo는 datetime을 밀리초까지만 저장한다. 시각 차이를 검증하는 테스트는
마이크로초가 아니라 초 단위 간격을 써야 fake와 실제 구현이 같은 결과를 낸다.
"""

from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId

from src.tasks.constants import ActivityLevel, TaskStatus
from src.tasks.domain import Activity, Task
from src.tasks.repository import (
    ActivityRepository,
    ActivityRepositoryProtocol,
    TaskRepository,
    TaskRepositoryProtocol,
)
from tests.fakes.task_repository import (
    InMemoryActivityRepository,
    InMemoryTaskRepository,
)

_BASE = datetime(2026, 2, 1, 9, 0, 0, tzinfo=UTC)


def _new_task(
    employee_id: PydanticObjectId | None = None,
    *,
    status: TaskStatus = TaskStatus.RUNNING,
    created_at: datetime = _BASE,
    started_at: datetime | None = None,
) -> Task:
    """id 없이 만든다. 저장은 repository.save가 담당한다.

    QUEUED 작업은 `started_at`이 없다 — 아직 시작하지 않았기 때문이다. 회수 쿼리가
    started_at을 기준으로 삼으므로 이 구분이 테스트 결과를 바꾼다.
    """
    return Task(
        employee_id=employee_id or PydanticObjectId(),
        kind="collect_market_data",
        status=status,
        started_at=None if status is TaskStatus.QUEUED else (started_at or created_at),
        created_at=created_at,
    )


def _new_activity(
    employee_id: PydanticObjectId,
    *,
    message: str = "수집을 시작한다",
    occurred_at: datetime = _BASE,
) -> Activity:
    return Activity(
        employee_id=employee_id,
        task_id=PydanticObjectId(),
        level=ActivityLevel.INFO,
        message=message,
        occurred_at=occurred_at,
    )


class TaskRepositoryContract:
    async def test_get_returns_none_when_task_does_not_exist(
        self, repository: TaskRepositoryProtocol
    ) -> None:
        assert await repository.get(PydanticObjectId()) is None

    async def test_save_assigns_id_when_task_is_new(
        self, repository: TaskRepositoryProtocol
    ) -> None:
        saved = await repository.save(_new_task())

        assert saved.id is not None

    async def test_get_returns_task_with_all_fields_after_save(
        self, repository: TaskRepositoryProtocol
    ) -> None:
        employee_id = PydanticObjectId()
        saved = await repository.save(_new_task(employee_id))

        found = await repository.get(saved.id)

        assert found is not None
        assert found.employee_id == employee_id
        assert found.kind == "collect_market_data"
        assert found.status is TaskStatus.RUNNING
        assert found.created_at == _BASE
        assert found.summary is None and found.finished_at is None and found.error is None

    async def test_save_replaces_instead_of_inserting_when_task_already_has_id(
        self, repository: TaskRepositoryProtocol
    ) -> None:
        saved = await repository.save(_new_task())

        await repository.save(
            saved.model_copy(
                update={"status": TaskStatus.SUCCEEDED, "finished_at": _BASE + timedelta(hours=1)}
            )
        )

        assert len(await repository.list()) == 1
        reloaded = await repository.get(saved.id)
        assert reloaded is not None
        assert reloaded.status is TaskStatus.SUCCEEDED

    async def test_list_returns_newest_first(self, repository: TaskRepositoryProtocol) -> None:
        employee_id = PydanticObjectId()
        await repository.save(_new_task(employee_id, created_at=_BASE))
        await repository.save(_new_task(employee_id, created_at=_BASE + timedelta(hours=2)))
        await repository.save(_new_task(employee_id, created_at=_BASE + timedelta(hours=1)))

        found = await repository.list(employee_id=employee_id)

        assert [task.created_at for task in found] == [
            _BASE + timedelta(hours=2),
            _BASE + timedelta(hours=1),
            _BASE,
        ]

    async def test_list_filters_by_employee_id(self, repository: TaskRepositoryProtocol) -> None:
        employee_id = PydanticObjectId()
        await repository.save(_new_task(employee_id))
        await repository.save(_new_task(PydanticObjectId()))

        found = await repository.list(employee_id=employee_id)

        assert len(found) == 1
        assert found[0].employee_id == employee_id

    async def test_list_filters_by_status(self, repository: TaskRepositoryProtocol) -> None:
        await repository.save(_new_task(status=TaskStatus.RUNNING))
        await repository.save(_new_task(status=TaskStatus.SUCCEEDED))

        found = await repository.list(status=TaskStatus.SUCCEEDED)

        assert len(found) == 1
        assert found[0].status is TaskStatus.SUCCEEDED

    async def test_list_filters_by_employee_id_and_status_together(
        self, repository: TaskRepositoryProtocol
    ) -> None:
        employee_id = PydanticObjectId()
        await repository.save(_new_task(employee_id, status=TaskStatus.RUNNING))
        await repository.save(_new_task(employee_id, status=TaskStatus.FAILED))
        await repository.save(_new_task(PydanticObjectId(), status=TaskStatus.RUNNING))

        found = await repository.list(employee_id=employee_id, status=TaskStatus.RUNNING)

        assert len(found) == 1
        assert found[0].employee_id == employee_id

    async def test_list_running_started_before_finds_only_stale_running(
        self, repository: TaskRepositoryProtocol
    ) -> None:
        """회수 대상 쿼리. fake와 실제 Mongo가 같은 기준으로 골라야 한다 —
        갈라지면 한쪽에서만 직원이 풀린다.
        """
        old = datetime.now(UTC) - timedelta(hours=2)
        recent = datetime.now(UTC) - timedelta(seconds=10)
        stale = await repository.save(_new_task(status=TaskStatus.RUNNING, started_at=old))
        await repository.save(_new_task(status=TaskStatus.RUNNING, started_at=recent))
        await repository.save(_new_task(status=TaskStatus.SUCCEEDED, started_at=old))
        await repository.save(_new_task(status=TaskStatus.QUEUED))

        found = await repository.list_running_started_before(
            datetime.now(UTC) - timedelta(minutes=15)
        )

        assert [task.id for task in found] == [stale.id]

    async def test_list_running_started_before_ignores_tasks_without_start_time(
        self, repository: TaskRepositoryProtocol
    ) -> None:
        """QUEUED 작업은 started_at이 없다. 스케줄러가 큐를 쌓는 구조에서 회수되면 안 된다."""
        await repository.save(_new_task(status=TaskStatus.QUEUED))

        found = await repository.list_running_started_before(datetime.now(UTC))

        assert found == []


class ActivityRepositoryContract:
    async def test_get_returns_none_when_activity_does_not_exist(
        self, repository: ActivityRepositoryProtocol
    ) -> None:
        assert await repository.get(PydanticObjectId()) is None

    async def test_append_assigns_id(self, repository: ActivityRepositoryProtocol) -> None:
        saved = await repository.append(_new_activity(PydanticObjectId()))

        assert saved.id is not None

    async def test_list_by_employee_returns_only_that_employee_recent_first(
        self, repository: ActivityRepositoryProtocol
    ) -> None:
        employee_id = PydanticObjectId()
        await repository.append(_new_activity(employee_id, message="첫째", occurred_at=_BASE))
        await repository.append(
            _new_activity(employee_id, message="셋째", occurred_at=_BASE + timedelta(minutes=2))
        )
        await repository.append(
            _new_activity(employee_id, message="둘째", occurred_at=_BASE + timedelta(minutes=1))
        )
        await repository.append(
            _new_activity(
                PydanticObjectId(), message="다른 직원", occurred_at=_BASE + timedelta(minutes=3)
            )
        )

        found = await repository.list_by_employee(employee_id, limit=10)

        assert [activity.message for activity in found] == ["셋째", "둘째", "첫째"]

    async def test_list_by_employee_applies_limit(
        self, repository: ActivityRepositoryProtocol
    ) -> None:
        employee_id = PydanticObjectId()
        for index in range(3):
            await repository.append(
                _new_activity(
                    employee_id,
                    message=f"{index}번째",
                    occurred_at=_BASE + timedelta(minutes=index),
                )
            )

        found = await repository.list_by_employee(employee_id, limit=2)

        assert [activity.message for activity in found] == ["2번째", "1번째"]

    async def test_list_by_employee_returns_activities_before_cursor(
        self, repository: ActivityRepositoryProtocol
    ) -> None:
        employee_id = PydanticObjectId()
        await repository.append(_new_activity(employee_id, message="첫째", occurred_at=_BASE))
        cursor = await repository.append(
            _new_activity(employee_id, message="둘째", occurred_at=_BASE + timedelta(minutes=1))
        )
        await repository.append(
            _new_activity(employee_id, message="셋째", occurred_at=_BASE + timedelta(minutes=2))
        )

        found = await repository.list_by_employee(employee_id, limit=10, before=cursor)

        assert [activity.message for activity in found] == ["첫째"]

    async def test_list_by_employee_uses_id_as_tiebreak_when_occurred_at_is_identical(
        self, repository: ActivityRepositoryProtocol
    ) -> None:
        """같은 시각에 여러 활동이 찍혀도 커서가 건너뛰거나 중복 반환하지 않아야 한다."""
        employee_id = PydanticObjectId()
        first = await repository.append(_new_activity(employee_id, message="첫째"))
        second = await repository.append(_new_activity(employee_id, message="둘째"))
        assert first.occurred_at == second.occurred_at

        page1 = await repository.list_by_employee(employee_id, limit=1)
        page2 = await repository.list_by_employee(employee_id, limit=1, before=page1[0])

        assert len(page1) == 1 and len(page2) == 1
        assert page1[0].id != page2[0].id


class TestInMemoryTaskRepository(TaskRepositoryContract):
    @pytest.fixture
    def repository(self) -> TaskRepositoryProtocol:
        return InMemoryTaskRepository()


class TestMongoTaskRepository(TaskRepositoryContract):
    @pytest.fixture
    def repository(self, mongo_repository_ready: None) -> TaskRepositoryProtocol:
        return TaskRepository()


class TestInMemoryActivityRepository(ActivityRepositoryContract):
    @pytest.fixture
    def repository(self) -> ActivityRepositoryProtocol:
        return InMemoryActivityRepository()


class TestMongoActivityRepository(ActivityRepositoryContract):
    @pytest.fixture
    def repository(self, mongo_repository_ready: None) -> ActivityRepositoryProtocol:
        return ActivityRepository()
