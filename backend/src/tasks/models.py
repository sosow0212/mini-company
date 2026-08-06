"""지속성 표현. 이 파일 밖으로 나가지 않는다 — repository가 도메인 모델로 변환한다."""

from datetime import datetime
from typing import ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pymongo import IndexModel

from src.tasks.constants import ActivityLevel, TaskStatus


class TaskDocument(Document):
    employee_id: PydanticObjectId
    kind: str
    title: str | None = None
    status: TaskStatus
    summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    created_at: datetime

    class Settings:
        name = "tasks"
        indexes: ClassVar[list[IndexModel | str]] = [
            IndexModel(
                [("employee_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
                name="employee_recent",
            ),
        ]


class ActivityDocument(Document):
    employee_id: PydanticObjectId
    task_id: PydanticObjectId | None
    level: ActivityLevel
    message: str
    occurred_at: datetime

    class Settings:
        name = "activities"
        indexes: ClassVar[list[IndexModel | str]] = [
            IndexModel(
                [("employee_id", pymongo.ASCENDING), ("occurred_at", pymongo.DESCENDING)],
                name="employee_recent",
            ),
        ]
