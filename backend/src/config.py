from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    mongo_uri: str = "mongodb://localhost:27017/?directConnection=true"

    # gRPC(19530)가 아니라 관리 포트다. Milvus는 두 포트를 같은 프로세스에서 서빙하므로
    # healthz 200은 gRPC도 떠 있다는 뜻이다. 벡터 접속 URI는 Phase 7에서 추가한다.
    milvus_health_url: str = "http://localhost:9091/healthz"


@lru_cache
def get_settings() -> Settings:
    return Settings()
