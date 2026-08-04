from typing import Annotated

from fastapi import Depends

from src.employees.repository import EmployeeRepository, EmployeeRepositoryProtocol
from src.employees.service import EmployeeService


def get_employee_repository() -> EmployeeRepositoryProtocol:
    return EmployeeRepository()


def get_employee_service(
    repository: Annotated[EmployeeRepositoryProtocol, Depends(get_employee_repository)],
) -> EmployeeService:
    return EmployeeService(repository)


EmployeeServiceDep = Annotated[EmployeeService, Depends(get_employee_service)]
