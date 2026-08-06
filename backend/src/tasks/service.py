import logging
import re
from datetime import UTC, datetime, timedelta

from beanie import PydanticObjectId
from bson.errors import InvalidId

from src.employees.constants import EmployeeStatus
from src.employees.domain import Employee
from src.employees.exceptions import EmployeeNotFound
from src.employees.repository import EmployeeRepositoryProtocol
from src.exceptions import AppError
from src.pagination import CursorPage
from src.realtime.bus import EventBus
from src.realtime.schemas import (
    ActivityCreated,
    ActivityCreatedData,
    EmployeeStatusChanged,
    EmployeeStatusChangedData,
)
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
        events: EventBus,
    ) -> None:
        self._tasks = task_repository
        self._activities = activity_repository
        self._employees = employee_repository
        self._events = events

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

    # ─── 사람이 시키는 일 ───────────────────────────────────────

    async def assign_task(
        self,
        *,
        employee_id: PydanticObjectId,
        kind: str,
        title: str | None = None,
    ) -> TaskResponse:
        """지시 → QUEUED. 실행은 워커가 집어갈 때 시작된다.

        여기서 바로 RUNNING으로 만들지 않는 이유: 실행 주체는 워커 프로세스다. API가
        RUNNING을 찍어두면 워커가 죽어 있어도 화면에는 일하는 것처럼 보이고, 회수
        루프가 타임아웃으로 걷어낼 때까지 아무도 그 사실을 모른다. QUEUED로 두면
        "시켰지만 아직 아무도 안 잡았다"가 화면에 그대로 드러난다.

        직원당 활성 작업은 1개다. 대기열을 허용하면 `current_task_id` 하나로는
        표현할 수 없고, 3D 씬의 아바타 상태도 무엇을 보여줄지 정해지지 않는다.
        """
        employee = await self._employees.get(employee_id)
        if employee is None:
            raise EmployeeNotFound
        if employee.current_task_id is not None:
            raise EmployeeBusy

        pending = await self._tasks.list(employee_id=employee_id, status=TaskStatus.QUEUED)
        if pending:
            raise EmployeeBusy

        task = await self._tasks.save(
            Task(
                employee_id=employee_id,
                kind=kind,
                title=(title or "").strip() or None,
                status=TaskStatus.QUEUED,
                created_at=datetime.now(UTC),
            )
        )
        return TaskResponse.from_domain(task)

    async def cancel_task(self, task_id: PydanticObjectId) -> TaskResponse:
        """대기 중인 지시를 거둔다. 실행 중인 작업은 워커가 마감한다.

        RUNNING을 여기서 CANCELLED로 만들면 워커는 그 사실을 모른 채 계속 돌고,
        나중에 마감을 시도하다 전이 거부(409)를 맞는다. 상태 머신은 RUNNING→CANCELLED를
        허용하지만 그건 회수 루프(Phase 9)의 자리다 — 워커가 이미 죽었다는 근거가 있을 때만.
        """
        task = await self._tasks.get(task_id)
        if task is None:
            raise TaskNotFound
        if task.status is not TaskStatus.QUEUED:
            raise InvalidTaskTransition
        cancelled = await self._tasks.save(
            task.model_copy(
                update={"status": TaskStatus.CANCELLED, "finished_at": datetime.now(UTC)}
            )
        )
        return TaskResponse.from_domain(cancelled)

    # ─── 내부 명령 (워커 전용) ──────────────────────────────────

    async def claim_next_task(self) -> TaskResponse | None:
        """대기열에서 하나를 집어 RUNNING으로 만든다. 없으면 None.

        `start_task`와 나눈 이유: 저쪽은 워커가 **스스로 만든** 일(스케줄 실행)이고,
        이쪽은 **사람이 시킨** 일을 집어가는 경로다. 둘을 합치면 "누가 시작시켰나"가
        기록에서 사라진다.

        전이는 repository가 원자적으로 처리한다. 여기서 조회 후 저장으로 나누면
        워커 둘이 같은 작업을 집는다.
        """
        task = await self._tasks.claim_oldest_queued(started_at=datetime.now(UTC))
        if task is None:
            return None

        employee = await self._employees.get(task.employee_id)
        if employee is None:
            # 지시 후 해고된 경우. 담당자가 없으니 실행할 수 없다.
            logger.warning("담당 직원이 사라진 작업을 마감한다: task=%s", task.id)
            await self._tasks.save(
                task.model_copy(
                    update={
                        "status": TaskStatus.CANCELLED,
                        "finished_at": datetime.now(UTC),
                        "error": "담당 직원이 존재하지 않습니다",
                    }
                )
            )
            return None

        working = await self._employees.save(
            employee.model_copy(
                update={"status": EmployeeStatus.WORKING, "current_task_id": task.id}
            )
        )
        await self._publish_status(working)
        return TaskResponse.from_domain(task)

    async def start_task(
        self, *, employee_id: PydanticObjectId, kind: str, title: str | None = None
    ) -> TaskResponse:
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
                title=(title or "").strip() or None,
                status=TaskStatus.RUNNING,
                started_at=now,
                created_at=now,
            )
        )
        # 작업 생성과 직원 상태 갱신은 원자적이지 않다(Phase 9 과제).
        working = await self._employees.save(
            employee.model_copy(
                update={"status": EmployeeStatus.WORKING, "current_task_id": task.id}
            )
        )
        await self._publish_status(working)
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
        await self._events.publish(
            ActivityCreated(
                data=ActivityCreatedData(
                    employee_id=str(activity.employee_id),
                    task_id=str(activity.task_id) if activity.task_id else None,
                    level=activity.level,
                    message=activity.message,
                    occurred_at=activity.occurred_at,
                )
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
            released = await self._employees.save(
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
            await self._publish_status(released)
        return TaskResponse.from_domain(finished)

    # ─── 운영 (Phase 9) ────────────────────────────────────────

    async def reap_stale_tasks(self, *, timeout_seconds: float) -> list[TaskResponse]:
        """오래 매달린 RUNNING 작업을 CANCELLED로 마감한다.

        이게 없으면 워커가 SIGKILL로 죽었을 때 직원의 `current_task_id`가 영구히 남아
        그 직원은 다시 일할 수 없다(EmployeeBusy). "하루 무인 운영"이 성립하려면
        사람이 개입하지 않고 이 상태가 풀려야 한다.

        FAILED가 아니라 CANCELLED인 이유: 작업이 실패한 게 아니라 **결과를 알 수 없다.**
        FAILED로 두면 직원이 ERROR가 되어 3D 씬에 장애로 표시되고, 그건 사실이 아니다.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        stale = await self._tasks.list_running_started_before(cutoff)
        if stale == []:
            return []

        logger.warning(
            "멈춘 작업을 회수한다", extra={"count": len(stale), "cutoff": cutoff.isoformat()}
        )
        reaped: list[TaskResponse] = []
        for task in stale:
            if task.id is None:
                continue
            # 개별 실패가 나머지 회수를 막지 않는다. 한 건이 이상해도 다른 직원은 풀려야 한다.
            try:
                reaped.append(
                    await self.finish_task(
                        task.id,
                        outcome=TaskStatus.CANCELLED,
                        error=f"{timeout_seconds:.0f}초를 넘겨 자동 회수됨",
                    )
                )
            except AppError:
                logger.exception("작업 회수 실패", extra={"task_id": str(task.id)})
        return reaped

    async def _publish_status(self, employee: Employee) -> None:
        """직원 상태 변경을 3D 씬에 알린다. 아바타 색이 이 이벤트로 바뀐다."""
        if employee.id is None:
            return
        await self._events.publish(
            EmployeeStatusChanged(
                data=EmployeeStatusChangedData(
                    employee_id=str(employee.id),
                    status=employee.status,
                    current_task_id=(
                        str(employee.current_task_id) if employee.current_task_id else None
                    ),
                )
            )
        )

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
