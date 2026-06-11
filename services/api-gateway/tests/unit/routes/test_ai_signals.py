"""Tests for routes/signals.py — the enriched GET /v1/signals/ai feed.

Covers the 2026-06-10 AI-Signals overhaul:
- dedup per (entity_id, doc_id) keeping the most informative claim
- nil-UUID entity rows dropped
- polarity-first label resolution (Avro polarity beats signal_type heuristic)
- KG enrichment carries ticker AND canonical_name
- KG-unknown entities dropped (no more UUID-prefix "9ECB" labels)
- KG outage degrades gracefully (rows kept, ticker/name None)
- signal_type humanization + market_impact_score passthrough
- limit trimming + over-fetch from S6
- route precedence: signals.py supersedes the legacy market.py handler
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest
from api_gateway.routes.signals import (
    _dedup_signals,
    _humanize_signal_type,
    _resolve_label,
)
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_JWT_SECRET = "test-secret"  # noqa: S105
_NIL = "00000000-0000-0000-0000-000000000000"


def _make_jwt() -> str:
    return jwt.encode({"sub": "user-1", "tenant_id": "t-1", "exp": 9999999999}, _JWT_SECRET, algorithm="HS256")


def _mock_response(status: int, content: bytes = b"{}") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.content = content
    resp.text = content.decode()
    resp.json.return_value = json.loads(content)
    return resp


def _s6_item(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "signal_id": "sig-1",
        "doc_id": "doc-1",
        "entity_id": "ent-1",
        "signal_type": "EARNINGS_RELEASE",
        "confidence": 0.95,
        "evidence_text": "claim-uuid",
        "detected_at": "2026-06-10T12:00:00Z",
        "market_impact_score": 0.0,
        "polarity": "neutral",
    }
    base.update(overrides)
    return base


def _s6_payload(items: list[dict[str, object]]) -> bytes:
    return json.dumps({"items": items, "total": len(items), "limit": 50, "offset": 0}).encode()


async def _call(authed_app, params: str = "") -> httpx.Response:
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/v1/signals/ai{params}",
            headers={"Authorization": f"Bearer {_make_jwt()}"},
        )


# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_resolve_label_prefers_decisive_polarity() -> None:
    """A non-neutral Avro polarity beats the signal_type heuristic."""
    # EARNINGS_RELEASE maps NEUTRAL by type, but the claim was judged negative.
    assert _resolve_label("negative", "EARNINGS_RELEASE") == "NEGATIVE"
    assert _resolve_label("positive", "EARNINGS_RELEASE") == "POSITIVE"


def test_resolve_label_falls_back_to_type_map_when_neutral() -> None:
    """Neutral/legacy polarity defers to the type→direction mapping."""
    assert _resolve_label("neutral", "M_AND_A") == "POSITIVE"
    assert _resolve_label("", "GUIDANCE_CUT") == "NEGATIVE"
    assert _resolve_label("neutral", "EARNINGS_RELEASE") == "NEUTRAL"


def test_humanize_signal_type_known_and_fallback() -> None:
    assert _humanize_signal_type("M_AND_A") == "M&A"
    assert _humanize_signal_type("EARNINGS_RELEASE") == "Earnings"
    # Unknown enum members degrade to readable words, never SNAKE_CASE.
    assert _humanize_signal_type("SUPPLY_CHAIN_DISRUPTION") == "Supply chain disruption"
    assert _humanize_signal_type("") == "News event"


def test_dedup_keeps_directional_claim_over_neutral() -> None:
    """GILD pattern: same article emits NEUTRAL 0.95 + POSITIVE 0.90 → keep POSITIVE."""
    neutral = _s6_item(signal_id="a", polarity="neutral", confidence=0.95)
    positive = _s6_item(signal_id="b", polarity="positive", confidence=0.90)
    survivors = _dedup_signals([neutral, positive])
    assert len(survivors) == 1
    assert survivors[0]["signal_id"] == "b"


def test_dedup_keeps_higher_confidence_within_same_directionality() -> None:
    low = _s6_item(signal_id="a", polarity="positive", confidence=0.80)
    high = _s6_item(signal_id="b", polarity="positive", confidence=0.95)
    survivors = _dedup_signals([low, high])
    assert len(survivors) == 1
    assert survivors[0]["signal_id"] == "b"


def test_dedup_preserves_distinct_entity_or_doc() -> None:
    """Different articles (or entities) are NOT collapsed — only true dupes are."""
    a = _s6_item(signal_id="a", doc_id="doc-1")
    b = _s6_item(signal_id="b", doc_id="doc-2")
    c = _s6_item(signal_id="c", doc_id="doc-1", entity_id="ent-2")
    assert len(_dedup_signals([a, b, c])) == 3


# ── Route behaviour ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_signals_requires_auth(app, mock_clients) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/signals/ai")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_enriched_payload_shape(authed_app, authed_mock_clients) -> None:
    """Happy path: KG + content-store both resolve → full enriched signal."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            _s6_payload([_s6_item(polarity="negative", signal_type="EARNINGS_GUIDANCE", market_impact_score=0.12)]),
        ),
    )
    authed_mock_clients.knowledge_graph.post = AsyncMock(
        return_value=_mock_response(
            200,
            json.dumps(
                {"entities": [{"entity_id": "ent-1", "ticker": "LULU", "canonical_name": "Lululemon Athletica"}]},
            ).encode(),
        ),
    )
    authed_mock_clients.content_store.post = AsyncMock(
        return_value=_mock_response(
            200,
            json.dumps(
                {
                    "documents": [
                        {
                            "doc_id": "doc-1",
                            "title": "Lululemon Cuts Outlook",
                            "url": "https://example.com/lulu",
                            "source_name": "Yahoo Finance",
                            "published_at": "2026-06-10T11:00:00Z",
                        },
                    ],
                },
            ).encode(),
        ),
    )

    resp = await _call(authed_app)
    assert resp.status_code == 200
    sig = resp.json()["signals"][0]
    assert sig["ticker"] == "LULU"
    assert sig["entity_name"] == "Lululemon Athletica"
    # Polarity (negative) overrides the directionless EARNINGS_GUIDANCE type.
    assert sig["label"] == "NEGATIVE"
    assert sig["polarity"] == "negative"
    assert sig["signal_type"] == "EARNINGS_GUIDANCE"
    assert sig["signal_type_label"] == "Guidance"
    assert sig["score"] == 0.95
    assert sig["market_impact_score"] == 0.12
    assert sig["article_title"] == "Lululemon Cuts Outlook"
    assert sig["article_url"] == "https://example.com/lulu"
    assert sig["source_name"] == "Yahoo Finance"
    assert sig["published_at"] == "2026-06-10T11:00:00Z"
    assert sig["created_at"] == "2026-06-10T12:00:00Z"


@pytest.mark.asyncio
async def test_kg_unknown_entities_are_dropped(authed_app, authed_mock_clients) -> None:
    """KG answered but does not know ent-2 → that row is dropped, never a UUID stub."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            _s6_payload(
                [
                    _s6_item(signal_id="a", entity_id="ent-1"),
                    _s6_item(signal_id="b", entity_id="ent-2", doc_id="doc-2"),
                ],
            ),
        ),
    )
    authed_mock_clients.knowledge_graph.post = AsyncMock(
        return_value=_mock_response(
            200,
            json.dumps(
                {"entities": [{"entity_id": "ent-1", "ticker": "AAPL", "canonical_name": "Apple Inc."}]},
            ).encode(),
        ),
    )
    authed_mock_clients.content_store.post = AsyncMock(return_value=_mock_response(200, b'{"documents": []}'))

    resp = await _call(authed_app)
    signals = resp.json()["signals"]
    assert [s["signal_id"] for s in signals] == ["a"]


@pytest.mark.asyncio
async def test_kg_outage_keeps_rows_unenriched(authed_app, authed_mock_clients) -> None:
    """KG 500 → kg_ok False → rows survive with ticker/name None (graceful degradation)."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(200, _s6_payload([_s6_item()])),
    )
    authed_mock_clients.knowledge_graph.post = AsyncMock(return_value=_mock_response(500, b"{}"))
    authed_mock_clients.content_store.post = AsyncMock(return_value=_mock_response(200, b'{"documents": []}'))

    resp = await _call(authed_app)
    signals = resp.json()["signals"]
    assert len(signals) == 1
    assert signals[0]["ticker"] is None
    assert signals[0]["entity_name"] is None


@pytest.mark.asyncio
async def test_nil_uuid_entities_are_dropped(authed_app, authed_mock_clients) -> None:
    """Rows with the nil-UUID placeholder entity carry no information → dropped."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(
        return_value=_mock_response(
            200,
            _s6_payload(
                [
                    _s6_item(signal_id="a", entity_id=_NIL),
                    _s6_item(signal_id="b", entity_id="ent-1"),
                ],
            ),
        ),
    )
    authed_mock_clients.knowledge_graph.post = AsyncMock(return_value=_mock_response(500, b"{}"))
    authed_mock_clients.content_store.post = AsyncMock(return_value=_mock_response(200, b'{"documents": []}'))

    resp = await _call(authed_app)
    assert [s["signal_id"] for s in resp.json()["signals"]] == ["b"]


@pytest.mark.asyncio
async def test_limit_trims_and_overfetches(authed_app, authed_mock_clients) -> None:
    """?limit=2 → returns 2 signals but asks S6 for 4x the budget (dedup headroom)."""
    items = [_s6_item(signal_id=f"s{i}", doc_id=f"doc-{i}", entity_id=f"ent-{i}") for i in range(6)]
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(200, _s6_payload(items)))
    authed_mock_clients.knowledge_graph.post = AsyncMock(return_value=_mock_response(500, b"{}"))
    authed_mock_clients.content_store.post = AsyncMock(return_value=_mock_response(200, b'{"documents": []}'))

    resp = await _call(authed_app, "?limit=2")
    assert len(resp.json()["signals"]) == 2
    call_kwargs = authed_mock_clients.nlp_pipeline.get.call_args[1]
    assert call_kwargs["params"]["limit"] == 8  # 2 * 4 over-fetch


@pytest.mark.asyncio
async def test_s6_error_passes_through(authed_app, authed_mock_clients) -> None:
    """Upstream S6 failure → status passthrough, never a fabricated 200."""
    authed_mock_clients.nlp_pipeline.get = AsyncMock(return_value=_mock_response(503, b'{"detail": "down"}'))
    resp = await _call(authed_app)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_route_supersedes_legacy_market_handler(authed_app) -> None:
    """Registration order: /v1/signals/ai must resolve to routes.signals.ai_signals.

    Guards the shadowing contract — if market_router is ever registered before
    signals_router the legacy un-enriched handler silently takes over.
    """
    for route in authed_app.routes:
        if getattr(route, "path", None) == "/v1/signals/ai":
            assert route.endpoint.__module__ == "api_gateway.routes.signals"
            break
    else:
        pytest.fail("/v1/signals/ai route not found")
