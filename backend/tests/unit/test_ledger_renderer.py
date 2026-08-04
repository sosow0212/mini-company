"""렌더러는 순수 함수다. mock 0개.

블루프린트 §13이 이름으로 지정한 필수 테스트 두 개가 여기 있다:
renderer_raises_when_placeholder_is_unknown / renderer_raises_when_unsubstituted_placeholder_remains
"""

import pytest

from src.ledger.exceptions import PlaceholderNotSubstituted, UnknownPlaceholder
from src.ledger.renderer import render

_VALUES = {
    "ledger.revenue.monthly": "82860000",
    "ledger.net.monthly": "-1240000",
}


def test_renderer_substitutes_known_placeholders() -> None:
    rendered = render(
        "이번 달 매출은 {{ledger.revenue.monthly}}원, 순손익은 {{ledger.net.monthly}}원입니다.",
        _VALUES,
    )

    assert rendered == "이번 달 매출은 82860000원, 순손익은 -1240000원입니다."


def test_renderer_raises_when_placeholder_is_unknown() -> None:
    with pytest.raises(UnknownPlaceholder):
        render("매출은 {{ledger.revenue.weekly}}원입니다.", _VALUES)


def test_renderer_raises_when_unsubstituted_placeholder_remains() -> None:
    """공백이 섞인 변형은 일부러 매칭시키지 않는다 — 표기가 흔들리면 발행을 멈춘다."""
    with pytest.raises(PlaceholderNotSubstituted):
        render("매출은 {{ ledger.revenue.monthly }}원입니다.", _VALUES)


def test_renderer_raises_when_placeholder_uses_uppercase() -> None:
    with pytest.raises(PlaceholderNotSubstituted):
        render("매출은 {{Ledger.Revenue.Monthly}}원입니다.", _VALUES)


def test_renderer_passes_through_text_without_placeholders() -> None:
    assert render("수집을 마쳤습니다.", _VALUES) == "수집을 마쳤습니다."


def test_renderer_reports_the_offending_key_in_message() -> None:
    with pytest.raises(UnknownPlaceholder) as raised:
        render("{{ledger.unknown.monthly}}", _VALUES)

    assert "ledger.unknown.monthly" in raised.value.message
