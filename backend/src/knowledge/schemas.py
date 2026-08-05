import base64
import binascii
from datetime import datetime

from beanie import PydanticObjectId
from pydantic import Field, model_validator

from src.knowledge.constants import BINARY_CONTENT_TYPES, ContentType, SourceType
from src.knowledge.domain import DocumentMetadata, SourceDocument
from src.schemas import ApiModel

_MAX_TEXT_LENGTH = 2_000_000
_MAX_BASE64_LENGTH = 20_000_000


class IngestDocumentRequest(ApiModel):
    """워커가 보내는 수집 결과.

    `text`와 `base64Content`를 나눈 이유: 텍스트 문서를 항상 base64로 실으면 33%가
    낭비되고, 텍스트 필드만 두면 PDF를 보낼 방법이 없다. 어느 쪽을 채울지는
    `contentType`이 결정한다.

    `metadata`는 워커가 **이미 아는** 메타를 넘기는 통로다(RSS 항목의 발행일 등).
    파서가 문서에서 뽑은 값 위에 덮인다 — 명시적으로 준 값이 이긴다.
    """

    source_type: SourceType
    content_type: ContentType
    collected_by: PydanticObjectId
    task_id: PydanticObjectId | None = None
    source_url: str | None = Field(default=None, max_length=2_000)
    title: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=_MAX_TEXT_LENGTH)
    base64_content: str | None = Field(default=None, max_length=_MAX_BASE64_LENGTH)
    metadata: dict[str, str] = Field(default_factory=dict)
    # 비우면 포맷 기본 전략(HTML·MD는 목차, PDF·줄글은 문단)을 쓴다. 문서 성격을 아는
    # 호출자만 지정한다 — 표를 덤프한 HTML이면 fixed_size가 맞다.
    chunking_strategy: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _require_matching_payload(self) -> "IngestDocumentRequest":
        binary = self.content_type in BINARY_CONTENT_TYPES
        if binary and self.base64_content is None:
            raise ValueError(f"{self.content_type.value}는 base64Content가 필요하다")
        if not binary and self.text is None:
            raise ValueError(f"{self.content_type.value}는 text가 필요하다")
        return self

    def decoded_data(self) -> bytes | None:
        if self.base64_content is None:
            return None
        try:
            return base64.b64decode(self.base64_content, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("base64Content를 디코딩할 수 없다") from exc


class DocumentMetadataResponse(ApiModel):
    title: str | None
    author: str | None
    description: str | None
    published_at: datetime | None
    language: str | None
    keywords: list[str]
    # 정규 필드로 흡수되지 않은 원문 메타. og:*, PDF /Producer 등이 여기 남는다.
    extra: dict[str, str]

    @classmethod
    def from_domain(cls, metadata: DocumentMetadata) -> "DocumentMetadataResponse":
        return cls(
            title=metadata.title,
            author=metadata.author,
            description=metadata.description,
            published_at=metadata.published_at,
            language=metadata.language,
            keywords=list(metadata.keywords),
            extra=dict(metadata.extra),
        )


class DocumentResponse(ApiModel):
    id: str
    title: str
    source_url: str | None
    source_type: SourceType
    content_type: ContentType
    metadata: DocumentMetadataResponse
    collected_by: str
    task_id: str | None
    collected_at: datetime
    content_hash: str
    chunk_count: int
    # 어떤 전략으로 잘렸는지. 전략을 바꿨을 때 재인덱싱 대상을 고르는 근거다.
    chunking_strategy: str
    # 절 개수. 0이면 구조를 알 수 없는 문서(줄글·PDF)라 목차 청킹이 폴백됐다는 뜻이다.
    section_count: int
    indexed_at: datetime | None
    # 본문 전체는 내리지 않는다. 목록·상세 화면에 2MB 텍스트가 필요한 경우는 없다.
    text_length: int

    @classmethod
    def from_domain(cls, document: SourceDocument) -> "DocumentResponse":
        if document.id is None:
            raise ValueError("저장되지 않은 문서는 응답으로 내릴 수 없다")
        return cls(
            id=str(document.id),
            title=document.title,
            source_url=document.source_url,
            source_type=document.source_type,
            content_type=document.content_type,
            metadata=DocumentMetadataResponse.from_domain(document.metadata),
            collected_by=str(document.collected_by),
            task_id=str(document.task_id) if document.task_id else None,
            collected_at=document.collected_at,
            content_hash=document.content_hash,
            chunk_count=document.chunk_count,
            chunking_strategy=document.chunking_strategy,
            section_count=len(document.outline),
            indexed_at=document.indexed_at,
            text_length=len(document.raw_text),
        )


class IngestResult(ApiModel):
    document: DocumentResponse
    # 중복은 오류가 아니다. 워커가 같은 피드를 다시 긁는 것은 정상이므로 플래그로 알린다.
    skipped_duplicate: bool


class ReindexRequest(ApiModel):
    """전략을 비우면 최초 적재에 쓴 전략을 그대로 재현한다."""

    chunking_strategy: str | None = Field(default=None, max_length=40)


class SearchResultItem(ApiModel):
    doc_id: str
    chunk_index: int
    text: str
    # 점수도 문자열로 내린다. 프론트가 임계값 비교 같은 계산을 하지 않게(ADR-006).
    score: str
    title: str


class SearchResponse(ApiModel):
    query: str
    items: list[SearchResultItem]
