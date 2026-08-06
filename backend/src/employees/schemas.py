from datetime import datetime

from pydantic import Field

from src.employees.constants import EmployeeStatus, Role
from src.employees.domain import Employee
from src.schemas import ApiModel

# 이름은 3D 씬의 이름표로도 쓰인다. 길면 아바타를 가린다.
_NAME_MAX = 30


class HireEmployeeRequest(ApiModel):
    """채용 요청.

    책상 좌표와 LLM 프로파일은 받지 않는다 — 서버가 정한다. 좌표는 사무실 레이아웃의
    문제이고, 프로파일은 직무에서 파생된다(§8.3). 클라이언트가 고르게 하면 배정 규칙이
    두 곳으로 갈라진다.
    """

    name: str = Field(min_length=1, max_length=_NAME_MAX)
    role: Role


class UpdateEmployeeRequest(ApiModel):
    """부분 수정. None인 필드는 건드리지 않는다.

    상태(status)와 진행 중 작업은 여기서 바꿀 수 없다 — 그건 작업 실행이 만드는
    결과이지 사람이 직접 쓰는 값이 아니다. 손으로 IDLE로 돌리면 실제로는 돌고 있는
    워커와 화면이 어긋난다.
    """

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    role: Role | None = None


class DeskResponse(ApiModel):
    x: float
    y: float
    z: float


class EmployeeResponse(ApiModel):
    id: str
    name: str
    role: Role
    status: EmployeeStatus
    desk: DeskResponse
    current_task_id: str | None
    # 프로파일 이름만 노출한다. 모델명·키는 서버 밖으로 나가지 않는다(§8.6).
    llm_profile: str
    hired_at: datetime

    @classmethod
    def from_domain(cls, employee: Employee) -> "EmployeeResponse":
        # ObjectId는 문자열로 내린다. 프론트는 이 값을 그대로 키로 쓴다.
        if employee.id is None:
            raise ValueError("저장되지 않은 직원은 응답으로 내릴 수 없다")
        return cls(
            id=str(employee.id),
            name=employee.name,
            role=employee.role,
            status=employee.status,
            desk=DeskResponse(x=employee.desk.x, y=employee.desk.y, z=employee.desk.z),
            current_task_id=(
                str(employee.current_task_id) if employee.current_task_id is not None else None
            ),
            llm_profile=employee.llm_profile,
            hired_at=employee.hired_at,
        )
