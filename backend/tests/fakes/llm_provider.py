"""LLM 프로바이더 경계 대체물. mock이 아니라 동작하는 구현체다.

LLM은 §13이 지정한 경계 중 하나다. 응답 텍스트를 스냅샷하지 않고, 어떤 프로파일로
호출되었는지·비용이 어떻게 기록되었는지 같은 구조적 성질만 검증한다.
"""

from src.llm.exceptions import LlmCallFailed
from src.llm.pricing import TokenUsage
from src.llm.profiles import LlmProfile
from src.llm.providers.base import LlmResult, Message


class FakeLlmProvider:
    def __init__(
        self,
        name: str = "fake",
        *,
        content: str = "생성된 문장",
        input_tokens: int = 1_000,
        output_tokens: int = 500,
        configured: bool = True,
        fail_models: set[str] | None = None,
    ) -> None:
        self.name = name
        self._content = content
        self._usage = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
        self._configured = configured
        # 특정 모델만 실패시켜 폴백 경로를 만든다.
        self._fail_models = fail_models or set()
        self.calls: list[LlmProfile] = []
        # 프로파일과 따로 둔다. `calls`는 이미 여러 테스트가 프로파일 목록으로 읽고 있다.
        self.received_messages: list[list[Message]] = []

    def is_configured(self) -> bool:
        return self._configured

    async def complete(self, profile: LlmProfile, messages: list[Message]) -> LlmResult:
        self.calls.append(profile)
        self.received_messages.append(list(messages))
        if profile.model in self._fail_models:
            raise LlmCallFailed(f"{profile.model} 호출 실패(의도된 실패)")
        return LlmResult(content=self._content, usage=self._usage)

    @property
    def called_models(self) -> list[str]:
        return [profile.model for profile in self.calls]

    @property
    def called_profiles(self) -> list[str]:
        return [profile.name for profile in self.calls]
