"""반복 지시(Schedule) 애그리거트 — "매일 몇 시에 누구에게 무엇을".

작업을 만드는 **규칙**을 소유한다. 만들어진 작업 자체는 `tasks`의 것이고, 실행은
에이전트가 한다. 여기서 실행까지 하면 백엔드가 워크플로우를 알게 되어 ADR-001이 깨진다.
"""

from beanie import PydanticObjectId
from fastapi import APIRouter, status

from src.schedules.dependencies import ScheduleServiceDep
from src.schedules.schemas import (
    CreateScheduleRequest,
    ScheduleResponse,
    UpdateScheduleRequest,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get("")
async def list_schedules(service: ScheduleServiceDep) -> list[ScheduleResponse]:
    return await service.list_schedules()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    request: CreateScheduleRequest, service: ScheduleServiceDep
) -> ScheduleResponse:
    """등록하면 매일 그 시각에 QUEUED 작업이 하나 생긴다."""
    return await service.create(
        employee_id=request.employee_id,
        kind=request.kind,
        hour=request.hour,
        minute=request.minute,
        title=request.title,
    )


@router.patch("/{schedule_id}")
async def update_schedule(
    schedule_id: PydanticObjectId,
    request: UpdateScheduleRequest,
    service: ScheduleServiceDep,
) -> ScheduleResponse:
    """켜고 끈다. 끄면 시각이 되어도 작업을 만들지 않는다."""
    return await service.set_enabled(schedule_id, enabled=request.enabled)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: PydanticObjectId, service: ScheduleServiceDep) -> None:
    await service.delete(schedule_id)
