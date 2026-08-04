from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.main import create_app

WORKER_KEY = get_settings().worker_api_key.get_secret_value()


@pytest.fixture
async def client(mongo_repository_ready: None) -> AsyncIterator[AsyncClient]:
    """실제 Mongo에 붙은 실제 DI 그래프의 앱.

    e2e는 fake로 아무것도 바꾸지 않는다. Beanie가 테스트 DB에 바인딩된 상태(mongo_repository_ready)
    위에서 기본 DI(실제 repository)를 그대로 쓴다.
    lifespan은 실행하지 않는다 — ASGITransport는 lifespan을 돌리지 않고,
    Beanie 바인딩은 fixture가 이미 핸들링했다.
    """
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Worker-Key": WORKER_KEY},
    ) as client:
        yield client
