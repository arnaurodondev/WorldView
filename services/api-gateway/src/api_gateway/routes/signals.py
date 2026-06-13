"""NEWS MOMENTUM route for the API Gateway.

Owns GET /v1/signals/ai — the dashboard "NEWS MOMENTUM" widget feed.

═══════════════════════════════════════════════════════════════════════════════
WHAT THIS IS (2026-06-12 PLAN-0099 W4 — true per-entity momentum)
═══════════════════════════════════════════════════════════════════════════════
Each row is an ENTITY that is gaining (or losing) news attention right now —
NOT a bare article. It answers "which ticker is surging in news coverage, and is
it accelerating?". Per entity, over a rolling window:

  - ``count``       — distinct articles mentioning the entity in [now-W, now]
  - ``prior_count`` — distinct articles in the prior equal window [now-2W, now-W]
  - ``delta`` / ``delta_pct`` — the MOMENTUM/velocity (e.g. +8, ↑200%), the whole
    point of the widget; rows are ranked by surge, not raw recency
  - ``top_article`` — the entity's single most relevant recent headline
    (clickable), with honest ``display_relevance_score`` relevance + sentiment

HISTORY: an earlier version of this route proxied ``/news/top`` and presented a
flat list of recent articles — which duplicated the Portfolio News widget and
carried no "momentum" (surge) information. The data to do this properly
(per-entity article counts over a window) lives in S6's ``entity_mentions`` table
but was not exposed by any endpoint; PLAN-0099 W4 added
``GET /api/v1/news/trending-entities`` (S6) which aggregates it and resolves each
entity to its ticker + canonical_name (dropping macro noise like NASDAQ / "U.S."
/ newswires that have no ticker). This route now simply proxies that endpoint.

═══════════════════════════════════════════════════════════════════════════════
WHY NO KG ENRICHMENT STEP HERE
═══════════════════════════════════════════════════════════════════════════════
The Wave-4 pattern was: gateway proxies S6, then enriches entity_ids → ticker
via the S7 KG batch call. S6's ``/news/trending-entities`` ALREADY resolves
ticker + canonical_name (it holds the intelligence_db session), so the row
arrives complete. The gateway is a stateless proxy (R9: no DB) and adds only the
window snapping + the ``signals`` response-key contract — no extra round-trip.

═══════════════════════════════════════════════════════════════════════════════
RESPONSE CONTRACT (backward compatible with the widget's prop shape)
═══════════════════════════════════════════════════════════════════════════════
``{ "signals": [ MomentumRow, ... ], "window_hours": int }``

Keeping the top-level key ``signals`` preserves the dashboard slot + the frontend
``AiSignalsResponse`` prop contract (the widget reads ``data.signals``). Each
item is now a MOMENTUM ROW:

  entity_id, ticker, name, count, prior_count, delta, delta_pct,
  top_article { id, title, url, source, published_at, sentiment, relevance }

Producing service: S6 nlp-pipeline (``GET /api/v1/news/trending-entities``).
Frontend consumer: apps/worldview-web components/dashboard/AiSignalsWidget.tsx.

ROUTE PRECEDENCE: this router is registered BEFORE ``market_router`` in
``routes/__init__.py`` (FastAPI resolves in registration order), so this handler
supersedes any legacy ``/signals/ai`` handler still present in ``routes/market.py``.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from api_gateway.routes.helpers import _auth_headers, _clients
from observability.logging import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/v1")
logger = get_logger(__name__)

# ── Window selector ───────────────────────────────────────────────────────────
# The widget offers three windows; we constrain the inbound ``hours`` param to
# this whitelist so an arbitrary value can't be passed through to S6. The dev
# corpus is dense enough that 24h is the default (live: 137 ticker'd entities
# with >=2 articles in the last 24h, with real surges) — "right now" is the most
# useful framing for momentum. 72h / 168h broaden the lens for quieter periods.
_ALLOWED_WINDOWS: frozenset[int] = frozenset({24, 72, 168})
_DEFAULT_WINDOW_HOURS = 24

# Normalise the noisy S6 sentiment enum to the three directions the UI renders.
# "mixed" collapses to neutral (we cannot draw a two-headed arrow at 22px); an
# unknown/empty/null sentiment also becomes neutral so the dot is always defined.
_SENTIMENT_MAP: dict[str, str] = {
    "positive": "positive",
    "negative": "negative",
    "neutral": "neutral",
    "mixed": "neutral",
}


def _normalise_sentiment(raw: str | None) -> str:
    """Map an S6 sentiment value to one of positive | negative | neutral.

    Defaults to ``neutral`` for null / "mixed" / unrecognised values so the
    frontend always has a defined direction to render (no undefined dot).
    """
    if not raw:
        return "neutral"
    return _SENTIMENT_MAP.get(raw.strip().lower(), "neutral")


def _to_momentum_row(entity: dict[str, Any]) -> dict[str, Any] | None:
    """Transform one S6 trending-entity into a NEWS MOMENTUM row for the widget.

    Returns ``None`` for a row the widget cannot render or navigate from — one
    with no ticker (defensive; S6 already filters these out). The row carries
    the entity's momentum signal + its top headline. The headline's ``relevance``
    is S6's honest ``display_relevance_score`` composite, never a fabricated
    confidence.
    """
    ticker = entity.get("ticker")
    if not ticker:
        # No ticker → nowhere to navigate; drop (S6 should never emit these).
        return None

    # top_article may be absent if the entity somehow had a count but no
    # joinable article row (defensive — S6 returns it on every row in practice).
    top = entity.get("top_article") or {}
    top_article = {
        "id": str(top.get("id")) if top.get("id") else None,
        "title": top.get("title"),
        "url": top.get("url"),
        "source": top.get("source"),
        "published_at": top.get("published_at"),
        # Direction dot: positive | negative | neutral (mixed/null → neutral).
        "sentiment": _normalise_sentiment(top.get("sentiment")),
        # HONEST relevance: composite of market impact + LLM relevance + routing
        # (PRD-0026 §6.5), 0-1.
        "relevance": top.get("relevance"),
    }
    return {
        "entity_id": str(entity.get("entity_id", "")),
        "ticker": ticker,
        "name": entity.get("name"),
        # Momentum fields — the whole point of the widget.
        "count": entity.get("count"),
        "prior_count": entity.get("prior_count"),
        "delta": entity.get("delta"),
        "delta_pct": entity.get("delta_pct"),
        "top_article": top_article,
    }


@router.get("/signals/ai")
async def ai_signals(
    request: Request,
    limit: int = Query(default=8, ge=1, le=50),
    hours: int = Query(
        default=_DEFAULT_WINDOW_HOURS,
        description="Momentum window in hours. Constrained to the UI options 24 | 72 | 168.",
    ),
) -> Any:
    """NEWS MOMENTUM feed for the dashboard widget.

    Proxies S6's ``/news/trending-entities`` — tradeable entities ranked by
    news-coverage momentum (surge) over the selected window. Each row carries the
    entity's article count, its trend vs the prior equal window, and its most
    relevant recent headline.

    Window: ``hours`` is snapped to the nearest allowed UI option (24 | 72 |
    168); anything else falls back to the 24h default. The response echoes the
    resolved ``window_hours`` so the frontend can confirm which window it got.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)

    # Snap the requested window to an allowed UI option. An out-of-set value
    # (e.g. a hand-crafted ?hours=5) degrades to the safe 24h default rather
    # than passing an arbitrary window downstream.
    window_hours = hours if hours in _ALLOWED_WINDOWS else _DEFAULT_WINDOW_HOURS

    # Proxy S6's per-entity momentum endpoint. S6 ranks by surge and resolves
    # ticker + name + top headline, so the rows arrive ready to render.
    resp = await clients.nlp_pipeline.get(
        "/api/v1/news/trending-entities",
        params={"window_hours": window_hours, "limit": limit},
        headers=headers,
    )
    if resp.status_code != 200:
        # Never fabricate a 200 — pass the upstream status through so the widget
        # can show its (named) error state and offer Retry.
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    try:
        body = json.loads(resp.content)
        entities = body.get("entities", [])
        rows = [row for e in entities if (row := _to_momentum_row(e)) is not None][:limit]
        return {"signals": rows, "window_hours": window_hours}
    except Exception:
        # The transform must never 500 the dashboard. Fall back to the raw S6
        # payload (the frontend treats an unexpected shape as empty).
        logger.warning("ai_signals_transform_failed", exc_info=True)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
