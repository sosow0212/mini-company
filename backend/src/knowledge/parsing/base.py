"""파서 경계.

새 포맷을 지원하려면 이 Protocol만 구현하고 `registry.py`에 등록한다.
`service.py`는 어떤 포맷이 들어왔는지 모르고, 그래서 포맷이 늘어도 수정되지 않는다.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from src.knowledge.chunking.base import Section
from src.knowledge.constants import ContentType
from src.knowledge.domain import DocumentMetadata

# Mongo는 키에 '.'과 '$'를 허용하지 않는다. extra에 담기 전에 반드시 통과시킨다.
_UNSAFE_KEY_CHARS = re.compile(r"[.$]")
# NO-BREAK SPACE(U+00A0)를 의도적으로 포함한다 — HTML에서 &nbsp;로 대량 유입된다.
_WHITESPACE = re.compile("[ \\t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class RawPayload:
    """파서 입력.

    텍스트 계열은 `text`, 바이너리 계열(PDF)은 `data`를 채운다. 둘 다 두는 이유:
    base64를 항상 거치게 하면 텍스트 문서에 33% 낭비가 붙고, 텍스트만 받으면 PDF를
    실을 방법이 없다.
    """

    content_type: ContentType
    text: str | None = None
    data: bytes | None = None
    # 워커가 이미 아는 메타(RSS 피드의 pubDate 등). 파서 추출값 위에 덮인다.
    hints: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    metadata: DocumentMetadata
    # 제목 구조. 목차 청킹의 전제조건이다 — 파싱 단계에서 `<h2>`나 `## `를 지워버리면
    # 텍스트만 보고 절 경계를 되찾을 방법이 없다.
    # 구조를 알 수 없는 포맷(줄글·PDF)은 비워 둔다. 청커가 문단 전략으로 폴백한다.
    outline: tuple[Section, ...] = ()


class DocumentParser(Protocol):
    content_type: ContentType

    def parse(self, payload: RawPayload) -> ParsedDocument:
        """실패 시 DocumentParseFailed를 던진다."""
        ...


def normalize_metadata_key(key: str) -> str:
    """Mongo에 안전하고 비교 가능한 키로 만든다."""
    return _UNSAFE_KEY_CHARS.sub("_", key.strip().lower())


def clean_text(text: str) -> str:
    """공백을 정리한다. 청킹 품질이 여기에 직접 달려 있다.

    줄바꿈은 보존한다 — 문단 경계가 청크 경계의 1순위 기준이기 때문이다.
    """
    collapsed = _WHITESPACE.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = (line.strip() for line in collapsed.split("\n"))
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def first_present(*values: str | None) -> str | None:
    """우선순위 목록에서 처음 비어 있지 않은 값. 메타 출처가 여러 개일 때 쓴다."""
    for value in values:
        if value is not None and value.strip() != "":
            return value.strip()
    return None


def parse_datetime(value: str | None) -> datetime | None:
    """ISO 8601을 관대하게 읽는다. 실패하면 None — 메타 하나 때문에 적재를 막지 않는다."""
    if value is None or value.strip() == "":
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def split_keywords(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip() != "")
