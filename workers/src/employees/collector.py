"""더미 수집 직원.

Phase 2의 완료 조건은 "더미 워커가 작업 1건 완주"다. 실제 데이터 소스(RSS/API)
수집은 Phase 7에서 구현한다. 지금의 목적은 워커 ↔ 백엔드 계약(작업 시작 →
활동 기록 → 완료)이 끝까지 동작하는지 확인하는 것이라, 고정된 활동 로그를
남기고 성공 종료한다.

실행: cd workers && .venv/bin/python -m src.employees.collector
"""

import asyncio
import logging

from src.runtime.client import BackendApiClient
from src.runtime.config import get_settings
from src.runtime.harness import run_task

logger = logging.getLogger(__name__)

_TASK_KIND = "collect_market_data"


async def run() -> int:
    settings = get_settings()
    async with BackendApiClient(
        base_url=settings.backend_base_url, worker_api_key=settings.worker_api_key
    ) as client:
        employee_id = await client.find_employee_id(settings.employee_name)
        if employee_id is None:
            logger.error(
                "직원을 찾을 수 없다: %s (make seed가 먼저 필요하다)", settings.employee_name
            )
            return 1
        async with run_task(client, employee_id=employee_id, kind=_TASK_KIND) as task:
            await task.log_info("수집 준비 완료")
            await asyncio.sleep(0.3)
            await task.log_info("외부 소스 접속 확인 (더미)")
            await asyncio.sleep(0.3)
            await task.log_info("수집 완료 — 문서 적재는 Phase 7에서 연결")
            task.set_summary("더미 수집 작업 완료")
    logger.info("작업 완주: %s (%s)", settings.employee_name, _TASK_KIND)
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
