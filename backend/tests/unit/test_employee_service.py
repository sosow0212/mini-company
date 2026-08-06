import pytest
from beanie import PydanticObjectId

from src.employees.constants import ROLE_LLM_PROFILES, EmployeeStatus, Role
from src.employees.domain import DeskPosition
from src.employees.exceptions import EmployeeAtWork, EmployeeNameTaken, EmployeeNotFound
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


# ─── 채용·수정·해고 (사람이 UI에서 하는 일) ──────────────────────


async def test_hire_places_the_new_desk_where_nobody_sits(make_employee) -> None:
    """좌표를 요청에서 받지 않는다. 서버가 빈 자리를 찾는다."""
    service = _service()

    first = await service.hire(name="첫 직원", role=Role.COLLECTOR)
    second = await service.hire(name="둘째 직원", role=Role.WRITER)

    assert (first.desk.x, first.desk.z) != (second.desk.x, second.desk.z)


async def test_hire_derives_the_llm_profile_from_the_role() -> None:
    """프로파일을 요청에서 받으면 "WRITER인데 cheap" 같은 조합이 생긴다(§8.3)."""
    service = _service()

    hired = await service.hire(name="작가", role=Role.WRITER)

    assert hired.llm_profile == ROLE_LLM_PROFILES[Role.WRITER]


async def test_hire_starts_offline_not_idle() -> None:
    """OFFLINE과 IDLE은 다르다. 채용 직후는 "아직 출근 전"이다."""
    hired = await _service().hire(name="신입", role=Role.ANALYST)

    assert hired.status is EmployeeStatus.OFFLINE


async def test_hire_rejects_a_duplicate_name(make_employee) -> None:
    service = _service(make_employee("수집가 노아"))

    with pytest.raises(EmployeeNameTaken):
        await service.hire(name="수집가 노아", role=Role.COLLECTOR)


async def test_hire_trims_surrounding_whitespace() -> None:
    hired = await _service().hire(name="  여백  ", role=Role.TRADER)

    assert hired.name == "여백"


async def test_changing_the_role_moves_the_llm_profile_with_it(make_employee) -> None:
    employee = make_employee("미르", role=Role.COLLECTOR)
    service = _service(employee)

    updated = await service.update(employee.id, role=Role.ENGINEER)

    assert updated.role is Role.ENGINEER
    assert updated.llm_profile == ROLE_LLM_PROFILES[Role.ENGINEER]


async def test_update_keeps_runtime_state(make_employee) -> None:
    """이름을 바꿨다고 일하던 직원이 놀게 되면 안 된다."""
    task_id = PydanticObjectId()
    employee = make_employee("미르", status=EmployeeStatus.WORKING, current_task_id=task_id)
    service = _service(employee)

    updated = await service.update(employee.id, name="새 이름")

    assert updated.status is EmployeeStatus.WORKING
    assert updated.current_task_id == str(task_id)


async def test_update_rejects_a_name_another_employee_already_has(make_employee) -> None:
    mine = make_employee("나")
    service = _service(mine, make_employee("남"))

    with pytest.raises(EmployeeNameTaken):
        await service.update(mine.id, name="남")


async def test_update_allows_keeping_the_same_name(make_employee) -> None:
    """자기 이름을 그대로 보내는 건 중복이 아니다."""
    employee = make_employee("그대로")
    service = _service(employee)

    updated = await service.update(employee.id, name="그대로", role=Role.TRADER)

    assert updated.name == "그대로"
    assert updated.role is Role.TRADER


async def test_fire_removes_an_idle_employee(make_employee) -> None:
    employee = make_employee("퇴사자", status=EmployeeStatus.IDLE)
    service = _service(employee)

    await service.fire(employee.id)

    with pytest.raises(EmployeeNotFound):
        await service.get_employee(employee.id)


async def test_fire_refuses_while_a_task_is_in_flight(make_employee) -> None:
    """지우면 그 작업은 담당자 없이 RUNNING에 남고 회수 루프가 풀어줄 대상을 잃는다."""
    employee = make_employee(
        "일하는중", status=EmployeeStatus.WORKING, current_task_id=PydanticObjectId()
    )
    service = _service(employee)

    with pytest.raises(EmployeeAtWork):
        await service.fire(employee.id)


async def test_fire_reuses_the_freed_desk(make_employee) -> None:
    """해고로 생긴 빈자리를 다음 채용이 다시 쓴다."""
    service = _service()
    first = await service.hire(name="먼저", role=Role.COLLECTOR)
    await service.hire(name="나중", role=Role.WRITER)

    await service.fire(PydanticObjectId(first.id))
    replacement = await service.hire(name="대체", role=Role.ANALYST)

    assert (replacement.desk.x, replacement.desk.z) == (first.desk.x, first.desk.z)
