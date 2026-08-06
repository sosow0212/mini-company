"""Redis Pub/Sub 이벤트 버스. 다중 replica에서 쓴다(ADR-008).

WebSocket 연결은 특정 Pod에 묶인다. 직원 상태를 바꾼 Pod와 그 사용자의 WS가 붙어 있는
Pod가 다르면, 프로세스 안에서 끝나는 InMemoryEventBus로는 이벤트가 닿지 않는다.
Redis가 그 사이를 잇는다.

**publish는 로컬 핸들러를 직접 호출하지 않는다.** 발행한 Pod의 구독자도 Redis를 한 바퀴
돌아 받는다. 로컬만 지름길을 두면 "발행한 Pod에서는 되는데 다른 Pod에서는 안 되는" 차이가
생기고, 그건 개발 중에는 절대 드러나지 않는다(replica 1에서는 늘 같은 Pod다).
같은 경로를 강제하면 개발 환경에서 겪는 동작이 곧 운영 동작이다.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis

from src.realtime.schemas import OfficeEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[OfficeEvent], Awaitable[None]]

_EVENT_ADAPTER: TypeAdapter[OfficeEvent] = TypeAdapter(OfficeEvent)

# 구독이 끊긴 뒤 다시 붙기까지 기다리는 시간. Redis 재시작은 초 단위로 끝나므로
# 지수 백오프까지 갈 이유가 없고, 짧게 계속 두드리는 편이 복구가 빠르다.
_RECONNECT_DELAY_SECONDS = 1.0


class RedisEventBus:
    def __init__(self, client: Redis, *, channel: str) -> None:
        self._client = client
        self._channel = channel
        self._handlers: list[EventHandler] = []
        self._listener: asyncio.Task[None] | None = None

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def publish(self, event: OfficeEvent) -> None:
        try:
            await self._client.publish(self._channel, event.model_dump_json())
        except Exception:
            # 발행 실패가 업무 트랜잭션을 되돌리면 안 된다. 이벤트를 놓친 화면은
            # 재연결 시 스냅샷으로 복구된다(§12) — 원장 기록이 사라지는 것과는 다르다.
            logger.exception("이벤트 발행 실패: type=%s", event.type)

    async def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = asyncio.create_task(self._listen_forever())

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            try:
                await self._listener
            except asyncio.CancelledError:
                pass
            self._listener = None
        await self._client.aclose()

    async def _listen_forever(self) -> None:
        """끊기면 다시 붙는다.

        재연결을 포기하면 그 Pod는 살아 있는 채로 이벤트만 받지 못하는 상태가 된다.
        readiness는 통과하므로 트래픽은 계속 들어오고, 증상은 "일부 사용자만 화면이
        멈춤"으로 나타난다 — 가장 찾기 어려운 형태다.
        """
        while True:
            try:
                await self._consume()
            except asyncio.CancelledError:
                logger.info("이벤트 구독 종료")
                raise
            except Exception:
                logger.exception("이벤트 구독이 끊겼다. %.1f초 후 재시도", _RECONNECT_DELAY_SECONDS)
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)

    async def _consume(self) -> None:
        pubsub = self._client.pubsub()
        try:
            await pubsub.subscribe(self._channel)
            logger.info("이벤트 구독 시작: channel=%s", self._channel)
            async for message in pubsub.listen():
                # subscribe 확인 메시지 등이 섞여 온다. 실제 발행분만 처리한다.
                if message.get("type") != "message":
                    continue
                await self._dispatch(message["data"])
        finally:
            await pubsub.aclose()

    async def _dispatch(self, raw: bytes | str) -> None:
        try:
            event = _EVENT_ADAPTER.validate_json(raw)
        except ValidationError:
            # 배포 중에는 구버전과 신버전 Pod가 공존한다. 신버전이 발행한 새 이벤트를
            # 구버전이 못 읽는 것은 정상이며, 그 때문에 구독이 끊기면 안 된다.
            logger.warning("알 수 없는 이벤트를 건너뛴다: %s", str(raw)[:200])
            return

        for handler in self._handlers:
            try:
                await handler(event)
            except Exception:
                # 구독자 하나가 실패해도 나머지에게는 전달한다(InMemoryEventBus와 같은 규칙).
                logger.exception("이벤트 구독자 처리 실패: type=%s", event.type)
