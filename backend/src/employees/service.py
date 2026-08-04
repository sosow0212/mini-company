from datetime import UTC, datetime

from beanie import PydanticObjectId

from src.employees.constants import EmployeeStatus, Role
from src.employees.domain import DeskPosition, Employee
from src.employees.exceptions import EmployeeNotFound
from src.employees.repository import EmployeeRepositoryProtocol
from src.employees.schemas import EmployeeResponse


class EmployeeService:
    """비즈니스 로직. Beanie 쿼리 API가 이 파일에 등장하면 레이어가 무너진다."""

    def __init__(self, repository: EmployeeRepositoryProtocol) -> None:
        self._repository = repository

    async def list_employees(
        self,
        *,
        role: Role | None = None,
        status: EmployeeStatus | None = None,
    ) -> list[EmployeeResponse]:
        employees = await self._repository.list(role=role, status=status)
        return [EmployeeResponse.from_domain(employee) for employee in employees]

    async def get_employee(self, employee_id: PydanticObjectId) -> EmployeeResponse:
        employee = await self._repository.get(employee_id)
        if employee is None:
            raise EmployeeNotFound
        return EmployeeResponse.from_domain(employee)

    async def hire_or_update(
        self,
        *,
        name: str,
        role: Role,
        desk: DeskPosition,
    ) -> EmployeeResponse:
        """시드가 쓰는 멱등 등록. 이름을 신원으로 본다.

        재실행이 런타임 상태(status)와 입사일을 되돌리면 안 된다. 시드가 정의하는 것은
        직무와 책상 위치뿐이다.
        """
        existing = await self._repository.get_by_name(name)
        target = (
            Employee(name=name, role=role, desk=desk, hired_at=datetime.now(UTC))
            if existing is None
            else existing.model_copy(update={"role": role, "desk": desk})
        )
        return EmployeeResponse.from_domain(await self._repository.save(target))
