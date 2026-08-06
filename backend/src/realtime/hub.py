"""WebSocket 연결 관리.

연결 객체는 프로세스 메모리에만 존재한다 — 소켓은 원래 프로세스에 묶이므로 이건
ADR-008 위반이 아니다. 중요한 건 **이벤트가 다른 replica의 연결에도 도달하는가**이고,
그건 EventBus가 담당한다. 허브는 자기 연결에만 쓴다.
"""

import logging
from contextlib import suppress

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

    async def close_all(self) -> None:
        """graceful shutdown에서 열린 WS를 정리한다(§10.1).

        닫지 않고 프로세스가 죽으면 브라우저는 그것을 네트워크 오류로 보고 지수 백오프
        재연결에 들어간다. 정상 종료 코드로 닫으면 즉시 재연결해 다른 replica에 붙는다.
        """
        connections = list(self._connections)
        self._connections.clear()
        for websocket in connections:
            with suppress(Exception):
                # 이미 끊긴 소켓에 close를 호출하면 예외가 난다. 종료 경로에서 그걸로
                # 멈출 이유가 없다.
                await websocket.close(code=1001)
        if connections:
            logger.info("WS 연결 정리", extra={"count": len(connections)})

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
