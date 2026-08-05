"""목차 청킹 — 제목 태그를 보고 절 단위로 자른다.

한 청크가 하나의 주제를 담는다는 점이 이 전략의 값어치다. 검색이 절을 맞추면 그 절
전체가 인용되므로 답변이 온전해진다. 문단 청킹은 같은 절을 여러 조각으로 쪼개서,
답이 걸친 경계마다 문맥이 끊긴다.

**각 청크 앞에 제목 경로를 붙인다.** 조각만 떼어 임베딩하면 "2.1절의 내용"이라는 정보가
사라지는데, 경로가 있으면 청크 자체가 문맥을 갖는다("1장 > 1.2 배경" + 본문).

outline이 없으면 문단 전략으로 폴백한다 — 줄글·PDF는 구조를 알 수 없고, 그때 호출자가
포맷을 판단해 전략을 바꾸게 만들면 그 판단이 여러 곳으로 흩어진다.
"""

from src.knowledge.chunking.base import (
    ChunkingInput,
    ChunkingOptions,
    Section,
    merge_with_overlap,
    split_oversized,
)
from src.knowledge.chunking.paragraph import ParagraphChunker

_PATH_SEPARATOR = " > "


class HeadingChunker:
    name = "heading"

    def __init__(self) -> None:
        self._fallback = ParagraphChunker()

    def chunk(self, source: ChunkingInput, options: ChunkingOptions) -> list[str]:
        if source.outline == ():
            return self._fallback.chunk(source, options)

        chunks: list[str] = []
        for section in source.outline:
            chunks.extend(self._chunk_section(section, options))
        return chunks

    def _chunk_section(self, section: Section, options: ChunkingOptions) -> list[str]:
        prefix = _render_prefix(section)
        body = section.text.strip()
        if body == "":
            # 제목만 있고 본문이 없는 절(상위 목차)은 건너뛴다. 제목 하나만 임베딩하면
            # 검색에서 내용 없는 청크가 잡힌다.
            return []

        # 제목 경로가 차지하는 만큼 본문 예산을 줄인다. 그러지 않으면 접두어를 붙인 뒤
        # target을 넘는다.
        budget = max(options.target_chars - len(prefix), _minimum_body_budget(options))
        blocks = split_oversized(body, budget)
        merged = merge_with_overlap(
            blocks, ChunkingOptions(target_chars=budget, overlap_chars=options.overlap_chars)
        )
        return [f"{prefix}{block}" for block in merged]


def _render_prefix(section: Section) -> str:
    trail = (*section.path, section.heading)
    labels = [item for item in trail if item.strip() != ""]
    return f"[{_PATH_SEPARATOR.join(labels)}]\n" if labels else ""


def _minimum_body_budget(options: ChunkingOptions) -> int:
    """제목 경로가 너무 길어 예산이 0 이하가 되는 경우를 막는다.

    겹침보다는 커야 한다 — 아니면 merge 단계에서 꼬리가 본문을 덮는다.
    """
    return max(options.overlap_chars + 1, options.target_chars // 4)
