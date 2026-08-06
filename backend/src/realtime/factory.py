"""버스 구현 선택. 조립 지점이라 설정을 읽는 유일한 곳이다.

Phase 12에서 RedisEventBus를 여기에 추가했고, 도메인 코드는 한 줄도 바뀌지 않았다 —
그게 ADR-008에서 인터페이스를 미리 둔 값어치다.
"""

import logging

from fastapi import FastAPI
from redis.asyncio import Redis

from src.config import Settings
from src.realtime.bus import EventBus, InMemoryEventBus
from src.realtime.hub import ConnectionHub
from src.realtime.redis_bus import RedisEventBus

logger = logging.getLogger(__name__)


def attach_realtime(app: FastAPI, settings: Settings) -> EventBus:
    """버스와 허브를 만들어 app.state에 붙이고 서로 연결한다.

    lifespan과 테스트가 같은 함수를 쓴다. 테스트가 이 배선을 손으로 재현하면
    조립 순서가 갈라지고, "테스트는 통과하는데 실서버에서 이벤트가 안 오는" 상태가 된다.

    **버스를 반환하는 이유**: 프로세스 밖에서 이벤트를 받는 구현은 `start()`로 리스너를
    띄우고 종료 시 `stop()`으로 거둬야 한다. 그 수명은 여기가 아니라 호출자(lifespan)가
    안다. 반환값을 두면 "이걸로 뭔가 더 해야 한다"가 시그니처에 드러난다 — 조립만 하고
    끝내면 그 Pod는 이벤트를 발행만 하고 받지는 못하는 상태로 조용히 뜬다.
    ASGITransport처럼 lifespan을 돌리지 않는 테스트는 memory 버스를 쓰므로 그대로 둬도 된다.
    """
    bus = build_event_bus(settings)
    hub = ConnectionHub()
    bus.subscribe(hub.broadcast)
    app.state.event_bus = bus
    app.state.connection_hub = hub
    return bus


def build_event_bus(settings: Settings) -> EventBus:
    if settings.event_bus == "redis":
        logger.info("EVENT_BUS=redis — channel=%s", settings.redis_event_channel)
        return RedisEventBus(
            Redis.from_url(settings.redis_url),
            channel=settings.redis_event_channel,
        )

    logger.warning(
        "EVENT_BUS=memory — backend replica가 2 이상이면 일부 클라이언트가 "
        "이벤트를 받지 못한다. 다중 replica에서는 EVENT_BUS=redis가 필수다(ADR-008)."
    )
    return InMemoryEventBus()
