"""연결 재시도.

**연결 실패만 재시도한다.** 5xx나 읽기 타임아웃은 재시도하지 않는다 — 서버가 요청을
이미 받아 상태를 바꿨을 수 있고, 그때 재시도는 중복을 만든다:

  - `POST /tasks` 재시도 → 작업이 두 개 생기고 직원 상태가 갈라진다
  - `POST /llm/completions` 재시도 → **비용이 두 번** 든다

`ConnectError`/`ConnectTimeout`은 요청이 서버에 도달하지 못했음이 확실하므로 안전하다.
그래서 재시도를 "안전한 경우"로 좁히고, 나머지는 호출자가 판단하게 예외를 그대로 올린다.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

# 도달 실패가 확실한 예외만. httpx.ConnectTimeout은 ConnectError의 하위가 아니라
# TimeoutException 계열이므로 따로 적는다.
_RETRIABLE = (httpx.ConnectError, httpx.ConnectTimeout)

_BASE_DELAY_SECONDS = 0.5
_MAX_DELAY_SECONDS = 8.0


def backoff_delay(attempt: int) -> float:
    """지수 백오프. 지터는 넣지 않는다 — 워커는 소수라 몰림이 문제되지 않고,
    재현 가능한 지연이 디버깅에 유리하다.
    """
    return min(_BASE_DELAY_SECONDS * 2**attempt, _MAX_DELAY_SECONDS)


async def with_connection_retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int,
    label: str,
) -> T:
    """연결 실패 시 재시도한다. 마지막 시도까지 실패하면 예외를 올린다."""
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await operation()
        except _RETRIABLE as exc:
            last_error = exc
            if attempt + 1 >= max_attempts:
                break
            delay = backoff_delay(attempt)
            logger.warning(
                "백엔드 연결 실패 — 재시도한다",
                extra={
                    "label": label,
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "delay_seconds": delay,
                    "error": type(exc).__name__,
                },
            )
            await asyncio.sleep(delay)

    assert last_error is not None  # 루프는 성공 반환 또는 예외 저장으로만 끝난다
    raise last_error
