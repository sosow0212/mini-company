"""원장 요약 툴.

**항상 주입한다.** 블루프린트 §11.2는 "숫자 질문 감지 시" 호출하라고 하지만, 감지를
키워드로 하면 오탐·미탐이 둘 다 생기고 미탐이 특히 나쁘다(모델이 숫자를 지어낸다).
요약은 열 줄이 안 되므로 항상 넣는 비용이 감지 실패 위험보다 싸다.

또 하나: 답변에 등장한 숫자가 이 표에 없으면 경고를 남긴다. tasks·ledger가 쓰는
`\\d{3,}` 방어선과 같은 성격이고, 하드 차단은 오탐이 많아 경고로 둔다(§7.3).
"""

import logging
import re

from src.ledger.constants import LedgerCategory
from src.ledger.schemas import LedgerSummaryResponse

logger = logging.getLogger(__name__)

_INLINE_NUMBER = re.compile(r"\d[\d,]{2,}")
_UNIT_BY_CATEGORY: dict[LedgerCategory, str] = {
    LedgerCategory.REVENUE: "KRW",
    LedgerCategory.COST: "KRW",
    LedgerCategory.LLM_COST: "KRW",
    LedgerCategory.VIEWS: "회",
    LedgerCategory.SUBSCRIBERS: "명",
}


def render_ledger_table(summary: LedgerSummaryResponse) -> str:
    """서버가 aggregate한 값을 그대로 표로 만든다. 여기서 계산하지 않는다."""
    rows = "\n".join(_render_row(summary, category) for category in LedgerCategory)
    return f"[원장 요약] (기간: {summary.period.value})\n{rows}\n- 순손익: {summary.net} KRW"


def _render_row(summary: LedgerSummaryResponse, category: LedgerCategory) -> str:
    amount = summary.totals.get(category, "0")
    unit = _UNIT_BY_CATEGORY.get(category, "")
    return f"- {category.value}: {amount} {unit}".rstrip()


def allowed_numbers(summary: LedgerSummaryResponse, context: str) -> set[str]:
    """답변에 쓰여도 되는 숫자. 원장 값과 컨텍스트에 등장한 숫자의 합집합이다."""
    allowed = {_digits(value) for value in summary.totals.values()}
    allowed.add(_digits(summary.net))
    allowed.update(_digits(match) for match in _INLINE_NUMBER.findall(context))
    return {item for item in allowed if item != ""}


def warn_on_invented_numbers(answer: str, allowed: set[str]) -> list[str]:
    """근거 없이 등장한 숫자를 찾아 경고 목록으로 돌려준다.

    반환값을 로그로만 쓰는 이유: 하드 차단은 오탐이 많다("2026년", "3가지" 같은 표현이
    잡힌다). 조용히 넘기지 않고 흔적을 남기는 것이 목적이다.
    """
    invented = sorted(
        {match for match in _INLINE_NUMBER.findall(answer) if _digits(match) not in allowed}
    )
    if invented:
        logger.warning("답변에 근거 없는 숫자가 있다: %s", invented)
    return invented


def _digits(value: str) -> str:
    """콤마·부호·소수점을 지우고 자릿수만 비교한다.

    LLM이 `82860000`을 `82,860,000`으로 다시 쓰는 것은 허용해야 하고(포맷팅은 표기),
    `82860001`로 바꾸는 것은 잡아야 한다.
    """
    return re.sub(r"[^\d]", "", value)
