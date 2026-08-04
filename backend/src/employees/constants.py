from enum import StrEnum


class Role(StrEnum):
    """직무. 블루프린트 §1의 용어를 그대로 쓴다."""

    COLLECTOR = "COLLECTOR"
    WRITER = "WRITER"
    ANALYST = "ANALYST"
    TRADER = "TRADER"
    ENGINEER = "ENGINEER"


class EmployeeStatus(StrEnum):
    """3D 씬의 아바타 색과 1:1 대응한다(블루프린트 §12)."""

    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    WORKING = "WORKING"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
