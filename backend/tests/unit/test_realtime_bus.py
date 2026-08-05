"""이벤트 버스. 구독자 격리가 핵심이다.

이벤트 전달 실패가 업무 트랜잭션을 되돌리면 안 된다 — 화면은 스냅샷으로 복구할 수
있지만, 원장 기록이 롤백되면 숫자가 사라진다.
"""

from src.realtime.bus import InMemoryEventBus
from src.realtime.schemas import EmployeeStatusChanged, EmployeeStatusChangedData

_EVENT = EmployeeStatusChanged(
    data=EmployeeStatusChangedData(employee_id="e1", status="WORKING", current_task_id="t1")
)


async def test_publish_delivers_to_every_subscriber() -> None:
    bus = InMemoryEventBus()
    first: list[str] = []
    second: list[str] = []

    async def handler_a(event) -> None:
        first.append(event.type)

    async def handler_b(event) -> None:
        second.append(event.type)

    bus.subscribe(handler_a)
    bus.subscribe(handler_b)
    await bus.publish(_EVENT)

    assert first == ["employee.status_changed"]
    assert second == ["employee.status_changed"]


async def test_publish_is_a_noop_when_nobody_subscribed() -> None:
    """WS 연결이 하나도 없어도 발행이 실패하면 안 된다."""
    await InMemoryEventBus().publish(_EVENT)


async def test_one_failing_subscriber_does_not_stop_the_others() -> None:
    bus = InMemoryEventBus()
    delivered: list[str] = []

    async def broken(_event) -> None:
        raise RuntimeError("구독자 폭발")

    async def healthy(event) -> None:
        delivered.append(event.type)

    bus.subscribe(broken)
    bus.subscribe(healthy)
    await bus.publish(_EVENT)

    assert delivered == ["employee.status_changed"]


async def test_publish_does_not_raise_when_a_subscriber_fails() -> None:
    """발행자(service)는 구독자 사정을 몰라야 한다."""
    bus = InMemoryEventBus()

    async def broken(_event) -> None:
        raise RuntimeError("구독자 폭발")

    bus.subscribe(broken)
    await bus.publish(_EVENT)
