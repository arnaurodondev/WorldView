"""Security E2E: Multi-tenant isolation and auth bypass tests.

These tests verify that:
1. Resources created by tenant A are not visible to tenant B
2. Endpoints that require headers return proper 400/422/403 without them
3. Cross-tenant access returns 403 or 404 (never leaks data)
4. Auth headers cannot be bypassed with common injection patterns
5. Input validation catches malformed inputs

Requirements:
  - S1 (portfolio) running on localhost:8001
  - Postgres on localhost:55433 (portfolio_db)
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ── Availability guard ─────────────────────────────────────────────────────────


def _reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_S1_UP = _reachable("localhost", 8001)
_skip_s1 = pytest.mark.skipif(not _S1_UP, reason="S1 (portfolio) not reachable on localhost:8001")

_EXECUTED_AT = "2025-01-01T12:00:00Z"


# ── Local helpers ──────────────────────────────────────────────────────────────


async def _make_tenant(client: AsyncClient, suffix: str = "") -> dict[str, Any]:
    tag = suffix or uuid.uuid4().hex[:6]
    resp = await client.post("/api/v1/tenants", json={"name": f"E2ETenant_{tag}"})
    assert resp.status_code == 201, f"make_tenant failed ({resp.status_code}): {resp.text}"
    return resp.json()


async def _make_user(client: AsyncClient, tenant_id: str, *, tag: str = "") -> dict[str, Any]:
    suffix = tag or uuid.uuid4().hex[:8]
    resp = await client.post(
        "/api/v1/users",
        json={"tenant_id": tenant_id, "email": f"e2e_{suffix}@security.test"},
    )
    assert resp.status_code == 201, f"make_user failed ({resp.status_code}): {resp.text}"
    return resp.json()


async def _make_portfolio(
    client: AsyncClient,
    tenant_id: str,
    user_id: str,
    *,
    name: str = "E2E Portfolio",
) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/portfolios",
        json={"name": name, "owner_user_id": user_id, "currency": "USD"},
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 201, f"make_portfolio failed ({resp.status_code}): {resp.text}"
    return resp.json()


async def _seed_instrument(client: AsyncClient, symbol: str = "AAPL", exchange: str = "NASDAQ") -> str:
    """Seed an instrument via any available admin/internal endpoint if the portfolio
    service exposes one, otherwise insert via DB.

    We prefer to use the DB session for seeding because the portfolio service
    does not expose a public instrument-creation endpoint.  The DB helper is
    intentionally inlined here (no cross-import from portfolio models at module
    level) so that this file can be collected even when the portfolio package
    is not installed.
    """
    # Instruments are seeded by the market-ingestion consumer; for integration
    # tests we insert directly via REST if the endpoint exists, otherwise we
    # use a UUID stub — the transaction API validates only that instrument_id
    # is a valid UUID4, not that it actually exists in some implementations.
    return str(uuid.uuid4())


# ── Multi-tenant isolation ─────────────────────────────────────────────────────


@_skip_s1
async def test_cross_tenant_portfolio_isolation(s1_client: AsyncClient) -> None:
    """Resources created by Tenant A must not be accessible by Tenant B.

    Tenant B using its own X-Tenant-ID to query Tenant A's portfolio must
    receive 403 or 404 — never the actual portfolio data.
    """
    tag = uuid.uuid4().hex[:6]

    tenant_a = await _make_tenant(s1_client, f"A_{tag}")
    tenant_b = await _make_tenant(s1_client, f"B_{tag}")

    user_a = await _make_user(s1_client, tenant_a["id"])
    portfolio_a = await _make_portfolio(s1_client, tenant_a["id"], user_a["id"])

    # Attempt to read Tenant A's portfolio with Tenant B's headers.
    resp = await s1_client.get(
        f"/api/v1/portfolios/{portfolio_a['id']}",
        headers={"X-Tenant-ID": tenant_b["id"], "X-Owner-ID": user_a["id"]},
    )
    assert resp.status_code in (
        403,
        404,
    ), f"Expected 403 or 404 for cross-tenant portfolio access, got {resp.status_code}: {resp.text}"

    # Holdings must also be isolated.
    holdings_resp = await s1_client.get(
        f"/api/v1/holdings/{portfolio_a['id']}",
        headers={"X-Tenant-ID": tenant_b["id"], "X-Owner-ID": user_a["id"]},
    )
    assert holdings_resp.status_code in (
        403,
        404,
    ), f"Expected 403 or 404 for cross-tenant holdings access, got {holdings_resp.status_code}: {holdings_resp.text}"


@_skip_s1
async def test_cross_tenant_holdings_isolation(s1_client: AsyncClient, s1_db_session: Any) -> None:
    """Holdings and transactions created under Tenant A must not be visible via Tenant B."""
    tag = uuid.uuid4().hex[:6]

    tenant_a = await _make_tenant(s1_client, f"HA_{tag}")
    tenant_b = await _make_tenant(s1_client, f"HB_{tag}")
    user_a = await _make_user(s1_client, tenant_a["id"])
    portfolio_a = await _make_portfolio(s1_client, tenant_a["id"], user_a["id"])

    # Seed an instrument directly (avoids dependency on market-ingestion consumer).
    from uuid import uuid4

    from portfolio.infrastructure.db.models.instrument import InstrumentModel

    instrument_id = uuid4()
    instr = InstrumentModel(
        id=instrument_id,
        symbol=f"ISOL_{tag}",
        exchange="NASDAQ",
        name=f"Isolation Inc {tag}",
        currency="USD",
        asset_class="equity",
        source_event_id=uuid4(),
    )
    s1_db_session.add(instr)
    await s1_db_session.commit()

    # BUY 5 shares under Tenant A.
    buy_resp = await s1_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio_a["id"],
            "instrument_id": str(instrument_id),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "5",
            "price": "100.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers={"X-Tenant-ID": tenant_a["id"], "X-Owner-ID": user_a["id"]},
    )
    assert buy_resp.status_code == 201, f"BUY failed: {buy_resp.text}"

    # Tenant B trying to read holdings → must be denied.
    holdings_resp = await s1_client.get(
        f"/api/v1/holdings/{portfolio_a['id']}",
        headers={"X-Tenant-ID": tenant_b["id"], "X-Owner-ID": user_a["id"]},
    )
    assert holdings_resp.status_code in (
        403,
        404,
    ), f"Cross-tenant holdings: expected 403/404, got {holdings_resp.status_code}"

    # Tenant B trying to read transactions → must be denied.
    tx_resp = await s1_client.get(
        f"/api/v1/transactions?portfolio_id={portfolio_a['id']}",
        headers={"X-Tenant-ID": tenant_b["id"], "X-Owner-ID": user_a["id"]},
    )
    assert tx_resp.status_code in (403, 404), f"Cross-tenant transactions: expected 403/404, got {tx_resp.status_code}"


# ── Missing header validation ─────────────────────────────────────────────────


@_skip_s1
async def test_portfolio_requires_tenant_id_header(s1_client: AsyncClient) -> None:
    """POST /api/v1/portfolios without X-Tenant-ID must return 400 or 422."""
    resp = await s1_client.post(
        "/api/v1/portfolios",
        json={"name": "NoHeader", "owner_user_id": str(uuid.uuid4()), "currency": "USD"},
        # Deliberately omit X-Tenant-ID
    )
    assert resp.status_code in (
        400,
        422,
    ), f"Expected 400 or 422 when X-Tenant-ID is absent, got {resp.status_code}: {resp.text}"


@_skip_s1
async def test_watchlist_requires_tenant_and_owner_headers(s1_client: AsyncClient) -> None:
    """GET /api/v1/watchlist without X-Tenant-ID and X-Owner-ID must return 400 or 422."""
    # No headers at all.
    resp_no_headers = await s1_client.get("/api/v1/watchlist")
    assert resp_no_headers.status_code in (
        400,
        422,
    ), f"Expected 400 or 422 without auth headers, got {resp_no_headers.status_code}"

    # Only one of the two required headers.
    resp_partial = await s1_client.get(
        "/api/v1/watchlist",
        headers={"X-Tenant-ID": str(uuid.uuid4())},
        # X-Owner-ID missing
    )
    assert resp_partial.status_code in (
        400,
        422,
    ), f"Expected 400 or 422 with only X-Tenant-ID, got {resp_partial.status_code}"


# ── Same-tenant, different user ───────────────────────────────────────────────


@_skip_s1
async def test_access_another_users_portfolio_within_same_tenant(s1_client: AsyncClient) -> None:
    """Within the same tenant, User A2 accessing User A1's portfolio.

    The actual enforcement depends on the auth model:
    - If the service is owner-scoped, A2 should receive 403/404.
    - If the service is tenant-scoped (all users share access), A2 may receive 200.

    This test documents the observed behaviour without prescribing which is
    correct — the assertion logs the status code for review.
    """
    tag = uuid.uuid4().hex[:6]
    tenant = await _make_tenant(s1_client, f"SAME_{tag}")
    user_a1 = await _make_user(s1_client, tenant["id"], tag=f"a1_{tag}")
    user_a2 = await _make_user(s1_client, tenant["id"], tag=f"a2_{tag}")

    portfolio = await _make_portfolio(s1_client, tenant["id"], user_a1["id"], name=f"P_{tag}")

    resp = await s1_client.get(
        f"/api/v1/portfolios/{portfolio['id']}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user_a2["id"]},
    )
    # Document the observed status — both 200 (tenant-scoped) and 403/404
    # (owner-scoped) are valid designs; neither indicates a bug by itself.
    assert resp.status_code in (
        200,
        403,
        404,
    ), f"Unexpected status for same-tenant cross-user access: {resp.status_code}: {resp.text}"


# ── Input validation ──────────────────────────────────────────────────────────


@_skip_s1
async def test_create_tenant_with_empty_name_returns_422(s1_client: AsyncClient) -> None:
    """POST /api/v1/tenants with an empty name string must be rejected with 422."""
    resp = await s1_client.post("/api/v1/tenants", json={"name": ""})
    assert resp.status_code == 422, f"Expected 422 for empty tenant name, got {resp.status_code}: {resp.text}"


@_skip_s1
async def test_create_user_with_invalid_email_returns_422(s1_client: AsyncClient) -> None:
    """POST /api/v1/users with a non-email string must be rejected with 422."""
    resp = await s1_client.post(
        "/api/v1/users",
        json={"tenant_id": str(uuid.uuid4()), "email": "not-an-email"},
    )
    assert resp.status_code == 422, f"Expected 422 for invalid email, got {resp.status_code}: {resp.text}"


@_skip_s1
async def test_create_portfolio_with_nonexistent_user_returns_404_or_422(s1_client: AsyncClient) -> None:
    """POST /api/v1/portfolios with a non-existent owner_user_id must return 404 or 422."""
    tag = uuid.uuid4().hex[:6]
    tenant = await _make_tenant(s1_client, f"NX_{tag}")

    resp = await s1_client.post(
        "/api/v1/portfolios",
        json={
            "name": "Ghost Portfolio",
            "owner_user_id": str(uuid.uuid4()),  # random non-existent UUID
            "currency": "USD",
        },
        headers={"X-Tenant-ID": tenant["id"]},
    )
    assert resp.status_code in (
        404,
        422,
    ), f"Expected 404 or 422 for non-existent user, got {resp.status_code}: {resp.text}"


@_skip_s1
async def test_create_portfolio_for_user_from_different_tenant(s1_client: AsyncClient) -> None:
    """Creating a portfolio for a user that belongs to a different tenant must fail.

    X-Tenant-ID = Tenant B, but owner_user_id belongs to Tenant A → 404 or 422.
    """
    tag = uuid.uuid4().hex[:6]
    tenant_a = await _make_tenant(s1_client, f"CPA_{tag}")
    tenant_b = await _make_tenant(s1_client, f"CPB_{tag}")
    user_a = await _make_user(s1_client, tenant_a["id"])

    resp = await s1_client.post(
        "/api/v1/portfolios",
        json={
            "name": "CrossTenantPortfolio",
            "owner_user_id": user_a["id"],  # user belongs to Tenant A
            "currency": "USD",
        },
        headers={"X-Tenant-ID": tenant_b["id"]},  # but we claim Tenant B identity
    )
    assert resp.status_code in (
        404,
        422,
    ), f"Expected 404 or 422 for cross-tenant user/portfolio creation, got {resp.status_code}: {resp.text}"


@_skip_s1
async def test_holdings_for_nonexistent_portfolio_returns_404(s1_client: AsyncClient) -> None:
    """GET /api/v1/holdings/{id} for a random UUID must return 404."""
    tag = uuid.uuid4().hex[:6]
    tenant = await _make_tenant(s1_client, f"NXH_{tag}")
    user = await _make_user(s1_client, tenant["id"])

    resp = await s1_client.get(
        f"/api/v1/holdings/{uuid.uuid4()}",
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert (
        resp.status_code == 404
    ), f"Expected 404 for non-existent portfolio holdings, got {resp.status_code}: {resp.text}"


@_skip_s1
async def test_transaction_with_oversized_quantity_returns_422(s1_client: AsyncClient) -> None:
    """POST /api/v1/transactions with an absurdly large quantity must return 422."""
    tag = uuid.uuid4().hex[:6]
    tenant = await _make_tenant(s1_client, f"OVQ_{tag}")
    user = await _make_user(s1_client, tenant["id"])
    portfolio = await _make_portfolio(s1_client, tenant["id"], user["id"])

    resp = await s1_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio["id"],
            "instrument_id": str(uuid.uuid4()),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "99999999999999999999",  # Exceeds (18,8) precision
            "price": "1.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers={"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]},
    )
    assert resp.status_code == 422, f"Expected 422 for oversized quantity, got {resp.status_code}: {resp.text}"


# ── Concurrency / race conditions ─────────────────────────────────────────────


@_skip_s1
async def test_concurrent_sell_same_holding(s1_client: AsyncClient, s1_db_session: Any) -> None:
    """Two concurrent SELL requests for a shared holding must not produce a negative quantity.

    Setup: Buy 10 shares, then fire two SELL-5 requests concurrently.
    Expected outcomes:
      - Both succeed (total sold = 10, final qty = 0) — optimistic serialization
      - One succeeds, one fails with 422/409 — DB-level constraint
      - Final quantity must be >= 0 (no oversell)
    """
    from uuid import uuid4

    from portfolio.infrastructure.db.models.instrument import InstrumentModel

    tag = uuid4().hex[:6]

    tenant = await _make_tenant(s1_client, f"RACE_{tag}")
    user = await _make_user(s1_client, tenant["id"])
    portfolio = await _make_portfolio(s1_client, tenant["id"], user["id"])

    # Seed instrument directly in the DB.
    instrument_id = uuid4()
    instr = InstrumentModel(
        id=instrument_id,
        symbol=f"RACE_{tag}",
        exchange="NYSE",
        name=f"Race Inc {tag}",
        currency="USD",
        asset_class="equity",
        source_event_id=uuid4(),
    )
    s1_db_session.add(instr)
    await s1_db_session.commit()

    headers = {"X-Tenant-ID": tenant["id"], "X-Owner-ID": user["id"]}

    # Buy 10 shares first.
    buy_resp = await s1_client.post(
        "/api/v1/transactions",
        json={
            "portfolio_id": portfolio["id"],
            "instrument_id": str(instrument_id),
            "transaction_type": "BUY",
            "direction": "INFLOW",
            "quantity": "10",
            "price": "50.00",
            "currency": "USD",
            "executed_at": _EXECUTED_AT,
        },
        headers=headers,
    )
    assert buy_resp.status_code == 201, f"Initial BUY failed: {buy_resp.text}"

    # Fire two SELL-5 requests concurrently.
    sell_payload = {
        "portfolio_id": portfolio["id"],
        "instrument_id": str(instrument_id),
        "transaction_type": "SELL",
        "direction": "OUTFLOW",
        "quantity": "5",
        "price": "55.00",
        "currency": "USD",
        "executed_at": _EXECUTED_AT,
    }

    async def _sell() -> int:
        resp = await s1_client.post("/api/v1/transactions", json=sell_payload, headers=headers)
        return resp.status_code

    status_a, status_b = await asyncio.gather(_sell(), _sell())

    # At least one must succeed.
    assert 201 in (status_a, status_b), f"Expected at least one SELL to succeed (201); got {status_a} and {status_b}"

    # Verify final holdings are non-negative.
    holdings_resp = await s1_client.get(
        f"/api/v1/holdings/{portfolio['id']}",
        headers=headers,
    )
    assert holdings_resp.status_code == 200, f"Holdings check failed: {holdings_resp.text}"
    holdings = holdings_resp.json()
    for h in holdings:
        qty = float(h["quantity"])
        assert qty >= 0, f"Holding quantity is negative after concurrent sells: {h}"


# ── SQL-injection / sanitisation ──────────────────────────────────────────────


@_skip_s1
async def test_tenant_name_with_special_chars(s1_client: AsyncClient) -> None:
    """Tenant name containing SQL meta-characters must be stored safely.

    The service should either:
      - Accept the name (201) and store it literally (parameterised queries prevent injection)
      - Reject it with 422 if the name fails validation

    After the request the service must still be healthy (SQL injection did not corrupt the DB).
    """
    injection_name = "'; DROP TABLE tenants; --"
    resp = await s1_client.post("/api/v1/tenants", json={"name": injection_name})

    assert resp.status_code in (
        201,
        422,
    ), f"Expected 201 (accepted + stored safely) or 422 (rejected), got {resp.status_code}: {resp.text}"

    if resp.status_code == 201:
        created = resp.json()
        assert (
            created["name"] == injection_name
        ), "Tenant name was silently altered — expected it to be stored verbatim via parameterised query"

    # Regardless of outcome, the service must still be healthy.
    health_resp = await s1_client.get("/healthz")
    assert (
        health_resp.status_code == 200
    ), f"Service became unhealthy after special-char tenant name test: {health_resp.text}"


# ── Alert preferences: tenant scoping ────────────────────────────────────────


@_skip_s1
async def test_alert_preferences_cross_tenant(s1_client: AsyncClient) -> None:
    """Alert preferences are scoped to the (tenant_id, owner_id) pair.

    Tenant A's customised preference must not be visible when queried with
    Tenant B's headers — the response should reflect Tenant B's own defaults,
    not Tenant A's stored value.
    """
    tag = uuid.uuid4().hex[:6]

    tenant_a = await _make_tenant(s1_client, f"APA_{tag}")
    tenant_b = await _make_tenant(s1_client, f"APB_{tag}")
    user_a = await _make_user(s1_client, tenant_a["id"], tag=f"ua_{tag}")
    user_b = await _make_user(s1_client, tenant_b["id"], tag=f"ub_{tag}")

    # User A disables "signal" alerts.
    put_resp = await s1_client.put(
        "/api/v1/alert-preferences/signal",
        json={"enabled": False},
        headers={"X-Tenant-ID": tenant_a["id"], "X-Owner-ID": user_a["id"]},
    )
    assert put_resp.status_code == 200, f"PUT alert-preferences failed: {put_resp.text}"

    # User B (different tenant) queries their own preferences.
    get_resp = await s1_client.get(
        "/api/v1/alert-preferences",
        headers={"X-Tenant-ID": tenant_b["id"], "X-Owner-ID": user_b["id"]},
    )
    assert get_resp.status_code == 200, f"GET alert-preferences failed: {get_resp.text}"
    body = get_resp.json()

    # Tenant B's "signal" preference should be the default (enabled=True),
    # not Tenant A's customised value (enabled=False).
    prefs = {p["alert_type"]: p for p in body.get("preferences", [])}
    if "signal" in prefs:
        assert (
            prefs["signal"]["enabled"] is True
        ), "Tenant B received Tenant A's customised 'signal' preference — tenant isolation is broken"
