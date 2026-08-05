"""포맷 → 파서.

**새 포맷 추가는 이 파일 한 줄과 파서 파일 하나로 끝난다.** service·router·모델은
수정하지 않는다 — 그게 이 레지스트리의 존재 이유다.
"""

from src.knowledge.constants import ContentType
from src.knowledge.exceptions import UnsupportedContentType
from src.knowledge.parsing.base import DocumentParser
from src.knowledge.parsing.html_document import HtmlParser
from src.knowledge.parsing.markdown import MarkdownParser
from src.knowledge.parsing.pdf_document import PdfParser
from src.knowledge.parsing.plain_text import PlainTextParser


def build_parser_registry() -> dict[ContentType, DocumentParser]:
    parsers: list[DocumentParser] = [
        PlainTextParser(),
        MarkdownParser(),
        HtmlParser(),
        PdfParser(),
    ]
    return {parser.content_type: parser for parser in parsers}


def resolve_parser(
    registry: dict[ContentType, DocumentParser],
    content_type: ContentType,
) -> DocumentParser:
    parser = registry.get(content_type)
    if parser is None:
        # enum에는 있는데 파서가 없는 상태. 부팅 검증이 막아야 하는 경로다.
        raise UnsupportedContentType(content_type.value)
    return parser


def missing_parsers(registry: dict[ContentType, DocumentParser]) -> list[str]:
    """부팅 시 검증용. enum에 선언했는데 파서가 없으면 런타임 첫 적재에서 발견된다."""
    return [item.value for item in ContentType if item not in registry]
