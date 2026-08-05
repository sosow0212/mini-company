"""인프라 DI만 둔다 — 버스와 허브.

도메인 service들(tasks/ledger)이 이 파일을 import하므로, **여기서 도메인을 import하면
순환이 된다.** 스냅샷 조립(employees+ledger service가 필요한 쪽)은 반대 방향이라
router.py가 담당한다.
"""

from typing import Annotated

from fastapi import Depends, Request, WebSocket

from src.realtime.bus import EventBus
from src.realtime.hub import ConnectionHub


def get_event_bus(request: Request) -> EventBus:
    """부팅 시 만든 버스를 꺼낸다. HTTP 라우터(tasks/ledger)의 service가 주입받아 publish한다."""
    return request.app.state.event_bus


def get_connection_hub(websocket: WebSocket) -> ConnectionHub:
    """WS 전용이라 Request가 아니라 WebSocket을 받는다.

    Request를 받으면 WS 엔드포인트에서 주입이 실패한다 — FastAPI가 둘을 다른 타입으로
    다루고, WS 스코프에는 Request를 만들 재료가 없다.
    """
    return websocket.app.state.connection_hub


EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
ConnectionHubDep = Annotated[ConnectionHub, Depends(get_connection_hub)]
