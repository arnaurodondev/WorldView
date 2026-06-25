"""E2E — rag-chat (S8) authenticated core happy-path smoke.

Complements the security-boundary rejection matrix: with a *fully valid* RS256
internal JWT, a guarded core endpoint must pass the middleware and return a
well-formed response. We target ``POST /internal/v1/briefings`` because it is a
real guarded route whose use case (``app.state.briefing_uc``) we can stub to a
deterministic result — so the test exercises middleware → route → response
serialisation end to end without LLM/infra dependencies.

Marked ``integration`` (e2e tier); runs in-process via ASGITransport.
"""

from __future__ import annotations

from typing import Any

import pytest

import common.time  # type: ignore[import-untyped]

pytestmark = pytest.mark.integration

_BRIEFING_PATH = "/internal/v1/briefings"


class _StubBriefingUseCase:
    """Deterministic stand-in for GenerateBriefingUseCase.execute()."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {
            "narrative": "Your portfolio is concentrated in mega-cap tech [c1].",
            "risk_summary": {"headline": "Elevated single-sector exposure.", "level": "high"},
            "citations": [{"id": "c1", "text": "AAPL is 42% of holdings."}],
            "generated_at": common.time.utc_now().isoformat(),
        }


def _briefing_body() -> dict[str, Any]:
    return {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "tenant_id": "00000000-0000-0000-0000-000000000002",
        "portfolio_context": {"total_value": 100000.0},
        "market_snapshots": [{"symbol": "AAPL"}],
        "active_signals": [],
        "lookback_days": 7,
    }


async def test_valid_jwt_briefing_returns_well_formed_response(app, client, mint_token) -> None:
    """Valid RS256 JWT → 200 + well-formed briefing payload (middleware passes through)."""
    stub = _StubBriefingUseCase()
    app.state.briefing_uc = stub

    resp = await client.post(
        _BRIEFING_PATH,
        json=_briefing_body(),
        headers={"X-Internal-JWT": mint_token()},
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    # Well-formed: every field of BriefingResponse the route constructs is present.
    assert payload["narrative"].startswith("Your portfolio")
    assert payload["risk_summary"]["level"] == "high"
    assert isinstance(payload["citations"], list)
    assert payload["citations"][0]["id"] == "c1"
    assert payload["generated_at"]

    # And the route actually drove the use case (not a short-circuited 401/empty).
    assert len(stub.calls) == 1
    assert str(stub.calls[0]["user_id"]) == "00000000-0000-0000-0000-000000000001"


async def test_briefing_without_jwt_is_rejected_before_use_case(app, unauth_client) -> None:
    """Same route with NO token → 401 and the use case is never invoked."""
    stub = _StubBriefingUseCase()
    app.state.briefing_uc = stub

    resp = await unauth_client.post(_BRIEFING_PATH, json=_briefing_body())

    assert resp.status_code == 401
    assert stub.calls == []  # boundary stopped the request before the route body
