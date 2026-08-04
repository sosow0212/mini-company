"""직원(Employee) 애그리거트 — AI 에이전트 1명의 신원과 현재 상태.

3D 씬의 캐릭터 1개와 1:1 대응한다. 이름·직무·책상 좌표·상태, 그리고 어떤 LLM
프로파일을 쓸지를 소유한다. 무엇을 했는지는 `tasks`가, 금액은 `ledger`가 가진다 —
여기에 수치를 두면 화면 숫자의 원천이 두 곳으로 갈라진다.
"""

from beanie import PydanticObjectId
from fastapi import APIRouter

from src.employees.constants import EmployeeStatus, Role
from src.employees.dependencies import EmployeeServiceDep
from src.employees.schemas import EmployeeResponse

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("")
async def list_employees(
    service: EmployeeServiceDep,
    role: Role | None = None,
    status: EmployeeStatus | None = None,
) -> list[EmployeeResponse]:
    return await service.list_employees(role=role, status=status)


@router.get("/{employee_id}")
async def get_employee(
    employee_id: PydanticObjectId,
    service: EmployeeServiceDep,
) -> EmployeeResponse:
    return await service.get_employee(employee_id)
