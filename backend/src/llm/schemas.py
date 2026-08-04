from beanie import PydanticObjectId
from pydantic import Field

from src.llm.profiles import LlmProfile
from src.llm.providers.base import LlmResult
from src.schemas import ApiModel

_MAX_MESSAGES = 50
_MAX_CONTENT_LENGTH = 100_000


class MessageRequest(ApiModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=_MAX_CONTENT_LENGTH)


class CompletionRequest(ApiModel):
    """워커가 보내는 요청.

    **`model` 필드가 없는 것이 핵심이다.** 어떤 모델을 쓸지는 요청이 아니라 직원의
    프로파일이 정한다 — 모델 정책이 중앙에서 관리된다(ADR-007 이유 3).
    """

    employee_id: PydanticObjectId
    task_id: PydanticObjectId | None = None
    messages: list[MessageRequest] = Field(min_length=1, max_length=_MAX_MESSAGES)


class UsageResponse(ApiModel):
    input_tokens: int
    output_tokens: int


class CompletionResponse(ApiModel):
    content: str
    profile: str
    provider: str
    model: str
    usage: UsageResponse
    # 서버가 단가표로 계산한 값. 문자열로 내린다(금액은 JS number를 거치지 않는다).
    cost_krw: str

    @classmethod
    def of(
        cls,
        result: LlmResult,
        *,
        profile: LlmProfile,
        cost_krw: str,
    ) -> "CompletionResponse":
        return cls(
            content=result.content,
            profile=profile.name,
            provider=profile.provider,
            model=profile.model,
            usage=UsageResponse(
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
            ),
            cost_krw=cost_krw,
        )
