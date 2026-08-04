"""라우터 계층. 인증 잠금과 요청 스키마의 경계가 핵심이다."""

from decimal import Decimal

import pytest
from beanie import PydanticObjectId
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.employees.dependencies import get_employee_repository
from src.ledger.dependencies import get_ledger_repository
from src.llm.dependencies import get_llm_gateway
from src.llm.gateway import LlmGateway
from src.llm.pricing import ModelPrice
from src.llm.profiles import LlmProfile
from src.main import create_app
from src.tasks.dependencies import get_activity_repository, get_task_repository
from tests.fakes.employee_repository import InMemoryEmployeeRepository
from tests.fakes.ledger_repository import InMemoryLedgerRepository
from tests.fakes.llm_provider import FakeLlmProvider
from tests.fakes.task_repository import InMemoryActivityRepository, InMemoryTaskRepository

WORKER_KEY = get_settings().worker_api_key.get_secret_value()
_PROFILE = LlmProfile("cheap", "fake", "cheap-model", 0.2, 1_000)


@pytest.fixture
def client_factory(make_employee):
    def _make(*, employee=None, provider: FakeLlmProvider | None = None):
        app = create_app()
        employee = employee or make_employee("작가 준", llm_profile="cheap")
        gateway = LlmGateway(
            profiles={"cheap": _PROFILE},
            pricing={"cheap-model": ModelPrice(Decimal("0.30"), Decimal("1.20"))},
            providers={"fake": provider or FakeLlmProvider()},
            usd_krw_rate=Decimal("1380"),
            daily_cost_limit_krw=Decimal(0),
        )
        employees = InMemoryEmployeeRepository([employee])
        ledger = InMemoryLedgerRepository()
        tasks = InMemoryTaskRepository()
        activities = InMemoryActivityRepository()
        app.dependency_overrides[get_llm_gateway] = lambda: gateway
        app.dependency_overrides[get_employee_repository] = lambda: employees
        app.dependency_overrides[get_ledger_repository] = lambda: ledger
        app.dependency_overrides[get_task_repository] = lambda: tasks
        app.dependency_overrides[get_activity_repository] = lambda: activities
        client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Worker-Key": WORKER_KEY},
        )
        return client, employee, ledger

    return _make


def _body(employee_id: PydanticObjectId) -> dict:
    return {
        "employeeId": str(employee_id),
        "messages": [{"role": "user", "content": "요약해줘"}],
    }


async def test_completion_returns_401_when_worker_key_is_missing(client_factory) -> None:
    client, employee, _ = client_factory()
    async with client:
        res = await client.post(
            "/internal/v1/llm/completions",
            json=_body(employee.id),
            headers={"X-Worker-Key": ""},
        )

    assert res.status_code == 401


async def test_completion_returns_content_usage_and_cost(client_factory) -> None:
    client, employee, _ = client_factory()
    async with client:
        res = await client.post("/internal/v1/llm/completions", json=_body(employee.id))

    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"content", "profile", "provider", "model", "usage", "costKrw"}
    assert body["profile"] == "cheap"
    assert body["model"] == "cheap-model"
    assert body["usage"] == {"inputTokens": 1_000, "outputTokens": 500}
    # 금액은 문자열로 내려간다.
    assert isinstance(body["costKrw"], str)
    assert Decimal(body["costKrw"]) > 0


async def test_completion_records_cost_in_the_ledger(client_factory) -> None:
    client, employee, ledger = client_factory()
    async with client:
        await client.post("/internal/v1/llm/completions", json=_body(employee.id))

    assert len(await ledger.list(limit=10)) == 1


async def test_completion_ignores_model_sent_by_the_client(client_factory) -> None:
    """요청이 모델을 정할 수 없다. 스키마에 필드가 없으므로 무시된다(ADR-007)."""
    client, employee, _ = client_factory()
    async with client:
        res = await client.post(
            "/internal/v1/llm/completions",
            json={**_body(employee.id), "model": "gpt-4o"},
        )

    assert res.json()["model"] == "cheap-model"


async def test_completion_returns_404_when_employee_is_unknown(client_factory) -> None:
    client, _, _ = client_factory()
    async with client:
        res = await client.post("/internal/v1/llm/completions", json=_body(PydanticObjectId()))

    assert res.status_code == 404
    assert res.json()["code"] == "employee_not_found"


async def test_completion_returns_409_when_employee_profile_is_unknown(
    client_factory, make_employee
) -> None:
    employee = make_employee("유령 프로파일", llm_profile="ghost")
    client, _, _ = client_factory(employee=employee)
    async with client:
        res = await client.post("/internal/v1/llm/completions", json=_body(employee.id))

    assert res.status_code == 409
    assert res.json()["code"] == "llm_profile_not_found"


async def test_completion_returns_502_when_provider_call_fails(
    client_factory, make_employee
) -> None:
    client, employee, _ = client_factory(provider=FakeLlmProvider(fail_models={"cheap-model"}))
    async with client:
        res = await client.post("/internal/v1/llm/completions", json=_body(employee.id))

    assert res.status_code == 502
    assert res.json()["code"] == "llm_call_failed"


async def test_completion_returns_503_when_provider_key_is_missing(client_factory) -> None:
    client, employee, _ = client_factory(provider=FakeLlmProvider(configured=False))
    async with client:
        res = await client.post("/internal/v1/llm/completions", json=_body(employee.id))

    assert res.status_code == 503
    assert res.json()["code"] == "llm_provider_not_configured"


async def test_completion_returns_422_when_messages_are_empty(client_factory) -> None:
    client, employee, _ = client_factory()
    async with client:
        res = await client.post(
            "/internal/v1/llm/completions",
            json={"employeeId": str(employee.id), "messages": []},
        )

    assert res.status_code == 422


async def test_completion_returns_422_when_role_is_not_allowed(client_factory) -> None:
    client, employee, _ = client_factory()
    async with client:
        res = await client.post(
            "/internal/v1/llm/completions",
            json={
                "employeeId": str(employee.id),
                "messages": [{"role": "tool", "content": "x"}],
            },
        )

    assert res.status_code == 422
