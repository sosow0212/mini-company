"""문단 우선 청킹. 구조를 모르는 문서의 기본값.

문단 경계를 1순위로 지킨다 — 문단은 글쓴이가 이미 "여기까지 한 덩어리"라고 표시해둔
경계이므로, 그걸 따르는 것이 어떤 자동 분할보다 낫다. 문단이 너무 길면 문장,
그래도 넘치면 문자로 내려간다.
"""

from src.knowledge.chunking.base import (
    ChunkingInput,
    ChunkingOptions,
    merge_with_overlap,
    split_oversized,
)


class ParagraphChunker:
    name = "paragraph"

    def chunk(self, source: ChunkingInput, options: ChunkingOptions) -> list[str]:
        cleaned = source.text.strip()
        if cleaned == "":
            return []
        return merge_with_overlap(split_oversized(cleaned, options.target_chars), options)
