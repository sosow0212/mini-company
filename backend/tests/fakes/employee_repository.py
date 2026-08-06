from beanie import PydanticObjectId

from src.employees.constants import EmployeeStatus, Role
from src.employees.domain import Employee


class InMemoryEmployeeRepository:
    """EmployeeRepository의 경계 대체물. mock이 아니라 실제로 동작하는 구현체다.

    실제 Mongo 구현과 동작이 갈라지면 테스트가 거짓말을 하므로,
    tests/integration의 계약 스위트를 두 구현에 동일하게 돌린다.
    """

    def __init__(self, employees: list[Employee] | None = None) -> None:
        self._by_id: dict[PydanticObjectId, Employee] = {}
        for employee in employees or []:
            self._by_id[_require_id(employee)] = employee

    async def get(self, employee_id: PydanticObjectId) -> Employee | None:
        return self._by_id.get(employee_id)

    async def get_by_name(self, name: str) -> Employee | None:
        return next((e for e in self._by_id.values() if e.name == name), None)

    async def list(
        self,
        *,
        role: Role | None = None,
        status: EmployeeStatus | None = None,
    ) -> list[Employee]:
        matched = [
            employee
            for employee in self._by_id.values()
            if (role is None or employee.role == role)
            and (status is None or employee.status == status)
        ]
        return sorted(matched, key=lambda employee: employee.name)

    async def save(self, employee: Employee) -> Employee:
        stored = (
            employee
            if employee.id is not None
            else employee.model_copy(update={"id": PydanticObjectId()})
        )
        self._by_id[_require_id(stored)] = stored
        return stored

    async def delete(self, employee_id: PydanticObjectId) -> bool:
        return self._by_id.pop(employee_id, None) is not None


def _require_id(employee: Employee) -> PydanticObjectId:
    if employee.id is None:
        raise ValueError("저장된 직원에는 id가 있어야 한다")
    return employee.id
