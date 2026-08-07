from datetime import datetime

from beanie import PydanticObjectId

from src.schedules.domain import Schedule


class InMemoryScheduleRepository:
    """ScheduleRepository의 경계 대체물. mock이 아니라 동작하는 구현체다."""

    def __init__(self, schedules: list[Schedule] | None = None) -> None:
        self._by_id: dict[PydanticObjectId, Schedule] = {}
        for schedule in schedules or []:
            self._by_id[_require_id(schedule)] = schedule

    async def get(self, schedule_id: PydanticObjectId) -> Schedule | None:
        return self._by_id.get(schedule_id)

    async def list_enabled(self) -> list[Schedule]:
        return [schedule for schedule in self._by_id.values() if schedule.enabled]

    async def list_all(self) -> list[Schedule]:
        return sorted(self._by_id.values(), key=lambda s: (s.hour, s.minute))

    async def save(self, schedule: Schedule) -> Schedule:
        stored = (
            schedule
            if schedule.id is not None
            else schedule.model_copy(update={"id": PydanticObjectId()})
        )
        self._by_id[_require_id(stored)] = stored
        return stored

    async def delete(self, schedule_id: PydanticObjectId) -> bool:
        return self._by_id.pop(schedule_id, None) is not None

    async def claim_run(
        self, schedule_id: PydanticObjectId, *, ran_at: datetime, not_run_since: datetime
    ) -> bool:
        schedule = self._by_id.get(schedule_id)
        if schedule is None:
            return False
        # 실제 구현과 같은 조건. 여기서 조건을 빠뜨리면 fake만 중복 실행을 허용해
        # "테스트는 통과하는데 replica 2에서 작업이 두 개 생기는" 상태가 된다.
        if schedule.last_run_at is not None and schedule.last_run_at >= not_run_since:
            return False
        self._by_id[schedule_id] = schedule.model_copy(update={"last_run_at": ran_at})
        return True


def _require_id(schedule: Schedule) -> PydanticObjectId:
    if schedule.id is None:
        raise ValueError("저장된 반복 지시에는 id가 있어야 한다")
    return schedule.id
