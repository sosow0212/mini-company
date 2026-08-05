"""HTML — 메타태그 추출이 이 파서의 본론이다.

같은 뜻을 부르는 이름이 여러 개다: 제목은 `og:title`·`<title>`·`twitter:title`,
날짜는 `article:published_time`·`<meta name=date>`·`<time datetime>`. 우선순위를 여기서
한 번 정하면 검색·표시 코드는 그 차이를 몰라도 된다.

**흡수되지 않은 메타는 버리지 않고 `extra`에 남긴다.** 지금 필요 없는 태그가 나중에
필요해질 수 있고, 원문을 다시 긁는 비용이 저장 비용보다 크다.
"""

from bs4 import BeautifulSoup, Tag

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
