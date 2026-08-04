"""작업(Task)·활동(Activity) 애그리거트 — 직원이 한 일과 그 과정의 기록.

Task는 직원의 1회 실행 단위이고 상태 전이(QUEUED→RUNNING→종결)를 소유한다.
Activity는 그 과정에서 발생한 append-only 이벤트로, 3D 씬 말풍선의 원천이다.
둘 다 수치를 담지 않는다 — 금액·카운트는 `ledger`에만 있고, 요약문에는
`{{ledger.*}}` 자리표시자만 남긴다(ADR-002).

공개/내부 라우터를 두 APIRouter로 분리한다. 내부 라우터가 실제로 잠기는 지점은
main.py의 include_router다 — 엔드포인트마다 인증을 붙이면 반드시 하나 빠뜨린다(§5).
"""

from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Query, status

from src.pagination import DEFAULT_LIMIT, MAX_LIMIT, CursorPage
from src.tasks.constants import TaskStatus
from src.tasks.dependencies import TaskServiceDep
from src.tasks.schemas import (
    ActivityResponse,
    AddActivityRequest,
    FinishTaskRequest,
    StartTaskRequest,
    TaskResponse,
)

public_router = APIRouter(tags=["tasks"])
internal_router = APIRouter(prefix="/tasks", tags=["internal-tasks"])


@public_router.get("/tasks")
async def list_tasks(
    service: TaskServiceDep,
    employee_id: PydanticObjectId | None = None,
    status: TaskStatus | None = None,
) -> list[TaskResponse]:
    return await service.list_tasks(employee_id=employee_id, status=status)


@public_router.get("/employees/{employee_id}/activities")
async def list_employee_activities(
    employee_id: PydanticObjectId,
    service: TaskServiceDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[ActivityResponse]:
    return await service.list_activities(employee_id, limit=limit, cursor=cursor)


@internal_router.post("", status_code=status.HTTP_201_CREATED)
async def start_task(
    request: StartTaskRequest,
    service: TaskServiceDep,
) -> TaskResponse:
    return await service.start_task(employee_id=request.employee_id, kind=request.kind)


@internal_router.post("/{task_id}/activities", status_code=status.HTTP_201_CREATED)
async def add_activity(
    task_id: PydanticObjectId,
    request: AddActivityRequest,
    service: TaskServiceDep,
) -> ActivityResponse:
    return await service.add_activity(task_id, level=request.level, message=request.message)


@internal_router.patch("/{task_id}")
async def finish_task(
    task_id: PydanticObjectId,
    request: FinishTaskRequest,
    service: TaskServiceDep,
) -> TaskResponse:
    return await service.finish_task(
        task_id, outcome=request.status, summary=request.summary, error=request.error
    )
