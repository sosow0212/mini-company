"""Repository 계약 스위트.

같은 테스트를 InMemory fake와 실제 Mongo 양쪽에 돌린다. 이걸 안 하면 fake가 서서히
실제와 달라지고, 통과하는 테스트와 깨지는 프로덕션이 공존한다(AGENTS.md 테스트 규칙).

베이스 클래스는 이름이 Test로 시작하지 않아 pytest가 직접 수집하지 않는다.
"""

from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from src.employees.constants import EmployeeStatus, Role
from src.employees.domain import DeskPosition, Employee
from src.employees.repository import EmployeeRepository, EmployeeRepositoryProtocol
from tests.fakes.employee_repository import InMemoryEmployeeRepository


def _new_employee(
    name: str,
    *,
    role: Role = Role.COLLECTOR,
    status: EmployeeStatus = EmployeeStatus.OFFLINE,
) -> Employee:
    """id 없이 만든다. 저장은 repository.save가 담당한다."""
    return Employee(
        name=name,
        role=role,
        status=status,
        desk=DeskPosition(x=0.0, y=0.0, z=0.0),
        hired_at=datetime.now(UTC),
    )


class EmployeeRepositoryContract:
    async def test_get_returns_none_when_employee_does_not_exist(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        assert await repository.get(PydanticObjectId()) is None

    async def test_get_returns_employee_after_save(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        saved = await repository.save(_new_employee("노아"))

        found = await repository.get(saved.id)

        assert found is not None
        assert found.name == "노아"

    async def test_save_assigns_id_when_employee_is_new(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        saved = await repository.save(_new_employee("아이디 없는 직원"))

        assert saved.id is not None

    async def test_save_replaces_instead_of_inserting_when_employee_already_has_id(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        saved = await repository.save(_new_employee("상태 바뀔 직원"))

        await repository.save(saved.model_copy(update={"status": EmployeeStatus.WORKING}))

        assert len(await repository.list()) == 1
        reloaded = await repository.get(saved.id)
        assert reloaded is not None
        assert reloaded.status is EmployeeStatus.WORKING

    async def test_get_by_name_returns_none_when_name_is_unknown(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        assert await repository.get_by_name("없는 이름") is None

    async def test_get_by_name_returns_matching_employee(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        await repository.save(_new_employee("찾을 직원"))
        await repository.save(_new_employee("다른 직원"))

        found = await repository.get_by_name("찾을 직원")

        assert found is not None
        assert found.name == "찾을 직원"

    async def test_list_returns_employees_sorted_by_name(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        await repository.save(_new_employee("b"))
        await repository.save(_new_employee("a"))
        await repository.save(_new_employee("c"))

        found = await repository.list()

        assert [employee.name for employee in found] == ["a", "b", "c"]

    async def test_list_filters_by_role(self, repository: EmployeeRepositoryProtocol) -> None:
        await repository.save(_new_employee("작가", role=Role.WRITER))
        await repository.save(_new_employee("수집가", role=Role.COLLECTOR))

        found = await repository.list(role=Role.WRITER)

        assert [employee.name for employee in found] == ["작가"]

    async def test_list_filters_by_status(self, repository: EmployeeRepositoryProtocol) -> None:
        await repository.save(_new_employee("일하는 직원", status=EmployeeStatus.WORKING))
        await repository.save(_new_employee("쉬는 직원", status=EmployeeStatus.IDLE))

        found = await repository.list(status=EmployeeStatus.WORKING)

        assert [employee.name for employee in found] == ["일하는 직원"]

    async def test_list_filters_by_role_and_status_together(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        await repository.save(
            _new_employee("일하는 작가", role=Role.WRITER, status=EmployeeStatus.WORKING)
        )
        await repository.save(
            _new_employee("쉬는 작가", role=Role.WRITER, status=EmployeeStatus.IDLE)
        )
        await repository.save(
            _new_employee("일하는 분석가", role=Role.ANALYST, status=EmployeeStatus.WORKING)
        )

        found = await repository.list(role=Role.WRITER, status=EmployeeStatus.WORKING)

        assert [employee.name for employee in found] == ["일하는 작가"]

    async def test_delete_removes_the_employee(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        saved = await repository.save(_new_employee("퇴사자"))

        assert await repository.delete(saved.id) is True
        assert await repository.get(saved.id) is None

    async def test_delete_reports_false_when_already_gone(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        """ "없음"이 오류인지는 service가 정한다. repository는 사실만 알린다."""
        assert await repository.delete(PydanticObjectId()) is False

    async def test_delete_frees_the_name_for_reuse(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        """이름이 신원이다. 지운 뒤에도 unique 인덱스가 남으면 재채용이 막힌다."""
        saved = await repository.save(_new_employee("이름"))
        await repository.delete(saved.id)

        await repository.save(_new_employee("이름"))

        assert await repository.get_by_name("이름") is not None


class TestInMemoryEmployeeRepository(EmployeeRepositoryContract):
    @pytest.fixture
    def repository(self) -> EmployeeRepositoryProtocol:
        return InMemoryEmployeeRepository()


class TestMongoEmployeeRepository(EmployeeRepositoryContract):
    @pytest.fixture
    def repository(self, mongo_repository_ready: None) -> EmployeeRepositoryProtocol:
        return EmployeeRepository()

    async def test_save_rejects_duplicate_name_via_unique_index(
        self, repository: EmployeeRepositoryProtocol
    ) -> None:
        """DB 제약은 실제 구현에만 있는 2차 방어선이라 계약에 넣지 않는다."""
        await repository.save(_new_employee("중복 이름"))

        with pytest.raises(DuplicateKeyError):
            await repository.save(_new_employee("중복 이름"))
