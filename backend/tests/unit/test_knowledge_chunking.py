"""청킹 전략 — 순수 함수라 mock 0개.

요구는 "청킹 전략이 여러 가지다"였다. 그래서 검증도 두 축이다:
새 전략을 붙일 자리가 열려 있는가, 그리고 **전략마다 실제로 다르게 자르는가**.
같은 결과를 내면 전략을 분리한 의미가 없다.
"""

import pytest

from src.knowledge.chunking.base import (
    ChunkingInput,
    ChunkingOptions,
    Section,
    merge_with_overlap,
    split_oversized,
)
from src.knowledge.chunking.fixed_size import FixedSizeChunker
from src.knowledge.chunking.heading import HeadingChunker
from src.knowledge.chunking.paragraph import ParagraphChunker
from src.knowledge.chunking.registry import (
    DEFAULT_STRATEGY_BY_CONTENT_TYPE,
    build_chunker_registry,
    missing_default_strategies,
    resolve_chunker,
)
from src.knowledge.constants import ContentType
from src.knowledge.exceptions import UnsupportedChunkingStrategy

REGISTRY = build_chunker_registry()
# 짧은 목표 크기로 경계 동작을 관찰한다. 실제 기본값(500토큰)은 테스트 문서를 한 청크에 담는다.
OPTIONS = ChunkingOptions(target_chars=60, overlap_chars=10)


# ─── 확장 지점 ─────────────────────────────────────────────────


def test_every_content_type_has_a_default_strategy() -> None:
    """새 포맷을 추가하고 기본 전략을 빠뜨리면 조용히 폴백된다. 부팅 검증이 이걸 잡는다."""
    assert missing_default_strategies(REGISTRY) == []


def test_registry_exposes_all_three_strategies() -> None:
    assert set(REGISTRY) == {"paragraph", "fixed_size", "heading"}


def test_structured_formats_default_to_heading() -> None:
    # HTML·Markdown은 제목 태그가 있어 목차 청킹이 가능하다.
    assert DEFAULT_STRATEGY_BY_CONTENT_TYPE[ContentType.HTML] == "heading"
    assert DEFAULT_STRATEGY_BY_CONTENT_TYPE[ContentType.MARKDOWN] == "heading"


def test_unstructured_formats_default_to_paragraph() -> None:
    assert DEFAULT_STRATEGY_BY_CONTENT_TYPE[ContentType.PDF] == "paragraph"
    assert DEFAULT_STRATEGY_BY_CONTENT_TYPE[ContentType.PLAIN_TEXT] == "paragraph"


def test_override_wins_over_format_default() -> None:
    """문서 성격을 아는 쪽은 호출자다 — 표를 덤프한 HTML이면 fixed_size가 맞다."""
    chunker = resolve_chunker(REGISTRY, content_type=ContentType.HTML, override="fixed_size")

    assert chunker.name == "fixed_size"


def test_unknown_strategy_is_rejected_with_available_names() -> None:
    with pytest.raises(UnsupportedChunkingStrategy) as raised:
        resolve_chunker(REGISTRY, content_type=ContentType.HTML, override="semantic")

    # 오타를 냈을 때 무엇을 쓸 수 있는지 알려줘야 한다.
    assert "semantic" in raised.value.message
    assert "paragraph" in raised.value.message


# ─── 전략이 실제로 다른가 ──────────────────────────────────────

_OUTLINE = (
    Section(level=1, heading="1장 개요", text="개요 본문이다. 배경을 설명한다."),
    Section(level=2, heading="1.1 배경", text="배경 상세 설명이다.", path=("1장 개요",)),
    Section(level=1, heading="2장 방법", text="방법 본문이다."),
)
_FLAT_TEXT = "개요 본문이다. 배경을 설명한다.\n\n배경 상세 설명이다.\n\n방법 본문이다."

# target을 확실히 넘는 문서. 짧은 문서는 어느 전략이든 한 청크가 되어 차이가 드러나지 않는다.
_LONG_OUTLINE = tuple(
    Section(level=1, heading=f"{index}장", text=f"{'본문 내용이다. ' * 6}({index})")
    for index in range(3)
)
_LONG_FLAT_TEXT = "\n\n".join(section.text for section in _LONG_OUTLINE)


def test_three_strategies_produce_different_chunkings() -> None:
    source = ChunkingInput(text=_LONG_FLAT_TEXT, outline=_LONG_OUTLINE)

    results = {
        name: REGISTRY[name].chunk(source, OPTIONS)
        for name in ("paragraph", "fixed_size", "heading")
    }

    # 전략이 같은 결과를 내면 분리한 의미가 없다.
    assert results["heading"] != results["paragraph"]
    assert results["fixed_size"] != results["paragraph"]


# ─── 문단 전략 ─────────────────────────────────────────────────


def test_paragraph_respects_paragraph_boundaries() -> None:
    chunker = ParagraphChunker()
    text = "\n\n".join(f"{'가' * 50} 문단{index}." for index in range(3))

    chunks = chunker.chunk(ChunkingInput(text=text), OPTIONS)

    # 문단은 글쓴이가 이미 표시해둔 경계다. 그 중간에서 자르지 않는다.
    assert len(chunks) >= 3


def test_paragraph_merges_small_paragraphs_up_to_target() -> None:
    chunker = ParagraphChunker()

    chunks = chunker.chunk(ChunkingInput(text="짧다.\n\n또 짧다.\n\n계속 짧다."), OPTIONS)

    assert len(chunks) == 1


def test_paragraph_splits_long_paragraph_at_sentence_boundary() -> None:
    chunker = ParagraphChunker()
    # 한 문단에 target을 넘는 문장 여러 개.
    text = " ".join(f"{'문장' * 12}{index}이다." for index in range(4))

    chunks = chunker.chunk(ChunkingInput(text=text), OPTIONS)

    assert len(chunks) > 1


def test_paragraph_returns_empty_for_blank_text() -> None:
    assert ParagraphChunker().chunk(ChunkingInput(text="   \n\n  "), OPTIONS) == []


def test_paragraph_ignores_outline() -> None:
    """구조가 있어도 문단 전략은 쓰지 않는다 — 전략 선택이 명시적이어야 한다."""
    chunker = ParagraphChunker()

    with_outline = chunker.chunk(ChunkingInput(text=_FLAT_TEXT, outline=_OUTLINE), OPTIONS)
    without = chunker.chunk(ChunkingInput(text=_FLAT_TEXT), OPTIONS)

    assert with_outline == without


# ─── 고정 크기 전략 ────────────────────────────────────────────


def test_fixed_size_produces_uniform_chunks() -> None:
    """청크 크기가 균일해서 임베딩 비용과 검색 지연이 예측 가능하다."""
    chunks = FixedSizeChunker().chunk(ChunkingInput(text="가" * 500), OPTIONS)

    assert all(len(chunk) == OPTIONS.target_chars for chunk in chunks[:-1])


def test_fixed_size_covers_the_whole_text() -> None:
    text = "".join(str(index % 10) for index in range(347))

    chunks = FixedSizeChunker().chunk(ChunkingInput(text=text), OPTIONS)

    # 겹침을 고려해 이어붙이면 원문이 복원되어야 한다 — 조각이 유실되면 검색에서 사라진다.
    step = OPTIONS.target_chars - OPTIONS.overlap_chars
    rebuilt = "".join(
        chunk[:step] if index < len(chunks) - 1 else chunk for index, chunk in enumerate(chunks)
    )
    assert rebuilt == text


def test_fixed_size_does_not_emit_overlap_only_tail() -> None:
    """겹침만 남은 짧은 조각은 앞 청크의 복사본이라 임베딩 낭비이고 검색에도 잡힌다."""
    chunks = FixedSizeChunker().chunk(ChunkingInput(text="가" * 105), OPTIONS)

    assert all(len(chunk) > OPTIONS.overlap_chars for chunk in chunks)


def test_fixed_size_ignores_boundaries_by_design() -> None:
    """산문에는 나쁘지만 표·로그처럼 구조 없는 텍스트에는 이게 맞다."""
    text = "짧은 문단.\n\n" * 20

    chunks = FixedSizeChunker().chunk(ChunkingInput(text=text), OPTIONS)

    assert len(chunks) > 1


def test_fixed_size_handles_text_shorter_than_target() -> None:
    chunks = FixedSizeChunker().chunk(ChunkingInput(text="짧다."), OPTIONS)

    assert chunks == ["짧다."]


# ─── 목차 전략 ─────────────────────────────────────────────────


def test_heading_creates_one_chunk_per_section() -> None:
    """한 청크가 하나의 주제를 담는다 — 검색이 절을 맞추면 절 전체가 인용된다."""
    chunks = HeadingChunker().chunk(ChunkingInput(text=_FLAT_TEXT, outline=_OUTLINE), OPTIONS)

    assert len(chunks) == len(_OUTLINE)


def test_heading_prefixes_chunks_with_the_heading_path() -> None:
    """조각만 떼어 임베딩하면 "1.1절의 내용"이라는 정보가 사라진다."""
    chunks = HeadingChunker().chunk(ChunkingInput(text=_FLAT_TEXT, outline=_OUTLINE), OPTIONS)

    assert chunks[0].startswith("[1장 개요]")
    # 상위 경로가 이어진다.
    assert chunks[1].startswith("[1장 개요 > 1.1 배경]")


def test_heading_falls_back_to_paragraph_without_outline() -> None:
    """줄글·PDF는 구조를 알 수 없다. 호출자가 포맷을 판단하게 만들면 그 판단이 흩어진다."""
    source = ChunkingInput(text=_FLAT_TEXT)

    heading = HeadingChunker().chunk(source, OPTIONS)
    paragraph = ParagraphChunker().chunk(source, OPTIONS)

    assert heading == paragraph


def test_heading_skips_sections_without_body() -> None:
    """제목만 있는 상위 목차를 임베딩하면 내용 없는 청크가 검색에 잡힌다."""
    outline = (
        Section(level=1, heading="목차만 있는 장", text=""),
        Section(level=2, heading="내용 있는 절", text="본문이다.", path=("목차만 있는 장",)),
    )

    chunks = HeadingChunker().chunk(ChunkingInput(text="본문이다.", outline=outline), OPTIONS)

    assert len(chunks) == 1
    assert "내용 있는 절" in chunks[0]


def test_heading_splits_oversized_section_but_keeps_prefix_on_each_part() -> None:
    long_section = (
        Section(
            level=1,
            heading="긴 절",
            text="\n\n".join(f"{'가' * 55} {index}." for index in range(4)),
        ),
    )

    chunks = HeadingChunker().chunk(ChunkingInput(text="무시됨", outline=long_section), OPTIONS)

    assert len(chunks) > 1
    # 절이 쪼개져도 각 조각이 문맥을 갖는다.
    assert all(chunk.startswith("[긴 절]") for chunk in chunks)


def test_heading_keeps_preamble_before_first_section() -> None:
    """첫 제목보다 앞에 있는 도입부를 버리면 문서 앞머리가 인덱싱에서 사라진다."""
    outline = (
        Section(level=0, heading="", text="도입부 문단이다."),
        Section(level=1, heading="1장", text="본문이다."),
    )

    chunks = HeadingChunker().chunk(ChunkingInput(text="무시됨", outline=outline), OPTIONS)

    assert chunks[0] == "도입부 문단이다."


# ─── 옵션 검증 ─────────────────────────────────────────────────


def test_options_convert_tokens_to_chars() -> None:
    options = ChunkingOptions.from_tokens(target_tokens=500, overlap_tokens=80)

    assert options.target_chars == 800
    assert options.overlap_chars == 128


def test_options_reject_non_positive_target() -> None:
    with pytest.raises(ValueError, match="target_tokens"):
        ChunkingOptions.from_tokens(target_tokens=0, overlap_tokens=0)


def test_options_reject_overlap_not_smaller_than_target() -> None:
    """overlap >= target이면 fixed_size의 창이 전진하지 않아 무한 루프가 된다."""
    with pytest.raises(ValueError, match="overlap_tokens"):
        ChunkingOptions.from_tokens(target_tokens=100, overlap_tokens=100)


# ─── 공통 헬퍼 ─────────────────────────────────────────────────


def test_split_oversized_falls_back_to_characters_for_unbreakable_text() -> None:
    """URL 나열처럼 문장 경계가 없는 텍스트는 문자로 자를 수밖에 없다."""
    blocks = split_oversized("가" * 200, 60)

    assert all(len(block) <= 60 for block in blocks)


def test_merge_with_overlap_prepends_tail_of_previous_chunk() -> None:
    """답이 경계에 걸치면 어느 조각도 온전한 문맥을 갖지 못한다."""
    blocks = ["가" * 55, "나" * 55]

    chunks = merge_with_overlap(blocks, ChunkingOptions(target_chars=60, overlap_chars=10))

    assert len(chunks) == 2
    assert chunks[1].startswith("가" * 10)
