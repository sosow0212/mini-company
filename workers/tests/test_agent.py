"""에이전트 루프 — 사람이 시킨 일을 집어 실행한다.

경계(HTTP)만 MockTransport로 대체한다. 검증은 "백엔드에 어떤 요청이 나갔는가"로 한다 —
클레임 후 시작 요청을 또 보내지는 않는지, 실패해도 마감이 나가는지가 핵심이다.
"""

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from src.agent import run_once
from src.runtime.client import BackendApiClient

RecordedCall = tuple[str, str, dict | None]


def _make_client(handler: Callable[[httpx.Request], httpx.Response]) -> BackendApiClient:
    return BackendApiClient(
        base_url="http://test",
        worker_api_key=SecretStr("test-key"),
        transport=httpx.MockTransport(handler),
    )


def _backend(calls: list[RecordedCall], *, claimed: dict | None, hits: list | None = None):
    """claimed가 None이면 대기열이 비었다는 뜻(204)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))

        if request.url.path == "/internal/v1/tasks/claim":
            if claimed is None:
                return httpx.Response(204)
            return httpx.Response(200, json=claimed)
        if request.url.path.endswith("/activities"):
            return httpx.Response(201, json={"id": "activity-1"})
        if request.url.path == "/api/v1/knowledge/search":
            return httpx.Response(200, json={"items": hits or []})
        if request.method == "PATCH":
            return httpx.Response(200, json={"id": "task-1"})
        if request.url.path == "/internal/v1/knowledge/documents":
            return httpx.Response(
                201,
                json={
                    "document": {"id": "doc-1", "title": "문서", "chunkCount": 1},
                    "skippedDuplicate": False,
                },
            )
        return httpx.Response(404, json={"code": "not_found", "message": "없음"})

    return handler


def _task(kind: str = "analyze_knowledge", title: str | None = "반도체") -> dict:
    return {"id": "task-1", "employeeId": "emp-1", "kind": kind, "title": title}


async def test_empty_queue_is_not_an_error() -> None:
    """대부분의 순간에 대기열은 비어 있다. 이걸 오류로 다루면 로그가 뒤덮인다."""
    calls: list[RecordedCall] = []

    async with _make_client(_backend(calls, claimed=None)) as client:
        assert await run_once(client) is False

    assert [path for _, path, _ in calls] == ["/internal/v1/tasks/claim"]


async def test_claimed_task_is_not_started_again() -> None:
    """클레임 시점에 이미 RUNNING이다. start_task를 또 부르면 작업이 둘이 되고
    직원은 EmployeeBusy로 막힌다."""
    calls: list[RecordedCall] = []

    async with _make_client(_backend(calls, claimed=_task())) as client:
        assert await run_once(client) is True

    assert ("POST", "/internal/v1/tasks", None) not in calls
    assert [path for _, path, _ in calls].count("/internal/v1/tasks") == 0


async def test_finished_task_is_marked_succeeded() -> None:
    calls: list[RecordedCall] = []

    async with _make_client(_backend(calls, claimed=_task())) as client:
        await run_once(client)

    finish = next(body for method, path, body in calls if method == "PATCH")
    assert finish is not None and finish["status"] == "SUCCEEDED"


async def test_workflow_without_evidence_reports_instead_of_failing() -> None:
    """근거가 없는 것은 실패가 아니라 결론이다. 그대로 보고한다."""
    calls: list[RecordedCall] = []

    async with _make_client(_backend(calls, claimed=_task(), hits=[])) as client:
        await run_once(client)

    finish = next(body for method, path, body in calls if method == "PATCH")
    assert finish["status"] == "SUCCEEDED"
    assert "자료" in finish["summary"]


async def test_unknown_kind_is_closed_as_failed_not_left_running() -> None:
    """집어놓고 방치하면 그 작업은 RUNNING에 남고 직원도 계속 묶인다."""
    calls: list[RecordedCall] = []

    async with _make_client(_backend(calls, claimed=_task(kind="없는_종류"))) as client:
        with pytest.raises(Exception):  # noqa: B017 — UnknownWorkflow를 하네스가 다시 던진다
            await run_once(client)

    finish = next(body for method, path, body in calls if method == "PATCH")
    assert finish["status"] == "FAILED"


async def test_title_becomes_the_search_query() -> None:
    """제목은 장식이 아니다. 분석·보고서 워크플로우가 검색어로 쓴다."""
    calls: list[RecordedCall] = []
    handler = _backend(calls, claimed=_task(title="메모리 반도체"), hits=[])

    async with _make_client(handler) as client:
        await run_once(client)

    # 검색 요청은 GET이라 본문이 없다. 활동 로그에 질의가 남는 것으로 확인한다.
    messages = [body["message"] for method, path, body in calls if path.endswith("/activities")]
    assert any("메모리 반도체" in message for message in messages)


async def test_missing_llm_config_is_reported_in_plain_words() -> None:
    """503을 그대로 흘리면 화면에 URL과 상태코드만 뜬다. 원인과 해결책을 남긴다."""
    calls: list[RecordedCall] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.url.path == "/internal/v1/tasks/claim":
            return httpx.Response(200, json=_task())
        if request.url.path.endswith("/activities"):
            return httpx.Response(201, json={"id": "activity-1"})
        if request.url.path == "/api/v1/knowledge/search":
            hit = {"docId": "d", "text": "본문", "score": 0.9}
            return httpx.Response(200, json={"items": [hit]})
        if request.url.path == "/internal/v1/llm/completions":
            return httpx.Response(503, json={"code": "provider_unavailable", "message": "없음"})
        return httpx.Response(200, json={"id": "task-1"})

    async with _make_client(handler) as client:
        await run_once(client)

    finish = next(body for method, path, body in calls if method == "PATCH")
    assert finish["status"] == "FAILED"
    assert "OLLAMA_ENABLED" in finish["error"]
