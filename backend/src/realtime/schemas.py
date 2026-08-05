"""프론트로 나가는 실시간 이벤트 페이로드.

숫자는 전부 **문자열**이다. Decimal을 JS number로 변환하면 정밀도가 손실되고,
프론트는 이 문자열을 그대로 렌더링한다(포맷팅만 허용 — ADR-006).

`type`을 판별자로 둔 discriminated union이라, 프론트가 `switch (event.type)` 하나로
분기할 수 있고 새 이벤트를 추가해도 기존 분기가 깨지지 않는다.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from src.employees.constants import EmployeeStatus
from src.employees.schemas import EmployeeResponse
from src.ledger.schemas import LedgerSummaryResponse
from src.schemas import ApiModel
from src.tasks.constants import ActivityLevel


class EmployeeStatusChangedData(ApiModel):
    employee_id: str
    status: EmployeeStatus
    current_task_id: str | None


class EmployeeStatusChanged(ApiModel):
    """3D 씬의 아바타 색을 바꾸는 이벤트."""

    type: Literal["employee.status_changed"] = "employee.status_changed"
    data: EmployeeStatusChangedData


class ActivityCreatedData(ApiModel):
    employee_id: str
    task_id: str | None
    level: ActivityLevel
    message: str
    occurred_at: datetime


class ActivityCreated(ApiModel):
    """말풍선의 원천. message에 수치가 들어가면 안 된다(§7.3)."""

    type: Literal["activity.created"] = "activity.created"
    data: ActivityCreatedData


class LedgerSummaryUpdated(ApiModel):
    """원장 패널 갱신. 값은 서버가 aggregate한 결과다(ADR-002)."""

    type: Literal["ledger.summary_updated"] = "ledger.summary_updated"
    data: LedgerSummaryResponse


OfficeEvent = Annotated[
    EmployeeStatusChanged | ActivityCreated | LedgerSummaryUpdated,
    Field(discriminator="type"),
]


class OfficeSnapshot(ApiModel):
    """프론트 최초 진입과 WS 재연결 직후에 1회 조회한다.

    재연결 시 이벤트만 이어받으면 끊긴 동안의 변경이 영구히 유실되므로,
    스냅샷으로 상태를 다시 맞춘다(§12).
    """

    employees: list[EmployeeResponse]
    ledger: LedgerSummaryResponse
