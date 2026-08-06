"""연결 재시도.

이 모듈의 핵심 판단은 "무엇을 재시도하지 **않는가**"다. 5xx나 읽기 타임아웃을 재시도하면
서버가 이미 처리한 요청이 두 번 실행될 수 있고, 그건 작업 중복과 LLM 비용 이중 청구로
이어진다. 그래서 검증도 그쪽에 무게를 둔다.
"""

import httpx
import pytest
from pydantic import SecretStr

from src.runtime.client import BackendApiClient
from src.runtime.retry import backoff_delay, with_connection_retry


async def test_returns_result_without_retrying_on_success() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    result = await with_connection_retry(operation, max_attempts=3, label="test")

    assert result == "ok"
    assert calls == 1


async def test_retries_connection_error_until_success() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("refused")
        return "ok"

    result = await with_connection_retry(operation, max_attempts=3, label="test")

    assert result == "ok"
    assert calls == 3


async def test_gives_up_after_max_attempts_and_raises_last_error() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused")

    with pytest.raises(httpx.ConnectError):
        await with_connection_retry(operation, max_attempts=3, label="test")

    assert calls == 3


async def test_retries_connect_timeout() -> None:
    """ConnectTimeout은 ConnectError의 하위가 아니라 TimeoutException 계열이다."""
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("timeout")
        return "ok"

    assert await with_connection_retry(operation, max_attempts=2, label="test") == "ok"


async def test_does_not_retry_read_timeout() -> None:
    """서버가 요청을 받아 처리했을 수 있다 — 재시도하면 작업이 두 번 생긴다."""
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(httpx.ReadTimeout):
        await with_connection_retry(operation, max_attempts=3, label="test")

    assert calls == 1


async def test_does_not_retry_arbitrary_exceptions() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        raise ValueError("도메인 오류")

    with pytest.raises(ValueError):
        await with_connection_retry(operation, max_attempts=3, label="test")

    assert calls == 1


def test_backoff_grows_and_is_capped() -> None:
    delays = [backoff_delay(attempt) for attempt in range(8)]

    assert delays == sorted(delays)
    assert max(delays) <= 8.0
    assert delays[0] <= 0.5


# ─── 클라이언트 통합 ──────────────────────────────────────────


async def test_client_retries_connection_failure_on_read() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json=[{"id": "emp-1", "name": "수집가 노아"}])

    client = BackendApiClient(
        base_url="http://test",
        worker_api_key=SecretStr("k"),
        max_attempts=3,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        assert await client.find_employee_id("수집가 노아") == "emp-1"

    assert attempts == 2


async def test_client_does_not_retry_server_error_on_write() -> None:
    """POST 재시도는 작업 중복을 만든다. 5xx는 호출자가 판단하게 올린다."""
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"code": "unavailable"})

    client = BackendApiClient(
        base_url="http://test",
        worker_api_key=SecretStr("k"),
        max_attempts=3,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.start_task(employee_id="emp-1", kind="collect")

    assert attempts == 1
