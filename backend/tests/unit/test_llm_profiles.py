"""프로파일 카탈로그 로딩과 검증. 순수 로직이라 mock 0개."""

import pytest

from src.llm.exceptions import InvalidProfileCatalog
from src.llm.profiles import DEFAULT_PROFILES, LlmProfile, load_profiles, validate_catalog

_KNOWN = {"minimax", "anthropic"}


def _validate(profiles: dict[str, LlmProfile], **overrides) -> list[str]:
    kwargs = {
        "known_providers": _KNOWN,
        "configured_providers": _KNOWN,
        "priced_models": {p.model for p in profiles.values()},
        "strict_keys": True,
    }
    kwargs.update(overrides)
    return validate_catalog(profiles, **kwargs)


def _profile(name: str, **overrides) -> LlmProfile:
    defaults = {
        "provider": "minimax",
        "model": "MiniMax-M2.7",
        "temperature": 0.2,
        "max_tokens": 1_000,
    }
    defaults.update(overrides)
    return LlmProfile(name=name, **defaults)


# ─── 로딩 ──────────────────────────────────────────────────────


def test_load_profiles_uses_defaults_when_json_is_blank() -> None:
    assert load_profiles(None) == DEFAULT_PROFILES
    assert load_profiles("  ") == DEFAULT_PROFILES


def test_load_profiles_overrides_catalog_entirely() -> None:
    profiles = load_profiles(
        '{"only": {"provider": "minimax", "model": "M", "temperature": 0.5, "maxTokens": 10}}'
    )

    assert set(profiles) == {"only"}
    assert profiles["only"].max_tokens == 10
    assert profiles["only"].temperature == 0.5


def test_load_profiles_accepts_snake_case_max_tokens() -> None:
    profiles = load_profiles('{"p": {"provider": "minimax", "model": "M", "max_tokens": 7}}')

    assert profiles["p"].max_tokens == 7


def test_load_profiles_raises_when_json_is_malformed() -> None:
    with pytest.raises(InvalidProfileCatalog):
        load_profiles("{nope")


def test_load_profiles_raises_when_provider_is_missing() -> None:
    with pytest.raises(InvalidProfileCatalog):
        load_profiles('{"p": {"model": "M"}}')


# ─── 검증 ──────────────────────────────────────────────────────


def test_default_catalog_passes_validation() -> None:
    assert _validate(dict(DEFAULT_PROFILES)) == []


def test_validate_raises_when_catalog_is_empty() -> None:
    with pytest.raises(InvalidProfileCatalog):
        _validate({})


def test_app_fails_to_start_when_profile_references_unknown_provider() -> None:
    """블루프린트 §13 필수 테스트."""
    profiles = {"p": _profile("p", provider="nonexistent")}

    with pytest.raises(InvalidProfileCatalog, match="알 수 없는 프로바이더"):
        _validate(profiles)


def test_app_fails_to_start_when_provider_key_is_missing() -> None:
    """블루프린트 §13 필수 테스트. strict_keys(= local이 아닌 환경)에서 부팅을 거부한다."""
    profiles = {"p": _profile("p")}

    with pytest.raises(InvalidProfileCatalog, match="키가 없습니다"):
        _validate(profiles, configured_providers=set())


def test_missing_key_is_only_a_warning_when_strict_keys_is_off() -> None:
    """로컬에서는 LLM 키 없이도 앱이 떠야 한다 — 프론트·원장 작업이 막히면 안 된다."""
    profiles = {"p": _profile("p")}

    warnings = _validate(profiles, configured_providers=set(), strict_keys=False)

    assert len(warnings) == 1
    assert "호출할 수 없습니다" in warnings[0]


def test_validate_raises_when_model_has_no_price() -> None:
    """단가를 모르면 비용이 0으로 기록되고, 그건 숫자 규칙 위반이다(§15-3)."""
    profiles = {"p": _profile("p")}

    with pytest.raises(InvalidProfileCatalog, match="단가가 없습니다"):
        _validate(profiles, priced_models=set())


def test_price_is_not_required_for_profiles_that_cannot_be_called() -> None:
    """키가 없으면 호출 자체가 불가하므로 단가 검증은 의미가 없다."""
    profiles = {"p": _profile("p")}

    warnings = _validate(
        profiles, configured_providers=set(), priced_models=set(), strict_keys=False
    )

    assert len(warnings) == 1


def test_validate_raises_when_fallback_is_unknown() -> None:
    profiles = {"p": _profile("p", fallback="ghost")}

    with pytest.raises(InvalidProfileCatalog, match="카탈로그에 없습니다"):
        _validate(profiles)


def test_validate_raises_when_fallback_points_to_itself() -> None:
    profiles = {"p": _profile("p", fallback="p")}

    with pytest.raises(InvalidProfileCatalog, match="자기 자신"):
        _validate(profiles)


def test_validate_raises_when_fallback_chain_exceeds_one_hop() -> None:
    """1홉 제한이 순환 참조도 함께 막는다."""
    profiles = {
        "a": _profile("a", fallback="b"),
        "b": _profile("b", fallback="c"),
        "c": _profile("c"),
    }

    with pytest.raises(InvalidProfileCatalog, match="1홉만"):
        _validate(profiles)


def test_validate_raises_when_fallback_forms_a_cycle() -> None:
    profiles = {
        "a": _profile("a", fallback="b"),
        "b": _profile("b", fallback="a"),
    }

    with pytest.raises(InvalidProfileCatalog, match="1홉만"):
        _validate(profiles)
