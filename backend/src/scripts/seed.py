"""직원 5명 시드. 이름을 신원으로 보는 멱등 실행이라 몇 번 돌려도 5명이다.

책상 좌표는 프론트가 아니라 DB가 가진다. 3D 씬은 이 값을 읽어 배치만 한다.
"""

import asyncio
import logging

from src.config import get_settings
from src.database import create_mongo_client, init_documents
from src.employees.constants import Role
from src.employees.domain import DeskPosition
from src.employees.repository import EmployeeRepository
from src.employees.service import EmployeeService

logger = logging.getLogger(__name__)

_DESK_SPACING = 2.0
_SEED_EMPLOYEES: list[tuple[str, Role]] = [
    ("수집가 노아", Role.COLLECTOR),
    ("분석가 리아", Role.ANALYST),
    ("작가 준", Role.WRITER),
    ("트레이더 태오", Role.TRADER),
    ("엔지니어 미르", Role.ENGINEER),
]


def _desk_at(index: int, total: int) -> DeskPosition:
    """일렬 배치. 원점을 기준으로 좌우 대칭."""
    offset = (index - (total - 1) / 2) * _DESK_SPACING
    return DeskPosition(x=offset, y=0.0, z=0.0)


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    client = create_mongo_client(settings)
    try:
        await init_documents(client, settings.mongo_db, skip_indexes=True)
        service = EmployeeService(EmployeeRepository())
        total = len(_SEED_EMPLOYEES)
        for index, (name, role) in enumerate(_SEED_EMPLOYEES):
            employee = await service.hire_or_update(
                name=name,
                role=role,
                desk=_desk_at(index, total),
            )
            logger.info("시드: %s (%s) id=%s", employee.name, employee.role, employee.id)
        logger.info("직원 %d명 시드 완료: db=%s", total, settings.mongo_db)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
