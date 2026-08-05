"""지속성 표현. 이 파일 밖으로 나가지 않는다 — repository가 도메인 모델로 변환한다."""

from datetime import datetime
from typing import ClassVar

import pymongo
from beanie import Document, PydanticObjectId
from pydantic import BaseModel, Field
from pymongo import IndexModel

from src.knowledge.constants import ContentType, SourceType


class DocumentMetadataEmbedded(BaseModel):
    """임베디드 문서. 도메인의 DocumentMetadata와 필드가 1:1이다.

    `extra`의 키는 파서가 정규화해서 넣는다 — Mongo는 키에 '.'과 '$'를 허용하지 않고,
    그걸 어기면 저장 시점이 아니라 **조회 시점**에 이상하게 깨진다.
    """

    title: str | None = None
    author: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    keywords: list[str] = Field(default_factory=list)
    extra: dict[str, str] = Field(default_factory=dict)


class SectionEmbedded(BaseModel):
    """파싱 시점의 절 구조. 재인덱싱이 최초 적재와 같은 결과를 내려면 필요하다."""

    level: int
    heading: str
    text: str
    path: list[str] = Field(default_factory=list)


class SourceDocumentDocument(Document):
    title: str
    source_url: str | None = None
    source_type: SourceType
    content_type: ContentType
    raw_text: str
    outline: list[SectionEmbedded] = Field(default_factory=list)
    chunking_strategy: str = ""
    metadata: DocumentMetadataEmbedded = DocumentMetadataEmbedded()
    collected_by: PydanticObjectId
    task_id: PydanticObjectId | None = None
    collected_at: datetime
    content_hash: str
    chunk_count: int = 0
    indexed_at: datetime | None = None

    class Settings:
        name = "source_documents"
        indexes: ClassVar[list[IndexModel | str]] = [
            # 중복 수집 차단의 2차 방어선. 1차는 service의 해시 조회다.
            IndexModel([("content_hash", pymongo.ASCENDING)], unique=True, name="uq_content_hash"),
            IndexModel(
                [("collected_at", pymongo.DESCENDING)],
                name="recent_first",
            ),
            IndexModel(
                [("source_type", pymongo.ASCENDING), ("content_type", pymongo.ASCENDING)],
                name="by_kind",
            ),
        ]
