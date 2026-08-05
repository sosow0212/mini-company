from enum import StrEnum


class SourceType(StrEnum):
    """**어디서** 왔는가. 수집 경로를 뜻한다.

    검색 필터의 기준이다("웹에서 긁은 것만 찾아줘").
    """

    RSS = "RSS"
    WEB = "WEB"
    API = "API"
    FILE = "FILE"


class ContentType(StrEnum):
    """**무슨 포맷**인가. 파서 선택의 기준이다.

    SourceType과 축이 다르다 — HTML 문서를 WEB에서 긁어올 수도, FILE로 받을 수도 있다.
    두 개념을 한 필드에 섞으면 "웹에서 받은 PDF"를 표현할 수 없다.

    새 포맷 지원은 이 enum에 한 줄 + `parsing/`에 파서 하나 + registry 등록이면 끝난다.
    도메인 service는 수정하지 않는다.
    """

    PLAIN_TEXT = "PLAIN_TEXT"
    HTML = "HTML"
    MARKDOWN = "MARKDOWN"
    PDF = "PDF"


# 바이너리로 들어오는 포맷. 요청은 base64로 실어 보내야 한다.
BINARY_CONTENT_TYPES: frozenset[ContentType] = frozenset({ContentType.PDF})
