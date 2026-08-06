"""Ollama 어댑터. 로컬에서 도는 모델을 같은 게이트웨이 뒤에 세운다.

Ollama는 `/v1/chat/completions`로 OpenAI 호환 스키마를 제공하고 `usage`도 채워준다.
그래서 원격 프로바이더와 같은 규칙(§8.5 비용 기록)을 그대로 적용할 수 있다 —
토큰 수를 세지 못하면 비용을 0으로 적게 되고, 그건 원장에서 LLM 비용이 사라지는 길이다.

**API 키가 없다.** 그래서 `is_configured()`가 보는 것은 키가 아니라 "쓰겠다고 켰는가"다.
서버가 실제로 떠 있는지는 확인하지 않는다 — 부팅을 로컬 프로세스 상태에 묶으면 Ollama를
껐다는 이유로 백엔드가 뜨지 않는다. 서버가 없으면 호출 시점에 `LlmCallFailed`가 난다.
"""

import logging

import httpx

from src.llm.exceptions import LlmCallFailed
from src.llm.pricing import TokenUsage
from src.llm.profiles import LlmProfile
from src.llm.providers.base import LlmResult, Message

logger = logging.getLogger(__name__)


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        enabled: bool,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._enabled = enabled
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def is_configured(self) -> bool:
        return self._enabled

    async def complete(self, profile: LlmProfile, messages: list[Message]) -> LlmResult:
        payload = {
            "model": profile.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": profile.temperature,
            "max_tokens": profile.max_tokens,
        }
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            try:
                response = await client.post("/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                # 로컬이라 연결 실패가 흔하다(서버 미기동, 모델 미설치). 원인을 좁혀준다.
                raise LlmCallFailed(
                    f"ollama 연결 실패: {type(exc).__name__} — "
                    f"`ollama serve`가 떠 있고 모델이 받아져 있는지 확인한다"
                ) from exc

        if response.status_code != httpx.codes.OK:
            raise LlmCallFailed(
                f"ollama가 {response.status_code}를 반환했습니다: {_error(response)}"
            )
        return _parse_result(response)


def _error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "unknown"
    if not isinstance(body, dict):
        return "unknown"
    error = body.get("error")
    if isinstance(error, dict):
        # 모델을 안 받아둔 경우가 가장 흔하다. 그 메시지는 그대로 보여주는 편이 낫다.
        return str(error.get("message") or error.get("type") or "unknown")
    return str(error or "unknown")


def _parse_result(response: httpx.Response) -> LlmResult:
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        usage = body["usage"]
        return LlmResult(
            content=content,
            usage=TokenUsage(
                input_tokens=int(usage["prompt_tokens"]),
                output_tokens=int(usage["completion_tokens"]),
            ),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmCallFailed(f"ollama 응답을 해석할 수 없습니다: {type(exc).__name__}") from exc
