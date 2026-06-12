"""AI Signals route for the API Gateway — NEWS MOMENTUM feed.

Owns GET /v1/signals/ai — the dashboard "AI SIGNALS" widget feed.

═══════════════════════════════════════════════════════════════════════════════
WHY THIS WAS REWRITTEN (2026-06-12 Wave-4 News-Momentum pivot)
═══════════════════════════════════════════════════════════════════════════════
The previous version of this route proxied S6's ``nlp.signal.detected.v1``
extraction claims (``GET /api/v1/signals``) and presented them as a feed of
"AI signals". The user's verdict on that widget: it surfaced *internal pipeline
state, not user-relevant information*. Concretely:

  - the headline number was the LLM **extraction confidence** (how sure the
    model was that an event was *stated* in an article). Live values are pinned
    at 0.90/0.95 — a constant, meaningless decoration that READ like a price
    prediction;
  - the row labels ("NEWS EVENT", "CORP ACTION", "EARNINGS") were opaque
    pipeline event-type enums, not something a user acts on;
  - the feed answered "what did the extractor emit?" — an engineer's question,
    not "what is moving in the news right now?", the user's question.

This rewrite pivots the feed to **NEWS MOMENTUM**: the most relevant *recent
news* in a user-selected time window. Each row is a real article that the user
can read, with an HONEST relevance score and a sentiment direction.

═══════════════════════════════════════════════════════════════════════════════
DATA INVENTORY (live, 2026-06-12) — why this is the truthful feed we can build
═══════════════════════════════════════════════════════════════════════════════
Investigated what "news occurrences per entity over a window" data exists:

  * ``entity_mentions`` (S6 nlp_db) — 80,762 resolved mentions over 5,802
    entities. A ``GROUP BY resolved_entity_id`` over a 72h window gives a clean
    "top entities by article count" ranking (NVDA 49, AMD …). This is the
    IDEAL per-entity-occurrence-count feed the user described.
  * BUT: the api-gateway is a **stateless proxy with no database** (R9: no
    cross-service DB access), and **no S6 endpoint aggregates entity news
    counts** — ``/news/top`` exposes ``primary_entity_symbol`` only for
    impact-labelled articles (36 of 6,212 in 7 days; 0 of the top-40 ranked).
    So the per-entity-count feed is NOT buildable today without a new S6
    endpoint. See the "ROADMAP" section at the bottom of this file.
  * Pure "most-mentioned entity" ranking is ALSO unattractive on its own: the
    top entities by raw mention count are macro noise (NASDAQ, NYSE, "U.S.",
    "S&P 500", a newswire "GLOBE NEWSWIRE") with no ticker and nowhere to
    navigate — not what a user wants front-and-centre.

  * ``GET /api/v1/news/top`` (S6 nlp-pipeline), which the gateway already
    proxies, IS rich and reliable for "what is moving in the news":
      - ``title`` + ``url``         — 100% populated (real, clickable events)
      - ``display_relevance_score`` — 100% populated; a real composite of
        market impact + LLM relevance + routing score (PRD-0026 §6.5). This is
        the honest replacement for the fake 95% extraction confidence.
      - ``sentiment``               — populated on ~52% of articles
        (positive | negative | neutral | mixed) → drives the direction dot.
      - ``published_at``            — drives recency.
      - window support              — ``hours`` param 1-168 (24h / 72h / 168h),
        which powers the widget's window selector.
      - ``source_name`` is EMPTY in the data, so we derive a short publisher
        label from the URL host instead (see ``_source_from_url``).

CONCLUSION: the truthful, user-relevant feed buildable TODAY is a
``/news/top``-backed **NEWS MOMENTUM** list (recent, relevant, clickable
articles with real relevance + sentiment). The per-entity-count "AI signals"
feed is on the roadmap pending a small S6 aggregation endpoint.

═══════════════════════════════════════════════════════════════════════════════
RESPONSE CONTRACT (backward compatible with the widget's prop shape)
═══════════════════════════════════════════════════════════════════════════════
``{ "signals": [ NewsMomentumItem, ... ], "window_hours": int }``

Keeping the top-level key ``signals`` preserves the dashboard slot + the
frontend ``AiSignalsResponse`` prop contract (the widget reads ``data.signals``).
Each item now carries NEWS-MOMENTUM fields (all additive vs. the legacy shape,
so a stale frontend degrades gracefully):

  article_id, title, url, source, published_at, sentiment ("positive" |
  "negative" | "neutral"), relevance (0-1 display_relevance_score),
  routing_tier, market_impact_score (0-1 | null).

Producing service: S6 nlp-pipeline (``GET /api/v1/news/top``).
Frontend consumer: apps/worldview-web components/dashboard/AiSignalsWidget.tsx.

ROUTE PRECEDENCE: this router is registered BEFORE ``market_router`` in
``routes/__init__.py`` (FastAPI resolves in registration order), so this handler
supersedes the legacy ``/signals/ai`` handler still present in ``routes/market.py``.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request, Response

from api_gateway.routes.helpers import _auth_headers, _clients
from observability.logging import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/v1")
logger = get_logger(__name__)

# ── Window selector ───────────────────────────────────────────────────────────
# The widget offers three windows; we constrain the inbound ``hours`` param to
# this whitelist so an arbitrary value can't be passed through to S6 (S6 itself
# caps at 1-168, but pinning to the three UI options keeps caches warm and the
# contract explicit). 72h (3 days) is the default: 24h is frequently too sparse
# to fill the widget (live: only 16 articles in the last 24h vs 2,466 in 72h),
# while a full week dilutes "right now". 3 days is the sweet spot.
_ALLOWED_WINDOWS: frozenset[int] = frozenset({24, 72, 168})
_DEFAULT_WINDOW_HOURS = 72

# Normalise the noisy S6 sentiment enum to the three directions the UI renders.
# "mixed" collapses to neutral (we cannot draw a two-headed arrow at 22px); an
# unknown/empty sentiment also becomes neutral so the dot is always defined.
_SENTIMENT_MAP: dict[str, str] = {
    "positive": "positive",
    "negative": "negative",
    "neutral": "neutral",
    "mixed": "neutral",
}

# Strip these leading host labels when deriving a short publisher name from a
# URL — "www.finance.yahoo.com" → "yahoo" reads better than the full host.
_HOST_NOISE_PREFIXES = ("www.", "m.", "uk.", "finance.", "markets.")


def _normalise_sentiment(raw: str | None) -> str:
    """Map an S6 sentiment value to one of positive | negative | neutral.

    Defaults to ``neutral`` for null / "mixed" / unrecognised values so the
    frontend always has a defined direction to render (no undefined dot).
    """
    if not raw:
        return "neutral"
    return _SENTIMENT_MAP.get(raw.strip().lower(), "neutral")


def _source_from_url(url: str | None, fallback: str | None) -> str | None:
    """Derive a short, human publisher label from an article URL host.

    WHY: ``document_source_metadata.source_name`` is empty in the live data
    (0% populated), so ``/news/top`` returns ``source_name: null``. The host of
    the article URL is the most reliable publisher signal we have. We strip the
    common ``www.``/``finance.``/region noise prefixes and the TLD so
    "https://finance.yahoo.com/…" → "yahoo", "https://www.fxstreet.com/…" →
    "fxstreet". Falls back to the (usually-null) ``source_name`` then to None.
    """
    if not url:
        return fallback
    try:
        host = urlparse(url).hostname or ""
    except (ValueError, TypeError):
        return fallback
    if not host:
        return fallback
    host = host.lower()
    # Peel known noise prefixes (possibly several, e.g. "uk.finance.yahoo.com").
    changed = True
    while changed:
        changed = False
        for prefix in _HOST_NOISE_PREFIXES:
            if host.startswith(prefix):
                host = host[len(prefix) :]
                changed = True
    # "yahoo.com" → "yahoo"; "fxstreet.com" → "fxstreet". Keep the first label.
    label = host.split(".")[0] if host else ""
    return label or fallback


def _to_momentum_item(article: dict[str, Any]) -> dict[str, Any]:
    """Transform one S6 ``/news/top`` article into a NEWS MOMENTUM row.

    Every field here is something a user can read or act on — the opposite of
    the old extraction-confidence row. ``relevance`` is the REAL
    ``display_relevance_score`` composite, NOT a fabricated confidence.
    """
    url = article.get("url")
    return {
        "article_id": str(article.get("article_id", "")),
        "title": article.get("title"),
        "url": url,
        "source": _source_from_url(url, article.get("source_name")),
        "published_at": article.get("published_at"),
        # Direction dot: positive | negative | neutral (mixed→neutral).
        "sentiment": _normalise_sentiment(article.get("sentiment")),
        # HONEST relevance: composite of market impact + LLM relevance + routing
        # (PRD-0026 §6.5), 0-1. Replaces the meaningless 0.90/0.95 confidence.
        "relevance": article.get("display_relevance_score"),
        "routing_tier": article.get("routing_tier"),
        # Observed day-0 abnormal price move (0-1) when the article has been
        # impact-labelled; null otherwise (the common case — labelling needs
        # 25h+ of post-publication OHLCV). Forwarded so the UI can show it when
        # present without ever fabricating it.
        "market_impact_score": article.get("market_impact_score"),
    }


@router.get("/signals/ai")
async def ai_signals(
    request: Request,
    limit: int = Query(default=8, ge=1, le=50),
    hours: int = Query(
        default=_DEFAULT_WINDOW_HOURS,
        description="Look-back window in hours. Constrained to the UI options 24 | 72 | 168.",
    ),
) -> Any:
    """NEWS MOMENTUM feed for the dashboard "AI SIGNALS" widget.

    Returns the most relevant *recent* news in the selected window, ranked by
    S6's ``display_relevance_score``. Each row is a real, clickable article with
    an honest relevance score and a sentiment direction — answering "what is
    moving in the news right now?".

    Window: ``hours`` is snapped to the nearest allowed UI option (24 | 72 |
    168); anything else falls back to the 72h default. The response echoes the
    resolved ``window_hours`` so the frontend can confirm which window it got.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)

    # Snap the requested window to an allowed UI option. An out-of-set value
    # (e.g. a hand-crafted ?hours=5) degrades to the safe 72h default rather
    # than passing an arbitrary window downstream.
    window_hours = hours if hours in _ALLOWED_WINDOWS else _DEFAULT_WINDOW_HOURS

    # Proxy S6's ranked-news endpoint. ``min_display_score`` is left unset: the
    # endpoint already ranks by display_relevance_score DESC, so the top ``limit``
    # rows are the most relevant by construction — an extra floor would only risk
    # an empty widget on a quiet news day.
    resp = await clients.nlp_pipeline.get(
        "/api/v1/news/top",
        params={"hours": window_hours, "limit": limit, "offset": 0},
        headers=headers,
    )
    if resp.status_code != 200:
        # Never fabricate a 200 — pass the upstream status through so the widget
        # can show its (named) error state and offer Retry.
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    try:
        body = json.loads(resp.content)
        articles = body.get("articles", [])
        # Drop rows with no title or URL — a row the user can neither read nor
        # open carries no momentum information (defensive; live data is 100%
        # populated on both).
        signals = [_to_momentum_item(a) for a in articles if a.get("title") and a.get("url")][:limit]
        return {"signals": signals, "window_hours": window_hours}
    except Exception:
        # The transform must never 500 the dashboard. Fall back to the raw S6
        # payload (the frontend treats an unexpected shape as empty).
        logger.warning("ai_signals_transform_failed", exc_info=True)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ═══════════════════════════════════════════════════════════════════════════════
# ROADMAP — the per-entity news-occurrence feed (deferred, needs S6 work)
# ═══════════════════════════════════════════════════════════════════════════════
# The user's original ask included a per-entity occurrence count ("8 articles /
# 24h" per ticker). The data exists in S6's ``entity_mentions`` table but is not
# exposed by any endpoint the gateway can call, and the gateway has no DB (R9).
# To ship that feed truthfully, add ONE read-only S6 endpoint (owned by the
# nlp-pipeline workstream, not this one):
#
#   GET /api/v1/news/trending-entities?hours=72&limit=20
#     SELECT em.resolved_entity_id, COUNT(DISTINCT em.doc_id) AS article_count,
#            <latest title/url/published_at>, <dominant sentiment>
#     FROM entity_mentions em
#     JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
#     WHERE em.resolved_entity_id IS NOT NULL
#       AND dsm.published_at >= now() - :hours * interval '1 hour'
#     GROUP BY em.resolved_entity_id
#     ORDER BY article_count DESC
#     -- then JOIN S7 canonical_entities and FILTER ticker IS NOT NULL so the
#     --   feed surfaces tradeable names (NVDA, AMD, AAPL …), not macro noise
#     --   (NASDAQ, "U.S.", a newswire) which dominate the raw mention ranking.
#
# Once that endpoint exists, this route would call it, enrich entity_ids→ticker
# via the existing S7 KG batch call, and emit rows of {ticker, name,
# article_count, top_headline, sentiment} — the full feed the user described.
