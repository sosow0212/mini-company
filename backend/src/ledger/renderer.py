"""요약문 플레이스홀더 치환. I/O 없는 순수 함수.

LLM은 `{{ledger.revenue.monthly}}`처럼 자리만 남기고, 실제 수치는 서버가 이 함수로
채운다(ADR-002). 알 수 없는 자리표시자나 치환되지 않은 `{{`가 남으면 예외를 던져
발행을 중단한다 — 조용히 통과시키면 규칙이 없는 것과 같다(블루프린트 §7.3).
"""

import re
from collections.abc import Mapping

from src.ledger.exceptions import PlaceholderNotSubstituted, UnknownPlaceholder

# 공백을 허용하지 않는다. `{{ ledger.x }}` 같은 변형은 일부러 매칭시키지 않고
# 아래 잔여 `{{` 검사에서 걸리게 해, 표기가 흔들리면 발행이 멈추도록 한다.
_PLACEHOLDER = re.compile(r"\{\{([a-z0-9_.]+)\}\}")
_LEFTOVER = "{{"


def render(template: str, values: Mapping[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise UnknownPlaceholder(key)
        return values[key]

    rendered = _PLACEHOLDER.sub(substitute, template)
    if _LEFTOVER in rendered:
        raise PlaceholderNotSubstituted
    return rendered
