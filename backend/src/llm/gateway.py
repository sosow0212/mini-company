"""게이트웨이 조립. 부팅 시 한 번 만들어 app.state에 둔다.

여기 담기는 것은 전부 불변이고 설정에서 재구성 가능하므로, 프로세스 메모리에
두어도 ADR-008(복구 불가능한 상태 금지)에 걸리지 않는다.

카탈로그 검증이 이 시점에 일어난다 — 실패하면 앱이 뜨지 않는다. 런타임 첫 호출에서
발견되면 이미 늦다(§8.2).
"""

import logging
from dataclasses import dataclass
from decimal import Decimal

from src.config import Settings
from src.llm.pricing import ModelPrice, load_pricing
from src.llm.profiles import LlmProfile, load_profiles, validate_catalog
from src.llm.providers.base import LlmProvider
from src.llm.providers.registry import build_registry, configured_names

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmGateway:
    profiles: dict[str, LlmProfile]
    pricing: dict[str, ModelPrice]
    providers: dict[str, LlmProvider]
    usd_krw_rate: Decimal
    daily_cost_limit_krw: Decimal


def build_gateway(settings: Settings) -> LlmGateway:
    profiles = load_profiles(settings.llm_profiles_json)
    pricing = load_pricing(settings.llm_pricing_json)
    providers = build_registry(settings)

    warnings = validate_catalog(
        profiles,
        known_providers=set(providers),
        configured_providers=configured_names(providers),
        priced_models=set(pricing),
        # 로컬에서는 키 없이도 앱이 떠야 한다(프론트·원장 작업 중에는 LLM이 필요 없다).
        # 그 외 환경에서는 키 누락이 곧 부팅 실패다.
        strict_keys=settings.app_env != "local",
    )
    for warning in warnings:
        logger.warning("LLM 카탈로그: %s", warning)

    return LlmGateway(
        profiles=profiles,
        pricing=pricing,
        providers=providers,
        usd_krw_rate=settings.usd_krw_rate,
        daily_cost_limit_krw=settings.llm_daily_cost_limit_krw,
    )
