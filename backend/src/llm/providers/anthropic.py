"""Anthropic 어댑터.

Messages API는 OpenAI 호환 스키마와 다르다(system이 별도 필드, usage 키 이름이 다름).
어댑터가 그 차이를 흡수하므로 service는 프로바이더를 구분하지 않는다.
"""

import logging

import httpx
from pydantic import SecretStr

from src.llm.exceptions import LlmCallFailed
from src.llm.pricing import TokenUsage
from src.llm.profiles import LlmProfile
from src.llm.providers.base import LlmResult, Message

logger = logging.getLogger(__name__)

_API_VERSION = "2023-06-01"
_SYSTEM_ROLE = "system"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def is_configured(self) -> bool:
        return bool(self._api_key.get_secret_value())

    async def complete(self, profile: LlmProfile, messages: list[Message]) -> LlmResult:
        # Anthropic은 system을 messages 배열이 아니라 최상위 필드로 받는다.
        system = "\n".join(m.content for m in messages if m.role == _SYSTEM_ROLE)
        payload: dict[str, object] = {
            "model": profile.model,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages if m.role != _SYSTEM_ROLE
            ],
            "temperature": profile.temperature,
            "max_tokens": profile.max_tokens,
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
            headers={
                "x-api-key": self._api_key.get_secret_value(),
                "anthropic-version": _API_VERSION,
            },
        ) as client:
            try:
                response = await client.post("/messages", json=payload)
            except httpx.HTTPError as exc:
                raise LlmCallFailed(f"anthropic 연결 실패: {type(exc).__name__}") from exc

        if response.status_code != httpx.codes.OK:
            raise LlmCallFailed(
                f"anthropic이 {response.status_code}를 반환했습니다: {_error_type(response)}"
            )
        return _parse_result(response)


def _error_type(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "unknown"
    error = body.get("error") if isinstance(body, dict) else None
    return str(error.get("type", "unknown")) if isinstance(error, dict) else "unknown"


def _parse_result(response: httpx.Response) -> LlmResult:
    try:
        body = response.json()
        content = "".join(block["text"] for block in body["content"] if block.get("type") == "text")
        usage = body["usage"]
        return LlmResult(
            content=content,
            usage=TokenUsage(
                input_tokens=int(usage["input_tokens"]),
                output_tokens=int(usage["output_tokens"]),
            ),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmCallFailed(f"anthropic 응답을 해석할 수 없습니다: {type(exc).__name__}") from exc
