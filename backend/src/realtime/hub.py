"""WebSocket 연결 관리.

연결 객체는 프로세스 메모리에만 존재한다 — 소켓은 원래 프로세스에 묶이므로 이건
ADR-008 위반이 아니다. 중요한 건 **이벤트가 다른 replica의 연결에도 도달하는가**이고,
그건 EventBus가 담당한다. 허브는 자기 연결에만 쓴다.
"""

import logging

from starlette.websockets import WebSocket, WebSocketState

from src.realtime.schemas import OfficeEvent

logger = logging.getLogger(__name__)


class ConnectionHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def register(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def unregister(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def broadcast(self, event: OfficeEvent) -> None:
        """EventBus의 구독자로 등록된다.

        mode="json"이어야 datetime·Decimal이 직렬화 가능한 형태로 나간다.
        by_alias로 camelCase를 쓴다 — 프론트가 받는 키는 API 응답과 같아야 한다.
        """
        if not self._connections:
            return
        payload = event.model_dump(by_alias=True, mode="json")
        for websocket in list(self._connections):
            await self._send(websocket, payload)

    async def _send(self, websocket: WebSocket, payload: dict[str, object]) -> None:
        if websocket.client_state is not WebSocketState.CONNECTED:
            self.unregister(websocket)
            return
        try:
            await websocket.send_json(payload)
        except Exception:
            # 끊긴 연결은 조용히 정리한다. 한 클라이언트의 단절이 다른 클라이언트의
            # 브로드캐스트를 막으면 안 된다.
            logger.debug("이벤트 전송 실패로 연결을 정리한다", exc_info=True)
            self.unregister(websocket)
