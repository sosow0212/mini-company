"""지식(SourceDocument) 애그리거트 — 수집한 원문과 그 벡터 인덱스.

소유하는 것은 원문 텍스트, 추출한 메타데이터, 그리고 청크 임베딩이다. 문서를 **누가**
수집했는지는 `employees`가, 그 수집이 **어떤 작업**이었는지는 `tasks`가 갖는다. 여기에는
수치를 두지 않는다 — 문서 건수 같은 지표가 필요해지면 `ledger`에 기록한다(ADR-002).

Mongo와 Milvus에 걸쳐 있지만 **진실의 원천은 Mongo**다(ADR-005). Milvus에는 검색에
필요한 최소 필드만 넣어서, 컬렉션을 지우고 다시 만들어도 재인덱싱으로 복구된다.
"""

from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Query, status

from src.knowledge.constants import SourceType
from src.knowledge.dependencies import KnowledgeServiceDep
from src.knowledge.schemas import (
    DocumentResponse,
    IngestDocumentRequest,
    IngestResult,
    ReindexRequest,
    SearchResponse,
)

public_router = APIRouter(prefix="/knowledge", tags=["knowledge"])
internal_router = APIRouter(prefix="/knowledge", tags=["internal-knowledge"])

_DEFAULT_LIST_LIMIT = 20
_MAX_LIST_LIMIT = 100


@public_router.get("/documents")
async def list_documents(
    service: KnowledgeServiceDep,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIST_LIMIT)] = _DEFAULT_LIST_LIMIT,
) -> list[DocumentResponse]:
    return await service.list_recent(limit)


@public_router.get("/documents/{doc_id}")
async def get_document(doc_id: PydanticObjectId, service: KnowledgeServiceDep) -> DocumentResponse:
    return await service.get_document(doc_id)


@public_router.get("/search")
async def search(
    service: KnowledgeServiceDep,
    q: Annotated[str, Query(min_length=1, max_length=1_000)],
    top_k: Annotated[int | None, Query(ge=1, le=50)] = None,
    source_type: SourceType | None = None,
) -> SearchResponse:
    """점수 임계값 미달은 결과에서 빠진다 — 빈 목록이 "자료에 없음"의 신호다."""
    return await service.search(q, top_k=top_k, source_type=source_type)


@internal_router.post("/documents", status_code=status.HTTP_201_CREATED)
async def ingest_document(
    request: IngestDocumentRequest,
    service: KnowledgeServiceDep,
) -> IngestResult:
    """수집 문서 적재. 청킹·임베딩·업서트를 서버가 한다.

    파싱을 워커가 아니라 여기서 하는 이유(ADR-001): 메타 추출 규칙이 워커마다 갈라지면
    같은 HTML에서 다른 제목이 나온다. 규칙은 한 곳에만 있어야 한다.
    """
    return await service.ingest(
        source_type=request.source_type,
        content_type=request.content_type,
        collected_by=request.collected_by,
        text=request.text,
        data=request.decoded_data(),
        source_url=request.source_url,
        title_hint=request.title,
        task_id=request.task_id,
        metadata_hints=request.metadata,
        chunking_strategy=request.chunking_strategy,
    )


@internal_router.post("/documents/{doc_id}/reindex")
async def reindex_document(
    doc_id: PydanticObjectId,
    request: ReindexRequest,
    service: KnowledgeServiceDep,
) -> DocumentResponse:
    """청킹 파라미터·전략·임베딩 모델을 바꿨을 때 문서 하나를 다시 인덱싱한다."""
    return await service.reindex(doc_id, chunking_strategy=request.chunking_strategy)
