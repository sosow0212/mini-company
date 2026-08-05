"""실시간 관제 채널 — 애그리거트가 아니라 읽기 전용 투영(projection)이다.

자체 영속 상태를 소유하지 않는다. 소유하는 것은 열린 WebSocket 연결 집합과
이벤트 전달 경로뿐이고, 데이터의 주인은 `employees`·`tasks`·`ledger`다.
여기서 수치를 계산하거나 상태를 바꾸지 않는다 — 그 순간 화면과 DB가 갈라진다.

두 엔드포인트가 짝을 이룬다:
  GET  /office/snapshot  현재 상태 전체 (진입 시 1회, WS 재연결 직후 1회)
  WS   /ws/office        이후의 변화분만

재연결 후 이벤트만 이어받으면 끊긴 동안의 변경이 영구히 유실되므로, 프론트는 반드시
재연결 성공 시 스냅샷을 다시 조회해야 한다(§12).
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from starlette.websockets import WebSocketDisconnect

from src.employees.dependencies import get_employee_service
from src.employees.service import EmployeeService
from src.ledger.dependencies import get_ledger_service
from src.ledger.service import LedgerService
from src.realtime.dependencies import ConnectionHubDep
from src.realtime.schemas import OfficeSnapshot
from src.realtime.service import OfficeService

logger = logging.getLogger(__name__)

public_router = APIRouter(tags=["office"])


def get_office_service(
    employee_service: Annotated[EmployeeService, Depends(get_employee_service)],
    ledger_service: Annotated[LedgerService, Depends(get_ledger_service)],
) -> OfficeService:
    """DI가 dependencies.py가 아니라 여기 있는 이유는 그 파일 docstring 참고. (순환 이유)"""
    return OfficeService(employee_service, ledger_service)


OfficeServiceDep = Annotated[OfficeService, Depends(get_office_service)]


@public_router.get("/office/snapshot")
async def get_snapshot(service: OfficeServiceDep) -> OfficeSnapshot:
    return await service.snapshot()


@public_router.websocket("/ws/office")
async def stream_office_events(websocket: WebSocket, hub: ConnectionHubDep) -> None:
    """서버 → 클라이언트 단방향 스트림.

    클라이언트 메시지는 읽어서 버린다. 읽지 않으면 연결이 끊겼다는 사실을
    감지할 수 없어 죽은 연결이 허브에 쌓인다.
    """
    await hub.register(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(websocket)
