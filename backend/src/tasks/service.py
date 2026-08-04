import logging
import re
from datetime import UTC, datetime

from beanie import PydanticObjectId
from bson.errors import InvalidId

from src.employees.constants import EmployeeStatus
from src.employees.exceptions import EmployeeNotFound
from src.employees.repository import EmployeeRepositoryProtocol
from src.pagination import CursorPage
from src.tasks.constants import ActivityLevel, TaskStatus
from src.tasks.domain import Activity, Task
from src.tasks.exceptions import (
    EmployeeBusy,
    InvalidPaginationCursor,
    InvalidTaskTransition,
    TaskNotFound,
)
from src.tasks.repository import ActivityRepositoryProtocol, TaskRepositoryProtocol
from src.tasks.schemas import ActivityResponse, TaskResponse
from src.tasks.state_machine import can_transition

logger = logging.getLogger(__name__)

# 블루프린트 §7.3 방어선: 수치는 원장에서만 나와야 하므로, 사람이 읽는 문장에
# 3자리 이상 숫자가 박히면 경고를 남긴다. 오탐이 많아 하드 차단은 하지 않는다.
_INLINE_NUMBER = re.compile(r"\d{3,}")


class TaskService:
    """비즈니스 로직. Beanie 쿼리 API가 이 파일에 등장하면 레이어가 무너진다."""

    def __init__(
        self,
        task_repository: TaskRepositoryProtocol,
        activity_repository: ActivityRepositoryProtocol,
        employee_repository: EmployeeRepositoryProtocol,
    ) -> None:
        self._tasks = task_repository
        self._activities = activity_repository
        self._employees = employee_repository

    # ─── 공개 조회 ──────────────────────────────────────────────

    async def list_tasks(
        self,
        *,
        employee_id: PydanticObjectId | None = None,
        status: TaskStatus | None = None,
    ) -> list[TaskResponse]:
        tasks = await self._tasks.list(employee_id=employee_id, status=status)
        return [TaskResponse.from_domain(task) for task in tasks]

    async def list_activities(
        self,
        employee_id: PydanticObjectId,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> CursorPage[ActivityResponse]:
        if await self._employees.get(employee_id) is None:
            raise EmployeeNotFound
        before = await self._resolve_cursor(employee_id, cursor)

        # limit+1개를 가져와 "다음 페이지 존재" 여부를 판단한다.
        activities = await self._activities.list_by_employee(
            employee_id, limit=limit + 1, before=before
        )
        page_items = activities[:limit]
        next_cursor = str(page_items[-1].id) if len(activities) > limit and page_items else None
        return CursorPage(
            items=[ActivityResponse.from_domain(activity) for activity in page_items],
            next_cursor=next_cursor,
        )

    # ─── 내부 명령 (워커 전용) ──────────────────────────────────

    async def start_task(self, *, employee_id: PydanticObjectId, kind: str) -> TaskResponse:
        employee = await self._employees.get(employee_id)
        if employee is None:
            raise EmployeeNotFound
        if employee.current_task_id is not None:
            # 직원 1명은 동시에 작업 1걸만. 이 검사가 없으면 두 작업이 current_task_id를
            # 덮어쓰며 상태가 갈라진다.
            raise EmployeeBusy

        now = datetime.now(UTC)
        task = await self._tasks.save(
            Task(
                employee_id=employee_id,
                kind=kind,
                status=TaskStatus.RUNNING,
                started_at=now,
                created_at=now,
            )
        )
        # 작업 생성과 직원 상태 갱신은 원자적이지 않다. 트랜잭션 경계는
        # Phase 3에서 원장 기록과 함께 설계한다.
        await self._employees.save(
            employee.model_copy(
                update={"status": EmployeeStatus.WORKING, "current_task_id": task.id}
            )
        )
        return TaskResponse.from_domain(task)

    async def add_activity(
        self, task_id: PydanticObjectId, *, level: ActivityLevel, message: str
    ) -> ActivityResponse:
        task = await self._tasks.get(task_id)
        if task is None:
            raise TaskNotFound
        if _INLINE_NUMBER.search(message):
            logger.warning(
                "활동 메시지에 3자리 이상 숫자 — 수치는 원장으로 기록해야 한다: task=%s",
                task_id,
            )
        activity = await self._activities.append(
            Activity(
                employee_id=task.employee_id,
                task_id=task.id,
                level=level,
                message=message,
                occurred_at=datetime.now(UTC),
            )
        )
        return ActivityResponse.from_domain(activity)

    async def finish_task(
        self,
        task_id: PydanticObjectId,
        *,
        outcome: TaskStatus,
        summary: str | None = None,
        error: str | None = None,
    ) -> TaskResponse:
        task = await self._tasks.get(task_id)
        if task is None:
            raise TaskNotFound
        if not can_transition(task.status, outcome):
            raise InvalidTaskTransition
        if summary is not None and _INLINE_NUMBER.search(summary):
            logger.warning(
                "작업 요약에 3자리 이상 숫자 — 수치는 원장 플레이스홀더로 남겨야 한다: task=%s",
                task_id,
            )

        finished = await self._tasks.save(
            task.model_copy(
                update={
                    "status": outcome,
                    "finished_at": datetime.now(UTC),
                    "summary": summary,
                    "error": error,
                }
            )
        )

        # 직원이 지금도 이 작업을 가리키고 있을 때만 상태를 되돌린다.
        employee = await self._employees.get(task.employee_id)
        if employee is not None and employee.current_task_id == task.id:
            await self._employees.save(
                employee.model_copy(
                    update={
                        # 실패만 ERROR다. 취소는 실패가 아니므로 3D 씬에서 빨간 아바타로
                        # 보여선 안 된다(관제실에서 장애로 오독된다).
                        "status": (
                            EmployeeStatus.ERROR
                            if outcome is TaskStatus.FAILED
                            else EmployeeStatus.IDLE
                        ),
                        "current_task_id": None,
                    }
                )
            )
        return TaskResponse.from_domain(finished)

    async def _resolve_cursor(
        self, employee_id: PydanticObjectId, cursor: str | None
    ) -> Activity | None:
        if cursor is None:
            return None
        try:
            cursor_id = PydanticObjectId(cursor)
        except InvalidId:
            # ObjectId 형식 위반. 클라이언트 오류이므로 500으로 두지 않는다.
            # InvalidId로 좁힌 이유: 넓게 잡으면 저장소 장애까지 400으로 바꿔버린다.
            raise InvalidPaginationCursor from None
        activity = await self._activities.get(cursor_id)
        if activity is None or activity.employee_id != employee_id:
            raise InvalidPaginationCursor
        return activity
