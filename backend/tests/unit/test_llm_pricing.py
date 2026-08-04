"""단가표와 비용 계산. 순수 함수라 mock 0개.

LLM 비용은 소액이 대량 누적되는 항목이라 Decimal 정밀도가 실제로 문제가 된다(§8.5).
"""

from decimal import Decimal

import pytest

from src.llm.exceptions import InvalidPricingTable
from src.llm.pricing import ModelPrice, TokenUsage, calculate_cost_krw, load_pricing

_RATE = Decimal("1380")
# 1M 토큰당 입력 $0.30 / 출력 $1.20
_PRICE = ModelPrice(
    input_usd_per_million=Decimal("0.30"),
    output_usd_per_million=Decimal("1.20"),
)


def test_load_pricing_returns_empty_when_json_is_blank() -> None:
    assert load_pricing(None) == {}
    assert load_pricing("   ") == {}


def test_load_pricing_parses_models() -> None:
    pricing = load_pricing('{"MiniMax-M3": {"in": 0.30, "out": 1.20}}')

    assert pricing["MiniMax-M3"].input_usd_per_million == Decimal("0.30")
    assert pricing["MiniMax-M3"].output_usd_per_million == Decimal("1.20")


def test_load_pricing_avoids_float_error_by_going_through_string() -> None:
    """JSON number를 float로 받아 Decimal(float)로 만들면 0.1이 0.1000000000000000055가 된다."""
    pricing = load_pricing('{"m": {"in": 0.1, "out": 0.3}}')

    assert pricing["m"].input_usd_per_million == Decimal("0.1")
    assert pricing["m"].output_usd_per_million == Decimal("0.3")


def test_load_pricing_raises_when_json_is_malformed() -> None:
    with pytest.raises(InvalidPricingTable):
        load_pricing("{not json")


def test_load_pricing_raises_when_model_lacks_output_price() -> None:
    with pytest.raises(InvalidPricingTable):
        load_pricing('{"m": {"in": 0.3}}')


def test_calculate_cost_multiplies_tokens_by_price_and_exchange_rate() -> None:
    # 입력 1M * $0.30 = $0.30, 출력 1M * $1.20 = $1.20 → $1.50 * 1380 = 2070 KRW
    cost = calculate_cost_krw(
        _PRICE,
        TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000),
        usd_krw_rate=_RATE,
    )

    assert cost == Decimal("2070.00")


def test_calculate_cost_keeps_precision_for_small_token_counts() -> None:
    """1820/640 토큰이면 원 단위 미만이다. 반올림하면 누적 오차가 실제 금액을 넘는다."""
    cost = calculate_cost_krw(
        _PRICE,
        TokenUsage(input_tokens=1_820, output_tokens=640),
        usd_krw_rate=_RATE,
    )

    # (1820*0.30 + 640*1.20) / 1e6 * 1380 = (546 + 768) / 1e6 * 1380
    expected = (Decimal("546") + Decimal("768")) / Decimal(1_000_000) * _RATE
    assert cost == expected
    assert cost > 0, "소액이라도 0으로 떨어지면 원장에서 비용이 사라진다"


def test_calculate_cost_is_zero_when_no_tokens_are_used() -> None:
    cost = calculate_cost_krw(
        _PRICE, TokenUsage(input_tokens=0, output_tokens=0), usd_krw_rate=_RATE
    )

    assert cost == 0


def test_output_tokens_dominate_cost_at_the_same_count() -> None:
    """출력 단가가 입력의 4배이므로 생성량이 많은 작업이 비용을 지배한다(§8.4)."""
    input_heavy = calculate_cost_krw(
        _PRICE, TokenUsage(input_tokens=1_000, output_tokens=0), usd_krw_rate=_RATE
    )
    output_heavy = calculate_cost_krw(
        _PRICE, TokenUsage(input_tokens=0, output_tokens=1_000), usd_krw_rate=_RATE
    )

    assert output_heavy == input_heavy * 4
