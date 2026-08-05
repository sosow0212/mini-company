from datetime import datetime

from pydantic import Field

from src.chat.domain import Citation, Conversation, Message, MessageRole
from src.schemas import ApiModel


class StartConversationRequest(ApiModel):
    title: str | None = Field(default=None, max_length=60)


class AskRequest(ApiModel):
    content: str = Field(min_length=1, max_length=2_000)


class CitationResponse(ApiModel):
    index: int
    doc_id: str
    chunk_index: int
    title: str
    excerpt: str
    score: str

    @classmethod
    def from_domain(cls, citation: Citation) -> "CitationResponse":
        return cls(
            index=citation.index,
            doc_id=citation.doc_id,
            chunk_index=citation.chunk_index,
            title=citation.title,
            excerpt=citation.excerpt,
            score=citation.score,
        )


class MessageResponse(ApiModel):
    role: MessageRole
    content: str
    created_at: datetime
    citations: list[CitationResponse]
    # False면 근거를 찾지 못해 답변을 거절한 경우다. 화면이 다르게 표시할 수 있다.
    grounded: bool

    @classmethod
    def from_domain(cls, message: Message) -> "MessageResponse":
        return cls(
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            citations=[CitationResponse.from_domain(item) for item in message.citations],
            grounded=message.grounded,
        )


class ConversationResponse(ApiModel):
    id: str
    title: str
    created_at: datetime
    messages: list[MessageResponse]

    @classmethod
    def from_domain(cls, conversation: Conversation) -> "ConversationResponse":
        if conversation.id is None:
            raise ValueError("저장되지 않은 대화는 응답으로 내릴 수 없다")
        return cls(
            id=str(conversation.id),
            title=conversation.title,
            created_at=conversation.created_at,
            messages=[MessageResponse.from_domain(item) for item in conversation.messages],
        )


class AnswerResponse(ApiModel):
    """답변 1건.

    `citations`를 필수 배열로 둔다 — 프론트가 출처 없는 문장을 즉시 발견할 수 있다(§11.2).
    근거를 찾지 못한 경우는 `grounded=false`이고 citations가 비어 있다.
    """

    conversation_id: str
    message: MessageResponse

    @classmethod
    def of(cls, message: Message, *, conversation_id: str) -> "AnswerResponse":
        return cls(conversation_id=conversation_id, message=MessageResponse.from_domain(message))
