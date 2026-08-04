from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 로컬 전용 기본값. 이 값이 staging/prod에 남아 있으면 부팅을 거부한다(아래 validator).
_DEFAULT_WORKER_API_KEY = "change-me"


class Settings(BaseSettings):
    """12-Factor: 설정은 전부 환경변수. 설정 파일을 읽거나 이미지에 굽지 않는다.
    .env는 로컬 편의 장치일 뿐이다. 컨테이너/K8s에서는 파일이 없고 환경변수만 들어온다.
    backend/ 안에서 실행하든 리포 루트에서 실행하든 같은 .env를 찾도록 두 경로를 본다.
    """

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "staging", "prod"] = "local"
    log_level: str = "INFO"

    # 27018: 로컬 설치 mongod(27017)와 compose mongo를 주소로 구분한다.
    mongo_uri: str = "mongodb://localhost:27018/?directConnection=true"
    mongo_db: str = "mini_company"

    # gRPC(19530)가 아니라 관리 포트다. Milvus는 두 포트를 같은 프로세스에서 서빙하므로
    # healthz 200은 gRPC도 떠 있다는 뜻이다. 벡터 접속 URI는 Phase 7에서 추가한다.
    milvus_health_url: str = "http://localhost:9091/healthz"

    # 워커 인증 키. SecretStr이라 로그·에러 트레이스에 값이 찍히지 않는다.
    worker_api_key: SecretStr = SecretStr(_DEFAULT_WORKER_API_KEY)

    @model_validator(mode="after")
    def _reject_default_worker_key_outside_local(self) -> "Settings":
        # 블루프린트 §15 부팅 검증 6: local이 아닌데 기본 키면 즉시 실패한다.
        if (
            self.app_env != "local"
            and self.worker_api_key.get_secret_value() == _DEFAULT_WORKER_API_KEY
        ):
            raise ValueError("APP_ENV가 local이 아니면 WORKER_API_KEY를 기본값으로 둘 수 없다")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
