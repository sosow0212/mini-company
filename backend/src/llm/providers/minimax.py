"""MiniMax 어댑터. 기본 프로바이더.

MiniMax는 OpenAI 호환 Chat Completions 스키마를 제공한다. openai SDK 대신 httpx를
쓰는 이유: httpx는 이미 의존성에 있고, 재시도·폴백은 service가 프로파일 규칙으로
직접 다루므로 SDK의 같은 기능과 겹친다.

국제용 호스트는 api.minimax.io이고 중국 본토 호스트는 별도다. 키 발급처와 호스트가
어긋나면 인증이 실패하므로 base_url을 설정값으로 둔다.
"""

import logging

import httpx
from pydantic import SecretStr

from src.llm.exceptions import LlmCallFailed
from src.llm.pricing import TokenUsage
from src.llm.profiles import LlmProfile
from src.llm.providers.base import LlmResult, Message

logger = logging.getLogger(__name__)


class MiniMaxProvider:
    name = "minimax"

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
            headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
        ) as client:
            try:
                response = await client.post("/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                # 예외 본문에 요청을 붙이지 않는다(키 노출).
                raise LlmCallFailed(f"minimax 연결 실패: {type(exc).__name__}") from exc

        if response.status_code != httpx.codes.OK:
            raise LlmCallFailed(
                f"minimax가 {response.status_code}를 반환했습니다: {_error_code(response)}"
            )
        return _parse_result(response)


def _error_code(response: httpx.Response) -> str:
    """에러 본문을 그대로 남기지 않고 코드만 추출한다."""
    try:
        body = response.json()
    except ValueError:
        return "unknown"
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("code") or error.get("type") or "unknown")
    base = body.get("base_resp") if isinstance(body, dict) else None
    if isinstance(base, dict):
        return str(base.get("status_code", "unknown"))
    return "unknown"


def _parse_result(response: httpx.Response) -> LlmResult:
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        return LlmResult(
            content=content,
            # 사용량이 없으면 0으로 넘기지 않고 실패시킨다 — 0은 비용 0으로 이어지고
            # 그건 원장에서 LLM 비용이 누락되는 경로가 된다.
            usage=TokenUsage(
                input_tokens=int(usage["prompt_tokens"]),
                output_tokens=int(usage["completion_tokens"]),
            ),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LlmCallFailed(f"minimax 응답을 해석할 수 없습니다: {type(exc).__name__}") from exc
