from enum import StrEnum


class TaskStatus(StrEnum):
    """작업 상태. 전이 규칙은 state_machine.py가 소유한다."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ActivityLevel(StrEnum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
