"""이름 → 프로바이더 인스턴스.

여기 등록된 이름만 프로파일의 `provider`로 쓸 수 있고, 부팅 검증이 그걸 확인한다.
"""

from src.config import Settings
from src.llm.providers.anthropic import AnthropicProvider
from src.llm.providers.base import LlmProvider
from src.llm.providers.minimax import MiniMaxProvider
from src.llm.providers.ollama import OllamaProvider


def build_registry(settings: Settings) -> dict[str, LlmProvider]:
    """프로세스당 한 번 만들고 재사용한다. 키는 여기서만 읽힌다."""
    providers: list[LlmProvider] = [
        MiniMaxProvider(
            api_key=settings.minimax_api_key,
            base_url=settings.minimax_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
        AnthropicProvider(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
        # 로컬 모델은 타임아웃이 다르다 — 공용 값(60초)으로는 긴 답변이 늘 잘린다.
        OllamaProvider(
            enabled=settings.ollama_enabled,
            base_url=settings.ollama_base_url,
            timeout_seconds=settings.ollama_timeout_seconds,
        ),
    ]
    return {provider.name: provider for provider in providers}


def configured_names(registry: dict[str, LlmProvider]) -> set[str]:
    return {name for name, provider in registry.items() if provider.is_configured()}
