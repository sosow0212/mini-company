"""도메인 모델. 지속성 기술(Beanie)을 모른다.

employees/domain.py와 같은 이유로 Document와 분리한다: beanie 2.x Document는
생성만으로 Mongo 바인딩을 요구해서, 도메인 모델로 쓰면 service 테스트에 DB가 필요해진다.
"""

from datetime import datetime

from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict

from src.tasks.constants import ActivityLevel, TaskStatus


class Task(BaseModel):
    model_config = ConfigDict(frozen=True)

    # 아직 저장되지 않은 작업은 id가 없다.
    id: PydanticObjectId | None = None
    employee_id: PydanticObjectId
    kind: str
    status: TaskStatus = TaskStatus.QUEUED
    # 플레이스홀더({{ledger.*}})를 포함할 수 있다. 치환은 Phase 3 렌더러의 몫이다.
    summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    created_at: datetime


class Activity(BaseModel):
    """append-only. 말풍선의 원천이라 message는 그대로 화면에 노출된다.

    정정이 필요하면 새 Activity를 남긴다. UPDATE/DELETE 경로는 아예 만들지 않는다.
    """

    model_config = ConfigDict(frozen=True)

    id: PydanticObjectId | None = None
    employee_id: PydanticObjectId
    task_id: PydanticObjectId | None
    level: ActivityLevel
    message: str
    # 서버 시계로 찍는다. 워커 시계에 의존하면 정렬·커서 페이지네이션이 흔들린다.
    occurred_at: datetime
