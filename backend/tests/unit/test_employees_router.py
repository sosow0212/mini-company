"""라우터 계층 검증. 도메인 예외가 HTTP 상태코드로 번역되는지가 핵심이다."""

import pytest
from beanie import PydanticObjectId
from httpx import ASGITransport, AsyncClient

from src.employees.constants import EmployeeStatus, Role
from src.employees.dependencies import get_employee_repository
from src.main import create_app
from tests.fakes.employee_repository import InMemoryEmployeeRepository


@pytest.fixture
def client_factory():
    def _make(*employees) -> AsyncClient:
        app = create_app()
        repository = InMemoryEmployeeRepository(list(employees))
        app.dependency_overrides[get_employee_repository] = lambda: repository
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return _make


async def test_get_employee_returns_404_with_domain_error_code_when_id_is_unknown(
    client_factory,
) -> None:
    async with client_factory() as client:
        res = await client.get(f"/api/v1/employees/{PydanticObjectId()}")

    assert res.status_code == 404
    assert res.json() == {
        "code": "employee_not_found",
        "message": "해당 직원을 찾을 수 없습니다.",
    }


async def test_get_employee_returns_422_when_id_is_not_an_object_id(client_factory) -> None:
    async with client_factory() as client:
        res = await client.get("/api/v1/employees/not-an-id")

    assert res.status_code == 422


async def test_list_employees_serializes_fields_in_camel_case(
    client_factory, make_employee
) -> None:
    async with client_factory(make_employee("수집가 노아")) as client:
        res = await client.get("/api/v1/employees")

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert "hiredAt" in body[0]
    assert "hired_at" not in body[0]


async def test_list_employees_applies_query_filters(client_factory, make_employee) -> None:
    employees = (
        make_employee("작가", role=Role.WRITER, status=EmployeeStatus.WORKING),
        make_employee("분석가", role=Role.ANALYST, status=EmployeeStatus.WORKING),
    )
    async with client_factory(*employees) as client:
        res = await client.get("/api/v1/employees", params={"role": "WRITER"})

    assert [employee["name"] for employee in res.json()] == ["작가"]


async def test_list_employees_returns_422_when_role_is_not_a_known_value(
    client_factory,
) -> None:
    async with client_factory() as client:
        res = await client.get("/api/v1/employees", params={"role": "CEO"})

    assert res.status_code == 422
