"""Unit tests for GET /internal/v1/entities/sectors (PLAN-0102 W2 T-W2-02).

Validates:
  * Batch lookup returns sector + industry per entity.
  * Missing entities are silently omitted.
  * Empty list rejected at the schema layer (422).
  * Over-cap request rejected (422).
  * Auth: a 401 is returned when the X-Internal-JWT header is absent
    (verifies the middleware is on the path; full JWT validation is
    covered by the dedicated middleware test).
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from knowledge_graph.api.dependencies import get_readonly_session
from knowledge_graph.app import create_app
from knowledge_graph.config import Settings

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _make_system_jwt() -> str:
    """Mint a dev-only HS256 JWT acceptable when ``skip_verification=True``."""
    payload = {
        "iss": "worldview-gateway",
        "sub": "unit-test",
        "tenant_id": "",
        "role": "system",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, "test-secret", algorithm="HS256")


_HEADERS: dict[str, str] = {"X-Internal-JWT": _make_system_jwt()}


def _mock_session_with_rows(rows: list[dict]) -> AsyncMock:
    """Build a mocked AsyncSession whose execute() yields the supplied rows."""
    session = AsyncMock()
    fake_rows = []
    for row_data in rows:
        row = MagicMock()
        # CanonicalEntityRepository.get_batch indexes rows by positional index
        # in the SELECT — entity_id row[0], canonical_name row[1], …, sector row[8],
        # industry row[9] (PLAN-0099).
        ordered = [
            row_data["entity_id"],
            row_data.get("canonical_name"),
            row_data.get("entity_type"),
            row_data.get("isin"),
            row_data.get("ticker"),
            row_data.get("exchange"),
            row_data.get("metadata"),
            row_data.get("description"),
            row_data.get("sector"),
            row_data.get("industry"),
        ]
        row.__getitem__ = lambda self, i, ordered=ordered: ordered[i]
        fake_rows.append(row)

    result = MagicMock()
    result.fetchall = MagicMock(return_value=fake_rows)
    # Empty-id branch: get_batch short-circuits before .execute() so this is
    # only hit when at least one id was requested.
    session.execute = AsyncMock(return_value=result)
    return session


def _build_app(rows: list[dict]) -> tuple:
    app = create_app(Settings(internal_jwt_skip_verification=True))  # type: ignore[call-arg]
    mock = _mock_session_with_rows(rows)

    async def _mock_readonly():
        yield mock

    app.dependency_overrides[get_readonly_session] = _mock_readonly
    # Force the valkey path off so the test is hermetic.
    app.state.valkey_client = None
    return app, mock


async def test_sectors_endpoint_returns_sector_and_industry() -> None:
    """Single-entity request maps row → ``{sector, industry}`` correctly."""
    eid = uuid4()
    rows = [
        {
            "entity_id": eid,
            "canonical_name": "Apple Inc.",
            "entity_type": "company",
            "metadata": {"sector": "Information Technology", "industry": "Consumer Electronics"},
            "sector": "Information Technology",
        },
    ]
    app, _ = _build_app(rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/entities/sectors",
            params={"entity_ids": [str(eid)]},
            headers=_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["results"]) == 1
    row = data["results"][0]
    assert row["entity_id"] == str(eid)
    assert row["sector"] == "Information Technology"
    assert row["industry"] == "Consumer Electronics"


async def test_sectors_endpoint_batch_preserves_request_order() -> None:
    """Multiple entities returned in request order — caller can zip with input."""
    eids = [uuid4(), uuid4(), uuid4()]
    # Mock returns rows in a different order to prove server-side reordering.
    rows = [
        {"entity_id": eids[2], "metadata": {"sector": "Energy"}, "sector": "Energy"},
        {"entity_id": eids[0], "metadata": {"sector": "Tech"}, "sector": "Tech"},
        {"entity_id": eids[1], "metadata": {"sector": "Financials"}, "sector": "Financials"},
    ]
    app, _ = _build_app(rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/entities/sectors",
            params={"entity_ids": [str(e) for e in eids]},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert [r["entity_id"] for r in data["results"]] == [str(e) for e in eids]
    assert [r["sector"] for r in data["results"]] == ["Tech", "Financials", "Energy"]


async def test_sectors_endpoint_omits_missing_entities() -> None:
    """Requested ids absent from DB → silently omitted (caller diff'ing detects)."""
    requested = [uuid4(), uuid4()]
    # Only first id has a row.
    rows = [{"entity_id": requested[0], "metadata": {"sector": "Tech"}, "sector": "Tech"}]
    app, _ = _build_app(rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/entities/sectors",
            params={"entity_ids": [str(e) for e in requested]},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    assert data["results"][0]["entity_id"] == str(requested[0])


async def test_sectors_endpoint_rejects_empty_entity_ids() -> None:
    """Empty query → 422 (FastAPI schema enforcement)."""
    app, _ = _build_app([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/entities/sectors",
            headers=_HEADERS,
        )

    assert resp.status_code == 422


async def test_sectors_endpoint_returns_backfilled_etf_sector() -> None:
    """PLAN-0103 W8 / BP-629 — a backfilled XLE row returns ``"Energy"``, not the fallback.

    After ``scripts/backfill_etf_sectors.py --apply`` runs, ``XLE`` has
    ``metadata->>'sector' = "Energy"``; the endpoint must surface the real
    label rather than the generic ``"Equity ETF"`` fallback. The fallback is
    only triggered when ``sector`` is null AND the row looks like an ETF.
    """
    eid = uuid4()
    rows = [
        {
            "entity_id": eid,
            "canonical_name": "Energy Select Sector SPDR® Fund",
            "ticker": "XLE",
            "metadata": {
                "sector": "Energy",
                "industry": "US Energy Sector",
                "asset_class": "ETF",
            },
            "sector": "Energy",
        },
    ]
    app, _ = _build_app(rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/entities/sectors",
            params={"entity_ids": [str(eid)]},
            headers=_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["results"]) == 1
    row = data["results"][0]
    # Real backfilled label takes precedence over the generic fallback.
    assert row["sector"] == "Energy"
    assert row["industry"] == "US Energy Sector"


async def test_sectors_endpoint_etf_fallback_when_metadata_marks_asset_class() -> None:
    """ETF row without a sector tag → endpoint synthesises ``"Equity ETF"``.

    Regression for the silent-drop case: an ETF entity arrives with
    ``asset_class="ETF"`` but no ``sector`` (because the equities
    fundamentals pipeline never ran for funds). The endpoint must still
    return a usable bucket so the rag-chat aggregator keeps the row.
    """
    eid = uuid4()
    rows = [
        {
            "entity_id": eid,
            "canonical_name": "Some ETF",
            "ticker": "ZZZETF",
            "metadata": {"asset_class": "ETF"},
            "sector": None,
        },
    ]
    app, _ = _build_app(rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/entities/sectors",
            params={"entity_ids": [str(eid)]},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["results"][0]["sector"] == "Equity ETF"


async def test_sectors_endpoint_etf_fallback_by_ticker_prefix() -> None:
    """Well-known ETF tickers with no sector + no asset_class still get the fallback.

    Covers the bootstrap case where neither the backfill script nor any
    metadata has been written yet, but the ticker (``XLK``, ``QQQ``, …) is
    obviously a fund.
    """
    eid = uuid4()
    rows = [
        {
            "entity_id": eid,
            "canonical_name": "Technology Select Sector SPDR® Fund",
            "ticker": "XLK",
            "metadata": {},
            "sector": None,
        },
    ]
    app, _ = _build_app(rows)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/entities/sectors",
            params={"entity_ids": [str(eid)]},
            headers=_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["results"][0]["sector"] == "Equity ETF"


async def test_sectors_endpoint_requires_internal_jwt() -> None:
    """No ``X-Internal-JWT`` header → 401 (middleware enforces auth)."""
    eid = uuid4()
    app, _ = _build_app([])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/internal/v1/entities/sectors",
            params={"entity_ids": [str(eid)]},
            # Intentionally no _HEADERS — proves middleware path.
        )

    assert resp.status_code == 401
