"""knowledge 런타임 묶음. 부팅 시 한 번 조립해 app.state에 둔다.

담기는 값은 전부 불변이고 설정에서 재구성 가능하므로 ADR-008에 걸리지 않는다
(LLM 게이트웨이와 같은 패턴).
"""

import logging
from dataclasses import dataclass

from pymilvus import AsyncMilvusClient

from src.config import Settings
from src.knowledge.chunking.base import ChunkingOptions, ChunkingStrategy
from src.knowledge.chunking.registry import build_chunker_registry, missing_default_strategies
from src.knowledge.constants import ContentType
from src.knowledge.embeddings.base import EmbeddingProvider
from src.knowledge.embeddings.hashing import HashingEmbeddingProvider
from src.knowledge.embeddings.openai_provider import OpenAiEmbeddingProvider
from src.knowledge.parsing.base import DocumentParser
from src.knowledge.parsing.registry import build_parser_registry, missing_parsers
from src.knowledge.vector_store import MilvusVectorStore, VectorStoreProtocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeSettings:
    parsers: dict[ContentType, DocumentParser]
    chunkers: dict[str, ChunkingStrategy]
    top_k: int
    score_threshold: float
    chunk_target_tokens: int
    chunk_overlap_tokens: int
    # 설정으로 포맷별 기본값을 덮는다. None이면 registry의 포맷 기본값을 쓴다.
    chunking_strategy: str | None = None

    def chunking_options(self) -> ChunkingOptions:
        return ChunkingOptions.from_tokens(
            target_tokens=self.chunk_target_tokens,
            overlap_tokens=self.chunk_overlap_tokens,
        )


@dataclass(frozen=True)
class KnowledgeRuntime:
    settings: KnowledgeSettings
    embeddings: EmbeddingProvider
    vector_store: VectorStoreProtocol
    client: AsyncMilvusClient


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "hashing":
        logger.warning(
            "EMBEDDING_PROVIDER=hashing — 의미를 모르는 개발용 임베딩이다. "
            "검색 품질이 무의미하므로 프로덕션에서는 openai를 쓴다."
        )
        return HashingEmbeddingProvider(dimension=settings.embedding_dim)

    provider = OpenAiEmbeddingProvider(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.embedding_model,
        dimension=settings.embedding_dim,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    if not provider.is_configured():
        # 로컬에서 키 없이 앱이 떠야 한다(LLM 게이트웨이와 같은 원칙). 적재 시점에 실패한다.
        logger.warning(
            "OPENAI_API_KEY가 없다 — 문서 적재·검색이 실패한다. "
            "키 없이 파이프라인을 돌려보려면 EMBEDDING_PROVIDER=hashing을 쓴다."
        )
    return provider


def build_knowledge_runtime(settings: Settings) -> KnowledgeRuntime:
    parsers = build_parser_registry()
    missing = missing_parsers(parsers)
    if missing:
        # enum에 포맷을 추가했는데 파서 등록을 잊은 상태. 런타임 첫 적재에서 발견되면 늦다.
        raise RuntimeError(f"파서가 등록되지 않은 ContentType: {missing}")

    chunkers = build_chunker_registry()
    chunking_problems = missing_default_strategies(chunkers)
    if chunking_problems:
        raise RuntimeError(f"청킹 전략 설정이 올바르지 않다: {chunking_problems}")
    if settings.chunking_strategy is not None and settings.chunking_strategy not in chunkers:
        raise RuntimeError(
            f"CHUNKING_STRATEGY='{settings.chunking_strategy}'가 등록되지 않았다. "
            f"사용 가능: {sorted(chunkers)}"
        )

    client = AsyncMilvusClient(uri=settings.milvus_uri)
    return KnowledgeRuntime(
        settings=KnowledgeSettings(
            parsers=parsers,
            chunkers=chunkers,
            chunking_strategy=settings.chunking_strategy,
            top_k=settings.rag_top_k,
            score_threshold=settings.rag_score_threshold,
            chunk_target_tokens=settings.chunk_target_tokens,
            chunk_overlap_tokens=settings.chunk_overlap_tokens,
        ),
        embeddings=build_embedding_provider(settings),
        vector_store=MilvusVectorStore(client, settings.milvus_collection),
        client=client,
    )
