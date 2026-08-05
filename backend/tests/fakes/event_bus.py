"""이벤트 버스 경계 대체물.

발행된 이벤트를 그대로 모아두므로, service 테스트가 "관찰 가능한 결과"로 검증할 수 있다
(`assert_called_with`가 아니라 실제로 나간 페이로드를 본다).
"""

from src.realtime.bus import EventHandler
from src.realtime.schemas import OfficeEvent


class RecordingEventBus:
    def __init__(self) -> None:
        self.published: list[OfficeEvent] = []
        self._handlers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def publish(self, event: OfficeEvent) -> None:
        self.published.append(event)
        for handler in self._handlers:
            await handler(event)

    def types(self) -> list[str]:
        return [event.type for event in self.published]

    def of_type(self, event_type: str) -> list[OfficeEvent]:
        return [event for event in self.published if event.type == event_type]
