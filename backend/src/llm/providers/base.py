"""프로바이더 경계.

새 프로바이더를 추가할 때는 이 Protocol만 구현하고 registry에 등록한다.
도메인 service를 수정할 일이 없어야 한다.
"""

from dataclasses import dataclass
from typing import Protocol

from src.llm.pricing import TokenUsage
from src.llm.profiles import LlmProfile


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class LlmResult:
    content: str
    usage: TokenUsage


class LlmProvider(Protocol):
    name: str

    def is_configured(self) -> bool:
        """키가 설정되어 있는가. 부팅 검증이 이 값을 본다."""
        ...

    async def complete(self, profile: LlmProfile, messages: list[Message]) -> LlmResult:
        """실패 시 LlmCallFailed를 던진다.

        구현체는 예외 메시지에 요청 헤더·본문 전체를 넣지 않는다 — 키가 로그로 샌다.
        상태코드와 프로바이더 에러코드만 남긴다.
        """
        ...
