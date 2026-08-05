"""HTML — 메타태그 추출이 이 파서의 본론이다.

같은 뜻을 부르는 이름이 여러 개다: 제목은 `og:title`·`<title>`·`twitter:title`,
날짜는 `article:published_time`·`<meta name=date>`·`<time datetime>`. 우선순위를 여기서
한 번 정하면 검색·표시 코드는 그 차이를 몰라도 된다.

**흡수되지 않은 메타는 버리지 않고 `extra`에 남긴다.** 지금 필요 없는 태그가 나중에
필요해질 수 있고, 원문을 다시 긁는 비용이 저장 비용보다 크다.
"""

from bs4 import BeautifulSoup, Tag

from src.knowledge.chunking.base import Section
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
from src.knowledge.parsing.outline import RawHeading, build_outline

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# 본문이 아닌 것. 남겨두면 청크가 코드와 메뉴로 채워진다.
_NOISE_TAGS = ("script", "style", "noscript", "template", "svg", "nav", "footer", "header", "aside")

# 정규 필드로 흡수하는 메타 이름. 앞에 있는 것이 이긴다.
_TITLE_KEYS = ("og:title", "twitter:title")
_DESCRIPTION_KEYS = ("og:description", "description", "twitter:description")
_AUTHOR_KEYS = ("author", "article:author", "og:article:author")
_PUBLISHED_KEYS = ("article:published_time", "og:article:published_time", "date", "pubdate")
_LANGUAGE_KEYS = ("og:locale", "language")
_ABSORBED = frozenset(
    _TITLE_KEYS
    + _DESCRIPTION_KEYS
    + _AUTHOR_KEYS
    + _PUBLISHED_KEYS
    + _LANGUAGE_KEYS
    + ("keywords",)
)


class HtmlParser:
    content_type = ContentType.HTML

    def parse(self, payload: RawPayload) -> ParsedDocument:
        if payload.text is None:
            raise DocumentParseFailed("HTML에는 text가 필요하다")

        # lxml을 쓰지 않는 이유: 표준 html.parser로 충분하고 의존성이 하나 줄어든다.
        soup = BeautifulSoup(payload.text, "html.parser")
        meta = _collect_meta(soup)

        for tag in soup(_NOISE_TAGS):
            tag.decompose()
        body = soup.body if soup.body is not None else soup

        return ParsedDocument(
            text=clean_text(body.get_text(separator="\n")),
            outline=_build_outline(body),
            metadata=DocumentMetadata(
                title=first_present(
                    *(meta.get(key) for key in _TITLE_KEYS),
                    soup.title.string if soup.title is not None else None,
                ),
                author=first_present(*(meta.get(key) for key in _AUTHOR_KEYS)),
                description=first_present(*(meta.get(key) for key in _DESCRIPTION_KEYS)),
                published_at=parse_datetime(
                    first_present(
                        *(meta.get(key) for key in _PUBLISHED_KEYS), _time_attribute(soup)
                    )
                ),
                language=first_present(
                    _html_lang(soup), *(meta.get(key) for key in _LANGUAGE_KEYS)
                ),
                keywords=split_keywords(meta.get("keywords")),
                # 흡수되지 않은 og:*, twitter:*, 사이트 고유 태그가 여기 남는다.
                extra={key: value for key, value in meta.items() if key not in _ABSORBED},
            ),
        )


def _build_outline(body: Tag) -> tuple[Section, ...]:
    """h1~h6를 훑어 절 구조를 만든다.

    각 제목의 본문은 "다음 제목이 나오기 전까지의 형제 노드"다. DOM 트리를 재귀로
    내려가지 않고 `find_all_next`로 평면 순회하는 이유: 제목이 `<section>`이나 `<div>`로
    감싸인 깊이는 문서마다 다르고, 문서 순서(document order)만이 목차와 일치한다.
    """
    headings = body.find_all(_HEADING_TAGS)
    if not headings:
        return ()

    raw: list[RawHeading] = []
    for index, heading in enumerate(headings):
        if not isinstance(heading, Tag):
            continue
        stop = headings[index + 1] if index + 1 < len(headings) else None
        raw.append(
            RawHeading(
                level=int(heading.name[1]),
                heading=clean_text(heading.get_text(separator=" ")),
                text=_text_between(heading, stop),
            )
        )
    return build_outline(raw, preamble=_text_before(body, headings[0]))


def _text_between(heading: Tag, stop: Tag | None) -> str:
    """제목 다음부터 다음 제목 전까지의 텍스트.

    제목 자신의 텍스트는 제외한다 — 청커가 접두어로 제목을 붙이므로, 여기 두면 청크에
    같은 제목이 두 번 나온다.
    """
    parts: list[str] = []
    for node in heading.find_all_next(string=True):
        if stop is not None and _is_within(node, stop):
            break
        if _is_within(node, heading):
            continue
        parts.append(str(node))
    return clean_text("\n".join(parts))


def _text_before(body: Tag, first_heading: Tag) -> str:
    """첫 제목보다 앞에 있는 도입부. 버리면 문서 앞머리가 인덱싱에서 사라진다."""
    parts = [
        str(node)
        for node in first_heading.find_all_previous(string=True)
        if _is_descendant_of(node, body)
    ]
    # find_all_previous는 역순으로 돌려준다.
    return clean_text("\n".join(reversed(parts)))


def _is_within(node: object, boundary: Tag) -> bool:
    return node is boundary or (
        hasattr(node, "parents") and boundary in getattr(node, "parents", ())
    )


def _is_descendant_of(node: object, ancestor: Tag) -> bool:
    return ancestor in getattr(node, "parents", ())


def _collect_meta(soup: BeautifulSoup) -> dict[str, str]:
    """`name`과 `property` 양쪽을 읽는다 — OG는 property, 표준 메타는 name을 쓴다."""
    collected: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        if not isinstance(tag, Tag):
            continue
        key = tag.get("property") or tag.get("name") or tag.get("http-equiv")
        content = tag.get("content")
        if not isinstance(key, str) or not isinstance(content, str) or content.strip() == "":
            continue
        normalized = normalize_metadata_key(key)
        # 먼저 나온 값을 유지한다. 문서 앞쪽 태그가 더 신뢰할 만하다.
        collected.setdefault(normalized, content.strip())
    return collected


def _html_lang(soup: BeautifulSoup) -> str | None:
    html = soup.find("html")
    if not isinstance(html, Tag):
        return None
    lang = html.get("lang")
    return lang if isinstance(lang, str) else None


def _time_attribute(soup: BeautifulSoup) -> str | None:
    """메타태그가 없는 문서에서 `<time datetime>`이 유일한 날짜 단서인 경우가 흔하다."""
    time_tag = soup.find("time")
    if not isinstance(time_tag, Tag):
        return None
    value = time_tag.get("datetime")
    return value if isinstance(value, str) else None
