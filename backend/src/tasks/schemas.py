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


class AddActivityRequest(ApiModel):
    level: ActivityLevel = ActivityLevel.INFO
    message: str = Field(min_length=1, max_length=500)


class FinishTaskRequest(ApiModel):
    # 워커에게 여는 종결 전이는 둘뿐이다. CANCELLED는 관리 기능(Phase 9 스케줄러)에서 다룬다.
    status: Literal[TaskStatus.SUCCEEDED, TaskStatus.FAILED]
    summary: str | None = Field(default=None, max_length=1000)
    error: str | None = Field(default=None, max_length=1000)
