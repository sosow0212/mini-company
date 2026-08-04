"""커서 페이지네이션 공통 규격.

정책(기본 20, 최대 100)은 이 모듈이 정하고, repository는 받은 값만 적용한다.
커서는 도메인마다 기준이 달라질 수 있어(activities는 occurred_at+id) 해석은 각 service가 한다.
"""

from src.schemas import ApiModel

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class CursorPage[T](ApiModel):
    items: list[T]
    # 다음 페이지가 있을 때만 마지막 아이템의 id를 담는다. 없으면 null.
    next_cursor: str | None
