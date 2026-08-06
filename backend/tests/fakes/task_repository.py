from datetime import datetime

from beanie import PydanticObjectId

from src.tasks.constants import TaskStatus
from src.tasks.domain import Activity, Task


class InMemoryTaskRepository:
    """TaskRepository의 경계 대체물. mock이 아니라 실제로 동작하는 구현체다.

    실제 Mongo 구현과 동작이 갈라지면 테스트가 거짓말을 하므로,
    tests/integration의 계약 스위트를 두 구현에 동일하게 돌린다.
    """

    def __init__(self, tasks: list[Task] | None = None) -> None:
        self._by_id: dict[PydanticObjectId, Task] = {}
        for task in tasks or []:
            self._by_id[_require_task_id(task)] = task

    async def get(self, task_id: PydanticObjectId) -> Task | None:
        return self._by_id.get(task_id)

    # 실제 구현과 같은 이유로 list()보다 앞에 둔다 — 클래스 본문에서 list 메서드를
    # 정의하면 그 뒤부터 내장 list가 가려져 list[Task] 표기가 깨진다.
    async def list_running_started_before(self, moment: datetime) -> list[Task]:
        return [
            task
            for task in self._by_id.values()
            if task.status is TaskStatus.RUNNING
            and task.started_at is not None
            and task.started_at < moment
        ]

    async def claim_oldest_queued(self, *, started_at: datetime) -> Task | None:
        queued = [task for task in self._by_id.values() if task.status is TaskStatus.QUEUED]
        if not queued:
            return None
        # 실제 구현과 같은 순서 규칙(먼저 지시한 것부터). 여기서 정렬을 빠뜨리면
        # fake만 무작위로 집어 "테스트는 통과하는데 순서가 뒤엉키는" 상태가 된다.
        oldest = min(queued, key=lambda task: task.created_at)
        claimed = oldest.model_copy(update={"status": TaskStatus.RUNNING, "started_at": started_at})
        self._by_id[_require_task_id(claimed)] = claimed
        return claimed

    async def list(
        self,
        *,
        employee_id: PydanticObjectId | None = None,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        matched = [
            task
            for task in self._by_id.values()
            if (employee_id is None or task.employee_id == employee_id)
            and (status is None or task.status == status)
        ]
        # 최신 우선 + _id tie-break. 실제 구현의 정렬과 같아야 한다.
        return sorted(matched, key=lambda task: (task.created_at, task.id), reverse=True)

    async def save(self, task: Task) -> Task:
        stored = task if task.id is not None else task.model_copy(update={"id": PydanticObjectId()})
        self._by_id[_require_task_id(stored)] = stored
        return stored


class InMemoryActivityRepository:
    """append-only 대체물. 갱신·삭제 메서드가 없는 것이 진짜 구현과의 약속이다."""

    def __init__(self, activities: list[Activity] | None = None) -> None:
        self._by_id: dict[PydanticObjectId, Activity] = {}
        for activity in activities or []:
            self._by_id[_require_activity_id(activity)] = activity

    async def get(self, activity_id: PydanticObjectId) -> Activity | None:
        return self._by_id.get(activity_id)

    async def append(self, activity: Activity) -> Activity:
        stored = (
            activity
            if activity.id is not None
            else activity.model_copy(update={"id": PydanticObjectId()})
        )
        self._by_id[_require_activity_id(stored)] = stored
        return stored

    async def list_by_employee(
        self,
        employee_id: PydanticObjectId,
        *,
        limit: int,
        before: Activity | None = None,
    ) -> list[Activity]:
        matched = [
            activity for activity in self._by_id.values() if activity.employee_id == employee_id
        ]
        ordered = sorted(
            matched, key=lambda activity: (activity.occurred_at, activity.id), reverse=True
        )
        if before is not None:
            before_id = _require_activity_id(before)
            ordered = [
                activity
                for activity in ordered
                if (activity.occurred_at, activity.id) < (before.occurred_at, before_id)
            ]
        return ordered[:limit]


def _require_task_id(task: Task) -> PydanticObjectId:
    if task.id is None:
        raise ValueError("저장된 작업에는 id가 있어야 한다")
    return task.id


def _require_activity_id(activity: Activity) -> PydanticObjectId:
    if activity.id is None:
        raise ValueError("저장된 활동에는 id가 있어야 한다")
    return activity.id
