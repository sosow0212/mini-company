"""RedisEventBus 계약. 실제 Redis에 붙는다.

여기서 확인하는 것은 하나다: **서로 다른 프로세스가 같은 이벤트를 받는가.**
그게 Phase 12의 완료 조건("어느 Pod에 붙어도 이벤트 수신")이고, 인메모리 버스가
못 하는 유일한 일이다. 버스 인스턴스 2개가 두 replica를 대신한다 — 한쪽이 발행하고
다른 쪽이 받으면, 프로세스 경계를 넘었다는 증거가 된다.

fake를 두지 않는다. 대체물로 검증할 수 있는 성질이 아니다(경계를 넘는 것이 본질이다).
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.config import get_settings
from src.employees.constants import EmployeeStatus
from src.realtime.redis_bus import RedisEventBus
from src.realtime.schemas import (
    ActivityCreated,
    ActivityCreatedData,
    EmployeeStatusChanged,
    EmployeeStatusChangedData,
    OfficeEvent,
)
from src.tasks.constants import ActivityLevel

# 테스트 전용 채널. 개발 중 띄워둔 앱이 같은 Redis를 보고 있어도 서로 섞이지 않는다.
_CHANNEL = "mini-company-test:office-events"
# Pub/Sub은 왕복이 필요하다. 폴링으로 기다리되 상한을 둔다 — 고정 sleep을 쓰면
# 느린 환경에서 깨지거나 빠른 환경에서 불필요하게 느려진다.
_TIMEOUT_SECONDS = 5.0


def _status_event(employee_id: str = "employee-1") -> EmployeeStatusChanged:
    return EmployeeStatusChanged(
        data=EmployeeStatusChangedData(
            employee_id=employee_id,
            status=EmployeeStatus.WORKING,
            current_task_id="task-1",
        )
    )


class _Recorder:
    """구독자 대역. 받은 이벤트를 모으고 도착을 기다릴 수 있게 한다."""

    def __init__(self) -> None:
        self.events: list[OfficeEvent] = []
        self._arrived = asyncio.Event()

    async def handle(self, event: OfficeEvent) -> None:
        self.events.append(event)
        self._arrived.set()

    async def wait_for(self, count: int) -> list[OfficeEvent]:
        """도착하는 즉시 깨어난다. 폴링하면 간격만큼 테스트가 느려지고,
        간격을 줄이면 느린 환경에서 CPU만 태운다."""
        async with asyncio.timeout(_TIMEOUT_SECONDS):
            while len(self.events) < count:
                # clear와 wait 사이에 await가 없어 그 틈으로 이벤트가 새지 않는다.
                self._arrived.clear()
                await self._arrived.wait()
        return self.events


@pytest.fixture
async def redis_ready() -> AsyncIterator[None]:
    settings = get_settings()
    client = Redis.from_url(settings.redis_url)
    try:
        await client.ping()
    except RedisError:
        pytest.skip("Redis가 필요하다. `make up`으로 인프라를 띄운다.")
    finally:
        await client.aclose()
    yield


@pytest.fixture
async def bus_factory(redis_ready: None) -> AsyncIterator[object]:
    """버스를 만들고 테스트가 끝나면 전부 정리한다.

    각 버스는 자기 Redis 연결을 갖는다 — 별도 프로세스를 흉내 내는 것이 목적이라
    연결을 공유하면 검증이 무의미해진다.
    """
    created: list[RedisEventBus] = []
    settings = get_settings()

    async def _make(*handlers) -> RedisEventBus:
        bus = RedisEventBus(Redis.from_url(settings.redis_url), channel=_CHANNEL)
        for handler in handlers:
            bus.subscribe(handler)
        await bus.start()
        # 구독이 실제로 등록되기 전에 발행하면 그 이벤트는 사라진다(Pub/Sub은 저장하지
        # 않는다). 채널 구독자 수가 늘어나는 것으로 준비 완료를 확인한다.
        await _await_subscriber_count(len(created) + 1)
        created.append(bus)
        return bus

    async def _await_subscriber_count(expected: int) -> None:
        probe = Redis.from_url(settings.redis_url)
        try:
            async with asyncio.timeout(_TIMEOUT_SECONDS):
                while True:
                    counts = await probe.pubsub_numsub(_CHANNEL)
                    if counts and counts[0][1] >= expected:
                        return
                    await asyncio.sleep(0.02)
        finally:
            await probe.aclose()

    yield _make

    for bus in created:
        await bus.stop()


async def test_event_published_on_one_bus_reaches_another(bus_factory) -> None:
    """Phase 12 완료 조건. 발행한 쪽과 받는 쪽이 다른 인스턴스다."""
    listener = _Recorder()
    await bus_factory(listener.handle)
    publisher = await bus_factory()

    await publisher.publish(_status_event())

    received = await listener.wait_for(1)
    assert isinstance(received[0], EmployeeStatusChanged)
    assert received[0].data.employee_id == "employee-1"
    assert received[0].data.status is EmployeeStatus.WORKING


async def test_publisher_also_receives_its_own_event(bus_factory) -> None:
    """발행한 Pod도 Redis를 한 바퀴 돌아 받는다.

    로컬 지름길을 두지 않기 때문이다. 그래야 replica 1과 2의 동작이 같고,
    "발행한 Pod에서만 되는" 차이가 개발 중에 숨지 않는다.
    """
    recorder = _Recorder()
    bus = await bus_factory(recorder.handle)

    await bus.publish(_status_event())

    assert len(await recorder.wait_for(1)) == 1


async def test_every_subscriber_gets_the_event(bus_factory) -> None:
    """replica 2대 + 발행자. 둘 다 받아야 한다."""
    first, second = _Recorder(), _Recorder()
    await bus_factory(first.handle)
    await bus_factory(second.handle)
    publisher = await bus_factory()

    await publisher.publish(_status_event())

    assert len(await first.wait_for(1)) == 1
    assert len(await second.wait_for(1)) == 1


async def test_event_survives_serialization_with_its_type(bus_factory) -> None:
    """discriminated union이 왕복 후에도 구체 타입으로 복원되어야 한다.

    dict로 흐르면 프론트로 나가는 스키마가 조용히 달라진다.
    """
    recorder = _Recorder()
    await bus_factory(recorder.handle)
    publisher = await bus_factory()
    occurred_at = datetime(2026, 8, 6, 12, tzinfo=UTC)

    await publisher.publish(
        ActivityCreated(
            data=ActivityCreatedData(
                employee_id="employee-1",
                task_id="task-1",
                level=ActivityLevel.INFO,
                message="자료 3건 수집",
                occurred_at=occurred_at,
            )
        )
    )

    received = (await recorder.wait_for(1))[0]
    assert isinstance(received, ActivityCreated)
    assert received.data.message == "자료 3건 수집"
    assert received.data.occurred_at == occurred_at


async def test_one_failing_subscriber_does_not_block_the_others(bus_factory) -> None:
    """구독자 하나가 터져도 나머지는 받는다. 이벤트 전달은 최선 노력이다."""

    async def explode(event: OfficeEvent) -> None:
        raise RuntimeError("의도된 실패")

    recorder = _Recorder()
    await bus_factory(explode, recorder.handle)
    publisher = await bus_factory()

    await publisher.publish(_status_event())

    assert len(await recorder.wait_for(1)) == 1


async def test_unknown_payload_does_not_kill_the_subscription(bus_factory) -> None:
    """배포 중에는 구버전과 신버전 Pod가 공존한다. 못 읽는 이벤트가 와도
    구독이 끊기면 그 Pod는 그 뒤로 아무것도 받지 못한다."""
    recorder = _Recorder()
    await bus_factory(recorder.handle)
    publisher = await bus_factory()

    raw = Redis.from_url(get_settings().redis_url)
    try:
        await raw.publish(_CHANNEL, '{"type": "future.event", "data": {}}')
    finally:
        await raw.aclose()

    await publisher.publish(_status_event())

    received = await recorder.wait_for(1)
    assert isinstance(received[0], EmployeeStatusChanged)
