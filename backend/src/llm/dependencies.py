from typing import Annotated

from fastapi import Depends, Request

from src.employees.dependencies import get_employee_repository
from src.employees.repository import EmployeeRepositoryProtocol
from src.ledger.dependencies import get_ledger_service
from src.ledger.service import LedgerService
from src.llm.gateway import LlmGateway
from src.llm.service import LlmService
from src.tasks.dependencies import get_task_service
from src.tasks.service import TaskService


def get_llm_gateway(request: Request) -> LlmGateway:
    """부팅 시 조립해 app.state에 둔 불변 게이트웨이를 꺼낸다."""
    return request.app.state.llm_gateway


def get_llm_service(
    gateway: Annotated[LlmGateway, Depends(get_llm_gateway)],
    employees: Annotated[EmployeeRepositoryProtocol, Depends(get_employee_repository)],
    ledger: Annotated[LedgerService, Depends(get_ledger_service)],
    tasks: Annotated[TaskService, Depends(get_task_service)],
) -> LlmService:
    return LlmService(gateway, employees=employees, ledger=ledger, tasks=tasks)


LlmServiceDep = Annotated[LlmService, Depends(get_llm_service)]
