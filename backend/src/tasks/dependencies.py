from typing import Annotated

from fastapi import Depends

from src.employees.dependencies import get_employee_repository
from src.employees.repository import EmployeeRepositoryProtocol
from src.realtime.dependencies import EventBusDep
from src.tasks.repository import (
    ActivityRepository,
    ActivityRepositoryProtocol,
    TaskRepository,
    TaskRepositoryProtocol,
)
from src.tasks.service import TaskService


def get_task_repository() -> TaskRepositoryProtocol:
    return TaskRepository()


def get_activity_repository() -> ActivityRepositoryProtocol:
    return ActivityRepository()


def get_task_service(
    task_repository: Annotated[TaskRepositoryProtocol, Depends(get_task_repository)],
    activity_repository: Annotated[ActivityRepositoryProtocol, Depends(get_activity_repository)],
    employee_repository: Annotated[EmployeeRepositoryProtocol, Depends(get_employee_repository)],
    events: EventBusDep,
) -> TaskService:
    return TaskService(task_repository, activity_repository, employee_repository, events)


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
