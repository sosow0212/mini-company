"""파서 — 확장 지점과 메타데이터 추출.

이 도메인의 요구는 "포맷이 늘어난다"와 "메타태그를 잘 적재한다"였다. 그래서 검증도
두 축이다: 새 포맷을 붙일 자리가 열려 있는가, 그리고 같은 뜻의 다른 이름을 흡수하는가.
"""

import zlib
from datetime import UTC, datetime

import pytest

from src.knowledge.constants import BINARY_CONTENT_TYPES, ContentType
from src.knowledge.exceptions import DocumentParseFailed
from src.knowledge.parsing.base import RawPayload, clean_text, normalize_metadata_key
from src.knowledge.parsing.registry import build_parser_registry, missing_parsers, resolve_parser

REGISTRY = build_parser_registry()


def _parse(content_type: ContentType, **payload) -> object:
    return resolve_parser(REGISTRY, content_type).parse(RawPayload(content_type, **payload))


# ─── 확장 지점 ─────────────────────────────────────────────────


def test_every_declared_content_type_has_a_parser() -> None:
    """enum에 포맷을 추가하고 파서 등록을 잊으면 런타임 첫 적재에서 발견된다.
    부팅 검증이 이 목록을 보고 앱을 세운다.
    """
    assert missing_parsers(REGISTRY) == []


def test_binary_content_types_are_declared() -> None:
    # 요청 스키마가 이 집합으로 text/base64 중 무엇이 필요한지 판단한다.
    assert ContentType.PDF in BINARY_CONTENT_TYPES
    assert ContentType.HTML not in BINARY_CONTENT_TYPES


# ─── 줄글 ──────────────────────────────────────────────────────


def test_plain_text_keeps_paragraph_boundaries() -> None:
    parsed = _parse(ContentType.PLAIN_TEXT, text="첫째 문단.\n\n\n\n둘째 문단.")

    # 문단 경계는 청킹의 1순위 기준이므로 보존되어야 한다.
    assert parsed.text == "첫째 문단.\n\n둘째 문단."


def test_plain_text_does_not_guess_a_title() -> None:
    """본문 첫 문장이 제목으로 박히면 목록 화면이 조용히 망가진다."""
    parsed = _parse(ContentType.PLAIN_TEXT, text="이건 제목이 아니다.\n본문이다.")

    assert parsed.metadata.title is None


def test_plain_text_requires_text() -> None:
    with pytest.raises(DocumentParseFailed):
        _parse(ContentType.PLAIN_TEXT, data=b"bytes")


# ─── HTML 메타태그 ─────────────────────────────────────────────

_HTML = """<!doctype html><html lang="ko"><head>
<title>태그 제목</title>
<meta property="og:title" content="OG 제목">
<meta name="description" content="설명문">
<meta name="author" content="박기자">
<meta property="article:published_time" content="2026-08-05T09:30:00Z">
<meta name="keywords" content="AI, 반도체 , 시장">
<meta property="og:site_name" content="테크뉴스">
<meta name="twitter:card" content="summary">
</head><body>
<nav>메뉴</nav><script>noise()</script><style>.x{}</style>
<h1>본문 제목</h1><p>첫째.</p><p>둘째.</p>
<footer>푸터</footer></body></html>"""


def test_html_prefers_og_title_over_title_tag() -> None:
    """같은 뜻을 부르는 이름이 여러 개다. 우선순위를 파서가 정하면 상위 코드가 몰라도 된다."""
    assert _parse(ContentType.HTML, text=_HTML).metadata.title == "OG 제목"


def test_html_falls_back_to_title_tag_when_og_is_absent() -> None:
    parsed = _parse(
        ContentType.HTML,
        text="<html><head><title>유일한 제목</title></head><body>본문</body></html>",
    )

    assert parsed.metadata.title == "유일한 제목"


def test_html_extracts_canonical_metadata_fields() -> None:
    metadata = _parse(ContentType.HTML, text=_HTML).metadata

    assert metadata.author == "박기자"
    assert metadata.description == "설명문"
    assert metadata.language == "ko"
    assert metadata.published_at == datetime(2026, 8, 5, 9, 30, tzinfo=UTC)
    assert metadata.keywords == ("AI", "반도체", "시장")


def test_html_keeps_unabsorbed_meta_tags_in_extra() -> None:
    """지금 안 쓰는 태그를 버리면 나중에 원문을 다시 긁어야 한다 — 저장이 더 싸다."""
    extra = _parse(ContentType.HTML, text=_HTML).metadata.extra

    assert extra["og:site_name"] == "테크뉴스"
    assert extra["twitter:card"] == "summary"
    # 정규 필드로 흡수된 것은 extra에 중복되지 않는다.
    assert "og:title" not in extra
    assert "description" not in extra


def test_html_strips_navigation_and_scripts_from_body() -> None:
    text = _parse(ContentType.HTML, text=_HTML).text

    assert "본문 제목" in text
    for noise in ("메뉴", "noise()", "푸터", ".x{}"):
        assert noise not in text


def test_html_reads_time_element_when_meta_date_is_absent() -> None:
    parsed = _parse(
        ContentType.HTML,
        text='<html><body><time datetime="2026-01-02T03:04:05Z">어제</time></body></html>',
    )

    assert parsed.metadata.published_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_html_survives_broken_dates() -> None:
    """메타 하나가 깨졌다고 적재를 막지 않는다."""
    parsed = _parse(
        ContentType.HTML,
        text='<html><head><meta name="date" content="어제쯤"></head><body>본문</body></html>',
    )

    assert parsed.metadata.published_at is None
    assert parsed.text == "본문"


# ─── Markdown ──────────────────────────────────────────────────

_MARKDOWN = """---
title: 분기 보고서
author: 리아
date: 2026-07-01
tags: 실적, 분석
custom_field: 남아야 함
---
# 마크다운 제목

**강조**와 [링크](https://example.com/very/long/url)가 있는 문단.
- 목록 항목
"""


def test_markdown_reads_front_matter() -> None:
    metadata = _parse(ContentType.MARKDOWN, text=_MARKDOWN).metadata

    assert metadata.title == "분기 보고서"
    assert metadata.author == "리아"
    assert metadata.keywords == ("실적", "분석")
    assert metadata.published_at == datetime(2026, 7, 1, tzinfo=UTC)


def test_markdown_keeps_unknown_front_matter_in_extra() -> None:
    assert (
        _parse(ContentType.MARKDOWN, text=_MARKDOWN).metadata.extra["custom_field"] == "남아야 함"
    )


def test_markdown_falls_back_to_first_heading_for_title() -> None:
    """`# `는 "제목"이라는 명시적 표시라 추측이 아니다."""
    parsed = _parse(ContentType.MARKDOWN, text="# 유일한 제목\n\n본문.")

    assert parsed.metadata.title == "유일한 제목"


def test_markdown_strips_markup_and_link_urls() -> None:
    """URL이 본문에 남으면 청크가 잡음으로 채워지고 임베딩 품질이 떨어진다."""
    text = _parse(ContentType.MARKDOWN, text=_MARKDOWN).text

    assert "https://example.com" not in text
    assert "링크" in text
    assert "**" not in text
    assert "강조" in text


# ─── PDF ───────────────────────────────────────────────────────


def _pdf_string(value: str) -> bytes:
    """PDF 문자열 리터럴.

    ASCII는 `(...)`로 쓰지만 한글은 latin-1에 없어서 UTF-16BE 16진 형식 `<FEFF...>`을
    써야 한다. 실제로 한글 제목이 달린 PDF를 받게 되므로 이 경로도 검증 대상이다.
    """
    try:
        return b"(" + value.encode("latin-1") + b")"
    except UnicodeEncodeError:
        return b"<FEFF" + value.encode("utf-16-be").hex().upper().encode("ascii") + b">"


def _minimal_pdf(*, title: str, author: str, body: str) -> bytes:
    """텍스트와 메타를 가진 최소 PDF. 외부 도구 없이 구조를 직접 조립한다."""
    content = f"BT /F1 12 Tf 72 720 Td ({body}) Tj ET".encode("latin-1")
    info = (
        b"<< /Title "
        + _pdf_string(title)
        + b" /Author "
        + _pdf_string(author)
        + b" /Producer (mini-company-test) /CreationDate (D:20260805093000Z) >>"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        info,
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body_bytes in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body_bytes + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_pdf_extracts_text_and_document_info() -> None:
    pdf = _minimal_pdf(title="PDF 보고서", author="노아", body="PDF body text")

    parsed = _parse(ContentType.PDF, data=pdf)

    assert "PDF body text" in parsed.text
    assert parsed.metadata.title == "PDF 보고서"
    assert parsed.metadata.author == "노아"


def test_pdf_keeps_producer_and_page_count_in_extra() -> None:
    parsed = _parse(ContentType.PDF, data=_minimal_pdf(title="t", author="a", body="body"))

    assert parsed.metadata.extra["page_count"] == "1"
    assert parsed.metadata.extra["/producer"] == "mini-company-test"


def test_pdf_requires_binary_payload() -> None:
    with pytest.raises(DocumentParseFailed):
        _parse(ContentType.PDF, text="이건 PDF가 아니다")


def test_pdf_rejects_unreadable_bytes() -> None:
    with pytest.raises(DocumentParseFailed):
        _parse(ContentType.PDF, data=zlib.compress(b"not a pdf at all"))


# ─── 공통 헬퍼 ─────────────────────────────────────────────────


def test_metadata_keys_are_safe_for_mongo() -> None:
    """Mongo는 키에 '.'과 '$'를 허용하지 않는다. 어기면 조회 시점에 이상하게 깨진다."""
    assert normalize_metadata_key("Article.Published$Time") == "article_published_time"
    assert normalize_metadata_key("  OG:Title  ") == "og:title"


def test_clean_text_collapses_spaces_but_keeps_paragraphs() -> None:
    assert clean_text("a   b\r\n\r\n\r\n\r\nc") == "a b\n\nc"


# ─── 절 구조(outline) — 목차 청킹의 전제조건 ──────────────────

_STRUCTURED_HTML = """<html><body>
<p>도입부 문단이다.</p>
<h1>1장 개요</h1><p>개요 본문이다.</p>
<h2>1.1 배경</h2><p>배경 설명이다.</p>
<h2>1.2 목표</h2><p>목표 설명이다.</p>
<h1>2장 방법</h1><p>방법 본문이다.</p>
</body></html>"""


def test_html_extracts_section_outline() -> None:
    """파싱 단계에서 `<h2>`를 지워버리면 텍스트만 보고 절 경계를 되찾을 수 없다."""
    outline = _parse(ContentType.HTML, text=_STRUCTURED_HTML).outline

    assert [(item.level, item.heading) for item in outline] == [
        (0, ""),
        (1, "1장 개요"),
        (2, "1.1 배경"),
        (2, "1.2 목표"),
        (1, "2장 방법"),
    ]


def test_html_outline_records_ancestor_path() -> None:
    """청크 앞에 붙는 경로다. 조각만 봐도 어느 절인지 알 수 있게 한다."""
    outline = _parse(ContentType.HTML, text=_STRUCTURED_HTML).outline

    assert outline[2].path == ("1장 개요",)
    assert outline[4].path == ()


def test_html_outline_excludes_heading_text_from_body() -> None:
    """청커가 접두어로 제목을 붙이므로, 본문에도 두면 청크에 제목이 두 번 나온다."""
    outline = _parse(ContentType.HTML, text=_STRUCTURED_HTML).outline

    assert outline[1].text == "개요 본문이다."


def test_html_outline_keeps_preamble_as_level_zero() -> None:
    """첫 제목보다 앞선 도입부를 버리면 문서 앞머리가 인덱싱에서 사라진다."""
    outline = _parse(ContentType.HTML, text=_STRUCTURED_HTML).outline

    assert outline[0].level == 0
    assert outline[0].text == "도입부 문단이다."


def test_html_outline_is_empty_without_headings() -> None:
    """구조를 알 수 없으면 비워 둔다. 목차 청커가 문단 전략으로 폴백한다."""
    outline = _parse(
        ContentType.HTML, text="<html><body><p>제목 없는 본문.</p></body></html>"
    ).outline

    assert outline == ()


def test_markdown_extracts_section_outline() -> None:
    markdown = "도입부다.\n\n# 1장\n개요 본문.\n\n## 1.1 배경\n배경 설명.\n\n# 2장\n방법 본문."

    outline = _parse(ContentType.MARKDOWN, text=markdown).outline

    assert [(item.level, item.heading, item.path) for item in outline] == [
        (0, "", ()),
        (1, "1장", ()),
        (2, "1.1 배경", ("1장",)),
        (1, "2장", ()),
    ]


def test_markdown_ignores_hash_inside_code_fence() -> None:
    """셸 주석은 제목이 아니다. 이걸 빼먹으면 스크립트 문서가 주석마다 쪼개진다."""
    markdown = "# 진짜 제목\n본문.\n\n```sh\n# 이건 주석이다\necho hi\n```\n\n## 다음 절\n계속."

    outline = _parse(ContentType.MARKDOWN, text=markdown).outline

    assert [item.heading for item in outline] == ["진짜 제목", "다음 절"]


def test_markdown_outline_strips_markup_from_section_body() -> None:
    outline = _parse(
        ContentType.MARKDOWN, text="# 제목\n**강조**와 [링크](https://x.test)다."
    ).outline

    assert "**" not in outline[0].text
    assert "https://x.test" not in outline[0].text


def test_plain_text_and_pdf_have_no_outline() -> None:
    """구조를 알 수 없는 포맷이다. 청커가 폴백할 근거가 된다."""
    assert _parse(ContentType.PLAIN_TEXT, text="줄글 본문.").outline == ()
    assert (
        _parse(ContentType.PDF, data=_minimal_pdf(title="t", author="a", body="body")).outline == ()
    )
