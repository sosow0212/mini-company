"""로컬 LLM(Ollama) 어댑터와 자동 카탈로그 등록.

원격 프로바이더와 다른 점만 검증한다: 키가 아니라 스위치로 활성화되는가,
카탈로그·단가가 자동으로 들어오는가, 직접 정의한 값을 덮지 않는가.
"""

from decimal import Decimal

import httpx
import pytest

from src.config import Settings
from src.llm.exceptions import LlmCallFailed
from src.llm.gateway import LOCAL_PROFILE_NAME, build_gateway
from src.llm.pricing import ModelPrice
from src.llm.profiles import LlmProfile
from src.llm.providers.base import Message
from src.llm.providers.ollama import OllamaProvider

_MODEL = "anpigon/eeve-korean-10.8b:latest"
_PROFILE = LlmProfile(LOCAL_PROFILE_NAME, "ollama", _MODEL, 0.3, 2_000)
_MESSAGES = [Message(role="user", content="한 문장으로 소개해줘")]


def _provider(handler, *, enabled: bool = True) -> OllamaProvider:
    return OllamaProvider(
        enabled=enabled,
        base_url="http://localhost:11434/v1",
        timeout_seconds=5.0,
        transport=httpx.MockTransport(handler),
    )


def _ok_body() -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "저는 AI입니다"}}],
        "usage": {"prompt_tokens": 54, "completion_tokens": 72},
    }


# ─── 어댑터 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reads_token_usage_from_openai_compatible_response() -> None:
    provider = _provider(lambda request: httpx.Response(200, json=_ok_body()))

    result = await provider.complete(_PROFILE, _MESSAGES)

    assert result.content == "저는 AI입니다"
    assert result.usage.input_tokens == 54
    assert result.usage.output_tokens == 72


@pytest.mark.asyncio
async def test_sends_no_authorization_header() -> None:
    """로컬 서버에는 키가 없다. 빈 Bearer를 보내면 프록시가 401로 되돌릴 수 있다."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json=_ok_body())

    await _provider(handler).complete(_PROFILE, _MESSAGES)

    assert "authorization" not in seen


@pytest.mark.asyncio
async def test_missing_usage_fails_instead_of_reporting_zero_tokens() -> None:
    """토큰 수를 0으로 넘기면 비용이 0이 되고 원장에서 LLM 비용이 사라진다."""
    body = _ok_body()
    del body["usage"]
    provider = _provider(lambda request: httpx.Response(200, json=body))

    with pytest.raises(LlmCallFailed):
        await provider.complete(_PROFILE, _MESSAGES)


@pytest.mark.asyncio
async def test_connection_failure_points_at_the_local_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(LlmCallFailed, match="ollama serve"):
        await _provider(handler).complete(_PROFILE, _MESSAGES)


@pytest.mark.asyncio
async def test_surfaces_model_not_pulled_message() -> None:
    provider = _provider(
        lambda request: httpx.Response(404, json={"error": {"message": 'model "x" not found'}})
    )

    with pytest.raises(LlmCallFailed, match="not found"):
        await provider.complete(_PROFILE, _MESSAGES)


def test_switch_not_key_decides_configuration() -> None:
    handler = lambda request: httpx.Response(200, json=_ok_body())  # noqa: E731

    assert _provider(handler, enabled=True).is_configured() is True
    assert _provider(handler, enabled=False).is_configured() is False


# ─── 카탈로그 자동 등록 ─────────────────────────────────────


def test_disabled_ollama_leaves_no_local_profile() -> None:
    gateway = build_gateway(Settings(_env_file=None, ollama_enabled=False))  # type: ignore[call-arg]

    assert LOCAL_PROFILE_NAME not in gateway.profiles


def test_enabling_ollama_registers_profile_and_zero_price() -> None:
    gateway = build_gateway(
        Settings(_env_file=None, ollama_enabled=True, ollama_model=_MODEL)  # type: ignore[call-arg]
    )

    profile = gateway.profiles[LOCAL_PROFILE_NAME]
    assert profile.provider == "ollama"
    assert profile.model == _MODEL
    # 단가가 카탈로그에 없으면 부팅 검증이 프로파일을 거부한다 — 함께 등록되어야 한다.
    assert gateway.pricing[_MODEL] == ModelPrice(Decimal("0"), Decimal("0"))


def test_explicit_definitions_win_over_autoregistration() -> None:
    """자동 등록은 기본값 제공이다. 직접 적은 값을 덮으면 설정이 무시되는 셈이 된다."""
    gateway = build_gateway(
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            ollama_enabled=True,
            ollama_model=_MODEL,
            llm_profiles_json=(
                '{"local": {"provider": "ollama", "model": "' + _MODEL + '",'
                ' "temperature": 0.9, "maxTokens": 128}}'
            ),
            llm_pricing_json='{"' + _MODEL + '": {"in": 1.5, "out": 2.5}}',
        )
    )

    assert gateway.profiles[LOCAL_PROFILE_NAME].temperature == 0.9
    assert gateway.pricing[_MODEL].input_usd_per_million == Decimal("1.5")
