from typing import Annotated

from fastapi import Depends, Request

from src.knowledge.repository import DocumentRepository, DocumentRepositoryProtocol
from src.knowledge.service import KnowledgeService
from src.knowledge.settings import KnowledgeRuntime


def get_knowledge_runtime(request: Request) -> KnowledgeRuntime:
    """부팅 시 조립한 불변 런타임(파서·임베딩·벡터스토어)을 꺼낸다."""
    return request.app.state.knowledge


def get_document_repository() -> DocumentRepositoryProtocol:
    return DocumentRepository()


def get_knowledge_service(
    runtime: Annotated[KnowledgeRuntime, Depends(get_knowledge_runtime)],
    repository: Annotated[DocumentRepositoryProtocol, Depends(get_document_repository)],
) -> KnowledgeService:
    return KnowledgeService(repository, runtime.vector_store, runtime.embeddings, runtime.settings)


KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]
