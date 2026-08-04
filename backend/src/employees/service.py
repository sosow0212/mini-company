from datetime import UTC, datetime

from beanie import PydanticObjectId

from src.employees.constants import ROLE_LLM_PROFILES, EmployeeStatus, Role
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

        시드가 소유하는 것은 직무·책상 위치, 그리고 **직무에서 파생되는 LLM 프로파일**이다.
        프로파일을 직무와 함께 갱신하는 이유: 둘이 갈라지면 "WRITER인데 cheap" 같은 조합이
        조용히 남는다. 배정 규칙은 ROLE_LLM_PROFILES 한 곳에만 있어야 한다(§8.3).

        런타임 상태(status)와 입사일은 보존한다 — 재실행이 일하는 직원을 되돌리면 안 된다.

        프로파일이 카탈로그에 실제로 존재하는지는 여기서 검증하지 않는다.
        `employees`가 `llm`을 알면 두 도메인이 서로를 참조하므로, 시드 스크립트와
        호출 시점(ProfileNotFound)이 그 역할을 맡는다.
        """
        existing = await self._repository.get_by_name(name)
        profile = ROLE_LLM_PROFILES[role]
        target = (
            Employee(
                name=name,
                role=role,
                desk=desk,
                llm_profile=profile,
                hired_at=datetime.now(UTC),
            )
            if existing is None
            else existing.model_copy(update={"role": role, "desk": desk, "llm_profile": profile})
        )
        return EmployeeResponse.from_domain(await self._repository.save(target))
