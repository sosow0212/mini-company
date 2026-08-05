"""적재·검색 비즈니스 로직.

흐름(§11.1):
  1. 포맷에 맞는 파서로 텍스트 + 메타 추출
  2. content_hash로 중복 판정 → 이미 있으면 **skip**(재적재하지 않음)
  3. Mongo에 SourceDocument 저장
  4. 청킹 → 배치 임베딩 → doc_id 기준 delete→insert (멱등)
  5. indexed_at·chunk_count 갱신

해시를 **파싱된 텍스트**로 계산하는 이유: 같은 기사를 HTML로 한 번, PDF로 한 번 받으면
바이트는 다르지만 내용은 같다. 표현이 아니라 내용으로 중복을 판정해야 한다.
"""

import hashlib
import logging
from datetime import UTC, datetime

from beanie import PydanticObjectId

from src.knowledge.chunking import split_into_chunks
from src.knowledge.constants import ContentType, SourceType
from src.knowledge.domain import Chunk, DocumentMetadata, SearchHit, SourceDocument
from src.knowledge.embeddings.base import EmbeddingProvider
from src.knowledge.exceptions import DocumentNotFound, EmptyDocument
from src.knowledge.parsing.base import RawPayload
from src.knowledge.parsing.registry import resolve_parser
from src.knowledge.repository import DocumentRepositoryProtocol
from src.knowledge.schemas import (
    DocumentResponse,
    IngestResult,
    SearchResponse,
    SearchResultItem,
)
from src.knowledge.settings import KnowledgeSettings
from src.knowledge.vector_store import VectorStoreProtocol

logger = logging.getLogger(__name__)

_UNTITLED = "제목 없음"
_TITLE_MAX = 200


class KnowledgeService:
    """비즈니스 로직. Beanie·pymilvus 호출이 이 파일에 등장하면 레이어가 무너진다."""

    def __init__(
        self,
        repository: DocumentRepositoryProtocol,
        vector_store: VectorStoreProtocol,
        embeddings: EmbeddingProvider,
        settings: KnowledgeSettings,
    ) -> None:
        self._repository = repository
        self._vectors = vector_store
        self._embeddings = embeddings
        self._settings = settings

    # ─── 적재 (워커 전용) ──────────────────────────────────────

    async def ingest(
        self,
        *,
        source_type: SourceType,
        content_type: ContentType,
        collected_by: PydanticObjectId,
        text: str | None = None,
        data: bytes | None = None,
        source_url: str | None = None,
        title_hint: str | None = None,
        task_id: PydanticObjectId | None = None,
        metadata_hints: dict[str, str] | None = None,
    ) -> IngestResult:
        parser = resolve_parser(self._settings.parsers, content_type)
        parsed = parser.parse(
            RawPayload(
                content_type=content_type,
                text=text,
                data=data,
                hints=dict(metadata_hints or {}),
            )
        )
        if parsed.text.strip() == "":
            raise EmptyDocument

        content_hash = _hash_text(parsed.text)
        existing = await self._repository.find_by_content_hash(content_hash)
        if existing is not None:
            # 중복은 오류가 아니다. 워커가 같은 피드를 다시 긁는 것은 정상 동작이다.
            logger.info("중복 문서 건너뜀: hash=%s doc=%s", content_hash[:12], existing.id)
            return IngestResult(
                document=DocumentResponse.from_domain(existing), skipped_duplicate=True
            )

        metadata = _merge_metadata(parsed.metadata, metadata_hints or {})
        saved = await self._repository.save(
            SourceDocument(
                title=_resolve_title(title_hint, metadata),
                source_url=source_url,
                source_type=source_type,
                content_type=content_type,
                raw_text=parsed.text,
                metadata=metadata,
                collected_by=collected_by,
                task_id=task_id,
                collected_at=datetime.now(UTC),
                content_hash=content_hash,
            )
        )
        indexed = await self._index(saved)
        return IngestResult(document=DocumentResponse.from_domain(indexed), skipped_duplicate=False)

    async def reindex(self, doc_id: PydanticObjectId) -> DocumentResponse:
        """문서 하나를 다시 인덱싱한다. 청킹 파라미터나 임베딩 모델을 바꿨을 때 쓴다."""
        document = await self._repository.get(doc_id)
        if document is None:
            raise DocumentNotFound
        return DocumentResponse.from_domain(await self._index(document))

    # ─── 검색 (공개 조회 / 챗봇) ───────────────────────────────

    async def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        source_type: SourceType | None = None,
    ) -> SearchResponse:
        """점수 임계값 미달은 결과에서 제외한다 — 환각 방지의 1차 방어선(§11.2)."""
        hits = await self.search_hits(query, top_k=top_k, source_type=source_type)
        titles = await self._titles_of(hits)
        return SearchResponse(
            query=query,
            items=[
                SearchResultItem(
                    doc_id=hit.doc_id,
                    chunk_index=hit.chunk_index,
                    text=hit.text,
                    score=f"{hit.score:.4f}",
                    title=titles.get(hit.doc_id, _UNTITLED),
                )
                for hit in hits
            ],
        )

    async def search_hits(
        self,
        query: str,
        *,
        top_k: int | None = None,
        source_type: SourceType | None = None,
    ) -> list[SearchHit]:
        """chat service가 쓰는 원시 검색. DTO 조립 없이 도메인 값을 넘긴다."""
        if query.strip() == "":
            return []
        vectors = await self._embeddings.embed([query])
        if vectors == []:
            return []
        hits = await self._vectors.search(
            vectors[0],
            top_k=top_k or self._settings.top_k,
            source_type=source_type,
        )
        return [hit for hit in hits if hit.score >= self._settings.score_threshold]

    async def titles_by_doc_id(self, doc_ids: list[str]) -> dict[str, str]:
        """인용 표시용. chat service가 출처 제목을 채울 때 쓴다."""
        return await self._titles_of(
            [SearchHit(doc_id=item, chunk_index=0, text="", score=0.0) for item in doc_ids]
        )

    async def list_recent(self, limit: int) -> list[DocumentResponse]:
        documents = await self._repository.list_recent(limit=limit)
        return [DocumentResponse.from_domain(document) for document in documents]

    async def get_document(self, doc_id: PydanticObjectId) -> DocumentResponse:
        document = await self._repository.get(doc_id)
        if document is None:
            raise DocumentNotFound
        return DocumentResponse.from_domain(document)

    # ─── 내부 ──────────────────────────────────────────────────

    async def _index(self, document: SourceDocument) -> SourceDocument:
        if document.id is None:
            raise DocumentNotFound

        doc_id = str(document.id)
        texts = split_into_chunks(
            document.raw_text,
            target_tokens=self._settings.chunk_target_tokens,
            overlap_tokens=self._settings.chunk_overlap_tokens,
        )
        chunks = [
            Chunk(doc_id=doc_id, chunk_index=index, text=text) for index, text in enumerate(texts)
        ]
        vectors = await self._embeddings.embed([chunk.text for chunk in chunks])
        await self._vectors.replace_document(
            doc_id,
            chunks,
            vectors,
            source_type=document.source_type,
            content_type=document.content_type,
        )
        return await self._repository.save(
            document.model_copy(
                update={"chunk_count": len(chunks), "indexed_at": datetime.now(UTC)}
            )
        )

    async def _titles_of(self, hits: list[SearchHit]) -> dict[str, str]:
        object_ids = [PydanticObjectId(doc_id) for doc_id in {hit.doc_id for hit in hits} if doc_id]
        documents = await self._repository.get_many(object_ids)
        return {str(document.id): document.title for document in documents}


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _merge_metadata(parsed: DocumentMetadata, hints: dict[str, str]) -> DocumentMetadata:
    """파서 추출값이 base, 워커 hints가 위에 덮는다.

    명시적으로 준 값이 이기게 하는 이유: 워커는 수집 맥락을 안다(RSS 항목의 발행일 등).
    파서는 문서 안에 적힌 것만 볼 수 있고, 그게 비어 있거나 틀린 경우가 흔하다.
    """
    if hints == {}:
        return parsed

    from src.knowledge.parsing.base import normalize_metadata_key, parse_datetime, split_keywords

    normalized = {normalize_metadata_key(key): value for key, value in hints.items()}
    absorbed = {"title", "author", "description", "published_at", "language", "keywords"}
    return DocumentMetadata(
        title=normalized.get("title") or parsed.title,
        author=normalized.get("author") or parsed.author,
        description=normalized.get("description") or parsed.description,
        published_at=parse_datetime(normalized.get("published_at")) or parsed.published_at,
        language=normalized.get("language") or parsed.language,
        keywords=split_keywords(normalized.get("keywords")) or parsed.keywords,
        extra={
            **parsed.extra,
            **{key: value for key, value in normalized.items() if key not in absorbed},
        },
    )


def _resolve_title(hint: str | None, metadata: DocumentMetadata) -> str:
    """제목은 화면 목록의 기본 식별자다. 비어 있으면 안 되므로 마지막에 기본값을 준다."""
    for candidate in (hint, metadata.title):
        if candidate is not None and candidate.strip() != "":
            return candidate.strip()[:_TITLE_MAX]
    return _UNTITLED
