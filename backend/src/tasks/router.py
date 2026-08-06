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
from fastapi import APIRouter, Query, Response, status

from src.pagination import DEFAULT_LIMIT, MAX_LIMIT, CursorPage
from src.tasks.constants import TaskStatus
from src.tasks.dependencies import TaskServiceDep
from src.tasks.schemas import (
    ActivityResponse,
    AddActivityRequest,
    AssignTaskRequest,
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


@public_router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def assign_task(request: AssignTaskRequest, service: TaskServiceDep) -> TaskResponse:
    """직원에게 일을 시킨다 → QUEUED. 워커가 집어가면 RUNNING이 된다.

    바로 RUNNING으로 만들지 않는 이유: 실행 주체는 워커다. API가 RUNNING을 찍으면
    워커가 죽어 있어도 화면에는 일하는 것처럼 보인다.
    """
    return await service.assign_task(
        employee_id=request.employee_id, kind=request.kind, title=request.title
    )


@public_router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: PydanticObjectId, service: TaskServiceDep) -> TaskResponse:
    """대기 중인 지시를 거둔다. 이미 실행 중이면 409 — 워커가 마감해야 한다."""
    return await service.cancel_task(task_id)


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
    """워커가 **스스로 만든** 일(스케줄 실행). 사람이 시킨 일은 claim으로 집어간다."""
    return await service.start_task(
        employee_id=request.employee_id, kind=request.kind, title=request.title
    )


@internal_router.post("/claim")
async def claim_task(service: TaskServiceDep, response: Response) -> TaskResponse | None:
    """대기열에서 하나를 집어 RUNNING으로 만든다. 비어 있으면 204.

    204를 쓰는 이유: "일이 없다"는 정상이다. 404로 답하면 워커 로그가 오류로 뒤덮여
    진짜 문제가 묻힌다.
    """
    task = await service.claim_next_task()
    if task is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return task


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
