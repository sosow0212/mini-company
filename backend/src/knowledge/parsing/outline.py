"""제목 목록 → 절 구조.

HTML과 Markdown이 제목을 표현하는 방법은 다르지만(`<h2>` vs `## `), 일단 (레벨, 제목,
본문) 목록으로 만들면 그다음 처리는 같다. 그 공통 부분을 여기 둔다.

상위 제목 경로(`path`)를 계산하는 게 이 모듈의 본론이다. 레벨이 내려가면 스택에 쌓고,
같거나 올라가면 그만큼 걷어낸다 — 목차 번호를 매기는 것과 같은 규칙이다.
"""

from dataclasses import dataclass

from src.knowledge.chunking.base import Section


@dataclass(frozen=True)
class RawHeading:
    """파서가 찾아낸 제목 1건과 그 뒤에 따라오는 본문."""

    level: int
    heading: str
    text: str


def build_outline(headings: list[RawHeading], *, preamble: str = "") -> tuple[Section, ...]:
    """제목 목록에 상위 경로를 채워 절 구조로 만든다.

    `preamble`은 첫 제목보다 앞에 있는 본문이다. 버리면 문서 도입부가 인덱싱에서
    사라지므로, 제목 없는 절(level 0)로 남긴다.
    """
    sections: list[Section] = []
    if preamble.strip() != "":
        sections.append(Section(level=0, heading="", text=preamble.strip()))

    # (레벨, 제목) 스택. 현재 절보다 상위인 제목만 남긴다.
    trail: list[tuple[int, str]] = []
    for item in headings:
        while trail and trail[-1][0] >= item.level:
            trail.pop()
        sections.append(
            Section(
                level=item.level,
                heading=item.heading.strip(),
                text=item.text.strip(),
                path=tuple(label for _, label in trail),
            )
        )
        trail.append((item.level, item.heading.strip()))
    return tuple(sections)
