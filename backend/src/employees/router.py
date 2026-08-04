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
