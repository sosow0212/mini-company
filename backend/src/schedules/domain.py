"""반복 지시 — "매일 11시에 이 직원에게 이 일을".

작업(Task)과의 관계: 스케줄은 **작업을 만드는 규칙**이고 작업은 그 결과다. 시간이 되면
스케줄이 QUEUED 작업 하나를 낳고, 그 뒤는 사람이 직접 시킨 일과 완전히 같은 경로를
탄다(에이전트가 집어감 → 하네스 실행 → 마감). 실행 경로를 나누지 않는 이유는,
갈라두면 "UI로 시킨 건 되는데 스케줄로 돈 건 안 되는" 상태가 생기기 때문이다.

cron 문자열 대신 시:분만 받는다. `*/5 9-18 * * 1-5` 같은 표현력은 지금 필요가 없고,
UI에서 시간 선택기로 고르는 값이 그대로 저장되는 편이 오해가 없다. 요일·간격이
필요해지면 그때 필드를 늘린다(YAGNI).
"""

from datetime import datetime

from beanie import PydanticObjectId
from pydantic import BaseModel, ConfigDict, Field


class Schedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: PydanticObjectId | None = None
    employee_id: PydanticObjectId
    # 워크플로우 종류. 워커의 레지스트리에 있는 이름이어야 실행된다.
    kind: str
    # 사람이 읽는 한 줄. 작업의 title로 그대로 넘어가고, 분석·보고서 워크플로우는
    # 이 값을 검색어·주제로 쓴다.
    title: str | None = None
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    # 끄면 시간이 되어도 만들지 않는다. 지우는 것과 다르다 — 잠시 멈추는 용도다.
    enabled: bool = True
    # 마지막으로 작업을 만든 시각. 같은 날 두 번 만들지 않는 근거이자,
    # 화면에서 "마지막 실행"으로 보여주는 값이다.
    last_run_at: datetime | None = None
    created_at: datetime
