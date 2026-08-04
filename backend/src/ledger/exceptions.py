from src.exceptions import AppError, NotFoundError


class LedgerEntryNotFound(NotFoundError):
    code = "ledger_entry_not_found"
    message = "해당 원장 엔트리를 찾을 수 없습니다."


class EntryAlreadyReversed(AppError):
    status_code = 409
    code = "entry_already_reversed"
    message = "이미 역분개된 엔트리입니다."


class CannotReverseReversal(AppError):
    status_code = 409
    code = "cannot_reverse_reversal"
    message = "역분개 엔트리를 다시 역분개할 수 없습니다."


class UnknownPlaceholder(AppError):
    """치환표에 없는 자리표시자. 렌더링을 중단한다."""

    code = "unknown_placeholder"

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.message = f"알 수 없는 자리표시자입니다: {{{{{key}}}}}"


class PlaceholderNotSubstituted(AppError):
    code = "placeholder_not_substituted"
    message = "치환되지 않은 자리표시자가 남아 있습니다."
