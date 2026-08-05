"""버스 구현 선택. 조립 지점이라 설정을 읽는 유일한 곳이다.

Phase 12에서 RedisEventBus를 여기에 추가하면 도메인 코드는 손대지 않는다 —
그게 ADR-008에서 인터페이스를 미리 둔 값어치다.
"""

import logging

from fastapi import FastAPI

from src.config import Settings
from src.realtime.bus import EventBus, InMemoryEventBus
from src.realtime.hub import ConnectionHub

logger = logging.getLogger(__name__)


def attach_realtime(app: FastAPI, settings: Settings) -> None:
    """버스와 허브를 만들어 app.state에 붙이고 서로 연결한다.

    lifespan과 테스트가 같은 함수를 쓴다. 테스트가 이 배선을 손으로 재현하면
    조립 순서가 갈라지고, "테스트는 통과하는데 실서버에서 이벤트가 안 오는" 상태가 된다.
    """
    bus = build_event_bus(settings)
    hub = ConnectionHub()
    bus.subscribe(hub.broadcast)
    app.state.event_bus = bus
    app.state.connection_hub = hub


def build_event_bus(settings: Settings) -> EventBus:
    if settings.event_bus == "redis":
        # 설정만 받아두고 조용히 memory로 떨어지면, replica 2에서 이벤트 유실을
        # 런타임에야 발견한다. 미구현은 부팅 실패로 드러내는 편이 낫다.
        raise NotImplementedError(
            "EVENT_BUS=redis는 Phase 12에서 구현한다. 지금은 memory만 지원한다."
        )

    logger.warning(
        "EVENT_BUS=memory — backend replica가 2 이상이면 일부 클라이언트가 "
        "이벤트를 받지 못한다. 다중 replica에서는 EVENT_BUS=redis가 필수다(ADR-008)."
    )
    return InMemoryEventBus()
