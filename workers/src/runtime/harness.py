"""작업 실행 하네스.

워커 구현체는 본연의 로직에만 집중하고, 시작/활동 기록/종료 전이는 이
컨텍스트매니저가 보장한다. 본문이 정상 종료하면 SUCCEEDED, 예외로 빠지면
FAILED로 마감하고 예외는 다시 던진다(호출자가 종료 코드를 결정한다).
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from src.runtime.client import BackendApiClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def run_task(
    client: BackendApiClient, *, employee_id: str, kind: str, title: str | None = None
) -> AsyncIterator["TaskContext"]:
    """워커가 **스스로 시작하는** 작업(스케줄 실행). 작업을 만들고 마감까지 책임진다."""
    task = await client.start_task(employee_id=employee_id, kind=kind, title=title)
    async with _finishing(client, task.id) as context:
        yield context


@asynccontextmanager
async def attach_to_task(client: BackendApiClient, task_id: str) -> AsyncIterator["TaskContext"]:
    """**사람이 지시해 이미 RUNNING인** 작업에 붙는다(클레임한 경우).

    시작을 다시 만들지 않는 이유: 클레임 시점에 백엔드가 이미 RUNNING으로 전이시켰다.
    여기서 start_task를 또 부르면 작업이 두 개가 되고 직원은 EmployeeBusy로 막힌다.
    """
    async with _finishing(client, task_id) as context:
        yield context


@asynccontextmanager
async def _finishing(client: BackendApiClient, task_id: str) -> AsyncIterator["TaskContext"]:
    """본문의 성패를 작업 마감으로 옮긴다. 두 진입점이 이 규칙을 공유한다."""
    context = TaskContext(client, task_id=task_id)
    try:
        yield context
    except BaseException as exc:
        # Exception이 아니라 BaseException을 잡는다. asyncio.CancelledError와
        # KeyboardInterrupt는 BaseException 상속이라, Exception만 잡으면 취소·Ctrl+C에서
        # 마감이 유실되고 작업은 RUNNING·직원은 WORKING에 남는다.
        # 취소 이후에도 이 await는 완료된다(취소는 한 번만 주입된다).
        await _finish_safely(client, task_id, status="FAILED", error=f"{type(exc).__name__}: {exc}")
        raise
    await _finish_safely(client, task_id, status="SUCCEEDED", summary=context.summary)


async def _finish_safely(
    client: BackendApiClient,
    task_id: str,
    *,
    status: str,
    summary: str | None = None,
    error: str | None = None,
) -> None:
    """마감 기록 실패가 본체의 결과(또는 예외)를 덮어쓰면 안 된다.

    마감이 유실되면 작업은 RUNNING에 멈추고 직원은 WORKING으로 남는다.
    관제실에서 멈춘 것으로 '보이는' 상태가 조용한 성공보다 낫다.
    """
    try:
        await client.finish_task(task_id, status=status, summary=summary, error=error)
    except Exception:
        logger.exception("작업 마감 기록 실패: task=%s status=%s", task_id, status)


class TaskContext:
    """작업 본문에 전달되는 손잡이. 활동 기록과 최종 요약만 담당한다."""

    def __init__(self, client: BackendApiClient, *, task_id: str) -> None:
        self._client = client
        self.task_id = task_id
        self.summary: str | None = None

    async def log_info(self, message: str) -> None:
        await self._client.add_activity(self.task_id, level="INFO", message=message)

    async def log_warn(self, message: str) -> None:
        await self._client.add_activity(self.task_id, level="WARN", message=message)

    async def log_error(self, message: str) -> None:
        await self._client.add_activity(self.task_id, level="ERROR", message=message)

    def set_summary(self, summary: str) -> None:
        # 수치를 직접 타이핑하지 않는다. 숫자가 필요하면 {{ledger.*}} 자리표시자(Phase 3).
        self.summary = summary
