"""멈춘 작업 회수 루프. 백엔드 lifespan에서 돈다.

**왜 워커가 아니라 백엔드인가:** 회수는 워커가 죽어서 생긴 문제를 고치는 일이다. 그걸
워커에게 맡기면 "죽은 프로세스가 자기 죽음을 정리한다"는 순환이 된다. 백엔드는 워커가
전부 죽어도 살아 있으므로 여기가 맞는 자리다.

**replica 2에서 중복 실행:** 여러 replica가 같은 작업을 회수하려 할 수 있다. 앞선 하나가
CANCELLED로 바꾸면 나머지는 `InvalidTaskTransition`에 걸려 아무 일도 하지 않는다 —
상태 전이 검증이 분산 락 역할을 한다. 로그만 조금 늘어난다.
"""

import asyncio
import logging

from src.config import Settings
from src.employees.repository import EmployeeRepository
from src.realtime.bus import EventBus
from src.tasks.repository import ActivityRepository, TaskRepository
from src.tasks.service import TaskService

logger = logging.getLogger(__name__)


async def run_reaper_loop(settings: Settings, events: EventBus) -> None:
    """`asyncio.CancelledError`로 종료된다 — lifespan이 취소하면 즉시 빠져나온다."""
    interval = settings.reaper_interval_seconds
    logger.info(
        "멈춘 작업 회수 루프 시작",
        extra={
            "interval_seconds": interval,
            "timeout_seconds": settings.stale_task_timeout_seconds,
        },
    )
    while True:
        # 부팅 직후에 바로 돌지 않는다. 배포 중이면 정상 작업이 아직 진행 중일 수 있고,
        # 그때 회수 쿼리가 도는 것은 의미가 없다.
        await asyncio.sleep(interval)
        try:
            await _reap_once(settings, events)
        except asyncio.CancelledError:
            logger.info("멈춘 작업 회수 루프 종료")
            raise
        except Exception:
            # 한 번의 실패로 루프가 죽으면 그 뒤로 회수가 영구히 멈춘다. 다음 주기에 재시도한다.
            logger.exception("멈춘 작업 회수 중 오류")


async def _reap_once(settings: Settings, events: EventBus) -> None:
    """요청 스코프가 없으므로 DI 대신 직접 조립한다.

    매 주기마다 새로 만드는 이유: repository는 상태가 없고 생성 비용이 사실상 0이다.
    루프 밖에 보관하면 Beanie 재바인딩(테스트·재시작) 시점과 얽힌다.
    """
    service = TaskService(TaskRepository(), ActivityRepository(), EmployeeRepository(), events)
    reaped = await service.reap_stale_tasks(timeout_seconds=settings.stale_task_timeout_seconds)
    if reaped:
        logger.warning(
            "멈춘 작업을 회수했다",
            extra={"count": len(reaped), "task_ids": ",".join(task.id for task in reaped)},
        )
