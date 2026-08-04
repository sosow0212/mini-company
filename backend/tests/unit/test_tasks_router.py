"""라우터 계층 검증. 인증 잠금과 도메인 예외 → HTTP 번역이 핵심이다."""

from datetime import UTC, datetime, timedelta

import pytest
from beanie import PydanticObjectId
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.employees.constants import EmployeeStatus
from src.employees.dependencies import get_employee_repository
from src.main import create_app
from src.tasks.constants import TaskStatus
from src.tasks.dependencies import get_activity_repository, get_task_repository
from tests.fakes.employee_repository import InMemoryEmployeeRepository
from tests.fakes.task_repository import (
    InMemoryActivityRepository,
    InMemoryTaskRepository,
)

WORKER_KEY = get_settings().worker_api_key.get_secret_value()
_BASE = datetime(2026, 2, 1, 9, 0, 0, tzinfo=UTC)


@pytest.fixture
def client_factory():
    def _make(*, employees=(), tasks=(), activities=()) -> AsyncClient:
        app = create_app()
        # 요청마다 새 fake가 만들어지면 첫 요청의 상태 변경이 다음 요청에서 사라진다.
        # FastAPI는 요청 단위로만 DI를 캐시하므로 인스턴스를 클로저에 고정한다.
        employee_repo = InMemoryEmployeeRepository(list(employees))
        task_repo = InMemoryTaskRepository(list(tasks))
        activity_repo = InMemoryActivityRepository(list(activities))
        app.dependency_overrides[get_employee_repository] = lambda: employee_repo
        app.dependency_overrides[get_task_repository] = lambda: task_repo
        app.dependency_overrides[get_activity_repository] = lambda: activity_repo
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Worker-Key": WORKER_KEY},
        )

    return _make


async def test_internal_endpoints_return_401_when_worker_key_is_missing(
    client_factory,
) -> None:
    task_id = PydanticObjectId()
    async with client_factory() as client:
        client.headers.pop("X-Worker-Key")
        responses = [
            await client.post(
                "/internal/v1/tasks",
                json={"employeeId": str(PydanticObjectId()), "kind": "collect_market_data"},
            ),
            await client.post(
                f"/internal/v1/tasks/{task_id}/activities", json={"message": "진행 중"}
            ),
            await client.patch(f"/internal/v1/tasks/{task_id}", json={"status": "SUCCEEDED"}),
        ]

    assert [res.status_code for res in responses] == [401, 401, 401]
    assert responses[0].json()["code"] == "worker_key_unauthorized"


async def test_internal_endpoints_return_401_when_worker_key_is_wrong(client_factory) -> None:
    async with client_factory() as client:
        client.headers["X-Worker-Key"] = "wrong-key"
        res = await client.post(
            "/internal/v1/tasks",
            json={"employeeId": str(PydanticObjectId()), "kind": "collect_market_data"},
        )

    assert res.status_code == 401


async def test_start_task_returns_201_with_camel_case_body(client_factory, make_employee) -> None:
    employee = make_employee("노아")
    async with client_factory(employees=[employee]) as client:
        res = await client.post(
            "/internal/v1/tasks",
            json={"employeeId": str(employee.id), "kind": "collect_market_data"},
        )

    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "RUNNING"
    assert body["employeeId"] == str(employee.id)
    assert "startedAt" in body
    assert "started_at" not in body


async def test_start_task_marks_employee_working_in_public_view(
    client_factory, make_employee
) -> None:
    employee = make_employee("노아")
    async with client_factory(employees=[employee]) as client:
        created = await client.post(
            "/internal/v1/tasks",
            json={"employeeId": str(employee.id), "kind": "collect_market_data"},
        )
        res = await client.get(f"/api/v1/employees/{employee.id}")

    assert res.json()["status"] == "WORKING"
    assert res.json()["currentTaskId"] == created.json()["id"]


async def test_start_task_returns_404_when_employee_is_unknown(client_factory) -> None:
    async with client_factory() as client:
        res = await client.post(
            "/internal/v1/tasks",
            json={"employeeId": str(PydanticObjectId()), "kind": "collect_market_data"},
        )

    assert res.status_code == 404
    assert res.json()["code"] == "employee_not_found"


async def test_start_task_returns_409_when_employee_is_busy(client_factory, make_employee) -> None:
    employee = make_employee(
        "노아", status=EmployeeStatus.WORKING, current_task_id=PydanticObjectId()
    )
    async with client_factory(employees=[employee]) as client:
        res = await client.post(
            "/internal/v1/tasks",
            json={"employeeId": str(employee.id), "kind": "collect_market_data"},
        )

    assert res.status_code == 409
    assert res.json()["code"] == "employee_busy"


async def test_add_activity_returns_201(client_factory, make_employee, make_task) -> None:
    employee = make_employee("노아")
    task = make_task(employee.id)
    async with client_factory(employees=[employee], tasks=[task]) as client:
        res = await client.post(
            f"/internal/v1/tasks/{task.id}/activities",
            json={"level": "WARN", "message": "중복 3건을 건너뛴다"},
        )

    assert res.status_code == 201
    body = res.json()
    assert body["level"] == "WARN"
    assert body["taskId"] == str(task.id)
    assert "occurredAt" in body


async def test_add_activity_returns_404_when_task_is_unknown(client_factory) -> None:
    async with client_factory() as client:
        res = await client.post(
            f"/internal/v1/tasks/{PydanticObjectId()}/activities",
            json={"message": "진행 중"},
        )

    assert res.status_code == 404
    assert res.json()["code"] == "task_not_found"


async def test_finish_task_returns_422_when_status_is_not_a_terminal_outcome(
    client_factory, make_employee, make_task
) -> None:
    employee = make_employee("노아")
    task = make_task(employee.id, status=TaskStatus.RUNNING)
    async with client_factory(employees=[employee], tasks=[task]) as client:
        res = await client.patch(f"/internal/v1/tasks/{task.id}", json={"status": "RUNNING"})

    assert res.status_code == 422


async def test_finish_task_returns_409_when_task_is_already_finished(
    client_factory, make_employee, make_task
) -> None:
    employee = make_employee("노아")
    task = make_task(
        employee.id,
        status=TaskStatus.SUCCEEDED,
        started_at=_BASE,
        finished_at=_BASE + timedelta(hours=1),
    )
    async with client_factory(employees=[employee], tasks=[task]) as client:
        res = await client.patch(f"/internal/v1/tasks/{task.id}", json={"status": "FAILED"})

    assert res.status_code == 409
    assert res.json()["code"] == "invalid_task_transition"


async def test_finish_task_returns_404_when_task_is_unknown(client_factory) -> None:
    async with client_factory() as client:
        res = await client.patch(
            f"/internal/v1/tasks/{PydanticObjectId()}", json={"status": "SUCCEEDED"}
        )

    assert res.status_code == 404
    assert res.json()["code"] == "task_not_found"


async def test_list_tasks_filters_by_employee_id_and_status(
    client_factory, make_employee, make_task
) -> None:
    employee = make_employee("노아")
    other = make_employee("리아")
    tasks = [
        make_task(employee.id, status=TaskStatus.RUNNING),
        make_task(employee.id, status=TaskStatus.SUCCEEDED),
        make_task(other.id, status=TaskStatus.RUNNING),
    ]
    async with client_factory(employees=[employee, other], tasks=tasks) as client:
        res = await client.get(
            "/api/v1/tasks",
            params={"employee_id": str(employee.id), "status": "RUNNING"},
        )

    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["employeeId"] == str(employee.id)
    assert body[0]["status"] == "RUNNING"


async def test_list_employee_activities_returns_page_envelope_and_paginates(
    client_factory, make_employee, make_activity
) -> None:
    employee = make_employee("노아")
    activities = [
        make_activity(
            employee.id,
            message=f"{index}번째",
            occurred_at=_BASE + timedelta(minutes=index),
        )
        for index in range(3)
    ]
    async with client_factory(employees=[employee], activities=activities) as client:
        first = await client.get(f"/api/v1/employees/{employee.id}/activities", params={"limit": 2})
        cursor = first.json()["nextCursor"]
        second = await client.get(
            f"/api/v1/employees/{employee.id}/activities",
            params={"limit": 2, "cursor": cursor},
        )

    first_body = first.json()
    assert [item["message"] for item in first_body["items"]] == ["2번째", "1번째"]
    assert cursor is not None
    second_body = second.json()
    assert [item["message"] for item in second_body["items"]] == ["0번째"]
    assert second_body["nextCursor"] is None


async def test_list_employee_activities_returns_400_when_cursor_is_invalid(
    client_factory, make_employee
) -> None:
    employee = make_employee("노아")
    async with client_factory(employees=[employee]) as client:
        res = await client.get(
            f"/api/v1/employees/{employee.id}/activities",
            params={"cursor": "not-an-object-id"},
        )

    assert res.status_code == 400
    assert res.json()["code"] == "invalid_pagination_cursor"
