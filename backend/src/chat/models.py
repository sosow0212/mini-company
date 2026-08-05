"""지속성 표현. 이 파일 밖으로 나가지 않는다 — repository가 도메인 모델로 변환한다.

메시지를 **임베디드**로 두는 이유: 대화 조회는 항상 전체를 함께 읽고, 챗봇 대화는
Mongo 문서 크기 제한(16MB)에 닿을 만큼 길어지지 않는다. 별 컬렉션으로 나누면
조회마다 조인이 필요해진다.
"""

from datetime import datetime
from typing import ClassVar

import pymongo
from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel

from src.chat.domain import MessageRole


class CitationEmbedded(BaseModel):
    index: int
    doc_id: str
    chunk_index: int
    title: str
    excerpt: str
    score: str


class MessageEmbedded(BaseModel):
    role: MessageRole
    content: str
    created_at: datetime
    citations: list[CitationEmbedded] = Field(default_factory=list)
    grounded: bool = True


class ConversationDocument(Document):
    title: str
    created_at: datetime
    messages: list[MessageEmbedded] = Field(default_factory=list)

    class Settings:
        name = "conversations"
        indexes: ClassVar[list[IndexModel | str]] = [
            IndexModel([("created_at", pymongo.DESCENDING)], name="recent_first"),
        ]
