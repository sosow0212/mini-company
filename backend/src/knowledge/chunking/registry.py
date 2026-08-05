"""전략 이름 → 구현, 그리고 포맷별 기본 전략.

**새 전략 추가는 이 파일 한 줄과 전략 파일 하나로 끝난다.** service·router·모델은
수정하지 않는다 — parsing 레지스트리와 같은 구조다.

기본값을 포맷으로 정하는 이유: HTML·Markdown은 제목 태그가 있어 목차 청킹이 가능하고,
PDF·줄글은 구조를 알 수 없으니 문단이 최선이다. 이 판단을 워커나 요청에 맡기면 같은
포맷이 호출처마다 다르게 잘린다.
"""

from src.knowledge.chunking.base import ChunkingStrategy
from src.knowledge.chunking.fixed_size import FixedSizeChunker
from src.knowledge.chunking.heading import HeadingChunker
from src.knowledge.chunking.paragraph import ParagraphChunker
from src.knowledge.constants import ContentType
from src.knowledge.exceptions import UnsupportedChunkingStrategy


def build_chunker_registry() -> dict[str, ChunkingStrategy]:
    chunkers: list[ChunkingStrategy] = [
        ParagraphChunker(),
        FixedSizeChunker(),
        HeadingChunker(),
    ]
    return {chunker.name: chunker for chunker in chunkers}


# 포맷별 기본 전략. 목차가 있는 포맷은 heading, 나머지는 paragraph.
# heading 전략은 outline이 비면 스스로 paragraph로 폴백하므로, 제목이 없는 HTML도 안전하다.
DEFAULT_STRATEGY_BY_CONTENT_TYPE: dict[ContentType, str] = {
    ContentType.HTML: "heading",
    ContentType.MARKDOWN: "heading",
    ContentType.PDF: "paragraph",
    ContentType.PLAIN_TEXT: "paragraph",
}

FALLBACK_STRATEGY = "paragraph"


def resolve_chunker(
    registry: dict[str, ChunkingStrategy],
    *,
    content_type: ContentType,
    override: str | None = None,
) -> ChunkingStrategy:
    """override가 있으면 그것, 없으면 포맷 기본값.

    override는 워커가 문서 성격을 아는 경우를 위한 통로다 — 표를 덤프한 HTML이라면
    heading이 아니라 fixed_size가 맞고, 그건 문서를 가져온 쪽만 안다.
    """
    name = override or DEFAULT_STRATEGY_BY_CONTENT_TYPE.get(content_type, FALLBACK_STRATEGY)
    chunker = registry.get(name)
    if chunker is None:
        raise UnsupportedChunkingStrategy(name, sorted(registry))
    return chunker


def missing_default_strategies(registry: dict[str, ChunkingStrategy]) -> list[str]:
    """부팅 검증용.

    두 가지를 본다: 포맷별 기본값이 실제로 등록되어 있는가, 그리고 모든 ContentType이
    기본값을 갖는가. 후자를 빠뜨리면 새 포맷이 조용히 FALLBACK으로 처리된다.
    """
    problems = [
        f"{content_type.value}→{name}"
        for content_type, name in DEFAULT_STRATEGY_BY_CONTENT_TYPE.items()
        if name not in registry
    ]
    problems.extend(
        f"{item.value}(기본 전략 미지정)"
        for item in ContentType
        if item not in DEFAULT_STRATEGY_BY_CONTENT_TYPE
    )
    if FALLBACK_STRATEGY not in registry:
        problems.append(f"폴백 전략 없음: {FALLBACK_STRATEGY}")
    return problems
