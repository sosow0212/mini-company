"""이벤트 버스. 브로드캐스트를 인터페이스 뒤에 두는 이유가 ADR-008이다.

WebSocket 연결 자체는 프로세스에 묶이지만, **이벤트 전달 경로**는 프로세스를 넘을 수
있어야 한다. 이걸 미리 추상화하지 않으면 replica를 2로 올리는 순간 "어떤 사용자는
이벤트를 못 받는" 디버깅 최악의 버그가 생긴다.

  로컬/단일 replica : InMemoryEventBus  (이 파일)
  K8s 다중 replica  : RedisEventBus     (Phase 12)

service가 상태를 바꾸고 publish하면, 각 replica의 허브가 자기 연결에만 전달한다.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from src.realtime.schemas import OfficeEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[OfficeEvent], Awaitable[None]]


class EventBus(Protocol):
    async def publish(self, event: OfficeEvent) -> None: ...

    def subscribe(self, handler: EventHandler) -> None: ...

    async def start(self) -> None:
        """수신 준비. 프로세스 밖에서 이벤트를 받는 구현은 여기서 리스너를 띄운다.

        인메모리 구현에는 할 일이 없지만 Protocol에 둔다 — 조립 지점이 어떤 구현인지
        알고 분기하기 시작하면 ADR-008의 추상화가 무의미해진다.
        """
        ...

    async def stop(self) -> None: ...


class InMemoryEventBus:
    """같은 프로세스의 구독자에게만 전달한다. replica 1에서만 완전하다."""

    def __init__(self) -> None:
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def start(self) -> None:
        """프로세스 안에서 끝나므로 띄울 리스너가 없다."""

    async def stop(self) -> None:
        """정리할 연결이 없다."""

    async def publish(self, event: OfficeEvent) -> None:
        for handler in self._handlers:
            try:
                await handler(event)
            except Exception:
                # 구독자 하나가 실패해도 발행은 계속된다. 이벤트 전달 실패가
                # 업무 트랜잭션을 되돌리면 안 된다 — 화면은 스냅샷으로 복구할 수 있다.
                logger.exception("이벤트 구독자 처리 실패: type=%s", event.type)
