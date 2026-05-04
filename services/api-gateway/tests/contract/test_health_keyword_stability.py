"""Monitoring contract test — /healthz keyword stability.

WHY THIS EXISTS:
UptimeRobot monitors /healthz with keyword check `"status":"ok"`. If any PR
changes the response shape (e.g. wraps it in {"data": {"status": "ok"}}), the
keyword check silently breaks and UptimeRobot stops alerting on outages.
This test catches the regression at PR time, before the monitor is blind.

NOT a functional test (test_health.py covers that). This is specifically
a *monitoring contract* — the literal substring that UptimeRobot searches for.

PLAN-0065 T-E-01, PRD-0034 §3 FR-T3-1
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_healthz_returns_200(client) -> None:
    """Liveness probe must return HTTP 200 — prerequisite for UptimeRobot."""
    response = await client.get("/healthz")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_healthz_contains_status_ok_literal(client) -> None:
    """UptimeRobot keyword check requires literal `"status":"ok"` in the body.

    WHY literal substring check (not JSON parse): UptimeRobot's keyword monitor
    searches the raw response body as a string, not parsed JSON. The monitor
    fires when the exact bytes `"status":"ok"` are absent. This test mirrors
    that exact check so a JSON restructure that changes key ordering or adds
    wrapping objects is caught here before it silently breaks the monitor.
    """
    response = await client.get("/healthz")
    raw_body = response.text

    # The monitoring contract: this exact substring must appear in the body.
    # FastAPI serialises {"status": "ok"} as `{"status":"ok"}` (no spaces).
    assert '"status":"ok"' in raw_body, (
        f'UptimeRobot keyword "status":"ok" not found in /healthz response body.\n'
        f"Actual body: {raw_body!r}\n"
        f"If you changed the response shape, update the UptimeRobot monitor keyword too."
    )


@pytest.mark.asyncio
async def test_healthz_body_is_valid_json(client) -> None:
    """Sanity: /healthz must return parseable JSON (not plain text or HTML)."""
    response = await client.get("/healthz")
    try:
        parsed = json.loads(response.text)
    except json.JSONDecodeError as exc:
        pytest.fail(f"/healthz response is not valid JSON: {exc}\nBody: {response.text!r}")
    assert isinstance(parsed, dict), f"Expected JSON object, got {type(parsed).__name__}"
