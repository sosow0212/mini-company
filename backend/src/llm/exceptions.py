from src.exceptions import AppError


class InvalidProfileCatalog(AppError):
    """부팅 시점 검증 실패. 앱을 띄우지 않는다."""

    code = "invalid_profile_catalog"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidPricingTable(AppError):
    code = "invalid_pricing_table"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ProfileNotFound(AppError):
    status_code = 409
    code = "llm_profile_not_found"
    message = "직원에게 배정된 LLM 프로파일이 카탈로그에 없습니다."


class ProviderNotConfigured(AppError):
    status_code = 503
    code = "llm_provider_not_configured"
    message = "해당 프로바이더의 API 키가 설정되지 않았습니다."


class LlmCallFailed(AppError):
    status_code = 502
    code = "llm_call_failed"
    message = "LLM 호출이 실패했습니다."


class DailyCostLimitExceeded(AppError):
    status_code = 429
    code = "llm_daily_cost_limit_exceeded"
    message = "오늘의 LLM 비용 한도를 초과했습니다."
