"""Beanie 쿼리는 이 파일에만 등장한다."""

from datetime import datetime
from typing import Protocol

from beanie import PydanticObjectId

from src.schedules.domain import Schedule
from src.schedules.models import ScheduleDocument


class ScheduleRepositoryProtocol(Protocol):
    """service가 의존하는 경계. "없으면 예외"는 service가 판단한다."""

    async def get(self, schedule_id: PydanticObjectId) -> Schedule | None: ...

    async def list_enabled(self) -> list[Schedule]: ...

    async def list_all(self) -> list[Schedule]: ...

    async def save(self, schedule: Schedule) -> Schedule: ...

    async def delete(self, schedule_id: PydanticObjectId) -> bool: ...

    async def claim_run(
        self, schedule_id: PydanticObjectId, *, ran_at: datetime, not_run_since: datetime
    ) -> bool:
        """실행권을 원자적으로 가져간다. 가져갔으면 True.

        `not_run_since` 이후에 이미 실행된 스케줄은 False를 준다. 백엔드 replica가
        둘이면 같은 틱에 두 프로세스가 같은 스케줄을 보므로, 이 검사가 없으면
        작업이 두 개 생긴다(직원은 하나라 둘째는 EmployeeBusy로 실패한다).
        """
        ...


class ScheduleRepository:
    async def get(self, schedule_id: PydanticObjectId) -> Schedule | None:
        document = await ScheduleDocument.get(schedule_id)
        return _to_domain(document) if document is not None else None

    async def list_enabled(self) -> list[Schedule]:
        documents = await ScheduleDocument.find(ScheduleDocument.enabled == True).to_list()  # noqa: E712
        return [_to_domain(document) for document in documents]

    async def list_all(self) -> list[Schedule]:
        documents = await ScheduleDocument.find().sort("+hour", "+minute").to_list()
        return [_to_domain(document) for document in documents]

    async def save(self, schedule: Schedule) -> Schedule:
        return _to_domain(await _to_document(schedule).save())

    async def delete(self, schedule_id: PydanticObjectId) -> bool:
        document = await ScheduleDocument.get(schedule_id)
        if document is None:
            return False
        await document.delete()
        return True

    async def claim_run(
        self, schedule_id: PydanticObjectId, *, ran_at: datetime, not_run_since: datetime
    ) -> bool:
        """조건부 갱신 한 번으로 끝낸다. 조회 후 저장으로 나누면 그 틈에 다른
        replica가 같은 스케줄을 집는다.
        """
        collection = ScheduleDocument.get_pymongo_collection()
        result = await collection.update_one(
            {
                "_id": schedule_id,
                "$or": [{"last_run_at": None}, {"last_run_at": {"$lt": not_run_since}}],
            },
            {"$set": {"last_run_at": ran_at}},
        )
        return result.modified_count == 1


def _to_domain(document: ScheduleDocument) -> Schedule:
    return Schedule(
        id=document.id,
        employee_id=document.employee_id,
        kind=document.kind,
        title=document.title,
        hour=document.hour,
        minute=document.minute,
        enabled=document.enabled,
        last_run_at=document.last_run_at,
        created_at=document.created_at,
    )


def _to_document(schedule: Schedule) -> ScheduleDocument:
    return ScheduleDocument(
        id=schedule.id,
        employee_id=schedule.employee_id,
        kind=schedule.kind,
        title=schedule.title,
        hour=schedule.hour,
        minute=schedule.minute,
        enabled=schedule.enabled,
        last_run_at=schedule.last_run_at,
        created_at=schedule.created_at,
    )
