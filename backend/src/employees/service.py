from datetime import UTC, datetime

from beanie import PydanticObjectId

from src.employees.constants import ROLE_LLM_PROFILES, EmployeeStatus, Role
from src.employees.desk import next_free_desk
from src.employees.domain import DeskPosition, Employee
from src.employees.exceptions import EmployeeAtWork, EmployeeNameTaken, EmployeeNotFound
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

    async def hire(self, *, name: str, role: Role) -> EmployeeResponse:
        """채용. 사람이 UI에서 부르는 경로다(시드의 `hire_or_update`와 다르다).

        좌표를 요청에서 받지 않는다 — 3D 자리 배치는 사무실의 문제이지 사용자의 문제가
        아니다. LLM 프로파일도 직무에서 파생시킨다. 둘 다 사용자가 고르게 하면 "WRITER인데
        cheap" 같은 조합이 생기고, 배정 규칙이 UI와 서버 두 곳으로 갈라진다(§8.3).
        """
        name = name.strip()
        if await self._repository.get_by_name(name) is not None:
            raise EmployeeNameTaken

        occupied = [employee.desk for employee in await self._repository.list()]
        hired = await self._repository.save(
            Employee(
                name=name,
                role=role,
                # 채용 직후는 OFFLINE이다. 일을 받으면 WORKING이 된다 —
                # 처음부터 IDLE로 두면 "대기 중"과 "출근 안 함"을 구분할 수 없다.
                status=EmployeeStatus.OFFLINE,
                desk=next_free_desk(occupied),
                llm_profile=ROLE_LLM_PROFILES[role],
                hired_at=datetime.now(UTC),
            )
        )
        return EmployeeResponse.from_domain(hired)

    async def update(
        self,
        employee_id: PydanticObjectId,
        *,
        name: str | None = None,
        role: Role | None = None,
    ) -> EmployeeResponse:
        """이름·직무 변경. 상태와 진행 중 작업은 건드리지 않는다.

        직무를 바꾸면 프로파일도 함께 바뀐다. 따로 두면 둘이 갈라진 조합이 조용히 남는다.
        """
        employee = await self._repository.get(employee_id)
        if employee is None:
            raise EmployeeNotFound

        changes: dict[str, object] = {}
        if name is not None and (name := name.strip()) != employee.name:
            existing = await self._repository.get_by_name(name)
            if existing is not None and existing.id != employee_id:
                raise EmployeeNameTaken
            changes["name"] = name
        if role is not None and role != employee.role:
            changes["role"] = role
            changes["llm_profile"] = ROLE_LLM_PROFILES[role]

        if not changes:
            return EmployeeResponse.from_domain(employee)
        return EmployeeResponse.from_domain(
            await self._repository.save(employee.model_copy(update=changes))
        )

    async def fire(self, employee_id: PydanticObjectId) -> None:
        """해고. 작업 중이면 거부한다.

        지우면 그 작업은 담당자 없이 RUNNING에 남고, 회수 루프가 풀어줄 직원을 찾지
        못한다. 활동·원장 기록은 그대로 남는다 — append-only라 직원이 사라져도
        "누가 무엇을 했는지"는 보존된다(ADR-003).
        """
        employee = await self._repository.get(employee_id)
        if employee is None:
            raise EmployeeNotFound
        if employee.current_task_id is not None:
            raise EmployeeAtWork
        await self._repository.delete(employee_id)

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
