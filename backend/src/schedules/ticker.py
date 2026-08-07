"""반복 지시 틱 루프.

**왜 워커가 아니라 백엔드에 있나**: 스케줄은 DB에 있고, DB를 아는 것은 백엔드다
(ADR-001). 워커가 스케줄을 읽으려면 DB 접근이나 전용 API가 필요한데, 둘 다 이 규칙을
흐린다. 여기서 하는 일은 "때가 된 스케줄로 QUEUED 작업을 만들기"까지이고, 실행은
그대로 에이전트 몫이다.

**왜 APScheduler가 아닌가**: 스케줄이 UI로 수시로 바뀐다. APScheduler를 쓰면 등록·해제를
DB 변경마다 동기화해야 하고, 그 동기화가 어긋나면 "화면엔 있는데 안 도는" 스케줄이
생긴다. 1분마다 DB를 다시 읽으면 DB가 언제나 진실이다 — 동기화할 것이 없다.

`reaper.py`와 같은 구조다(§9): lifespan이 띄우고, 예외를 삼키고, 취소로 끝난다.
"""

import asyncio
import logging
from datetime import UTC, datetime

from src.config import Settings
from src.employees.repository import EmployeeRepository
from src.realtime.bus import EventBus
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.tasks.repository import ActivityRepository, TaskRepository
from src.tasks.service import TaskService

logger = logging.getLogger(__name__)


async def run_schedule_loop(settings: Settings, events: EventBus) -> None:
    interval = settings.schedule_tick_seconds
    logger.info("반복 지시 루프 시작", extra={"interval": interval})
    while True:
        await asyncio.sleep(interval)
        try:
            await _tick_once(settings, events)
        except asyncio.CancelledError:
            logger.info("반복 지시 루프 종료")
            raise
        except Exception:
            # 한 번의 실패로 루프가 죽으면 그 뒤 모든 반복 지시가 조용히 멈춘다.
            logger.exception("반복 지시 확인 중 오류")


async def _tick_once(settings: Settings, events: EventBus) -> None:
    """DI 그래프를 여기서 직접 조립한다.

    FastAPI의 Depends는 요청 스코프라 백그라운드 루프에서 쓸 수 없다. reaper와 같은
    이유이고, 같은 방식으로 필요한 것만 손으로 만든다.
    """
    service = ScheduleService(
        ScheduleRepository(),
        EmployeeRepository(),
        TaskService(TaskRepository(), ActivityRepository(), EmployeeRepository(), events),
        timezone=settings.schedule_timezone,
    )
    created = await service.run_due(datetime.now(UTC))
    if created > 0:
        logger.info("반복 지시로 작업 생성", extra={"count": created})
