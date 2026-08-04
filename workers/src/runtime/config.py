from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
