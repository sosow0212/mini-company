from typing import Protocol

from beanie import PydanticObjectId

from src.employees.constants import EmployeeStatus, Role
from src.employees.domain import Employee
from src.employees.models import EmployeeDocument


class EmployeeRepositoryProtocol(Protocol):
    """service가 의존하는 경계. 구현이 둘(Beanie / InMemory)이라 Protocol이 값을 한다.

    "없으면 예외"를 판단하지 않는다. None을 반환하고 그게 오류인지는 service가 정한다.
    """

    async def get(self, employee_id: PydanticObjectId) -> Employee | None: ...

    async def get_by_name(self, name: str) -> Employee | None: ...

    async def list(
        self,
        *,
        role: Role | None = None,
        status: EmployeeStatus | None = None,
    ) -> list[Employee]: ...

    async def save(self, employee: Employee) -> Employee: ...


class EmployeeRepository:
    """Beanie 쿼리는 이 파일에만 등장한다."""

    async def get(self, employee_id: PydanticObjectId) -> Employee | None:
        document = await EmployeeDocument.get(employee_id)
        return _to_domain(document) if document is not None else None

    async def get_by_name(self, name: str) -> Employee | None:
        document = await EmployeeDocument.find_one(EmployeeDocument.name == name)
        return _to_domain(document) if document is not None else None

    async def list(
        self,
        *,
        role: Role | None = None,
        status: EmployeeStatus | None = None,
    ) -> list[Employee]:
        conditions = []
        if role is not None:
            conditions.append(EmployeeDocument.role == role)
        if status is not None:
            conditions.append(EmployeeDocument.status == status)
        documents = await EmployeeDocument.find(*conditions).sort("+name").to_list()
        return [_to_domain(document) for document in documents]

    async def save(self, employee: Employee) -> Employee:
        # id가 없으면 insert, 있으면 replace.
        return _to_domain(await _to_document(employee).save())


def _to_domain(document: EmployeeDocument) -> Employee:
    return Employee(
        id=document.id,
        name=document.name,
        role=document.role,
        status=document.status,
        desk=document.desk,
        current_task_id=document.current_task_id,
        hired_at=document.hired_at,
    )


def _to_document(employee: Employee) -> EmployeeDocument:
    return EmployeeDocument(
        id=employee.id,
        name=employee.name,
        role=employee.role,
        status=employee.status,
        desk=employee.desk,
        current_task_id=employee.current_task_id,
        hired_at=employee.hired_at,
    )
