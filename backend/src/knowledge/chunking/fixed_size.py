"""고정 크기 청킹 — "500자씩 자른다".

경계를 전혀 존중하지 않는다. 문단·문장 중간에서 잘리므로 산문에는 나쁜 선택이지만,
**구조가 없는 텍스트**에는 이게 맞다: 표를 덤프한 데이터, 로그, 줄바꿈 없이 이어진
스크래핑 결과. 그런 입력에서 문단 전략은 "문단이 하나"라고 판단해 거대한 조각을 만든다.

청크 크기가 균일해서 임베딩 비용과 검색 지연이 예측 가능하다는 것도 실질적인 장점이다.
"""

from src.knowledge.chunking.base import ChunkingInput, ChunkingOptions


class FixedSizeChunker:
    name = "fixed_size"

    def chunk(self, source: ChunkingInput, options: ChunkingOptions) -> list[str]:
        cleaned = source.text.strip()
        if cleaned == "":
            return []

        # 겹침만큼 되돌아가며 창을 옮긴다. step이 0 이하면 무한 루프가 되므로 옵션 검증
        # (overlap < target)에 의존한다 — ChunkingOptions.from_tokens가 보장한다.
        step = options.target_chars - options.overlap_chars
        chunks: list[str] = []
        start = 0
        while start < len(cleaned):
            chunks.append(cleaned[start : start + options.target_chars])
            start += step
            # 남은 꼬리가 겹침 안에 다 들어가면 새 정보가 없다. 그대로 두면 앞 청크의
            # 복사본 같은 짧은 조각이 생겨 임베딩을 낭비하고 검색에도 잡힌다.
            if 0 < len(cleaned) - start <= options.overlap_chars:
                break
        return chunks
