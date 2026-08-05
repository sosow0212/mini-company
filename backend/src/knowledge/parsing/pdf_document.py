"""PDF — 텍스트 추출 + 문서 정보 딕셔너리.

PDF 메타는 `/Title`, `/Author`처럼 슬래시 접두 키를 쓴다. pypdf가 날짜 파싱까지
해주므로(`D:20260805...` 형식) 직접 다루지 않는다.

페이지 텍스트 추출은 완벽하지 않다(표·다단 레이아웃에서 순서가 섞인다). 그래도 스캔
이미지가 아닌 PDF에서는 검색에 쓸 만하고, OCR은 이 프로젝트 범위 밖이다.
"""

from datetime import datetime
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src.knowledge.constants import ContentType
from src.knowledge.domain import DocumentMetadata
from src.knowledge.exceptions import DocumentParseFailed
from src.knowledge.parsing.base import (
    ParsedDocument,
    RawPayload,
    clean_text,
    first_present,
    normalize_metadata_key,
    split_keywords,
)

# 정규 필드로 흡수하는 PDF 문서 정보 키.
_ABSORBED = frozenset({"/title", "/author", "/subject", "/keywords", "/creationdate", "/moddate"})


class PdfParser:
    content_type = ContentType.PDF

    def parse(self, payload: RawPayload) -> ParsedDocument:
        if payload.data is None:
            raise DocumentParseFailed("PDF에는 base64 본문이 필요하다")

        try:
            reader = PdfReader(BytesIO(payload.data))
            pages = [page.extract_text() or "" for page in reader.pages]
        except (PdfReadError, ValueError, OSError) as exc:
            raise DocumentParseFailed(f"PDF를 읽을 수 없다: {type(exc).__name__}") from exc

        if reader.is_encrypted:
            # 암호가 걸린 PDF는 본문이 비어 나온다. 조용히 빈 문서를 적재하지 않는다.
            raise DocumentParseFailed("암호가 걸린 PDF는 적재할 수 없다")

        info = reader.metadata
        raw = {normalize_metadata_key(str(key)): str(value) for key, value in (info or {}).items()}

        return ParsedDocument(
            # 페이지 사이를 빈 줄로 나눈다. 청킹이 문단 경계를 먼저 보므로 페이지가 섞이지 않는다.
            text=clean_text("\n\n".join(pages)),
            metadata=DocumentMetadata(
                title=first_present(info.title if info else None),
                author=first_present(info.author if info else None),
                description=first_present(info.subject if info else None),
                published_at=_creation_date(reader),
                keywords=split_keywords(raw.get("/keywords")),
                extra={
                    **{key: value for key, value in raw.items() if key not in _ABSORBED},
                    "page_count": str(len(reader.pages)),
                },
            ),
        )


def _creation_date(reader: PdfReader) -> datetime | None:
    """pypdf가 D: 형식을 datetime으로 바꿔준다. 깨진 값이면 None으로 넘긴다."""
    try:
        return reader.metadata.creation_date if reader.metadata else None
    except (ValueError, TypeError):
        return None
