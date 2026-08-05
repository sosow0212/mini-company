"""적재·검색 service. 경계(Mongo/Milvus)만 대체하고 임베딩은 실제 구현을 쓴다.

블루프린트 §13이 이름으로 지정한 필수 테스트 2개가 여기 있다:
document_is_skipped_when_content_hash_already_exists
reindex_replaces_chunks_without_duplicating_when_document_is_reingested
"""

import pytest
from beanie import PydanticObjectId

from src.knowledge.chunking.registry import build_chunker_registry
from src.knowledge.constants import ContentType, SourceType
from src.knowledge.embeddings.hashing import HashingEmbeddingProvider
from src.knowledge.exceptions import DocumentNotFound, EmptyDocument, UnsupportedContentType
from src.knowledge.parsing.registry import build_parser_registry
from src.knowledge.service import KnowledgeService
from src.knowledge.settings import KnowledgeSettings
from tests.fakes.knowledge import InMemoryDocumentRepository, InMemoryVectorStore

_DIMENSION = 64
_EMPLOYEE = PydanticObjectId()


class Harness:
    def __init__(self, *, threshold: float = 0.0, target_tokens: int = 40) -> None:
        self.repository = InMemoryDocumentRepository()
        self.vectors = InMemoryVectorStore()
        self.service = KnowledgeService(
            self.repository,
            self.vectors,
            HashingEmbeddingProvider(dimension=_DIMENSION),
            KnowledgeSettings(
                parsers=build_parser_registry(),
                chunkers=build_chunker_registry(),
                top_k=5,
                score_threshold=threshold,
                chunk_target_tokens=target_tokens,
                chunk_overlap_tokens=8,
            ),
        )

    async def ingest_text(self, text: str, **overrides):
        payload = {
            "source_type": SourceType.WEB,
            "content_type": ContentType.PLAIN_TEXT,
            "collected_by": _EMPLOYEE,
            "text": text,
        }
        payload.update(overrides)
        return await self.service.ingest(**payload)


# ─── 적재 ──────────────────────────────────────────────────────


async def test_ingest_stores_document_and_indexes_chunks() -> None:
    harness = Harness()

    result = await harness.ingest_text("첫째 문단이다.\n\n둘째 문단이다.")

    assert result.skipped_duplicate is False
    assert result.document.chunk_count >= 1
    assert result.document.indexed_at is not None
    assert harness.vectors.chunk_count(result.document.id) == result.document.chunk_count


async def test_document_is_skipped_when_content_hash_already_exists() -> None:
    """블루프린트 §13 필수 테스트.

    워커가 같은 피드를 다시 긁는 것은 정상 동작이다. 오류가 아니라 skip으로 알린다.
    """
    harness = Harness()
    text = "같은 내용을 두 번 보낸다."

    first = await harness.ingest_text(text)
    second = await harness.ingest_text(text)

    assert first.skipped_duplicate is False
    assert second.skipped_duplicate is True
    assert second.document.id == first.document.id
    assert harness.repository.count == 1
    assert harness.vectors.total_chunks == first.document.chunk_count


async def test_duplicate_is_detected_across_formats_with_same_text() -> None:
    """해시를 파싱된 텍스트로 계산하는 이유 — 같은 기사를 HTML/줄글로 받으면 바이트는
    달라도 내용은 같다. 표현이 아니라 내용으로 판정해야 한다.
    """
    harness = Harness()
    await harness.ingest_text("본문 내용이다.")

    result = await harness.ingest_text(
        "<html><body>본문 내용이다.</body></html>", content_type=ContentType.HTML
    )

    assert result.skipped_duplicate is True
    assert harness.repository.count == 1


async def test_reindex_replaces_chunks_without_duplicating_when_document_is_reingested() -> None:
    """블루프린트 §13 필수 테스트.

    재인덱싱은 doc_id 기준 delete → insert다. upsert면 문서가 짧아졌을 때 남은
    옛 청크가 검색에 계속 잡힌다.
    """
    harness = Harness()
    ingested = await harness.ingest_text("문단 하나.\n\n문단 둘.\n\n문단 셋.")
    before = harness.vectors.chunk_count(ingested.document.id)
    assert before >= 1

    reindexed = await harness.service.reindex(PydanticObjectId(ingested.document.id))

    assert harness.vectors.chunk_count(ingested.document.id) == before
    assert harness.vectors.total_chunks == before
    assert reindexed.chunk_count == before


async def test_reindex_shrinks_chunk_set_when_document_gets_shorter() -> None:
    harness = Harness(target_tokens=20)
    ingested = await harness.ingest_text("\n\n".join(f"문단 {index}." for index in range(8)))
    long_count = harness.vectors.chunk_count(ingested.document.id)

    # 본문을 짧게 교체한 뒤 재인덱싱한다.
    stored = await harness.repository.get(PydanticObjectId(ingested.document.id))
    assert stored is not None
    await harness.repository.save(stored.model_copy(update={"raw_text": "짧아진 본문."}))
    reindexed = await harness.service.reindex(PydanticObjectId(ingested.document.id))

    assert reindexed.chunk_count < long_count
    assert harness.vectors.chunk_count(ingested.document.id) == reindexed.chunk_count


async def test_reindex_raises_when_document_is_unknown() -> None:
    with pytest.raises(DocumentNotFound):
        await Harness().service.reindex(PydanticObjectId())


async def test_ingest_rejects_document_without_extractable_text() -> None:
    """빈 문서를 조용히 적재하면 검색 결과에 빈 청크가 섞인다."""
    with pytest.raises(EmptyDocument):
        await Harness().ingest_text("   \n\n   ")


async def test_ingest_rejects_unknown_content_type() -> None:
    harness = Harness()
    harness.service._settings.parsers.pop(ContentType.HTML)

    with pytest.raises(UnsupportedContentType):
        await harness.ingest_text("<html><body>x</body></html>", content_type=ContentType.HTML)


# ─── 메타데이터 ────────────────────────────────────────────────


async def test_ingest_persists_extracted_metadata() -> None:
    harness = Harness()
    html = (
        '<html lang="ko"><head><meta property="og:title" content="적재된 제목">'
        '<meta name="author" content="박기자">'
        '<meta property="og:site_name" content="테크뉴스"></head>'
        "<body>본문이 충분히 길어야 한다.</body></html>"
    )

    result = await harness.ingest_text(html, content_type=ContentType.HTML)

    metadata = result.document.metadata
    assert metadata.title == "적재된 제목"
    assert metadata.author == "박기자"
    assert metadata.extra["og:site_name"] == "테크뉴스"


async def test_worker_hints_override_parsed_metadata() -> None:
    """워커는 수집 맥락을 안다(RSS 항목의 발행일 등). 명시적으로 준 값이 이긴다."""
    harness = Harness()
    html = (
        '<html><head><meta property="og:title" content="문서 안 제목"></head>'
        "<body>본문.</body></html>"
    )

    result = await harness.ingest_text(
        html,
        content_type=ContentType.HTML,
        metadata_hints={"title": "워커가 아는 제목", "feed": "tech-rss"},
    )

    assert result.document.metadata.title == "워커가 아는 제목"
    # 흡수되지 않은 hint도 남는다.
    assert result.document.metadata.extra["feed"] == "tech-rss"


async def test_title_falls_back_to_metadata_then_placeholder() -> None:
    harness = Harness()

    from_meta = await harness.ingest_text(
        "<html><head><title>메타 제목</title></head><body>본문 하나.</body></html>",
        content_type=ContentType.HTML,
    )
    without_meta = await harness.ingest_text("제목 단서가 없는 본문.")

    assert from_meta.document.title == "메타 제목"
    assert without_meta.document.title == "제목 없음"


async def test_explicit_title_wins_over_metadata() -> None:
    harness = Harness()

    result = await harness.ingest_text(
        "<html><head><title>메타 제목</title></head><body>본문.</body></html>",
        content_type=ContentType.HTML,
        title_hint="워커 지정 제목",
    )

    assert result.document.title == "워커 지정 제목"


# ─── 검색 ──────────────────────────────────────────────────────


async def test_search_finds_ingested_text() -> None:
    harness = Harness()
    await harness.ingest_text("반도체 시장이 회복되고 있다.")

    response = await harness.service.search("반도체 시장")

    assert response.items != []
    assert "반도체" in response.items[0].text


async def test_search_filters_by_source_type() -> None:
    harness = Harness()
    await harness.ingest_text("웹에서 긁은 문서.", source_type=SourceType.WEB)
    await harness.ingest_text("파일로 받은 문서.", source_type=SourceType.FILE)

    only_files = await harness.service.search("문서", source_type=SourceType.FILE)

    assert all("파일" in item.text for item in only_files.items)


async def test_search_drops_hits_below_score_threshold() -> None:
    """임계값 미달 제외가 환각 방지의 1차 방어선이다(§11.2)."""
    harness = Harness(threshold=0.99)
    await harness.ingest_text("전혀 관련 없는 주제의 문서다.")

    response = await harness.service.search("완전히 다른 질문")

    assert response.items == []


async def test_search_returns_score_as_string() -> None:
    """프론트가 임계값 비교 같은 계산을 하지 않게 문자열로 내린다(ADR-006)."""
    harness = Harness()
    await harness.ingest_text("검색될 문서.")

    response = await harness.service.search("검색될 문서")

    assert isinstance(response.items[0].score, str)


async def test_search_attaches_document_title_for_citation() -> None:
    harness = Harness()
    await harness.ingest_text("인용될 본문.", title_hint="인용 대상 문서")

    response = await harness.service.search("인용될 본문")

    assert response.items[0].title == "인용 대상 문서"


async def test_search_returns_empty_for_blank_query() -> None:
    assert (await Harness().service.search("   ")).items == []


async def test_list_recent_returns_documents_newest_first() -> None:
    harness = Harness()
    await harness.ingest_text("먼저 적재.")
    await harness.ingest_text("나중 적재.")

    documents = await harness.service.list_recent(10)

    assert len(documents) == 2
    assert documents[0].collected_at >= documents[1].collected_at


# ─── 청킹 전략 선택 ────────────────────────────────────────────


async def test_html_uses_heading_strategy_by_default() -> None:
    """HTML은 제목 태그가 있으니 절 단위로 잘라야 한 청크가 하나의 주제를 담는다."""
    harness = Harness()
    html = (
        "<html><body><h1>1장</h1><p>개요 본문이다.</p>"
        "<h2>1.1 배경</h2><p>배경 설명이다.</p></body></html>"
    )

    result = await harness.ingest_text(html, content_type=ContentType.HTML)

    assert result.document.chunking_strategy == "heading"
    assert result.document.section_count == 2


async def test_plain_text_uses_paragraph_strategy_by_default() -> None:
    result = await Harness().ingest_text("줄글 본문이다.")

    assert result.document.chunking_strategy == "paragraph"
    assert result.document.section_count == 0


async def test_request_can_override_the_strategy() -> None:
    """표를 덤프한 HTML이라면 heading이 아니라 fixed_size가 맞고, 그건 호출자만 안다."""
    harness = Harness()

    result = await harness.ingest_text(
        "<html><body><h1>제목</h1><p>본문.</p></body></html>",
        content_type=ContentType.HTML,
        chunking_strategy="fixed_size",
    )

    assert result.document.chunking_strategy == "fixed_size"


async def test_unknown_strategy_is_rejected_at_ingest() -> None:
    from src.knowledge.exceptions import UnsupportedChunkingStrategy

    with pytest.raises(UnsupportedChunkingStrategy):
        await Harness().ingest_text("본문.", chunking_strategy="semantic")


async def test_heading_chunks_carry_the_section_path() -> None:
    """조각만 떼어 임베딩하면 절 정보가 사라진다. 경로가 있으면 청크가 문맥을 갖는다."""
    harness = Harness()
    html = (
        "<html><body><h1>1장 개요</h1><p>개요 본문이다.</p>"
        "<h2>1.1 배경</h2><p>배경 설명이다.</p></body></html>"
    )

    ingested = await harness.ingest_text(html, content_type=ContentType.HTML)
    found = await harness.service.search("배경 설명")

    assert ingested.document.chunk_count >= 2
    assert any("1장 개요 > 1.1 배경" in item.text for item in found.items)


async def test_reindex_reproduces_the_original_strategy() -> None:
    """전략까지 바뀌면 재인덱싱 결과를 예측할 수 없다. 구조를 저장해 그걸 막는다."""
    harness = Harness()
    html = "<html><body><h1>1장</h1><p>본문 하나.</p><h2>1.1</h2><p>본문 둘.</p></body></html>"
    ingested = await harness.ingest_text(html, content_type=ContentType.HTML)

    reindexed = await harness.service.reindex(PydanticObjectId(ingested.document.id))

    assert reindexed.chunking_strategy == "heading"
    assert reindexed.chunk_count == ingested.document.chunk_count


async def test_reindex_can_switch_the_strategy_explicitly() -> None:
    harness = Harness()
    html = "<html><body><h1>1장</h1><p>본문 하나.</p><h2>1.1</h2><p>본문 둘.</p></body></html>"
    ingested = await harness.ingest_text(html, content_type=ContentType.HTML)

    reindexed = await harness.service.reindex(
        PydanticObjectId(ingested.document.id), chunking_strategy="fixed_size"
    )

    assert reindexed.chunking_strategy == "fixed_size"
    assert harness.vectors.chunk_count(reindexed.id) == reindexed.chunk_count


async def test_outline_is_persisted_for_later_reindexing() -> None:
    """원본 바이트를 보관하지 않으므로 다시 파싱할 수 없다 — 구조를 저장해야 한다."""
    harness = Harness()
    html = "<html><body><h1>1장</h1><p>본문.</p></body></html>"
    ingested = await harness.ingest_text(html, content_type=ContentType.HTML)

    stored = await harness.repository.get(PydanticObjectId(ingested.document.id))

    assert stored is not None
    assert [section.heading for section in stored.outline] == ["1장"]
