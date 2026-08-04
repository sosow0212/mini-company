from typing import Protocol

import pymongo
from beanie import PydanticObjectId

from src.tasks.constants import TaskStatus
from src.tasks.domain import Activity, Task
from src.tasks.models import ActivityDocument, TaskDocument

# 목록 정렬은 최신 우선으로 고정한다. 동일 시각 tie-break는 _id로 —
# occurred_at/created_at 하나만으로는 순서가 결정적이지 않아 커서 페이지네이션이 깨진다.
_RECENT_FIRST = [("occurred_at", pymongo.DESCENDING), ("_id", pymongo.DESCENDING)]
_RECENT_FIRST_TASK = [("created_at", pymongo.DESCENDING), ("_id", pymongo.DESCENDING)]


class TaskRepositoryProtocol(Protocol):
    """service가 의존하는 경계. "없으면 예외"를 판단하지 않고 None을 반환한다."""

    async def get(self, task_id: PydanticObjectId) -> Task | None: ...

    async def list(
        self,
        *,
        employee_id: PydanticObjectId | None = None,
        status: TaskStatus | None = None,
    ) -> list[Task]: ...

    async def save(self, task: Task) -> Task: ...


class TaskRepository:
    """Beanie 쿼리는 이 파일에만 등장한다."""

    async def get(self, task_id: PydanticObjectId) -> Task | None:
        document = await TaskDocument.get(task_id)
        return _task_to_domain(document) if document is not None else None

    async def list(
        self,
        *,
        employee_id: PydanticObjectId | None = None,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        conditions = []
        if employee_id is not None:
            conditions.append(TaskDocument.employee_id == employee_id)
        if status is not None:
            conditions.append(TaskDocument.status == status)
        documents = await TaskDocument.find(*conditions).sort(_RECENT_FIRST_TASK).to_list()
        return [_task_to_domain(document) for document in documents]

    async def save(self, task: Task) -> Task:
        # id가 없으면 insert, 있으면 replace. 상태 전이는 Task가 UPDATE를 가지는 유일한 경로다.
        return _task_to_domain(await _task_to_document(task).save())


class ActivityRepositoryProtocol(Protocol):
    """append-only 경계. 조회와 추가만 있고 갱신·삭제 메서드는 의도적으로 없다."""

    async def get(self, activity_id: PydanticObjectId) -> Activity | None: ...

    async def append(self, activity: Activity) -> Activity: ...

    async def list_by_employee(
        self,
        employee_id: PydanticObjectId,
        *,
        limit: int,
        before: Activity | None = None,
    ) -> list[Activity]: ...


class ActivityRepository:
    async def get(self, activity_id: PydanticObjectId) -> Activity | None:
        document = await ActivityDocument.get(activity_id)
        return _activity_to_domain(document) if document is not None else None

    async def append(self, activity: Activity) -> Activity:
        # save()가 아니라 insert()만 쓴다 — UPDATE 경로를 물리적으로 열지 않는다.
        document = _activity_to_document(activity)
        await document.insert()
        return _activity_to_domain(document)

    async def list_by_employee(
        self,
        employee_id: PydanticObjectId,
        *,
        limit: int,
        before: Activity | None = None,
    ) -> list[Activity]:
        # before는 "(occurred_at, id)가 커서보다 과거인 것"으로 해석한다.
        query: dict[str, object] = {"employee_id": employee_id}
        if before is not None:
            query["$or"] = [
                {"occurred_at": {"$lt": before.occurred_at}},
                {"occurred_at": before.occurred_at, "_id": {"$lt": before.id}},
            ]
        documents = await ActivityDocument.find(query).sort(_RECENT_FIRST).limit(limit).to_list()
        return [_activity_to_domain(document) for document in documents]


def _task_to_domain(document: TaskDocument) -> Task:
    return Task(
        id=document.id,
        employee_id=document.employee_id,
        kind=document.kind,
        status=document.status,
        summary=document.summary,
        started_at=document.started_at,
        finished_at=document.finished_at,
        error=document.error,
        created_at=document.created_at,
    )


def _task_to_document(task: Task) -> TaskDocument:
    return TaskDocument(
        id=task.id,
        employee_id=task.employee_id,
        kind=task.kind,
        status=task.status,
        summary=task.summary,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error=task.error,
        created_at=task.created_at,
    )


def _activity_to_domain(document: ActivityDocument) -> Activity:
    return Activity(
        id=document.id,
        employee_id=document.employee_id,
        task_id=document.task_id,
        level=document.level,
        message=document.message,
        occurred_at=document.occurred_at,
    )


def _activity_to_document(activity: Activity) -> ActivityDocument:
    return ActivityDocument(
        id=activity.id,
        employee_id=activity.employee_id,
        task_id=activity.task_id,
        level=activity.level,
        message=activity.message,
        occurred_at=activity.occurred_at,
    )
