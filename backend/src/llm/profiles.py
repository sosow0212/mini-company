"""프로파일 카탈로그. I/O 없는 순수 로직.

3계층 분리(§8.1)의 가운데 층이다:
  API 키          → 환경변수(K8s Secret)
  **카탈로그**    → 코드 + LLM_PROFILES_JSON 오버라이드(K8s ConfigMap)  ← 이 파일
  직원별 선택     → MongoDB(`Employee.llm_profile`)

직원은 프로파일 **이름만** 참조한다. `Employee`에 모델명을 저장하면 모델을 교체할 때
마이그레이션이 필요하고, 존재하지 않는 모델명이 DB에 남는다.
"""

import json
from dataclasses import dataclass

from src.llm.exceptions import InvalidProfileCatalog


@dataclass(frozen=True)
class LlmProfile:
    name: str
    provider: str
    model: str
    temperature: float
    max_tokens: int
    # 실패 시 넘어갈 프로파일 이름. 1홉만 허용한다(연쇄 폴백은 지연을 예측 불가하게 만든다).
    fallback: str | None = None


# 기본 카탈로그는 MiniMax만 둔다. anthropic을 섞으면 ANTHROPIC_API_KEY 없이는
# 부팅 검증이 실패해 로컬 개발이 막힌다. coder 프로파일이 필요하면
# LLM_PROFILES_JSON으로 추가한다(.env.example에 예시 있음).
DEFAULT_PROFILES: dict[str, LlmProfile] = {
    # 저가 기본값. 분류·판정·짧은 요약 등 중간 산출물 전담.
    "cheap": LlmProfile("cheap", "minimax", "MiniMax-M2.7", 0.2, 1_500),
    # 구조화 출력 전용. temperature 0 고정.
    "structured": LlmProfile("structured", "minimax", "MiniMax-M2.7", 0.0, 2_000),
    # 사람에게 그대로 노출되는 문장. 여기서 아끼면 결과물 품질이 바로 떨어진다(§8.3).
    "writer": LlmProfile("writer", "minimax", "MiniMax-M3", 0.8, 4_000, fallback="cheap"),
    # 긴 컨텍스트 분석·도구 사용.
    "reasoner": LlmProfile("reasoner", "minimax", "MiniMax-M3", 0.3, 8_000, fallback="cheap"),
}


def load_profiles(raw_json: str | None) -> dict[str, LlmProfile]:
    """LLM_PROFILES_JSON이 비어 있으면 코드의 기본 카탈로그를 쓴다."""
    if not raw_json or not raw_json.strip():
        return dict(DEFAULT_PROFILES)

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise InvalidProfileCatalog(f"LLM_PROFILES_JSON을 파싱할 수 없습니다: {exc}") from exc
    if not isinstance(parsed, dict):
        raise InvalidProfileCatalog("LLM_PROFILES_JSON은 이름→프로파일 객체여야 합니다")

    profiles: dict[str, LlmProfile] = {}
    for name, spec in parsed.items():
        try:
            profiles[name] = LlmProfile(
                name=name,
                provider=spec["provider"],
                model=spec["model"],
                temperature=float(spec.get("temperature", 0.2)),
                max_tokens=int(spec.get("maxTokens", spec.get("max_tokens", 1_500))),
                fallback=spec.get("fallback"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidProfileCatalog(f"프로파일 '{name}'이 올바르지 않습니다: {exc}") from exc
    return profiles


def validate_catalog(
    profiles: dict[str, LlmProfile],
    *,
    known_providers: set[str],
    configured_providers: set[str],
    priced_models: set[str],
    strict_keys: bool,
) -> list[str]:
    """부팅 시점에 카탈로그를 검증한다. 런타임 첫 호출에서 발견되면 이미 늦다(§8.2).

    반환값은 경고 목록이다. 치명적 문제는 예외로 던져 앱을 띄우지 않는다.

    `strict_keys=False`(로컬)에서는 키 누락을 경고로만 남긴다 — LLM이 필요 없는
    프론트·원장 작업 중에 앱이 아예 뜨지 않으면 개발이 막힌다. 대신 키가 있는
    프로파일은 어느 환경에서든 완전히 검증한다("호출 가능한 것만 엄격하게").
    """
    if not profiles:
        raise InvalidProfileCatalog("프로파일 카탈로그가 비어 있습니다")

    warnings: list[str] = []
    for profile in profiles.values():
        if profile.provider not in known_providers:
            raise InvalidProfileCatalog(
                f"프로파일 '{profile.name}'이 알 수 없는 프로바이더 "
                f"'{profile.provider}'를 참조합니다"
            )
        _validate_fallback(profile, profiles)

        if profile.provider not in configured_providers:
            message = f"프로파일 '{profile.name}'의 프로바이더 '{profile.provider}' 키가 없습니다"
            if strict_keys:
                raise InvalidProfileCatalog(message)
            warnings.append(f"{message} — 이 프로파일은 호출할 수 없습니다")
            # 키가 없으면 호출 자체가 불가하므로 단가 검증은 의미가 없다.
            continue

        if profile.model not in priced_models:
            # 단가를 모르면 비용을 0으로 기록하게 되고, 그건 숫자 규칙 위반이다(§15-3).
            raise InvalidProfileCatalog(
                f"프로파일 '{profile.name}'의 모델 '{profile.model}'에 단가가 없습니다"
            )
    return warnings


def _validate_fallback(profile: LlmProfile, profiles: dict[str, LlmProfile]) -> None:
    if profile.fallback is None:
        return
    if profile.fallback not in profiles:
        raise InvalidProfileCatalog(
            f"프로파일 '{profile.name}'의 fallback '{profile.fallback}'이 카탈로그에 없습니다"
        )
    if profile.fallback == profile.name:
        raise InvalidProfileCatalog(f"프로파일 '{profile.name}'의 fallback이 자기 자신입니다")
    # 1홉만 허용하므로 폴백 대상은 폴백을 가질 수 없다. 이 규칙이 순환도 함께 막는다.
    if profiles[profile.fallback].fallback is not None:
        raise InvalidProfileCatalog(
            f"fallback은 1홉만 허용합니다: '{profile.name}' → '{profile.fallback}' → "
            f"'{profiles[profile.fallback].fallback}'"
        )
