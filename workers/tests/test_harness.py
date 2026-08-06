"""하네스 테스트.

경계(HTTP)만 MockTransport로 대체하고 클라이언트는 실제 구현을 쓴다.
검증은 "백엔드에 어떤 요청이 어떤 순서로 나갔는가" — 관찰 가능한 결과로 한다.
"""

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from src.runtime.client import BackendApiClient
from src.runtime.harness import run_task

RecordedCall = tuple[str, str, dict | None, str | None]


def _make_client(handler: Callable[[httpx.Request], httpx.Response]) -> BackendApiClient:
    return BackendApiClient(
        base_url="http://test",
        worker_api_key=SecretStr("test-key"),
        transport=httpx.MockTransport(handler),
    )


def _recording_backend(calls: list[RecordedCall]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append(
            (
                request.method,
                request.url.path,
                body,
                request.headers.get("X-Worker-Key"),
            )
        )
        if request.method == "POST" and request.url.path == "/internal/v1/tasks":
            return httpx.Response(201, json={"id": "task-1"})
        if request.method == "POST" and request.url.path.endswith("/activities"):
            return httpx.Response(201, json={"id": "activity-1"})
        if request.method == "PATCH" and request.url.path == "/internal/v1/tasks/task-1":
            return httpx.Response(200, json={"id": "task-1"})
        return httpx.Response(404, json={"code": "not_found", "message": "없음"})

    return handler


async def test_run_task_records_start_activity_and_success_finish_in_order() -> None:
    calls: list[RecordedCall] = []

    async with _make_client(_recording_backend(calls)) as client:
        async with run_task(client, employee_id="emp-1", kind="collect_market_data") as task:
            await task.log_info("수집을 시작한다")
            task.set_summary("더미 수집 작업 완료")

    assert [(method, path) for method, path, *_ in calls] == [
        ("POST", "/internal/v1/tasks"),
        ("POST", "/internal/v1/tasks/task-1/activities"),
        ("PATCH", "/internal/v1/tasks/task-1"),
    ]
    assert calls[0][2] == {"employeeId": "emp-1", "kind": "collect_market_data", "title": None}
    assert calls[1][2] == {"level": "INFO", "message": "수집을 시작한다"}
    assert calls[2][2] == {"status": "SUCCEEDED", "summary": "더미 수집 작업 완료", "error": None}


async def test_run_task_sends_worker_key_on_every_request() -> None:
    calls: list[RecordedCall] = []

    async with _make_client(_recording_backend(calls)) as client:
        async with run_task(client, employee_id="emp-1", kind="collect_market_data"):
            pass

    assert calls, "최소 시작/마감 요청이 나가야 한다"
    assert all(worker_key == "test-key" for *_, worker_key in calls)


async def test_run_task_finishes_failed_and_reraises_when_body_raises() -> None:
    calls: list[RecordedCall] = []

    with pytest.raises(RuntimeError, match="외부 소스 다운"):
        async with _make_client(_recording_backend(calls)) as client:
            async with run_task(client, employee_id="emp-1", kind="collect_market_data"):
                raise RuntimeError("외부 소스 다운")

    finish = calls[-1]
    assert finish[0] == "PATCH"
    assert finish[2]["status"] == "FAILED"
    assert "외부 소스 다운" in finish[2]["error"]


@pytest.mark.parametrize(
    "raised",
    [asyncio.CancelledError, KeyboardInterrupt],
    ids=["cancelled", "keyboard_interrupt"],
)
async def test_run_task_finishes_failed_when_body_is_interrupted(
    raised: type[BaseException],
) -> None:
    """CancelledError/KeyboardInterrupt는 BaseException이다.

    Exception만 잡으면 SIGTERM·Ctrl+C에서 마감이 유실되고, 작업은 RUNNING·직원은
    WORKING에 남아 그 직원이 다음 작업을 시작할 수 없게 된다(EmployeeBusy).
    """
    calls: list[RecordedCall] = []

    with pytest.raises(raised):
        async with _make_client(_recording_backend(calls)) as client:
            async with run_task(client, employee_id="emp-1", kind="collect_market_data"):
                raise raised

    finish = calls[-1]
    assert finish[0] == "PATCH", "중단되어도 마감 요청은 나가야 한다"
    assert finish[2]["status"] == "FAILED"
    assert raised.__name__ in finish[2]["error"]


async def test_run_task_finishes_failed_when_task_is_really_cancelled() -> None:
    """직접 raise가 아니라 실제 task.cancel()로 취소되는 경로."""
    calls: list[RecordedCall] = []

    async def body() -> None:
        async with _make_client(_recording_backend(calls)) as client:
            async with run_task(client, employee_id="emp-1", kind="collect_market_data"):
                await asyncio.sleep(10)

    task = asyncio.create_task(body())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    finish = calls[-1]
    assert finish[0] == "PATCH"
    assert finish[2]["status"] == "FAILED"


async def test_run_task_does_not_swallow_finish_failure() -> None:
    """마감 요청이 실패해도 본문의 성공/실패 결과가 유지되어야 한다."""

    def failing_finish(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/internal/v1/tasks":
            return httpx.Response(201, json={"id": "task-1"})
        return httpx.Response(500, json={"code": "internal_error", "message": "다운"})

    async with _make_client(failing_finish) as client:
        # 마감(500)이 실패해도 예외 없이 빠져나와야 한다
        async with run_task(client, employee_id="emp-1", kind="collect_market_data"):
            pass


async def test_find_employee_id_returns_matching_id_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "emp-1", "name": "수집가 노아"},
                {"id": "emp-2", "name": "분석가 리아"},
            ],
        )

    async with _make_client(handler) as client:
        assert await client.find_employee_id("분석가 리아") == "emp-2"
        assert await client.find_employee_id("없는 이름") is None
