"""LLM 프록시 클라이언트. 경계(HTTP)만 MockTransport로 대체한다.

검증 핵심: 워커가 model을 보내지 않는다는 것. 보내면 모델 정책이 워커로 흩어진다.
"""

import json

import httpx
import pytest
from pydantic import SecretStr

from src.runtime.client import BackendApiClient

_MESSAGES = [{"role": "user", "content": "요약해줘"}]


def _client(handler) -> BackendApiClient:
    return BackendApiClient(
        base_url="http://test",
        worker_api_key=SecretStr("test-key"),
        transport=httpx.MockTransport(handler),
    )


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": "수집을 마쳤습니다",
            "profile": "structured",
            "provider": "minimax",
            "model": "MiniMax-M2.7",
            "usage": {"inputTokens": 100, "outputTokens": 50},
            "costKrw": "3.21",
        },
    )


async def test_complete_reads_content_profile_model_and_cost() -> None:
    async with _client(_ok) as client:
        completion = await client.complete(employee_id="emp-1", messages=_MESSAGES)

    assert completion.content == "수집을 마쳤습니다"
    assert completion.profile == "structured"
    assert completion.model == "MiniMax-M2.7"
    # 비용은 문자열로 받고 계산에 쓰지 않는다.
    assert completion.cost_krw == "3.21"


async def test_complete_does_not_send_a_model_field() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _ok(request)

    async with _client(handler) as client:
        await client.complete(employee_id="emp-1", messages=_MESSAGES)

    assert "model" not in captured, "모델 선택 권한은 서버에만 있다(ADR-007)"
    assert captured["employeeId"] == "emp-1"


async def test_complete_omits_task_id_when_not_given() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _ok(request)

    async with _client(handler) as client:
        await client.complete(employee_id="emp-1", messages=_MESSAGES)

    assert "taskId" not in captured


async def test_complete_sends_task_id_when_given() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return _ok(request)

    async with _client(handler) as client:
        await client.complete(employee_id="emp-1", messages=_MESSAGES, task_id="task-1")

    assert captured["taskId"] == "task-1"


async def test_complete_sends_the_worker_key() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["key"] = request.headers.get("X-Worker-Key")
        return _ok(request)

    async with _client(handler) as client:
        await client.complete(employee_id="emp-1", messages=_MESSAGES)

    assert captured["key"] == "test-key"


async def test_complete_raises_on_error_status_so_the_caller_can_decide() -> None:
    """503(키 없음)은 작업 실패가 아니라 '이 환경에선 LLM 불가'다. 판단은 호출자가 한다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"code": "llm_provider_not_configured"})

    async with _client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError) as raised:
            await client.complete(employee_id="emp-1", messages=_MESSAGES)

    assert raised.value.response.status_code == 503
