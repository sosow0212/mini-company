"""에이전트 루프 — 사람이 시킨 일을 집어 실행한다.

`scheduler.py`와의 차이:
  scheduler : 시간이 되면 **스스로** 작업을 만든다(매일 11시 수집).
  agent     : 사람이 UI에서 지시한 QUEUED 작업을 **집어간다**.

둘 다 같은 하네스와 같은 워크플로우를 쓴다. 실행 경로가 갈리면 "UI로 시킨 것과
스케줄로 돈 것의 결과가 다른" 상태가 되고, 그건 재현이 어렵다.

실행: cd workers && .venv/bin/python -m src.agent
"""

import asyncio
import logging
import signal

from src.logging_setup import configure_logging
from src.runtime.client import BackendApiClient, ClaimedTask
from src.runtime.config import get_settings
from src.runtime.harness import attach_to_task
from src.workflows import WORKFLOWS

logger = logging.getLogger(__name__)

# 대기열이 비었을 때 다시 물어보기까지의 간격. 짧으면 백엔드에 빈 요청이 쌓이고,
# 길면 "시켰는데 한참 가만히 있는" 것처럼 보인다.
_IDLE_POLL_SECONDS = 2.0
# 집어온 직후에는 곧바로 다음 것을 확인한다. 여러 건을 몰아 지시했을 때
# 건마다 대기 간격을 두면 체감이 급격히 나빠진다.
_BUSY_POLL_SECONDS = 0.0


async def run_once(client: BackendApiClient) -> bool:
    """대기열에서 하나를 처리한다. 처리했으면 True, 비어 있으면 False."""
    task = await client.claim_task()
    if task is None:
        return False

    workflow = WORKFLOWS.get(task.kind)
    if workflow is None:
        # 집어놓고 방치하면 그 작업은 RUNNING에 남고 직원도 묶인다. 마감까지 책임진다.
        logger.error("알 수 없는 작업 종류: %s (task=%s)", task.kind, task.id)
        async with attach_to_task(client, task.id) as context:
            await context.log_error(f"실행할 수 없는 작업 종류입니다: {task.kind}")
            raise UnknownWorkflow(task.kind)

    await _execute(client, task, workflow)
    return True


async def _execute(client: BackendApiClient, task: ClaimedTask, workflow) -> None:
    """워크플로우 실패가 루프를 멈추지 않는다.

    하네스가 이미 FAILED로 마감하고 예외를 다시 던지므로, 여기서는 로그만 남기고
    다음 작업으로 넘어간다. 한 건의 실패로 에이전트가 죽으면 그 뒤 모든 지시가
    대기열에 쌓인 채 아무도 처리하지 않는다.
    """
    logger.info("작업 시작: kind=%s task=%s title=%s", task.kind, task.id, task.title)
    try:
        async with attach_to_task(client, task.id) as context:
            summary = await workflow(client, context, task.employee_id, task.title)
            context.set_summary(summary)
    except Exception:
        logger.exception("작업 실패: task=%s", task.id)
        return
    logger.info("작업 완주: task=%s", task.id)


class UnknownWorkflow(Exception):
    """레지스트리에 없는 kind. 하네스가 FAILED로 마감하도록 예외로 올린다."""


async def run_forever() -> None:
    settings = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        # asyncio는 SIGTERM 핸들러를 기본으로 설치하지 않는다. 없으면 컨테이너 종료
        # 신호에 프로세스가 즉시 죽고 진행 중 작업이 항상 잘린다(Phase 9와 같은 이유).
        loop.add_signal_handler(signal_number, stop.set)

    async with BackendApiClient(
        base_url=settings.backend_base_url,
        worker_api_key=settings.worker_api_key,
        max_attempts=settings.max_attempts,
    ) as client:
        logger.info("에이전트 대기 시작: %s", settings.backend_base_url)
        while not stop.is_set():
            try:
                worked = await run_once(client)
            except Exception:
                # 백엔드 재시작 등으로 claim 자체가 실패할 수 있다. 루프는 살아남는다.
                logger.exception("대기열 확인 실패")
                worked = False
            delay = _BUSY_POLL_SECONDS if worked else _IDLE_POLL_SECONDS
            if delay > 0:
                # stop 이벤트를 함께 기다린다. sleep만 하면 종료 신호를 받고도
                # 최대 한 주기만큼 늦게 반응한다.
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
    logger.info("에이전트 종료")


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
