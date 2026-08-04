from datetime import datetime

from src.employees.constants import EmployeeStatus, Role
from src.employees.domain import Employee
from src.schemas import ApiModel


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
