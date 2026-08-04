"""직원 5명 시드. 이름을 신원으로 보는 멱등 실행이라 몇 번 돌려도 5명이다.

책상 좌표는 프론트가 아니라 DB가 가진다. 3D 씬은 이 값을 읽어 배치만 한다.
"""

import asyncio
import logging

from src.config import Settings, get_settings
from src.database import create_mongo_client, init_documents
from src.employees.constants import ROLE_LLM_PROFILES, Role
from src.employees.domain import DeskPosition
from src.employees.repository import EmployeeRepository
from src.employees.service import EmployeeService
from src.llm.profiles import load_profiles

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


def _reject_unknown_role_profiles(settings: Settings) -> None:
    """직무별 프로파일이 카탈로그에 실제로 있는지 확인한다(§8.2).

    이 검증을 `employees` 도메인이 아니라 시드가 하는 이유: `employees`가 `llm`을 알면
    두 도메인이 서로를 참조하게 된다. 스크립트는 조립 지점이라 양쪽을 봐도 된다.
    """
    catalog = load_profiles(settings.llm_profiles_json)
    unknown = {
        role.value: profile for role, profile in ROLE_LLM_PROFILES.items() if profile not in catalog
    }
    if unknown:
        raise SystemExit(
            f"카탈로그에 없는 프로파일을 직무에 배정했습니다: {unknown}. "
            f"사용 가능: {sorted(catalog)}"
        )


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    client = create_mongo_client(settings)
    try:
        await init_documents(client, settings.mongo_db, skip_indexes=True)
        _reject_unknown_role_profiles(settings)
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
