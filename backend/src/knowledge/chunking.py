"""청킹. I/O 없는 순수 함수.

**문단 경계를 1순위로 지킨다.** 문장 중간에서 자르면 그 조각만 읽었을 때 뜻이 달라지고,
검색이 맞춰도 인용문이 이상해진다. 문단이 너무 길면 문장 → 마지막 수단으로 문자.

토큰 수는 문자 수로 근사한다. tiktoken을 쓰지 않는 이유: 모델마다 다른 토크나이저를
끌어오는 비용이 크고, 청크 크기는 정확할 필요가 없다(검색 품질에 ±20%는 영향이 미미하다).
한글은 토큰당 문자가 영문보다 적어 보수적인 계수를 쓴다.
"""

import re

# 한글 기준 1토큰 ≈ 1.6자. 영문 위주 문서에서는 청크가 작아지는데, 작은 쪽이 안전하다
# (임베딩 모델의 입력 한계를 넘기지 않는다).
CHARS_PER_TOKEN = 1.6

_PARAGRAPH = re.compile(r"\n\s*\n")
# 전각 종결부호(U+FF1F, U+FF01, U+3002)를 의도적으로 포함한다 — 한국어·일본어 문서에서
# 실제로 쓰이고, 빼면 그 문서의 문장 경계를 못 찾는다.
_SENTENCE = re.compile("(?<=[.!?。？！])\\s+|(?<=다\\.)\\s+")


def split_into_chunks(text: str, *, target_tokens: int, overlap_tokens: int) -> list[str]:
    """[start, end) 조각 목록. 인접 조각은 overlap만큼 겹친다.

    겹치는 이유: 답이 경계에 걸쳐 있으면 어느 조각도 온전한 문맥을 갖지 못한다.
    """
    if target_tokens <= 0:
        raise ValueError("target_tokens는 1 이상이어야 한다")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens는 0 이상이고 target_tokens보다 작아야 한다")

    cleaned = text.strip()
    if cleaned == "":
        return []

    target = int(target_tokens * CHARS_PER_TOKEN)
    overlap = int(overlap_tokens * CHARS_PER_TOKEN)

    chunks: list[str] = []
    for block in _split_to_fitting_blocks(cleaned, target):
        _append_with_overlap(chunks, block, target=target, overlap=overlap)
    return chunks


def _split_to_fitting_blocks(text: str, target: int) -> list[str]:
    """문단 → (필요 시) 문장 → (필요 시) 문자 순으로 target 이하 조각을 만든다."""
    blocks: list[str] = []
    for paragraph in (item.strip() for item in _PARAGRAPH.split(text)):
        if paragraph == "":
            continue
        if len(paragraph) <= target:
            blocks.append(paragraph)
            continue
        blocks.extend(_split_long_paragraph(paragraph, target))
    return blocks


def _split_long_paragraph(paragraph: str, target: int) -> list[str]:
    blocks: list[str] = []
    buffer = ""
    for sentence in (item.strip() for item in _SENTENCE.split(paragraph)):
        if sentence == "":
            continue
        if len(sentence) > target:
            # 문장 하나가 target을 넘으면 문자로 자를 수밖에 없다(URL 나열, 표 등).
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


def _append_with_overlap(chunks: list[str], block: str, *, target: int, overlap: int) -> None:
    """앞 조각과 합쳐 target 이하이면 합치고, 아니면 겹침을 붙여 새 조각을 만든다."""
    if chunks:
        merged = f"{chunks[-1]}\n\n{block}"
        if len(merged) <= target:
            chunks[-1] = merged
            return

    if chunks and overlap > 0:
        tail = chunks[-1][-overlap:]
        # 겹침이 조각 하나를 통째로 복제하지 않도록 앞 조각보다 짧을 때만 붙인다.
        if len(tail) < len(chunks[-1]):
            chunks.append(f"{tail}\n\n{block}")
            return
    chunks.append(block)
