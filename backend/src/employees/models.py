"""지속성 표현. 이 파일 밖으로 나가지 않는다 — repository가 도메인 모델로 변환한다."""

from datetime import datetime
from typing import ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pymongo import IndexModel

from src.employees.constants import EmployeeStatus, Role
from src.employees.domain import DeskPosition


class EmployeeDocument(Document):
    name: str
    role: Role
    status: EmployeeStatus = EmployeeStatus.OFFLINE
    # 임베디드 필드는 순수 BaseModel이라 도메인의 것을 그대로 재사용한다.
    desk: DeskPosition
    current_task_id: PydanticObjectId | None = None
    hired_at: datetime

    class Settings:
        name = "employees"
        indexes: ClassVar[list[IndexModel | str]] = [
            # 블루프린트에 없는 추가 인덱스. 시드를 이름 기준 멱등 upsert로 만들기 위한
            # 2차 방어선이다(1차는 service의 존재 확인).
            IndexModel([("name", pymongo.ASCENDING)], unique=True, name="uq_name"),
            "role",
            "status",
        ]
