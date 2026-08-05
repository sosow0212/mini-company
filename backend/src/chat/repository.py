from typing import Protocol

from beanie import PydanticObjectId

from src.chat.domain import Citation, Conversation, Message
from src.chat.models import CitationEmbedded, ConversationDocument, MessageEmbedded


class ConversationRepositoryProtocol(Protocol):
    """service가 의존하는 경계. "없으면 예외"를 판단하지 않고 None을 반환한다."""

    async def get(self, conversation_id: PydanticObjectId) -> Conversation | None: ...

    async def save(self, conversation: Conversation) -> Conversation: ...

    async def list_recent(self, *, limit: int) -> list[Conversation]: ...


class ConversationRepository:
    """Beanie 쿼리는 이 파일에만 등장한다."""

    async def get(self, conversation_id: PydanticObjectId) -> Conversation | None:
        document = await ConversationDocument.get(conversation_id)
        return _to_domain(document) if document is not None else None

    async def save(self, conversation: Conversation) -> Conversation:
        return _to_domain(await _to_document(conversation).save())

    async def list_recent(self, *, limit: int) -> list[Conversation]:
        documents = await ConversationDocument.find().sort("-created_at").limit(limit).to_list()
        return [_to_domain(document) for document in documents]


def _to_domain(document: ConversationDocument) -> Conversation:
    return Conversation(
        id=document.id,
        title=document.title,
        created_at=document.created_at,
        messages=tuple(
            Message(
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                citations=tuple(
                    Citation(
                        index=citation.index,
                        doc_id=citation.doc_id,
                        chunk_index=citation.chunk_index,
                        title=citation.title,
                        excerpt=citation.excerpt,
                        score=citation.score,
                    )
                    for citation in message.citations
                ),
                grounded=message.grounded,
            )
            for message in document.messages
        ),
    )


def _to_document(conversation: Conversation) -> ConversationDocument:
    return ConversationDocument(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        messages=[
            MessageEmbedded(
                role=message.role,
                content=message.content,
                created_at=message.created_at,
                citations=[
                    CitationEmbedded(
                        index=citation.index,
                        doc_id=citation.doc_id,
                        chunk_index=citation.chunk_index,
                        title=citation.title,
                        excerpt=citation.excerpt,
                        score=citation.score,
                    )
                    for citation in message.citations
                ],
                grounded=message.grounded,
            )
            for message in conversation.messages
        ],
    )
