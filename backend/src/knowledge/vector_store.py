"""Milvus 어댑터 — 벡터 쪽 repository.

ADR-005: **Milvus를 진실의 원천으로 삼지 않는다.** 검색에 필요한 최소 필드만 넣는다.
원문·메타·직원 정보는 Mongo에 있고, 그래서 컬렉션을 지우고 다시 만들어도 데이터가
사라지지 않는다(재인덱싱만 하면 된다).

재적재는 **doc_id 기준 delete → insert**로 멱등하게 만든다. upsert가 아니라 delete인
이유: 문서가 수정되면 청크 수가 줄어들 수 있고, 그때 남은 옛 청크가 검색에 계속 잡힌다.
"""

import logging
from typing import Protocol

from pymilvus import AsyncMilvusClient, DataType
from pymilvus.exceptions import MilvusException

from src.knowledge.constants import ContentType, SourceType
from src.knowledge.domain import Chunk, SearchHit
from src.knowledge.exceptions import VectorStoreFailed

logger = logging.getLogger(__name__)

_DOC_ID_MAX = 24
_TEXT_MAX = 4_000
_ENUM_MAX = 16
_INDEX_PARAMS = {"M": 16, "efConstruction": 200}
_SEARCH_PARAMS = {"ef": 64}


class VectorStoreProtocol(Protocol):
    async def ensure_ready(self, dimension: int) -> None: ...

    async def replace_document(
        self,
        doc_id: str,
        chunks: list[Chunk],
        vectors: list[list[float]],
        *,
        source_type: SourceType,
        content_type: ContentType,
    ) -> None: ...

    async def delete_document(self, doc_id: str) -> None: ...

    async def search(
        self,
        vector: list[float],
        *,
        top_k: int,
        source_type: SourceType | None = None,
    ) -> list[SearchHit]: ...


class MilvusVectorStore:
    """pymilvus 호출은 이 파일에만 등장한다."""

    def __init__(self, client: AsyncMilvusClient, collection: str) -> None:
        self._client = client
        self._collection = collection

    async def ensure_ready(self, dimension: int) -> None:
        """컬렉션이 없으면 만들고, 있으면 차원이 설정과 같은지 확인한다.

        차원 검증을 부팅 시점에 하는 이유(§15-1): 불일치 상태로 돌면 예외 없이
        검색 품질만 조용히 망가진다.
        """
        try:
            if not await self._client.has_collection(self._collection):
                await self._create_collection(dimension)
            else:
                await self._verify_dimension(dimension)
            await self._client.load_collection(self._collection)
        except MilvusException as exc:
            raise VectorStoreFailed(f"Milvus 준비 실패: {exc}") from exc

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
            raise VectorStoreFailed("청크 수와 벡터 수가 다르다")

        # 먼저 지운다. insert 후 지우면 중간에 실패했을 때 중복이 남는다.
        await self.delete_document(doc_id)
        if chunks == []:
            return

        rows = [
            {
                "doc_id": doc_id,
                "chunk_index": chunk.chunk_index,
                # Milvus VARCHAR는 길이 제한이 있다. 초과분은 잘라 넣되 원문은 Mongo에 온전하다.
                "text": chunk.text[:_TEXT_MAX],
                "source_type": source_type.value,
                "content_type": content_type.value,
                "embedding": vector,
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        try:
            await self._client.insert(collection_name=self._collection, data=rows)
        except MilvusException as exc:
            raise VectorStoreFailed(f"청크 삽입 실패: {exc}") from exc

    async def delete_document(self, doc_id: str) -> None:
        try:
            await self._client.delete(
                collection_name=self._collection,
                filter=f'doc_id == "{_escape(doc_id)}"',
            )
        except MilvusException as exc:
            raise VectorStoreFailed(f"청크 삭제 실패: {exc}") from exc

    async def search(
        self,
        vector: list[float],
        *,
        top_k: int,
        source_type: SourceType | None = None,
    ) -> list[SearchHit]:
        try:
            results = await self._client.search(
                collection_name=self._collection,
                data=[vector],
                limit=top_k,
                filter=f'source_type == "{source_type.value}"' if source_type else "",
                output_fields=["doc_id", "chunk_index", "text"],
                search_params={"metric_type": "COSINE", "params": _SEARCH_PARAMS},
            )
        except MilvusException as exc:
            raise VectorStoreFailed(f"검색 실패: {exc}") from exc

        first = results[0] if results else []
        return [_to_hit(item) for item in first]

    async def _create_collection(self, dimension: int) -> None:
        schema = self._client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("pk", DataType.INT64, is_primary=True)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=_DOC_ID_MAX)
        schema.add_field("chunk_index", DataType.INT64)
        schema.add_field("text", DataType.VARCHAR, max_length=_TEXT_MAX)
        schema.add_field("source_type", DataType.VARCHAR, max_length=_ENUM_MAX)
        # content_type도 넣는다. 필드 추가는 컬렉션 재생성을 요구하므로 나중보다 지금이 싸다.
        schema.add_field("content_type", DataType.VARCHAR, max_length=_ENUM_MAX)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="HNSW",
            metric_type="COSINE",
            params=_INDEX_PARAMS,
        )
        # doc_id로 delete/filter를 하므로 스칼라 인덱스가 있으면 재적재가 빨라진다.
        index_params.add_index(field_name="doc_id", index_type="INVERTED")

        await self._client.create_collection(
            collection_name=self._collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info("Milvus 컬렉션 생성: %s (dim=%d)", self._collection, dimension)

    async def _verify_dimension(self, dimension: int) -> None:
        described = await self._client.describe_collection(self._collection)
        fields = described.get("fields", [])
        actual = next(
            (
                field.get("params", {}).get("dim")
                for field in fields
                if field.get("name") == "embedding"
            ),
            None,
        )
        if actual is None:
            raise VectorStoreFailed(f"컬렉션 {self._collection}에 embedding 필드가 없다")
        if int(actual) != dimension:
            raise VectorStoreFailed(
                f"임베딩 차원이 어긋난다: 컬렉션 {actual}, 설정 {dimension}. "
                "EMBEDDING_DIM을 되돌리거나 컬렉션을 지우고 재인덱싱해야 한다."
            )


def _to_hit(item: object) -> SearchHit:
    """pymilvus의 결과 항목은 dict 유사 객체다. 형태 변화에 대비해 방어적으로 읽는다."""
    if not isinstance(item, dict):
        raise VectorStoreFailed("검색 결과 형식을 해석할 수 없다")
    entity = item.get("entity", item)
    if not isinstance(entity, dict):
        raise VectorStoreFailed("검색 결과 entity를 해석할 수 없다")
    return SearchHit(
        doc_id=str(entity.get("doc_id", "")),
        chunk_index=int(entity.get("chunk_index", 0)),
        text=str(entity.get("text", "")),
        # COSINE에서 distance는 유사도(1에 가까울수록 유사)로 돌아온다.
        score=float(item.get("distance", item.get("score", 0.0))),
    )


def _escape(value: str) -> str:
    """filter 표현식에 넣기 전에 따옴표를 막는다. doc_id는 ObjectId 문자열이라
    정상 경로에서는 걸릴 일이 없지만, 표현식 조립에 문자열을 끼우는 건 그 자체로 위험하다.
    """
    return value.replace("\\", "").replace('"', "")
