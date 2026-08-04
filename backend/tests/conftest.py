from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId

from src.employees.constants import EmployeeStatus, Role
from src.employees.domain import DeskPosition, Employee

_HIRED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.fixture
def make_employee():
    """테스트용 도메인 Employee 빌더. id가 있으면 이미 저장된 직원을 뜻한다."""

    def _make(
        name: str,
        *,
        role: Role = Role.COLLECTOR,
        status: EmployeeStatus = EmployeeStatus.OFFLINE,
        desk: DeskPosition | None = None,
        hired_at: datetime = _HIRED_AT,
        with_id: bool = True,
    ) -> Employee:
        return Employee(
            id=PydanticObjectId() if with_id else None,
            name=name,
            role=role,
            status=status,
            desk=desk or DeskPosition(x=0.0, y=0.0, z=0.0),
            hired_at=hired_at,
        )

    return _make
