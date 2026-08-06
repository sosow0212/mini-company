"""설정 로딩의 경계 동작.

환경변수에는 "빈 문자열"과 "미설정"을 구분할 방법이 없다. 그 둘을 다르게 다루면
`.env`나 ConfigMap에 빈 값을 남긴 순간 기본값이 조용히 사라진다.
"""

import pytest

from src.config import Settings


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """.env 파일과 실제 환경변수의 영향을 끊는다."""
    for key in ("CHUNKING_STRATEGY", "LOG_LEVEL", "APP_ENV"):
        monkeypatch.delenv(key, raising=False)


def test_blank_env_var_falls_back_to_default(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — ConfigMap에 `CHUNKING_STRATEGY: ""`를 둔 상황과 같다.
    monkeypatch.setenv("CHUNKING_STRATEGY", "")

    # Act
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    # Assert — 빈 문자열이 아니라 기본값(미설정)이어야 한다.
    assert settings.chunking_strategy is None


def test_blank_does_not_erase_non_optional_default(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.log_level == "INFO"


def test_real_value_still_wins(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHUNKING_STRATEGY", "heading")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.chunking_strategy == "heading"
