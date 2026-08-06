"""WS 연결 허브. 죽은 연결이 쌓이지 않는가, 한 연결의 단절이 다른 연결을 막지 않는가."""

from starlette.websockets import WebSocketState

from src.realtime.hub import ConnectionHub
from src.realtime.schemas import (
    ActivityCreated,
    ActivityCreatedData,
    EmployeeStatusChanged,
    EmployeeStatusChangedData,
)

_STATUS_EVENT = EmployeeStatusChanged(
    data=EmployeeStatusChangedData(employee_id="e1", status="WORKING", current_task_id="t1")
)


class FakeWebSocket:
    """WebSocket 경계 대체물. accept/send_json/client_state만 흉내낸다."""

    def __init__(self, *, connected: bool = True, fail_on_send: bool = False) -> None:
        self.client_state = WebSocketState.CONNECTED if connected else WebSocketState.DISCONNECTED
        self._fail_on_send = fail_on_send
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        if self._fail_on_send:
            raise RuntimeError("소켓이 이미 닫혔다")
        self.sent.append(payload)


async def test_register_accepts_the_connection() -> None:
    hub = ConnectionHub()
    websocket = FakeWebSocket()

    await hub.register(websocket)

    assert websocket.accepted is True
    assert hub.connection_count == 1


async def test_unregister_removes_the_connection() -> None:
    hub = ConnectionHub()
    websocket = FakeWebSocket()
    await hub.register(websocket)

    hub.unregister(websocket)

    assert hub.connection_count == 0


async def test_unregister_is_idempotent() -> None:
    hub = ConnectionHub()
    websocket = FakeWebSocket()

    hub.unregister(websocket)
    hub.unregister(websocket)

    assert hub.connection_count == 0


async def test_broadcast_sends_to_every_connection() -> None:
    hub = ConnectionHub()
    first, second = FakeWebSocket(), FakeWebSocket()
    await hub.register(first)
    await hub.register(second)

    await hub.broadcast(_STATUS_EVENT)

    assert len(first.sent) == 1
    assert len(second.sent) == 1


async def test_broadcast_serializes_in_camel_case_with_a_type_discriminator() -> None:
    hub = ConnectionHub()
    websocket = FakeWebSocket()
    await hub.register(websocket)

    await hub.broadcast(_STATUS_EVENT)

    payload = websocket.sent[0]
    assert payload["type"] == "employee.status_changed"
    assert payload["data"]["employeeId"] == "e1"
    assert payload["data"]["currentTaskId"] == "t1"
    assert "employee_id" not in payload["data"]


async def test_broadcast_serializes_datetime_as_a_string() -> None:
    """mode="json"이 아니면 WS 전송에서 datetime 직렬화가 터진다."""
    hub = ConnectionHub()
    websocket = FakeWebSocket()
    await hub.register(websocket)
    from datetime import UTC, datetime

    event = ActivityCreated(
        data=ActivityCreatedData(
            employee_id="e1",
            task_id="t1",
            level="INFO",
            message="수집 준비 완료",
            occurred_at=datetime(2026, 8, 5, 12, tzinfo=UTC),
        )
    )

    await hub.broadcast(event)

    assert isinstance(websocket.sent[0]["data"]["occurredAt"], str)


async def test_broadcast_drops_a_connection_that_fails_to_send() -> None:
    hub = ConnectionHub()
    broken, healthy = FakeWebSocket(fail_on_send=True), FakeWebSocket()
    await hub.register(broken)
    await hub.register(healthy)

    await hub.broadcast(_STATUS_EVENT)

    assert hub.connection_count == 1
    assert len(healthy.sent) == 1, "한 연결의 단절이 다른 연결을 막으면 안 된다"


async def test_broadcast_drops_a_connection_that_is_no_longer_connected() -> None:
    hub = ConnectionHub()
    stale = FakeWebSocket(connected=False)
    await hub.register(stale)

    await hub.broadcast(_STATUS_EVENT)

    assert hub.connection_count == 0
    assert stale.sent == []


async def test_broadcast_is_a_noop_when_there_are_no_connections() -> None:
    await ConnectionHub().broadcast(_STATUS_EVENT)


# ─── graceful shutdown (Phase 9) ──────────────────────────────


class ClosableFakeWebSocket(FakeWebSocket):
    """close()까지 흉내내는 대체물. 종료 경로 검증용."""

    def __init__(self, *, fail_on_close: bool = False) -> None:
        super().__init__()
        self._fail_on_close = fail_on_close
        self.closed_with: int | None = None

    async def close(self, code: int = 1000) -> None:
        if self._fail_on_close:
            raise RuntimeError("이미 끊긴 소켓")
        self.closed_with = code


async def test_close_all_closes_every_connection_with_going_away() -> None:
    """정상 종료 코드로 닫으면 브라우저가 즉시 재연결해 다른 replica에 붙는다.
    닫지 않고 죽으면 네트워크 오류로 보고 지수 백오프에 들어간다.
    """
    hub = ConnectionHub()
    first, second = ClosableFakeWebSocket(), ClosableFakeWebSocket()
    await hub.register(first)
    await hub.register(second)

    await hub.close_all()

    assert first.closed_with == 1001
    assert second.closed_with == 1001
    assert hub.connection_count == 0


async def test_close_all_survives_a_socket_that_fails_to_close() -> None:
    """종료 경로에서 예외가 나면 나머지 정리가 멈춘다."""
    hub = ConnectionHub()
    broken, healthy = ClosableFakeWebSocket(fail_on_close=True), ClosableFakeWebSocket()
    await hub.register(broken)
    await hub.register(healthy)

    await hub.close_all()

    assert healthy.closed_with == 1001
    assert hub.connection_count == 0


async def test_close_all_is_a_noop_without_connections() -> None:
    await ConnectionHub().close_all()
