"""주기 실행. 로컬용이고 K8s에서는 CronJob이 이 역할을 대체한다(§10.2).

**여기서 "매일 오전 11시에 이 일을 해라"가 성립한다.** 지금까지는 사람이 워커를 직접
실행해야 했다.

K8s로 옮길 때 이 파일을 지우고 CronJob 매니페스트를 쓴다 — 그래서 잡 본체를
`_JOBS`에 이름→함수로만 두고, 스케줄러가 그것을 감싸는 구조로 만든다. CronJob은 같은
함수를 `python -m src.employees.collector`로 한 번 호출하면 된다.

실행: cd workers && .venv/bin/python -m src.scheduler
"""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.employees import collector
from src.logging_setup import configure_logging
from src.runtime.config import get_settings

logger = logging.getLogger(__name__)

# 잡 이름 → 실행 함수. 새 주기 작업은 여기 한 줄과 크론 설정으로 추가한다.
_JOBS: dict[str, Callable[[], Awaitable[int]]] = {
    "collect": collector.run,
}


async def run_job(name: str) -> None:
    """잡 하나를 실행하고 결과를 남긴다.

    예외를 밖으로 내지 않는다 — 스케줄러가 죽으면 이후 모든 주기 작업이 멈춘다.
    개별 잡의 실패는 로그로 남기고 다음 주기를 기다린다.
    """
    job = _JOBS.get(name)
    if job is None:
        logger.error("등록되지 않은 잡", extra={"job": name, "available": ",".join(_JOBS)})
        return

    logger.info("잡 시작", extra={"job": name})
    try:
        exit_code = await job()
    except Exception:
        logger.exception("잡 실패", extra={"job": name})
        return
    logger.info("잡 종료", extra={"job": name, "exit_code": exit_code})


def build_scheduler(*, cron: str, job: str, timezone: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        run_job,
        trigger=CronTrigger.from_crontab(cron, timezone=timezone),
        args=[job],
        id=job,
        # 겹침 방지: 앞 실행이 아직 돌고 있으면 새로 띄우지 않는다. 같은 직원에게 두 작업을
        # 시키면 EmployeeBusy(409)가 나므로, 여기서 막는 편이 낫다.
        max_instances=1,
        # 프로세스가 잠깐 멈췄다 살아난 경우 놓친 실행을 한 번만 따라잡는다.
        coalesce=True,
        misfire_grace_time=300,
    )
    return scheduler


async def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)

    scheduler = build_scheduler(
        cron=settings.schedule_cron,
        job=settings.schedule_job,
        timezone=settings.schedule_timezone,
    )
    scheduler.start()
    logger.info(
        "스케줄러 시작",
        extra={
            "cron": settings.schedule_cron,
            "job": settings.schedule_job,
            "timezone": settings.schedule_timezone,
            "next_run": str(scheduler.get_job(settings.schedule_job).next_run_time),
        },
    )

    # SIGTERM 핸들러를 **명시적으로** 등록한다. asyncio는 기본으로 설치하지 않아서,
    # 없으면 SIGTERM에 프로세스가 즉시 죽고 아래 finally가 실행되지 않는다. 컨테이너와
    # K8s가 보내는 신호가 바로 SIGTERM이므로, 이게 없으면 진행 중 잡이 항상 잘린다
    # (그 작업은 RUNNING에 남아 백엔드 회수 루프를 기다리게 된다).
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, stop.set)

    try:
        await stop.wait()
        logger.info("종료 신호 수신")
    finally:
        # 진행 중 잡을 기다린다. 기다리지 않으면 작업이 RUNNING에 남아 회수 대상이 된다.
        scheduler.shutdown(wait=True)
        logger.info("스케줄러 종료 완료")


if __name__ == "__main__":
    # SIGINT는 위에서 핸들러로 처리하지만, 핸들러 등록 전에 눌린 Ctrl+C는 여기로 온다.
    with suppress(KeyboardInterrupt):
        asyncio.run(main())
