"""도메인 모델. 지속성 기술을 모른다."""

from datetime import datetime
from enum import StrEnum

from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Citation(BaseModel):
    """답변이 근거로 쓴 청크 1건.

    **서버가 검색 결과로 채운다.** LLM 출력에서 `[1]`을 파싱해 만들지 않는다 — 그러면
    모델이 표기를 빼먹는 순간 출처 없는 답변이 통과한다.
    """

    model_config = ConfigDict(frozen=True)

    index: int
    doc_id: str
    chunk_index: int
    title: str
    excerpt: str
    score: str


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str
    created_at: datetime
    citations: tuple[Citation, ...] = ()
    # 근거를 찾지 못해 답변을 거절한 경우. 화면이 이 플래그로 다르게 표시할 수 있다.
    grounded: bool = True


class Conversation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: PydanticObjectId | None = None
    title: str
    created_at: datetime
    messages: tuple[Message, ...] = ()
