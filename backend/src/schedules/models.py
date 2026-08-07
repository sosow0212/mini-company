"""Beanie Document. 도메인 모델과 나누는 이유는 ADR-004(employees/models.py 참고)."""

from datetime import datetime
from typing import ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pymongo import IndexModel


class ScheduleDocument(Document):
    employee_id: PydanticObjectId
    kind: str
    title: str | None = None
    hour: int
    minute: int
    enabled: bool = True
    last_run_at: datetime | None = None
    created_at: datetime

    class Settings:
        name = "schedules"
        indexes: ClassVar[list[IndexModel | str]] = [
            # 틱 루프가 "켜져 있는 것"만 훑는다. 꺼둔 스케줄이 쌓여도 비용이 늘지 않는다.
            IndexModel([("enabled", pymongo.ASCENDING)], name="by_enabled"),
        ]
