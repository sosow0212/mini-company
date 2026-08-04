import httpx
from httpx import ASGITransport, AsyncClient
from pymongo.errors import ServerSelectionTimeoutError

from src.main import create_app


class FakeMongo:
    """admin.command("ping")만 흉내내는 경계 대체물. mock 객체가 아니다."""

    def __init__(self, *, reachable: bool) -> None:
        self._reachable = reachable

    @property
    def admin(self) -> "FakeMongo":
        return self

    async def command(self, _name: str) -> dict[str, int]:
        if not self._reachable:
            raise ServerSelectionTimeoutError("no server available")
        return {"ok": 1}


def _milvus_http(*, status_code: int | None) -> httpx.AsyncClient:
    def handle(_request: httpx.Request) -> httpx.Response:
        if status_code is None:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(status_code)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def _client(*, mongo_up: bool, milvus_status: int | None) -> AsyncClient:
    # ASGITransport는 lifespan을 실행하지 않으므로 state를 직접 채운다.
    app = create_app()
    app.state.mongo = FakeMongo(reachable=mongo_up)
    app.state.http = _milvus_http(status_code=milvus_status)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_live_returns_200_when_dependencies_are_down() -> None:
    async with _client(mongo_up=False, milvus_status=None) as client:
        res = await client.get("/health/live")

    assert res.status_code == 200


async def test_ready_returns_200_when_all_dependencies_are_healthy() -> None:
    async with _client(mongo_up=True, milvus_status=200) as client:
        res = await client.get("/health/ready")

    assert res.status_code == 200
    assert res.json() == {"ready": True, "checks": {"mongo": True, "milvus": True}}


async def test_ready_returns_503_when_mongo_is_unreachable() -> None:
    async with _client(mongo_up=False, milvus_status=200) as client:
        res = await client.get("/health/ready")

    assert res.status_code == 503
    assert res.json()["checks"] == {"mongo": False, "milvus": True}


async def test_ready_returns_503_when_milvus_refuses_connection() -> None:
    async with _client(mongo_up=True, milvus_status=None) as client:
        res = await client.get("/health/ready")

    assert res.status_code == 503
    assert res.json()["checks"] == {"mongo": True, "milvus": False}


async def test_ready_returns_503_when_milvus_healthz_is_not_200() -> None:
    async with _client(mongo_up=True, milvus_status=503) as client:
        res = await client.get("/health/ready")

    assert res.status_code == 503
    assert res.json()["checks"] == {"mongo": True, "milvus": False}
