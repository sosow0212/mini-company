from decimal import Decimal
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
    # 로그는 stdout에 JSON 한 줄(§10.1). 로컬 디버깅에서만 console을 쓴다.
    log_format: Literal["json", "console"] = "json"

    # ─── graceful shutdown (Phase 9) ──────────────────────────
    # SIGTERM 후 진행 중 요청을 기다리는 시간. K8s의 terminationGracePeriodSeconds보다
    # 짧아야 한다 — 길면 K8s가 SIGKILL로 끊어 이 설정이 무의미해진다.
    shutdown_grace_seconds: float = 20.0

    # ─── 멈춘 작업 회수 (Phase 9) ─────────────────────────────
    # 워커가 SIGKILL로 죽으면 작업이 RUNNING에 남고 직원의 current_task_id가 풀리지 않아
    # 그 직원은 영구히 EmployeeBusy가 된다. 이 시간을 넘긴 작업은 자동으로 마감한다.
    stale_task_timeout_seconds: float = 900.0
    # 회수 루프 주기. 0 이하면 루프를 띄우지 않는다(K8s CronJob으로 대체할 때).
    reaper_interval_seconds: float = 120.0

    # 27018: 로컬 설치 mongod(27017)와 compose mongo를 주소로 구분한다.
    mongo_uri: str = "mongodb://localhost:27018/?directConnection=true"
    mongo_db: str = "mini_company"

    # gRPC(19530)가 아니라 관리 포트다. Milvus는 두 포트를 같은 프로세스에서 서빙하므로
    # healthz 200은 gRPC도 떠 있다는 뜻이다. 벡터 접속 URI는 Phase 7에서 추가한다.
    milvus_health_url: str = "http://localhost:9091/healthz"

    # 워커 인증 키. SecretStr이라 로그·에러 트레이스에 값이 찍히지 않는다.
    worker_api_key: SecretStr = SecretStr(_DEFAULT_WORKER_API_KEY)

    # ─── EventBus (ADR-008) ───────────────────────────────────
    # replica가 2 이상이면 redis가 필수다. memory면 이벤트가 자기 프로세스의 연결에만
    # 전달되어 "어떤 사용자는 이벤트를 못 받는" 상태가 된다. redis 구현은 Phase 12.
    event_bus: Literal["memory", "redis"] = "memory"

    # ─── LLM: 키 (프로바이더 단위, 전부 SECRET) ────────────────
    # 키는 이 프로세스에만 존재한다. 워커는 프록시를 경유하므로 키를 갖지 않는다(ADR-007).
    minimax_api_key: SecretStr = SecretStr("")
    minimax_base_url: str = "https://api.minimax.io/v1"
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_base_url: str = "https://api.anthropic.com/v1"

    # ─── LLM: 카탈로그·단가 (ConfigMap 대상, 비밀 아님) ────────
    # 비우면 llm/profiles.py의 DEFAULT_PROFILES를 쓴다.
    llm_profiles_json: str | None = None
    # 모델 단위 1M 토큰당 USD. 코드에 단가 상수를 두지 않는다 — 자주 바뀐다.
    llm_pricing_json: str | None = None
    llm_timeout_seconds: float = 60.0
    # 원장은 KRW로 기록한다. 환율도 설정값.
    usd_krw_rate: Decimal = Decimal("1380")
    # 0 이하면 한도 검사를 하지 않는다.
    llm_daily_cost_limit_krw: Decimal = Decimal("5000")

    # ─── 임베딩 (Phase 7) ─────────────────────────────────────
    # hashing은 키 없이 파이프라인을 돌리기 위한 개발용이다. 의미를 모르므로
    # 프로덕션에서는 openai를 쓴다(부팅 시 경고를 남긴다).
    embedding_provider: Literal["openai", "hashing"] = "hashing"
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    # 차원이 바뀌면 기존 벡터를 전부 버려야 한다. 부팅 시 컬렉션과 비교한다(§15-1).
    embedding_dim: int = 1536

    # ─── Milvus / RAG (Phase 7) ───────────────────────────────
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "knowledge_chunks"
    rag_top_k: int = 8
    rag_score_threshold: float = 0.35
    chunk_target_tokens: int = 500
    chunk_overlap_tokens: int = 80
    # 비우면 포맷별 기본 전략을 쓴다(HTML·MARKDOWN → heading, PDF·줄글 → paragraph).
    # 등록되지 않은 이름이면 부팅을 거부한다.
    chunking_strategy: str | None = None

    # ─── 챗봇 (Phase 8) ───────────────────────────────────────
    # 챗봇은 직원이 아니라서 프로파일을 이름으로 직접 고른다.
    chat_llm_profile: str = "reasoner"
    chat_history_limit: int = 10

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
