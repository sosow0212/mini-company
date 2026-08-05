"""마크다운.

렌더링하지 않는다 — 검색 대상은 텍스트이고, 마크업 기호는 임베딩에 잡음이다.
제목만 첫 h1에서 가져온다(줄글과 달리 `# `는 "제목"이라는 명시적 표시라 추측이 아니다).
YAML front matter가 있으면 그것도 메타로 읽는다.
"""

import re

from src.knowledge.constants import ContentType
from src.knowledge.domain import DocumentMetadata
from src.knowledge.exceptions import DocumentParseFailed
from src.knowledge.parsing.base import (
    ParsedDocument,
    RawPayload,
    clean_text,
    first_present,
    normalize_metadata_key,
    parse_datetime,
    split_keywords,
)

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_MARKUP = re.compile(r"^#{1,6}\s+|^\s*[-*+]\s+|^>\s?|`{1,3}|\*{1,2}|_{1,2}", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


class MarkdownParser:
    content_type = ContentType.MARKDOWN

    def parse(self, payload: RawPayload) -> ParsedDocument:
        if payload.text is None:
            raise DocumentParseFailed("마크다운에는 text가 필요하다")

        front_matter, body = _split_front_matter(payload.text)
        heading = _H1.search(body)

        # 링크는 표시 텍스트만 남긴다. URL이 본문에 섞이면 청크가 잡음으로 채워진다.
        stripped = _MARKUP.sub("", _LINK.sub(r"\1", body))

        return ParsedDocument(
            text=clean_text(stripped),
            metadata=DocumentMetadata(
                title=first_present(
                    front_matter.get("title"), heading.group(1) if heading else None
                ),
                author=front_matter.get("author"),
                description=front_matter.get("description"),
                published_at=parse_datetime(
                    first_present(front_matter.get("date"), front_matter.get("published"))
                ),
                language=front_matter.get("lang"),
                keywords=split_keywords(front_matter.get("keywords") or front_matter.get("tags")),
                extra={
                    key: value
                    for key, value in front_matter.items()
                    if key
                    not in {
                        "title",
                        "author",
                        "description",
                        "date",
                        "published",
                        "lang",
                        "keywords",
                        "tags",
                    }
                },
            ),
        )


def _split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """`key: value` 한 줄짜리만 읽는다. 중첩 YAML까지 지원하려면 파서가 필요한데,
    front matter는 대개 평평하고 아니면 extra에 문자열로 남겨도 손실이 없다.
    """
    match = _FRONT_MATTER.match(text)
    if match is None:
        return {}, text

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator == "":
            continue
        cleaned = value.strip().strip("\"'").strip("[]")
        if cleaned != "":
            fields[normalize_metadata_key(key)] = cleaned
    return fields, text[match.end() :]
