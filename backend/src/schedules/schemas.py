from datetime import datetime

from beanie import PydanticObjectId
from pydantic import Field

from src.schedules.domain import Schedule
from src.schemas import ApiModel


class ScheduleResponse(ApiModel):
    id: str
    employee_id: str
    kind: str
    title: str | None
    hour: int
    minute: int
    enabled: bool
    last_run_at: datetime | None
    created_at: datetime

    @classmethod
    def from_domain(cls, schedule: Schedule) -> "ScheduleResponse":
        if schedule.id is None:
            raise ValueError("저장되지 않은 반복 지시는 응답으로 내릴 수 없다")
        return cls(
            id=str(schedule.id),
            employee_id=str(schedule.employee_id),
            kind=schedule.kind,
            title=schedule.title,
            hour=schedule.hour,
            minute=schedule.minute,
            enabled=schedule.enabled,
            last_run_at=schedule.last_run_at,
            created_at=schedule.created_at,
        )


class CreateScheduleRequest(ApiModel):
    """ "매일 hour:minute에 이 직원에게 이 일을".

    요일·간격은 받지 않는다. 지금 필요한 것은 "매일 몇 시"뿐이고, cron 문자열을 받으면
    UI가 그걸 만들어 보내야 한다 — 잘못 만든 표현식은 저장은 되고 실행만 안 된다.
    """

    employee_id: PydanticObjectId
    kind: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=120)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)


class UpdateScheduleRequest(ApiModel):
    """지금은 켜고 끄는 것만 바꾼다. 시각을 바꾸려면 지우고 다시 만든다 —
    반복 지시는 몇 개 되지 않고, 부분 수정 경로를 늘리면 검증만 복잡해진다.
    """

    enabled: bool
