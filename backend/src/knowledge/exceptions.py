from src.exceptions import AppError, NotFoundError


class DocumentNotFound(NotFoundError):
    code = "document_not_found"
    message = "해당 문서를 찾을 수 없습니다."


class DocumentParseFailed(AppError):
    status_code = 422
    code = "document_parse_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedContentType(AppError):
    status_code = 422
    code = "unsupported_content_type"

    def __init__(self, content_type: str) -> None:
        super().__init__(content_type)
        self.message = f"지원하지 않는 문서 포맷입니다: {content_type}"


class UnsupportedChunkingStrategy(AppError):
    status_code = 422
    code = "unsupported_chunking_strategy"

    def __init__(self, name: str, available: list[str]) -> None:
        super().__init__(name)
        self.message = f"지원하지 않는 청킹 전략입니다: {name} (사용 가능: {', '.join(available)})"


class EmptyDocument(AppError):
    status_code = 422
    code = "empty_document"
    message = "본문에서 텍스트를 추출하지 못했습니다."


class EmbeddingFailed(AppError):
    status_code = 502
    code = "embedding_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class VectorStoreFailed(AppError):
    status_code = 502
    code = "vector_store_failed"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EmbeddingDimensionMismatch(AppError):
    """부팅 검증 실패(§15-1). 앱을 띄우지 않는다.

    이걸 통과시키면 검색 품질만 조용히 망가진다 — 가장 발견이 어려운 버그다.
    """

    code = "embedding_dimension_mismatch"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
