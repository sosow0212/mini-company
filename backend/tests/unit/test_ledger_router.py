"""라우터 계층 검증. 인증 잠금, 금액의 문자열 직렬화, 도메인 예외 → HTTP 번역."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from beanie import PydanticObjectId
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.ledger.constants import CATEGORY_UNITS, LedgerCategory
from src.ledger.dependencies import get_ledger_repository
from src.ledger.domain import LedgerEntry
from src.main import create_app
from tests.fakes.ledger_repository import InMemoryLedgerRepository

WORKER_KEY = get_settings().worker_api_key.get_secret_value()
_NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)


def _entry(category: LedgerCategory, amount: str, **overrides) -> LedgerEntry:
    return LedgerEntry(
        id=PydanticObjectId(),
        category=category,
        amount=Decimal(amount),
        unit=CATEGORY_UNITS[category],
        occurred_at=_NOW,
        **overrides,
    )


@pytest.fixture
def client_factory():
    def _make(*entries: LedgerEntry) -> AsyncClient:
        app = create_app()
        # 인스턴스를 클로저에 고정한다. 요청마다 새 fake면 이전 요청의 기록이 사라진다.
        repository = InMemoryLedgerRepository(list(entries))
        app.dependency_overrides[get_ledger_repository] = lambda: repository
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Worker-Key": WORKER_KEY},
        )

    return _make


# ─── 인증 ──────────────────────────────────────────────────────


async def test_record_entry_returns_401_when_worker_key_is_missing(client_factory) -> None:
    async with client_factory() as client:
        res = await client.post(
            "/internal/v1/ledger/entries",
            json={"category": "REVENUE", "amount": "1000", "occurredAt": _NOW.isoformat()},
            headers={"X-Worker-Key": ""},
        )

    assert res.status_code == 401


async def test_reverse_entry_returns_401_when_worker_key_is_missing(client_factory) -> None:
    async with client_factory() as client:
        res = await client.post(
            f"/internal/v1/ledger/entries/{PydanticObjectId()}/reversal",
            json={},
            headers={"X-Worker-Key": ""},
        )

    assert res.status_code == 401


async def test_summary_is_public_and_needs_no_worker_key(client_factory) -> None:
    async with client_factory() as client:
        res = await client.get("/api/v1/ledger/summary", headers={"X-Worker-Key": ""})

    assert res.status_code == 200


# ─── 기록 ──────────────────────────────────────────────────────


async def test_record_entry_returns_201_with_server_assigned_unit(client_factory) -> None:
    async with client_factory() as client:
        res = await client.post(
            "/internal/v1/ledger/entries",
            json={"category": "VIEWS", "amount": "1200", "occurredAt": _NOW.isoformat()},
        )

    assert res.status_code == 201
    body = res.json()
    assert body["unit"] == "count"
    assert body["amount"] == "1200"


async def test_record_entry_ignores_unit_sent_by_the_client(client_factory) -> None:
    """단위는 카테고리가 결정한다. 요청이 우겨도 서버 값이 이긴다."""
    async with client_factory() as client:
        res = await client.post(
            "/internal/v1/ledger/entries",
            json={
                "category": "REVENUE",
                "amount": "1000",
                "occurredAt": _NOW.isoformat(),
                "unit": "USD",
            },
        )

    assert res.json()["unit"] == "KRW"


async def test_record_entry_keeps_precision_when_amount_is_sent_as_string(
    client_factory,
) -> None:
    async with client_factory() as client:
        res = await client.post(
            "/internal/v1/ledger/entries",
            json={
                "category": "REVENUE",
                "amount": "82860000.55",
                "occurredAt": _NOW.isoformat(),
            },
        )

    assert res.json()["amount"] == "82860000.55"


async def test_record_entry_returns_422_when_category_is_unknown(client_factory) -> None:
    async with client_factory() as client:
        res = await client.post(
            "/internal/v1/ledger/entries",
            json={"category": "BONUS", "amount": "1000", "occurredAt": _NOW.isoformat()},
        )

    assert res.status_code == 422


async def test_record_entry_returns_422_when_amount_is_not_a_number(client_factory) -> None:
    async with client_factory() as client:
        res = await client.post(
            "/internal/v1/ledger/entries",
            json={"category": "REVENUE", "amount": "많이", "occurredAt": _NOW.isoformat()},
        )

    assert res.status_code == 422


# ─── 역분개 ────────────────────────────────────────────────────


async def test_reverse_entry_returns_201_with_opposite_amount(client_factory) -> None:
    original = _entry(LedgerCategory.REVENUE, "82860000")

    async with client_factory(original) as client:
        res = await client.post(
            f"/internal/v1/ledger/entries/{original.id}/reversal",
            json={"memo": "중복 정산 취소"},
        )

    assert res.status_code == 201
    body = res.json()
    assert body["amount"] == "-82860000"
    assert body["reversesId"] == str(original.id)


async def test_reverse_entry_returns_404_when_entry_is_unknown(client_factory) -> None:
    async with client_factory() as client:
        res = await client.post(
            f"/internal/v1/ledger/entries/{PydanticObjectId()}/reversal", json={}
        )

    assert res.status_code == 404
    assert res.json()["code"] == "ledger_entry_not_found"


async def test_reverse_entry_returns_409_when_entry_is_already_reversed(client_factory) -> None:
    original = _entry(LedgerCategory.REVENUE, "1000")
    reversal = _entry(LedgerCategory.REVENUE, "-1000", reverses_id=original.id)

    async with client_factory(original, reversal) as client:
        res = await client.post(f"/internal/v1/ledger/entries/{original.id}/reversal", json={})

    assert res.status_code == 409
    assert res.json()["code"] == "entry_already_reversed"


async def test_reverse_entry_returns_409_when_target_is_itself_a_reversal(
    client_factory,
) -> None:
    original = _entry(LedgerCategory.REVENUE, "1000")
    reversal = _entry(LedgerCategory.REVENUE, "-1000", reverses_id=original.id)

    async with client_factory(original, reversal) as client:
        res = await client.post(f"/internal/v1/ledger/entries/{reversal.id}/reversal", json={})

    assert res.status_code == 409
    assert res.json()["code"] == "cannot_reverse_reversal"


# ─── 집계 응답 ─────────────────────────────────────────────────


async def test_summary_serializes_amounts_as_strings_in_camel_case(client_factory) -> None:
    async with client_factory(_entry(LedgerCategory.REVENUE, "82860000")) as client:
        res = await client.get("/api/v1/ledger/summary", params={"period": "all"})

    body = res.json()
    assert set(body) == {"period", "start", "end", "totals", "net"}
    assert body["totals"]["REVENUE"] == "82860000"
    assert isinstance(body["net"], str)


async def test_summary_defaults_to_monthly_period(client_factory) -> None:
    async with client_factory() as client:
        res = await client.get("/api/v1/ledger/summary")

    assert res.json()["period"] == "monthly"


async def test_summary_returns_422_when_period_is_unknown(client_factory) -> None:
    async with client_factory() as client:
        res = await client.get("/api/v1/ledger/summary", params={"period": "weekly"})

    assert res.status_code == 422
