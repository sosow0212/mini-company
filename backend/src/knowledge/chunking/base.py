"""청킹 전략 경계.

전략을 여러 개 두는 이유: 문서 종류마다 "의미 있는 조각"의 기준이 다르다.
목차가 있는 기술 문서는 절 단위로 잘라야 한 청크가 하나의 주제를 담고, 표·로그처럼
구조가 없는 텍스트는 고정 크기로 자르는 게 낫다. 하나로 통일하면 어느 쪽이든 나빠진다.

새 전략을 추가하려면 이 Protocol만 구현하고 `registry.py`에 등록한다.
`service.py`는 어떤 전략이 쓰였는지 모르고, 그래서 전략이 늘어도 수정되지 않는다.
"""

import re
from dataclasses import dataclass
from typing import Protocol

# 한글 기준 1토큰 ≈ 1.6자. tiktoken을 쓰지 않는 이유: 모델마다 다른 토크나이저를
# 끌어오는 비용이 크고, 청크 크기는 정확할 필요가 없다(±20%는 검색 품질에 미미하다).
# 한글은 토큰당 문자가 영문보다 적어 보수적인 계수를 쓴다 — 작은 쪽이 안전하다
# (임베딩 모델의 입력 한계를 넘기지 않는다).
CHARS_PER_TOKEN = 1.6

PARAGRAPH_PATTERN = re.compile(r"\n\s*\n")
# 전각 종결부호(U+FF1F, U+FF01, U+3002)를 의도적으로 포함한다 — 한국어·일본어 문서에서
# 실제로 쓰이고, 빼면 그 문서의 문장 경계를 못 찾는다.
SENTENCE_PATTERN = re.compile("(?<=[.!?。？！])\\s+|(?<=다\\.)\\s+")


@dataclass(frozen=True)
class Section:
    """문서의 한 절. 파서가 구조를 보고 채운다.

    이게 없으면 목차 청킹이 불가능하다 — HTML의 `<h2>`나 Markdown의 `## `를 파싱 단계에서
    지워버리면 텍스트만 보고 절 경계를 되찾을 방법이 없다.
    """

    level: int
    heading: str
    text: str
    # 상위 제목 경로(["1장", "1.2절"]). 청크 앞에 붙여 조각만 봐도 문맥을 알 수 있게 한다.
    path: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChunkingOptions:
    """크기 기준은 **문자**다.

    설정은 토큰으로 받지만(블루프린트 §15의 `CHUNK_TARGET_TOKENS`) 여기서는 문자로
    환산해 넘긴다 — 토큰은 애초에 근사치이고, 전략마다 다시 환산하면 계수가 갈라진다.
    """

    target_chars: int
    overlap_chars: int

    @classmethod
    def from_tokens(cls, *, target_tokens: int, overlap_tokens: int) -> "ChunkingOptions":
        if target_tokens <= 0:
            raise ValueError("target_tokens는 1 이상이어야 한다")
        if overlap_tokens < 0 or overlap_tokens >= target_tokens:
            raise ValueError("overlap_tokens는 0 이상이고 target_tokens보다 작아야 한다")
        return cls(
            target_chars=int(target_tokens * CHARS_PER_TOKEN),
            overlap_chars=int(overlap_tokens * CHARS_PER_TOKEN),
        )


@dataclass(frozen=True)
class ChunkingInput:
    """청커 입력.

    `outline`이 비어 있으면 구조를 알 수 없는 문서다(줄글·PDF). 목차 전략은 그때
    문단 전략으로 스스로 폴백한다 — 호출자가 포맷을 판단하지 않아도 되게.
    """

    text: str
    outline: tuple[Section, ...] = ()


class ChunkingStrategy(Protocol):
    name: str

    def chunk(self, source: ChunkingInput, options: ChunkingOptions) -> list[str]:
        """빈 입력에는 빈 목록을 돌려준다. 예외를 던지지 않는다."""
        ...


def split_oversized(text: str, target: int) -> list[str]:
    """target을 넘는 텍스트를 문단 → 문장 → 문자 순으로 쪼갠다.

    문장 중간에서 자르면 그 조각만 읽었을 때 뜻이 달라지고, 검색이 맞춰도 인용문이
    이상해진다. 그래서 문자 분할은 마지막 수단이다(URL 나열, 표 등).
    """
    blocks: list[str] = []
    for paragraph in (item.strip() for item in PARAGRAPH_PATTERN.split(text)):
        if paragraph == "":
            continue
        if len(paragraph) <= target:
            blocks.append(paragraph)
            continue
        blocks.extend(_split_paragraph(paragraph, target))
    return blocks


def _split_paragraph(paragraph: str, target: int) -> list[str]:
    blocks: list[str] = []
    buffer = ""
    for sentence in (item.strip() for item in SENTENCE_PATTERN.split(paragraph)):
        if sentence == "":
            continue
        if len(sentence) > target:
            if buffer != "":
                blocks.append(buffer)
                buffer = ""
            blocks.extend(
                sentence[index : index + target] for index in range(0, len(sentence), target)
            )
            continue
        candidate = f"{buffer} {sentence}".strip()
        if len(candidate) <= target:
            buffer = candidate
        else:
            blocks.append(buffer)
            buffer = sentence
    if buffer != "":
        blocks.append(buffer)
    return blocks


def merge_with_overlap(blocks: list[str], options: ChunkingOptions) -> list[str]:
    """작은 조각을 target까지 합치고, 새 조각에는 앞 조각의 꼬리를 겹쳐 붙인다.

    겹치는 이유: 답이 경계에 걸쳐 있으면 어느 조각도 온전한 문맥을 갖지 못한다.
    """
    chunks: list[str] = []
    for block in blocks:
        if chunks:
            merged = f"{chunks[-1]}\n\n{block}"
            if len(merged) <= options.target_chars:
                chunks[-1] = merged
                continue

        if chunks and options.overlap_chars > 0:
            tail = chunks[-1][-options.overlap_chars :]
            # 겹침이 앞 조각을 통째로 복제하지 않을 때만 붙인다.
            if len(tail) < len(chunks[-1]):
                chunks.append(f"{tail}\n\n{block}")
                continue
        chunks.append(block)
    return chunks
