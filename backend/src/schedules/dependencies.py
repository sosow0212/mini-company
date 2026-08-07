from typing import Annotated

from fastapi import Depends

from src.config import Settings, get_settings
from src.employees.dependencies import get_employee_repository
from src.employees.repository import EmployeeRepositoryProtocol
from src.schedules.repository import ScheduleRepository, ScheduleRepositoryProtocol
from src.schedules.service import ScheduleService
from src.tasks.dependencies import get_task_service
from src.tasks.service import TaskService


def get_schedule_repository() -> ScheduleRepositoryProtocol:
    return ScheduleRepository()


def get_schedule_service(
    repository: Annotated[ScheduleRepositoryProtocol, Depends(get_schedule_repository)],
    employees: Annotated[EmployeeRepositoryProtocol, Depends(get_employee_repository)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ScheduleService:
    return ScheduleService(repository, employees, tasks, timezone=settings.schedule_timezone)


ScheduleServiceDep = Annotated[ScheduleService, Depends(get_schedule_service)]
