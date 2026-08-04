from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from beanie import PydanticObjectId
from pymongo.errors import PyMongoError

from src.config import get_settings
from src.database import create_mongo_client, init_documents
from src.employees.constants import DEFAULT_LLM_PROFILE, EmployeeStatus, Role
from src.employees.domain import DeskPosition, Employee
from src.tasks.constants import ActivityLevel, TaskStatus
from src.tasks.domain import Activity, Task

_HIRED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
_TEST_DB = "mini_company_integration_test"


@pytest.fixture
def make_employee():
    """테스트용 도메인 Employee 빌더. id가 있으면 이미 저장된 직원을 뜻한다."""

    def _make(
        name: str,
        *,
        role: Role = Role.COLLECTOR,
        status: EmployeeStatus = EmployeeStatus.OFFLINE,
        desk: DeskPosition | None = None,
        current_task_id: PydanticObjectId | None = None,
        llm_profile: str = DEFAULT_LLM_PROFILE,
        hired_at: datetime = _HIRED_AT,
        with_id: bool = True,
    ) -> Employee:
        return Employee(
            id=PydanticObjectId() if with_id else None,
            name=name,
            role=role,
            status=status,
            desk=desk or DeskPosition(x=0.0, y=0.0, z=0.0),
            current_task_id=current_task_id,
            llm_profile=llm_profile,
            hired_at=hired_at,
        )

    return _make


@pytest.fixture
def make_task():
    """테스트용 도메인 Task 빌더. 기본은 이미 저장된 RUNNING 작업."""

    def _make(
        employee_id: PydanticObjectId | None = None,
        *,
        kind: str = "collect_market_data",
        status: TaskStatus = TaskStatus.RUNNING,
        summary: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        created_at: datetime = _HIRED_AT,
        with_id: bool = True,
    ) -> Task:
        return Task(
            id=PydanticObjectId() if with_id else None,
            employee_id=employee_id or PydanticObjectId(),
            kind=kind,
            status=status,
            summary=summary,
            started_at=started_at,
            finished_at=finished_at,
            error=error,
            created_at=created_at,
        )

    return _make


@pytest.fixture
def make_activity():
    """테스트용 도메인 Activity 빌더. 기본은 이미 저장된 INFO 활동."""

    def _make(
        employee_id: PydanticObjectId | None = None,
        *,
        task_id: PydanticObjectId | None = None,
        level: ActivityLevel = ActivityLevel.INFO,
        message: str = "수집을 시작한다",
        occurred_at: datetime = _HIRED_AT,
        with_id: bool = True,
    ) -> Activity:
        return Activity(
            id=PydanticObjectId() if with_id else None,
            employee_id=employee_id or PydanticObjectId(),
            task_id=task_id,
            level=level,
            message=message,
            occurred_at=occurred_at,
        )

    return _make


@pytest.fixture
async def mongo_repository_ready() -> AsyncIterator[None]:
    """실제 Mongo에 Beanie를 바인딩한다. 인프라가 없으면 스킵한다.

    인덱스도 함께 만든다(skip_indexes=False) — unique 제약이 실제로 걸리는지
    계약 테스트에서 확인할 수 있어야 한다.
    """
    settings = get_settings()
    client = create_mongo_client(settings)
    try:
        server_info = await client.admin.command("hello")
    except PyMongoError:
        await client.close()
        pytest.skip("Mongo가 필요하다. `make up`으로 인프라를 띄운다.")

    if server_info.get("setName") is None:
        # 로컬에 설치된 standalone mongod에 붙으면 replica set 전용 기능이 없는데도
        # 테스트가 통과해 버린다. 엉뚱한 서버에 붙었다는 사실을 여기서 잡는다.
        await client.close()
        pytest.fail(
            f"replica set이 아닌 Mongo에 붙었다: {settings.mongo_uri}\n"
            "compose mongo(27018)를 가리키는지 .env를 확인한다."
        )

    try:
        # 순서가 중요하다. drop을 나중에 하면 방금 만든 인덱스까지 날아가고,
        # unique 제약을 검증하는 테스트가 조용히 통과한다.
        await client.drop_database(_TEST_DB)
        await init_documents(client, _TEST_DB, skip_indexes=False)
        yield
    finally:
        await client.drop_database(_TEST_DB)
        await client.close()
