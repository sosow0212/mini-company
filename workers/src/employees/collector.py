"""수집 직원의 **스케줄 실행 진입점**.

작업 본문은 `src/workflows/collect.py`에 있다. 여기서 하는 일은 "누가, 어떤 종류로
스스로 작업을 시작하는가"까지다.

두 경로가 같은 워크플로우 함수를 부른다:
  이 파일        — 스케줄러/CronJob이 시간에 맞춰 실행 (작업을 스스로 만든다)
  src/agent.py  — 사람이 UI에서 지시한 QUEUED 작업을 집어 실행

갈라두면 "UI로 시킨 것과 스케줄로 돈 것의 결과가 다른" 상태가 되고, 그건 재현이 어렵다.

실행: cd workers && .venv/bin/python -m src.employees.collector
"""

import asyncio
import logging

from src.logging_setup import configure_logging
from src.runtime.client import BackendApiClient
from src.runtime.config import get_settings
from src.runtime.harness import run_task
from src.workflows import collect

logger = logging.getLogger(__name__)

_TASK_KIND = "collect_market_data"
_TITLE = "정기 자료 수집"


async def run() -> int:
    settings = get_settings()
    async with BackendApiClient(
        base_url=settings.backend_base_url,
        worker_api_key=settings.worker_api_key,
        max_attempts=settings.max_attempts,
    ) as client:
        employee_id = await client.find_employee_id(settings.employee_name)
        if employee_id is None:
            logger.error(
                "직원을 찾을 수 없다: %s (make seed가 먼저 필요하다)", settings.employee_name
            )
            return 1

        async with run_task(client, employee_id=employee_id, kind=_TASK_KIND, title=_TITLE) as task:
            task.set_summary(await collect.run(client, task, employee_id))

    logger.info("작업 완주: %s", settings.employee_name)
    return 0


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
