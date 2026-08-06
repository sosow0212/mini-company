from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """워커 설정. 백엔드와 같은 .env를 읽되 워커에 필요한 키만 해석한다.

    backend/ 또는 리포 루트가 아니라 workers/에서 실행할 때를 위해 두 경로를 본다.
    """

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend_base_url: str = "http://localhost:8000"
    # 워커 키는 필수다. 없으면 첫 요청이 아니라 실행 즉시 실패해야 한다.
    worker_api_key: SecretStr
    # 워커는 자기 이름으로 공개 API에서 id를 해석한다. 시드의 이름과 일치해야 한다.
    employee_name: str = "수집가 노아"

    # 로그는 백엔드와 같은 형식으로 낸다 — 수집기가 두 형식을 구분할 이유가 없다.
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # 연결 실패 재시도 횟수(retry.py). 5xx·읽기 타임아웃은 재시도하지 않는다.
    max_attempts: int = 3

    # ─── 스케줄러 (Phase 9) ───────────────────────────────────
    # 크론 표현식. 기본값은 "매일 오전 11시".
    schedule_cron: str = "0 11 * * *"
    schedule_job: str = "collect"
    # UTC가 아니라 로컬 타임존을 쓴다 — "오전 11시"는 사람이 사는 시간대의 11시다.
    schedule_timezone: str = "Asia/Seoul"


@lru_cache
def get_settings() -> Settings:
    return Settings()
