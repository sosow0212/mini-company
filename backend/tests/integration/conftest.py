from collections.abc import AsyncIterator

import pytest
from pymongo.errors import PyMongoError

from src.config import get_settings
from src.database import create_mongo_client, init_documents

_TEST_DB = "mini_company_integration_test"


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
        # 로컬에 설치된 standalone mongod에 붙으면 트랜잭션·change stream이 없는데도
        # Phase 1 테스트는 통과해버린다. 엉뚱한 서버에 붙었다는 사실을 여기서 잡는다.
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
