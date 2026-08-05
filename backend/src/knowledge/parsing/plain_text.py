"""줄글. 추출할 메타가 없으므로 텍스트 정리만 한다.

제목을 첫 줄에서 추측하지 않는다 — 본문 첫 문장이 제목으로 박히면 목록 화면이 망가지고,
그게 틀렸다는 걸 알아차리기도 어렵다. 제목은 워커가 hints로 주거나 비워둔다.
"""

from src.knowledge.constants import ContentType
from src.knowledge.domain import DocumentMetadata
from src.knowledge.exceptions import DocumentParseFailed
from src.knowledge.parsing.base import ParsedDocument, RawPayload, clean_text


class PlainTextParser:
    content_type = ContentType.PLAIN_TEXT

    def parse(self, payload: RawPayload) -> ParsedDocument:
        if payload.text is None:
            raise DocumentParseFailed("줄글에는 text가 필요하다")
        return ParsedDocument(text=clean_text(payload.text), metadata=DocumentMetadata())
