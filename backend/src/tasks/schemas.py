from datetime import datetime
from typing import Literal

from beanie import PydanticObjectId
from pydantic import Field

from src.pagination import CursorPage
from src.schemas import ApiModel
from src.tasks.constants import ActivityLevel, TaskStatus
from src.tasks.domain import Activity, Task


class TaskResponse(ApiModel):
    id: str
    employee_id: str
    kind: str
    title: str | None
    status: TaskStatus
    summary: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    created_at: datetime

    @classmethod
    def from_domain(cls, task: Task) -> "TaskResponse":
        if task.id is None:
            raise ValueError("저장되지 않은 작업은 응답으로 내릴 수 없다")
        return cls(
            id=str(task.id),
            employee_id=str(task.employee_id),
            kind=task.kind,
            title=task.title,
            status=task.status,
            summary=task.summary,
            started_at=task.started_at,
            finished_at=task.finished_at,
            error=task.error,
            created_at=task.created_at,
        )


class ActivityResponse(ApiModel):
    id: str
    employee_id: str
    task_id: str | None
    level: ActivityLevel
    message: str
    occurred_at: datetime

    @classmethod
    def from_domain(cls, activity: Activity) -> "ActivityResponse":
        if activity.id is None:
            raise ValueError("저장되지 않은 활동은 응답으로 내릴 수 없다")
        return cls(
            id=str(activity.id),
            employee_id=str(activity.employee_id),
            task_id=str(activity.task_id) if activity.task_id is not None else None,
            level=activity.level,
            message=activity.message,
            occurred_at=activity.occurred_at,
        )


ActivityPage = CursorPage[ActivityResponse]


class StartTaskRequest(ApiModel):
    employee_id: PydanticObjectId
    kind: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=120)


class AssignTaskRequest(ApiModel):
    """사람이 UI에서 시키는 일.

    `kind`는 워커가 실행할 워크플로우를 고르는 식별자이고, `title`은 화면에 뜨는
    한 줄 설명이다. 상태는 받지 않는다 — 항상 QUEUED로 들어가고, RUNNING은 워커가
    실제로 집어갈 때만 찍힌다.
    """

    employee_id: PydanticObjectId
    kind: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=120)


class AddActivityRequest(ApiModel):
    level: ActivityLevel = ActivityLevel.INFO
    message: str = Field(min_length=1, max_length=500)


class FinishTaskRequest(ApiModel):
    # 워커에게 여는 종결 전이는 둘뿐이다. CANCELLED는 관리 기능(Phase 9 스케줄러)에서 다룬다.
    status: Literal[TaskStatus.SUCCEEDED, TaskStatus.FAILED]
    summary: str | None = Field(default=None, max_length=1000)
    error: str | None = Field(default=None, max_length=1000)
