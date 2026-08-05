from typing import Protocol

from beanie import PydanticObjectId

from src.knowledge.domain import DocumentMetadata, SourceDocument
from src.knowledge.models import DocumentMetadataEmbedded, SourceDocumentDocument


class DocumentRepositoryProtocol(Protocol):
    """service가 의존하는 경계. "없으면 예외"를 판단하지 않고 None을 반환한다."""

    async def get(self, doc_id: PydanticObjectId) -> SourceDocument | None: ...

    async def find_by_content_hash(self, content_hash: str) -> SourceDocument | None: ...

    async def save(self, document: SourceDocument) -> SourceDocument: ...

    async def list_recent(self, *, limit: int) -> list[SourceDocument]: ...

    async def get_many(self, doc_ids: list[PydanticObjectId]) -> list[SourceDocument]: ...


class DocumentRepository:
    """Beanie 쿼리는 이 파일에만 등장한다."""

    async def get(self, doc_id: PydanticObjectId) -> SourceDocument | None:
        document = await SourceDocumentDocument.get(doc_id)
        return _to_domain(document) if document is not None else None

    async def find_by_content_hash(self, content_hash: str) -> SourceDocument | None:
        document = await SourceDocumentDocument.find_one(
            SourceDocumentDocument.content_hash == content_hash
        )
        return _to_domain(document) if document is not None else None

    async def save(self, document: SourceDocument) -> SourceDocument:
        # id가 없으면 insert, 있으면 replace(재인덱싱 후 chunk_count 갱신).
        return _to_domain(await _to_document(document).save())

    async def list_recent(self, *, limit: int) -> list[SourceDocument]:
        documents = await SourceDocumentDocument.find().sort("-collected_at").limit(limit).to_list()
        return [_to_domain(document) for document in documents]

    async def get_many(self, doc_ids: list[PydanticObjectId]) -> list[SourceDocument]:
        """검색 결과의 인용 정보를 채울 때 쓴다. 청크마다 조회하면 N+1이 된다."""
        if doc_ids == []:
            return []
        documents = await SourceDocumentDocument.find({"_id": {"$in": doc_ids}}).to_list()
        return [_to_domain(document) for document in documents]


def _to_domain(document: SourceDocumentDocument) -> SourceDocument:
    return SourceDocument(
        id=document.id,
        title=document.title,
        source_url=document.source_url,
        source_type=document.source_type,
        content_type=document.content_type,
        raw_text=document.raw_text,
        metadata=DocumentMetadata(
            title=document.metadata.title,
            author=document.metadata.author,
            description=document.metadata.description,
            published_at=document.metadata.published_at,
            language=document.metadata.language,
            keywords=tuple(document.metadata.keywords),
            extra=dict(document.metadata.extra),
        ),
        collected_by=document.collected_by,
        task_id=document.task_id,
        collected_at=document.collected_at,
        content_hash=document.content_hash,
        chunk_count=document.chunk_count,
        indexed_at=document.indexed_at,
    )


def _to_document(document: SourceDocument) -> SourceDocumentDocument:
    return SourceDocumentDocument(
        id=document.id,
        title=document.title,
        source_url=document.source_url,
        source_type=document.source_type,
        content_type=document.content_type,
        raw_text=document.raw_text,
        metadata=DocumentMetadataEmbedded(
            title=document.metadata.title,
            author=document.metadata.author,
            description=document.metadata.description,
            published_at=document.metadata.published_at,
            language=document.metadata.language,
            keywords=list(document.metadata.keywords),
            extra=dict(document.metadata.extra),
        ),
        collected_by=document.collected_by,
        task_id=document.task_id,
        collected_at=document.collected_at,
        content_hash=document.content_hash,
        chunk_count=document.chunk_count,
        indexed_at=document.indexed_at,
    )
