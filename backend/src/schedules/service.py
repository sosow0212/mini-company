"""반복 지시의 등록·수정과 "지금 돌릴 때가 됐는가" 판단.

**작업을 직접 실행하지 않는다.** QUEUED 작업을 만들고 끝낸다 — 실행은 에이전트가
집어가서 한다. 여기서 실행까지 하면 백엔드가 워크플로우를 아는 셈이 되고,
ADR-001(워커만 일한다)이 무너진다.
"""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from beanie import PydanticObjectId

from src.employees.exceptions import EmployeeNotFound
from src.employees.repository import EmployeeRepositoryProtocol
from src.schedules.domain import Schedule
from src.schedules.exceptions import ScheduleNotFound
from src.schedules.repository import ScheduleRepositoryProtocol
from src.schedules.schemas import ScheduleResponse
from src.tasks.exceptions import EmployeeBusy
from src.tasks.service import TaskService

logger = logging.getLogger(__name__)

# 예정 시각을 지난 뒤 이 시간 안에만 따라잡는다.
#
# 왜 필요한가: 백엔드가 몇 시간 꺼져 있다가 켜지면, 창이 없을 때 "오늘 아직 안 돌았다"는
# 이유로 지난 스케줄이 한꺼번에 실행된다. 새벽 3시 작업이 오후 2시에 도는 셈이다.
# 창을 넘겼으면 그날은 건너뛰고 다음 날을 기다리는 편이 예측 가능하다.
_CATCH_UP_WINDOW = timedelta(minutes=30)


class ScheduleService:
    def __init__(
        self,
        repository: ScheduleRepositoryProtocol,
        employees: EmployeeRepositoryProtocol,
        tasks: TaskService,
        *,
        timezone: str,
    ) -> None:
        self._repository = repository
        self._employees = employees
        self._tasks = tasks
        self._timezone = ZoneInfo(timezone)

    async def list_schedules(self) -> list[ScheduleResponse]:
        schedules = await self._repository.list_all()
        return [ScheduleResponse.from_domain(schedule) for schedule in schedules]

    async def create(
        self,
        *,
        employee_id: PydanticObjectId,
        kind: str,
        hour: int,
        minute: int,
        title: str | None = None,
    ) -> ScheduleResponse:
        if await self._employees.get(employee_id) is None:
            raise EmployeeNotFound
        saved = await self._repository.save(
            Schedule(
                employee_id=employee_id,
                kind=kind,
                title=(title or "").strip() or None,
                hour=hour,
                minute=minute,
                created_at=datetime.now(UTC),
            )
        )
        return ScheduleResponse.from_domain(saved)

    async def set_enabled(
        self, schedule_id: PydanticObjectId, *, enabled: bool
    ) -> ScheduleResponse:
        schedule = await self._repository.get(schedule_id)
        if schedule is None:
            raise ScheduleNotFound
        updated = await self._repository.save(schedule.model_copy(update={"enabled": enabled}))
        return ScheduleResponse.from_domain(updated)

    async def delete(self, schedule_id: PydanticObjectId) -> None:
        if not await self._repository.delete(schedule_id):
            raise ScheduleNotFound

    # ─── 틱 루프가 부르는 부분 ──────────────────────────────────

    async def run_due(self, now: datetime | None = None) -> int:
        """지금 시각에 해당하는 스케줄로 작업을 만든다. 만든 개수를 돌려준다.

        예외를 밖으로 내지 않는다. 하나가 실패해도(직원이 이미 작업 중이라거나)
        나머지 스케줄은 돌아야 한다.
        """
        moment = (now or datetime.now(UTC)).astimezone(self._timezone)
        created = 0
        for schedule in await self._repository.list_enabled():
            if not _is_due(schedule, moment):
                continue
            if await self._start(schedule, moment):
                created += 1
        return created

    async def _start(self, schedule: Schedule, moment: datetime) -> bool:
        assert schedule.id is not None
        # 실행권을 먼저 가져간다. 작업을 만든 뒤에 갱신하면, 그 사이에 다른 replica가
        # 같은 스케줄로 작업을 하나 더 만든다.
        claimed = await self._repository.claim_run(
            schedule.id,
            ran_at=moment.astimezone(UTC),
            not_run_since=_start_of_day(moment).astimezone(UTC),
        )
        if not claimed:
            return False

        try:
            await self._tasks.assign_task(
                employee_id=schedule.employee_id,
                kind=schedule.kind,
                title=schedule.title,
            )
        except EmployeeBusy:
            # 앞 작업이 아직 안 끝났다. 건너뛰는 편이 맞다 — 쌓아두면 직원 하나가
            # 밀린 작업을 며칠치 처리하게 된다.
            logger.info(
                "직원이 작업 중이라 반복 지시를 건너뛴다",
                extra={"schedule": str(schedule.id), "employee": str(schedule.employee_id)},
            )
            return False
        except Exception:
            logger.exception("반복 지시 실행 실패", extra={"schedule": str(schedule.id)})
            return False

        logger.info(
            "반복 지시로 작업 생성",
            extra={"schedule": str(schedule.id), "kind": schedule.kind},
        )
        return True


def _is_due(schedule: Schedule, moment: datetime) -> bool:
    """예정 시각을 지났고, 오늘 아직 돌지 않았는가."""
    scheduled = moment.replace(hour=schedule.hour, minute=schedule.minute, second=0, microsecond=0)
    if moment < scheduled:
        return False
    if moment - scheduled > _CATCH_UP_WINDOW:
        # 창을 놓쳤다. 오늘은 건너뛴다.
        return False
    if schedule.last_run_at is None:
        return True
    return schedule.last_run_at.astimezone(moment.tzinfo) < _start_of_day(moment)


def _start_of_day(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)
