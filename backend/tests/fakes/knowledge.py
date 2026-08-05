"""knowledge 경계 대체물.

임베딩은 fake를 만들지 않고 **실제 HashingEmbeddingProvider**를 작은 차원으로 쓴다.
결정론적이고 네트워크가 없어서 경계를 대체할 이유가 없다 — classist 원칙대로 실제 객체다.
대체하는 것은 Mongo(repository)와 Milvus(vector store)뿐이다.
"""

import math

from beanie import PydanticObjectId

from src.knowledge.constants import ContentType, SourceType
from src.knowledge.domain import Chunk, SearchHit, SourceDocument


class InMemoryDocumentRepository:
    def __init__(self, documents: list[SourceDocument] | None = None) -> None:
        self._by_id: dict[PydanticObjectId, SourceDocument] = {}
        for document in documents or []:
            self._by_id[_require_id(document)] = document

    async def get(self, doc_id: PydanticObjectId) -> SourceDocument | None:
        return self._by_id.get(doc_id)

    async def find_by_content_hash(self, content_hash: str) -> SourceDocument | None:
        return next(
            (item for item in self._by_id.values() if item.content_hash == content_hash), None
        )

    async def save(self, document: SourceDocument) -> SourceDocument:
        stored = (
            document
            if document.id is not None
            else document.model_copy(update={"id": PydanticObjectId()})
        )
        self._by_id[_require_id(stored)] = stored
        return stored

    async def list_recent(self, *, limit: int) -> list[SourceDocument]:
        ordered = sorted(self._by_id.values(), key=lambda item: item.collected_at, reverse=True)
        return ordered[:limit]

    async def get_many(self, doc_ids: list[PydanticObjectId]) -> list[SourceDocument]:
        return [self._by_id[key] for key in doc_ids if key in self._by_id]

    @property
    def count(self) -> int:
        return len(self._by_id)


class InMemoryVectorStore:
    """doc_id → (청크, 벡터). 코사인 유사도로 검색을 흉내낸다.

    Milvus 구현과 같은 계약 스위트를 돌려서 동작이 갈라지지 않게 한다
    (tests/integration/test_knowledge_vector_store.py).
    """

    def __init__(self) -> None:
        self._rows: dict[str, list[tuple[Chunk, list[float], SourceType, ContentType]]] = {}
        self.ready_dimension: int | None = None

    async def ensure_ready(self, dimension: int) -> None:
        self.ready_dimension = dimension

    async def replace_document(
        self,
        doc_id: str,
        chunks: list[Chunk],
        vectors: list[list[float]],
        *,
        source_type: SourceType,
        content_type: ContentType,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("청크 수와 벡터 수가 다르다")
        # delete → insert. 옛 청크가 남으면 재적재 때 중복이 검색에 잡힌다.
        await self.delete_document(doc_id)
        if chunks == []:
            return
        self._rows[doc_id] = [
            (chunk, vector, source_type, content_type)
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]

    async def delete_document(self, doc_id: str) -> None:
        self._rows.pop(doc_id, None)

    async def search(
        self,
        vector: list[float],
        *,
        top_k: int,
        source_type: SourceType | None = None,
    ) -> list[SearchHit]:
        scored: list[SearchHit] = []
        for rows in self._rows.values():
            for chunk, stored, row_source, _ in rows:
                if source_type is not None and row_source is not source_type:
                    continue
                scored.append(
                    SearchHit(
                        doc_id=chunk.doc_id,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        score=_cosine(vector, stored),
                    )
                )
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:top_k]

    def chunk_count(self, doc_id: str) -> int:
        return len(self._rows.get(doc_id, []))

    @property
    def total_chunks(self) -> int:
        return sum(len(rows) for rows in self._rows.values())


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("차원이 다른 벡터를 비교할 수 없다")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return 0.0 if norm == 0.0 else dot / norm


def _require_id(document: SourceDocument) -> PydanticObjectId:
    if document.id is None:
        raise ValueError("저장된 문서에는 id가 있어야 한다")
    return document.id
