"""금액 문자열 표현. 순수 함수라 mock 0개.

이 함수가 프론트로 나가는 모든 집계 숫자의 유일한 표현 경로다. 여기서 같은 값이
다른 문자열이 되면 화면 값이 이력에 따라 흔들린다(ADR-006: 프론트는 렌더링만 한다).
"""

from decimal import Decimal

import pytest

from src.ledger.schemas import normalized_amount


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        # 역분개 합산이 남기는 scale. Decimal("0.00")과 Decimal("0")은 같은 값이므로
        # 같은 문자열이어야 한다 — 실제 Mongo $sum은 전자를, fake는 후자를 만든다.
        (Decimal("0.00"), "0"),
        (Decimal("0"), "0"),
        (Decimal("-0.00"), "-0"),
        # normalize()만 쓰면 8.286E+7이 된다. 지수 표기가 화면에 나가면 안 된다.
        (Decimal("82860000.00"), "82860000"),
        (Decimal("82860000"), "82860000"),
        # 유효 소수는 유지한다. LLM 비용은 원 단위 미만 소액이 누적된다(§8.5).
        (Decimal("0.30"), "0.3"),
        (Decimal("0.3"), "0.3"),
        (Decimal("82860000.55"), "82860000.55"),
        (Decimal("-1240000"), "-1240000"),
        (Decimal("0.0000001"), "0.0000001"),
    ],
)
def test_normalized_amount_maps_equal_values_to_one_string(amount: Decimal, expected: str) -> None:
    assert normalized_amount(amount) == expected


def test_normalized_amount_never_uses_scientific_notation() -> None:
    for exponent in range(0, 12):
        rendered = normalized_amount(Decimal(10) ** exponent)
        assert "E" not in rendered and "e" not in rendered


def test_equal_amounts_with_different_scales_render_identically() -> None:
    """fake(순수 Decimal)와 실제 Mongo($sum)가 만드는 scale이 달라도 표시는 같아야 한다."""
    assert normalized_amount(Decimal("3000")) == normalized_amount(Decimal("3000.00"))
