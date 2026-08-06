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


# Ollama를 켜면 카탈로그에 자동으로 들어가는 프로파일 이름.
LOCAL_PROFILE_NAME = "local"


def _with_local_model(
    profiles: dict[str, LlmProfile],
    pricing: dict[str, ModelPrice],
    *,
    model: str,
) -> tuple[dict[str, LlmProfile], dict[str, ModelPrice]]:
    """Ollama가 켜져 있으면 `local` 프로파일과 단가 0을 카탈로그에 넣는다.

    왜 자동인가: 이걸 손으로 하려면 `LLM_PROFILES_JSON`에 프로파일 전체를, 동시에
    `LLM_PRICING_JSON`에 단가를 적어야 한다. 둘 중 하나만 빠지면 부팅이 거부되고,
    그 조합을 매번 직접 쓰는 건 실수하기 쉽다. `OLLAMA_ENABLED=true` 하나로 끝낸다.

    **단가 0의 의미**: 로컬 추론은 호출당 청구가 실제로 없다. 이건 "단가를 몰라서 0"이
    아니라 "0인 것을 안다"이고, 그래서 카탈로그 검증(§8.2)의 취지에 어긋나지 않는다.
    비용 기록 경로 자체는 그대로 살아 있어서 호출 횟수와 토큰 수는 남는다 —
    전기값을 계산하고 싶으면 여기 단가만 채우면 된다.

    직접 정의한 값이 있으면 건드리지 않는다. 자동 등록은 기본값 제공이지 강제가 아니다.
    """
    merged_profiles = dict(profiles)
    merged_profiles.setdefault(
        LOCAL_PROFILE_NAME,
        # max_tokens를 원격 프로파일보다 낮게 잡는다. 로컬은 토큰당 시간이 길어서
        # 8,000토큰을 허용하면 한 번의 채팅이 수 분을 잡아먹는다.
        LlmProfile(LOCAL_PROFILE_NAME, "ollama", model, 0.3, 2_000),
    )
    merged_pricing = dict(pricing)
    merged_pricing.setdefault(model, ModelPrice(Decimal("0"), Decimal("0")))
    return merged_profiles, merged_pricing


def _redirect_to_local(profiles: dict[str, LlmProfile], *, model: str) -> dict[str, LlmProfile]:
    """호출할 수 없는 프로파일을 로컬 모델로 돌린다.

    **언제 일어나나**: Ollama만 설정되어 있고 원격 프로바이더 키가 하나도 없을 때.
    이 상황에서 직원의 프로파일(`writer` 등)을 그대로 두면 모든 LLM 작업이 503으로
    실패한다 — 카탈로그에는 있지만 부를 수 없는 프로파일이기 때문이다.

    **왜 이게 마법이 아닌가**: 대안은 "아무 LLM 작업도 못 하는 상태"뿐이다. 키가 없는
    프로파일은 실행 가능한 선택지가 애초에 없고, 로컬 모델은 있다. 무엇이 바뀌었는지는
    부팅 로그에 남긴다.

    temperature와 max_tokens는 원래 프로파일 값을 유지한다. 직무마다 다른 성격
    (structured는 0, writer는 높게)은 모델이 바뀌어도 유지되어야 의미가 있다.
    """
    return {
        name: (
            profile
            if profile.provider == "ollama"
            # fallback을 지운다. 폴백 대상도 같은 로컬 모델이라 재시도가 무의미하고,
            # 느린 로컬 추론을 두 번 하게 된다.
            else LlmProfile(profile.name, "ollama", model, profile.temperature, profile.max_tokens)
        )
        for name, profile in profiles.items()
    }


def build_gateway(settings: Settings) -> LlmGateway:
    profiles = load_profiles(settings.llm_profiles_json)
    pricing = load_pricing(settings.llm_pricing_json)
    providers = build_registry(settings)

    if settings.ollama_enabled:
        profiles, pricing = _with_local_model(profiles, pricing, model=settings.ollama_model)

    configured = configured_names(providers)
    if settings.ollama_enabled and configured == {"ollama"}:
        # 로컬 모델만 있는 환경. 그대로 두면 직원 프로파일이 전부 호출 불가라
        # 모든 LLM 작업이 503으로 끝난다.
        profiles = _redirect_to_local(profiles, model=settings.ollama_model)
        logger.warning(
            "원격 프로바이더 키가 없어 모든 프로파일을 로컬 모델로 돌린다: %s "
            "(원격 모델을 쓰려면 키를 설정한다)",
            settings.ollama_model,
        )

    warnings = validate_catalog(
        profiles,
        known_providers=set(providers),
        configured_providers=configured,
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
