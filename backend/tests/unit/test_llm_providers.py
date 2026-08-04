"""프로바이더 어댑터. 경계(HTTP)만 MockTransport로 대체한다.

응답 텍스트를 스냅샷하지 않고 구조적 성질을 검증한다: 사용량을 제대로 읽는가,
사용량이 없을 때 0으로 넘기지 않는가, 에러에 키가 섞이지 않는가.
"""

import httpx
import pytest
from pydantic import SecretStr

from src.llm.exceptions import LlmCallFailed
from src.llm.profiles import LlmProfile
from src.llm.providers.anthropic import AnthropicProvider
from src.llm.providers.base import Message
from src.llm.providers.minimax import MiniMaxProvider

_SECRET = "sk-super-secret-value"
_PROFILE = LlmProfile("writer", "minimax", "MiniMax-M3", 0.8, 4_000)
_MESSAGES = [Message(role="system", content="너는 작가다"), Message(role="user", content="써줘")]


def _minimax(handler) -> MiniMaxProvider:
    return MiniMaxProvider(
        api_key=SecretStr(_SECRET),
        base_url="https://api.example.test/v1",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )


def _anthropic(handler) -> AnthropicProvider:
    return AnthropicProvider(
        api_key=SecretStr(_SECRET),
        base_url="https://api.example.test/v1",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )


def _minimax_ok(extra: dict | None = None):
    def handler(_request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [{"message": {"content": "생성된 문장"}}],
            "usage": {"prompt_tokens": 1_820, "completion_tokens": 640},
        }
        body.update(extra or {})
        return httpx.Response(200, json=body)

    return handler


# ─── MiniMax ───────────────────────────────────────────────────


async def test_minimax_is_not_configured_when_key_is_blank() -> None:
    provider = MiniMaxProvider(
        api_key=SecretStr(""), base_url="https://x.test", timeout_seconds=1.0
    )

    assert provider.is_configured() is False


async def test_minimax_reads_content_and_usage() -> None:
    result = await _minimax(_minimax_ok()).complete(_PROFILE, _MESSAGES)

    assert result.content == "생성된 문장"
    assert result.usage.input_tokens == 1_820
    assert result.usage.output_tokens == 640


async def test_minimax_sends_model_and_parameters_from_the_profile() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return _minimax_ok()(request)

    await _minimax(handler).complete(_PROFILE, _MESSAGES)

    assert captured["model"] == "MiniMax-M3"
    assert captured["temperature"] == 0.8
    assert captured["max_tokens"] == 4_000
    assert [m["role"] for m in captured["messages"]] == ["system", "user"]


async def test_minimax_sends_bearer_token() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return _minimax_ok()(request)

    await _minimax(handler).complete(_PROFILE, _MESSAGES)

    assert captured["auth"] == f"Bearer {_SECRET}"


async def test_minimax_ignores_cost_reported_in_the_response() -> None:
    """프로바이더가 비용을 담아 보내도 어댑터가 파싱하지 않는다.

    LlmResult에 비용 필드가 아예 없어서, 외부 값이 원장에 들어갈 경로가 구조적으로
    존재하지 않는다(§13 마지막 테스트의 뿌리).
    """
    result = await _minimax(_minimax_ok({"cost": 999_999, "cost_krw": "999999"})).complete(
        _PROFILE, _MESSAGES
    )

    assert not hasattr(result, "cost")
    assert not hasattr(result, "cost_krw")
    assert result.usage.input_tokens == 1_820


async def test_minimax_raises_when_usage_is_missing() -> None:
    """사용량이 없으면 비용이 0이 되고, 그건 원장에서 LLM 비용이 사라지는 경로다."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    with pytest.raises(LlmCallFailed):
        await _minimax(handler).complete(_PROFILE, _MESSAGES)


async def test_minimax_raises_when_status_is_not_ok() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": "rate_limit"}})

    with pytest.raises(LlmCallFailed, match="429"):
        await _minimax(handler).complete(_PROFILE, _MESSAGES)


async def test_minimax_error_does_not_leak_the_api_key(caplog) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # 프로바이더가 요청을 그대로 에코해도 키가 예외 메시지로 새면 안 된다.
        return httpx.Response(401, json={"error": {"code": "invalid_key", "sent": _SECRET}})

    with pytest.raises(LlmCallFailed) as raised:
        await _minimax(handler).complete(_PROFILE, _MESSAGES)

    assert _SECRET not in str(raised.value)
    assert _SECRET not in caplog.text
    assert "invalid_key" in str(raised.value)


async def test_minimax_raises_when_connection_fails() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(LlmCallFailed, match="연결 실패"):
        await _minimax(handler).complete(_PROFILE, _MESSAGES)


# ─── Anthropic ─────────────────────────────────────────────────


async def test_anthropic_moves_system_out_of_the_messages_array() -> None:
    """Messages API는 system을 최상위 필드로 받는다. 어댑터가 그 차이를 흡수한다."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "응답"}],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        )

    result = await _anthropic(handler).complete(_PROFILE, _MESSAGES)

    assert captured["system"] == "너는 작가다"
    assert [m["role"] for m in captured["messages"]] == ["user"]
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 20


async def test_anthropic_sends_api_key_header_not_bearer() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["x_api_key"] = request.headers.get("x-api-key")
        captured["version"] = request.headers.get("anthropic-version")
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "응답"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    await _anthropic(handler).complete(_PROFILE, _MESSAGES)

    assert captured["x_api_key"] == _SECRET
    assert captured["version"]


async def test_anthropic_concatenates_text_blocks_and_skips_others() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "앞"},
                    {"type": "thinking", "thinking": "무시됨"},
                    {"type": "text", "text": "뒤"},
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    result = await _anthropic(handler).complete(_PROFILE, _MESSAGES)

    assert result.content == "앞뒤"
