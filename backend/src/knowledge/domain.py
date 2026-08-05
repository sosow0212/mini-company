"""도메인 모델. 지속성 기술(Beanie/Milvus)을 모른다."""

from collections.abc import Mapping
from datetime import datetime

from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field

from src.knowledge.constants import ContentType, SourceType


class DocumentMetadata(BaseModel):
    """문서에서 뽑아낸 서지 정보.

    **정규 필드 + extra**로 나눈 이유: 소스마다 같은 뜻을 다른 이름으로 부른다
    (`og:title` / `<title>` / PDF `/Title`). 파서가 그 차이를 흡수해 정규 필드를 채우면
    검색·표시 코드가 소스 종류를 몰라도 된다. 흡수되지 않은 것은 버리지 않고 `extra`에
    남긴다 — 나중에 필요해질 태그를 지금 판단해 버릴 이유가 없다.
    """

    model_config = ConfigDict(frozen=True)

    title: str | None = None
    author: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    keywords: tuple[str, ...] = ()
    # 원문에 있던 나머지 메타. 키는 파서가 정규화해 넣는다(Mongo가 '.'·'$'를 거부한다).
    extra: Mapping[str, str] = Field(default_factory=dict)


class SourceDocument(BaseModel):
    """수집 직원이 가져온 원문 1건.

    `raw_text`는 파싱된 **텍스트**다. 원본 바이트(PDF 등)는 보관하지 않는다 — 검색과
    인용에 필요한 것은 텍스트이고, 바이너리를 Mongo에 넣으면 문서 크기 제한에 먼저 부딪힌다.
    """

    model_config = ConfigDict(frozen=True)

    id: PydanticObjectId | None = None
    title: str
    source_url: str | None = None
    source_type: SourceType
    content_type: ContentType
    raw_text: str
    metadata: DocumentMetadata = DocumentMetadata()
    collected_by: PydanticObjectId
    task_id: PydanticObjectId | None = None
    collected_at: datetime
    # 같은 내용을 두 번 적재하지 않기 위한 지문. 텍스트에서 계산한다.
    content_hash: str
    chunk_count: int = 0
    indexed_at: datetime | None = None


class Chunk(BaseModel):
    """문서를 쪼갠 조각. 벡터는 여기 없다 — 임베딩은 저장소 경계에서만 다룬다."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    chunk_index: int
    text: str


class SearchHit(BaseModel):
    """검색 결과 1건. 점수는 프로바이더가 준 값을 그대로 싣는다."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    chunk_index: int
    text: str
    score: float
