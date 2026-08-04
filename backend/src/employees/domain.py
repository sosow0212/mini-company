"""도메인 모델. 지속성 기술(Beanie)을 모른다.

Beanie Document를 그대로 도메인 모델로 쓰지 않는 이유:
beanie 2.x의 `Document.__init__`은 `get_pymongo_collection()`을 호출하므로,
인스턴스를 만드는 것만으로도 `init_beanie`(= 실제 Mongo 접속)가 필요하다.
그러면 ADR-004가 약속한 "service 테스트에서 DB가 사라진다"가 성립하지 않는다.
변환 비용(repository의 매핑 함수 2개)을 내고 그 보상을 지킨다.
"""

from datetime import datetime

from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict

from src.employees.constants import EmployeeStatus, Role


class DeskPosition(BaseModel):
    """3D 씬의 책상 좌표."""

    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    z: float


class Employee(BaseModel):
    model_config = ConfigDict(frozen=True)

    # 아직 저장되지 않은 직원은 id가 없다.
    id: PydanticObjectId | None = None
    name: str
    role: Role
    status: EmployeeStatus = EmployeeStatus.OFFLINE
    desk: DeskPosition
    # 지금 수행 중인 작업. None이면 비어 있다. 직원 1명은 동시에 작업 1걸만 가진다.
    current_task_id: PydanticObjectId | None = None
    hired_at: datetime
