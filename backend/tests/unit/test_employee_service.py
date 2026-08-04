import pytest
from beanie import PydanticObjectId

from src.employees.constants import ROLE_LLM_PROFILES, EmployeeStatus, Role
from src.employees.domain import DeskPosition
from src.employees.exceptions import EmployeeNotFound
from src.employees.service import EmployeeService
from tests.fakes.employee_repository import InMemoryEmployeeRepository

_DESK = DeskPosition(x=1.0, y=0.0, z=2.0)


def _service(*employees) -> EmployeeService:
    return EmployeeService(InMemoryEmployeeRepository(list(employees)))


async def test_get_employee_raises_not_found_when_id_is_unknown() -> None:
    service = _service()

    with pytest.raises(EmployeeNotFound):
        await service.get_employee(PydanticObjectId())


async def test_get_employee_returns_dto_with_string_id(make_employee) -> None:
    employee = make_employee("수집가 노아", role=Role.COLLECTOR)
    service = _service(employee)

    found = await service.get_employee(employee.id)

    assert found.id == str(employee.id)
    assert found.name == "수집가 노아"
    assert found.role is Role.COLLECTOR


async def test_list_employees_returns_all_when_no_filter_is_given(make_employee) -> None:
    service = _service(make_employee("가"), make_employee("나"))

    found = await service.list_employees()

    assert [employee.name for employee in found] == ["가", "나"]


async def test_list_employees_filters_by_role(make_employee) -> None:
    service = _service(
        make_employee("수집", role=Role.COLLECTOR),
        make_employee("작문", role=Role.WRITER),
    )

    found = await service.list_employees(role=Role.WRITER)

    assert [employee.name for employee in found] == ["작문"]


async def test_list_employees_filters_by_role_and_status_together(make_employee) -> None:
    service = _service(
        make_employee("일하는 작가", role=Role.WRITER, status=EmployeeStatus.WORKING),
        make_employee("쉬는 작가", role=Role.WRITER, status=EmployeeStatus.IDLE),
        make_employee("일하는 분석가", role=Role.ANALYST, status=EmployeeStatus.WORKING),
    )

    found = await service.list_employees(role=Role.WRITER, status=EmployeeStatus.WORKING)

    assert [employee.name for employee in found] == ["일하는 작가"]


async def test_hire_or_update_creates_employee_when_name_is_new() -> None:
    service = _service()

    hired = await service.hire_or_update(name="새 직원", role=Role.TRADER, desk=_DESK)

    assert hired.id
    assert hired.status is EmployeeStatus.OFFLINE
    assert (hired.desk.x, hired.desk.z) == (1.0, 2.0)


async def test_hire_or_update_updates_role_and_desk_when_employee_already_exists(
    make_employee,
) -> None:
    existing = make_employee("이동하는 직원", role=Role.COLLECTOR)
    service = _service(existing)

    updated = await service.hire_or_update(name="이동하는 직원", role=Role.ENGINEER, desk=_DESK)

    assert updated.id == str(existing.id)
    assert updated.role is Role.ENGINEER
    assert (updated.desk.x, updated.desk.z) == (1.0, 2.0)


async def test_hire_or_update_preserves_status_when_employee_already_exists(
    make_employee,
) -> None:
    """시드 재실행이 일하고 있는 직원을 OFFLINE으로 되돌리면 안 된다."""
    existing = make_employee("일하는 직원", status=EmployeeStatus.WORKING)
    service = _service(existing)

    updated = await service.hire_or_update(name="일하는 직원", role=Role.ANALYST, desk=_DESK)

    assert updated.status is EmployeeStatus.WORKING


async def test_hire_or_update_assigns_profile_from_role(make_employee) -> None:
    """프로파일 배정 규칙은 ROLE_LLM_PROFILES 한 곳에만 있어야 한다(§8.3)."""
    service = _service()

    writer = await service.hire_or_update(name="작가", role=Role.WRITER, desk=_DESK)
    analyst = await service.hire_or_update(name="분석가", role=Role.ANALYST, desk=_DESK)

    assert writer.llm_profile == ROLE_LLM_PROFILES[Role.WRITER]
    assert analyst.llm_profile == ROLE_LLM_PROFILES[Role.ANALYST]
    assert writer.llm_profile != analyst.llm_profile


async def test_hire_or_update_realigns_profile_when_role_changes(make_employee) -> None:
    """직무가 바뀌면 프로파일도 따라온다 — 갈라지면 'WRITER인데 cheap'이 조용히 남는다."""
    existing = make_employee("전직하는 직원", role=Role.TRADER, llm_profile="cheap")
    service = _service(existing)

    updated = await service.hire_or_update(name="전직하는 직원", role=Role.WRITER, desk=_DESK)

    assert updated.role is Role.WRITER
    assert updated.llm_profile == ROLE_LLM_PROFILES[Role.WRITER]


async def test_hire_or_update_preserves_hired_at_when_employee_already_exists(
    make_employee,
) -> None:
    existing = make_employee("오래된 직원")
    service = _service(existing)

    updated = await service.hire_or_update(name="오래된 직원", role=Role.ANALYST, desk=_DESK)

    assert updated.hired_at == existing.hired_at


async def test_hire_or_update_does_not_duplicate_when_run_twice() -> None:
    repository = InMemoryEmployeeRepository()
    service = EmployeeService(repository)

    await service.hire_or_update(name="멱등 직원", role=Role.WRITER, desk=_DESK)
    await service.hire_or_update(name="멱등 직원", role=Role.WRITER, desk=_DESK)

    assert len(await service.list_employees()) == 1
