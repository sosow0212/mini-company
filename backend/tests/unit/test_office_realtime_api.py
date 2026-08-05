"""스냅샷 + WebSocket 왕복.

Phase 5의 완료 조건은 "이벤트가 브라우저에 도착"이다. 그 경로를 끝까지 태운다:
  service가 상태를 바꾼다 → EventBus → ConnectionHub → 실제 WS 프레임

TestClient(starlette)를 쓰는 이유: httpx는 WebSocket을 지원하지 않는다. 동기 클라이언트라
`with client.websocket_connect(...)` 블록 안에서 요청을 보내야 한다.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from beanie import PydanticObjectId
from fastapi.testclient import TestClient

from src.config import get_settings
from src.employees.constants import EmployeeStatus
from src.employees.dependencies import get_employee_repository
from src.ledger.constants import LedgerCategory
from src.ledger.dependencies import get_ledger_repository
from src.ledger.domain import LedgerEntry
from src.main import create_app
from src.realtime.factory import attach_realtime
from src.tasks.dependencies import get_activity_repository, get_task_repository
from tests.fakes.employee_repository import InMemoryEmployeeRepository
from tests.fakes.ledger_repository import InMemoryLedgerRepository
from tests.fakes.task_repository import InMemoryActivityRepository, InMemoryTaskRepository

WORKER_KEY = get_settings().worker_api_key.get_secret_value()
_NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)
_WS_PATH = "/api/v1/ws/office"


@pytest.fixture
def client_factory(make_employee):
    def _make(*, employees=None, entries=None):
        app = create_app()
        # 프로덕션과 같은 배선 함수를 쓴다 — 손으로 재현하면 조립이 갈라진다.
        attach_realtime(app, get_settings())

        # 인스턴스를 클로저에 고정한다. lambda가 매번 새 fake를 만들면 첫 요청이 만든
        # task를 다음 요청이 찾지 못해 404가 나고, 이벤트가 발행되지 않는다.
        employee_repo = InMemoryEmployeeRepository(list(employees or []))
        ledger_repo = InMemoryLedgerRepository(list(entries or []))
        task_repo = InMemoryTaskRepository()
        activity_repo = InMemoryActivityRepository()
        app.dependency_overrides[get_employee_repository] = lambda: employee_repo
        app.dependency_overrides[get_ledger_repository] = lambda: ledger_repo
        app.dependency_overrides[get_task_repository] = lambda: task_repo
        app.dependency_overrides[get_activity_repository] = lambda: activity_repo
        return TestClient(app, headers={"X-Worker-Key": WORKER_KEY})

    return _make


def _entry(category: LedgerCategory, amount: str) -> LedgerEntry:
    return LedgerEntry(
        id=PydanticObjectId(),
        category=category,
        amount=Decimal(amount),
        unit="KRW",
        occurred_at=_NOW,
    )


# ─── 스냅샷 ────────────────────────────────────────────────────


def test_snapshot_returns_employees_and_ledger_in_one_response(
    client_factory, make_employee
) -> None:
    client = client_factory(
        employees=[make_employee("수집가 노아")],
        entries=[_entry(LedgerCategory.REVENUE, "82860000")],
    )

    res = client.get("/api/v1/office/snapshot")

    assert res.status_code == 200
    body = res.json()
    assert [e["name"] for e in body["employees"]] == ["수집가 노아"]
    assert body["ledger"]["totals"]["REVENUE"] == "82860000"


def test_snapshot_is_public(client_factory) -> None:
    client = client_factory()

    assert client.get("/api/v1/office/snapshot", headers={"X-Worker-Key": ""}).status_code == 200


def test_snapshot_amounts_are_strings(client_factory) -> None:
    """프론트는 문자열을 그대로 렌더링한다(ADR-006)."""
    client = client_factory(entries=[_entry(LedgerCategory.REVENUE, "82860000.55")])

    ledger = client.get("/api/v1/office/snapshot").json()["ledger"]

    assert ledger["totals"]["REVENUE"] == "82860000.55"
    assert isinstance(ledger["net"], str)


# ─── WebSocket ─────────────────────────────────────────────────


def test_websocket_accepts_a_connection(client_factory) -> None:
    client = client_factory()

    with client.websocket_connect(_WS_PATH):
        pass


def test_status_change_reaches_the_websocket(client_factory, make_employee) -> None:
    """직원이 일을 시작하면 아바타 색이 바뀌어야 한다 — 그 경로 전체."""
    employee = make_employee("수집가 노아")
    client = client_factory(employees=[employee])

    with client.websocket_connect(_WS_PATH) as websocket:
        client.post(
            "/internal/v1/tasks",
            json={"employeeId": str(employee.id), "kind": "collect_market_data"},
        )
        event = websocket.receive_json()

    assert event["type"] == "employee.status_changed"
    assert event["data"]["employeeId"] == str(employee.id)
    assert event["data"]["status"] == EmployeeStatus.WORKING.value


def test_activity_reaches_the_websocket_as_speech_bubble_source(
    client_factory, make_employee
) -> None:
    employee = make_employee("수집가 노아")
    client = client_factory(employees=[employee])

    with client.websocket_connect(_WS_PATH) as websocket:
        started = client.post(
            "/internal/v1/tasks",
            json={"employeeId": str(employee.id), "kind": "collect_market_data"},
        )
        # 응답을 먼저 검증한다. 요청이 실패하면 이벤트가 오지 않아 receive_json이
        # 영원히 대기하고, 실패가 hang으로 위장된다.
        assert started.status_code == 201, started.text
        websocket.receive_json()  # status_changed

        logged = client.post(
            f"/internal/v1/tasks/{started.json()['id']}/activities",
            json={"level": "INFO", "message": "수집 준비 완료"},
        )
        assert logged.status_code == 201, logged.text
        event = websocket.receive_json()

    assert event["type"] == "activity.created"
    assert event["data"]["message"] == "수집 준비 완료"


def test_ledger_entry_reaches_the_websocket_with_server_computed_values(client_factory) -> None:
    client = client_factory()

    with client.websocket_connect(_WS_PATH) as websocket:
        client.post(
            "/internal/v1/ledger/entries",
            json={"category": "REVENUE", "amount": "82860000", "occurredAt": _NOW.isoformat()},
        )
        event = websocket.receive_json()

    assert event["type"] == "ledger.summary_updated"
    assert event["data"]["totals"]["REVENUE"] == "82860000"
    assert event["data"]["net"] == "82860000"


def test_every_connected_client_receives_the_same_event(client_factory, make_employee) -> None:
    employee = make_employee("수집가 노아")
    client = client_factory(employees=[employee])

    with (
        client.websocket_connect(_WS_PATH) as first,
        client.websocket_connect(_WS_PATH) as second,
    ):
        client.post(
            "/internal/v1/tasks",
            json={"employeeId": str(employee.id), "kind": "collect_market_data"},
        )
        first_event = first.receive_json()
        second_event = second.receive_json()

    assert first_event == second_event


def test_disconnect_removes_the_connection_from_the_hub(client_factory) -> None:
    """죽은 연결이 쌓이면 브로드캐스트마다 실패 처리 비용이 늘어난다."""
    client = client_factory()
    hub = client.app.state.connection_hub

    with client.websocket_connect(_WS_PATH):
        assert hub.connection_count == 1

    assert hub.connection_count == 0


def test_events_are_not_delivered_after_disconnect(client_factory, make_employee) -> None:
    employee = make_employee("수집가 노아")
    client = client_factory(employees=[employee])

    with client.websocket_connect(_WS_PATH):
        pass
    # 연결이 끊긴 뒤 발행해도 예외 없이 지나가야 한다.
    res = client.post(
        "/internal/v1/tasks",
        json={"employeeId": str(employee.id), "kind": "collect_market_data"},
    )

    assert res.status_code == 201
