"""토큰 단가표와 비용 계산. I/O 없는 순수 함수.

단가를 코드에 하드코딩하지 않는 이유: 자주 바뀐다(M3 입력 단가는 최근 90일간 20% 하락).
환경변수/ConfigMap에서 읽는다.

**프로바이더 응답에 비용이 담겨 와도 그 값을 쓰지 않는다.** 외부 값을 원장에 그대로
넣으면 숫자 규칙이 외부에 위임된다(§13 마지막 테스트가 이걸 지킨다).
"""

import json
from dataclasses import dataclass
from decimal import Decimal

from src.llm.exceptions import InvalidPricingTable

# 단가는 100만 토큰당 USD로 표기한다.
_TOKENS_PER_UNIT = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


def load_pricing(raw_json: str | None) -> dict[str, ModelPrice]:
    if not raw_json or not raw_json.strip():
        return {}

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise InvalidPricingTable(f"LLM_PRICING_JSON을 파싱할 수 없습니다: {exc}") from exc
    if not isinstance(parsed, dict):
        raise InvalidPricingTable("LLM_PRICING_JSON은 모델명→단가 객체여야 합니다")

    pricing: dict[str, ModelPrice] = {}
    for model, spec in parsed.items():
        try:
            # float를 거치지 않도록 문자열로 만든 뒤 Decimal에 넣는다.
            pricing[model] = ModelPrice(
                input_usd_per_million=Decimal(str(spec["in"])),
                output_usd_per_million=Decimal(str(spec["out"])),
            )
        except (KeyError, TypeError, ArithmeticError) as exc:
            raise InvalidPricingTable(f"모델 '{model}'의 단가가 올바르지 않습니다: {exc}") from exc
    return pricing


def calculate_cost_krw(
    price: ModelPrice,
    usage: TokenUsage,
    *,
    usd_krw_rate: Decimal,
) -> Decimal:
    """토큰 사용량 * 단가 → USD → KRW. 전 구간 Decimal이다.

    반올림하지 않는다. LLM 비용은 소액이 대량 누적되는 항목이라, 호출마다 원 단위로
    자르면 누적 오차가 실제 금액을 넘어선다(§8.5). 원장은 전체 정밀도로 보관하고
    표시 단계에서만 정리한다.
    """
    input_usd = Decimal(usage.input_tokens) * price.input_usd_per_million / _TOKENS_PER_UNIT
    output_usd = Decimal(usage.output_tokens) * price.output_usd_per_million / _TOKENS_PER_UNIT
    return (input_usd + output_usd) * usd_krw_rate
