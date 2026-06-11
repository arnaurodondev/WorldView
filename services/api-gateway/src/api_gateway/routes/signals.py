"""AI Signals route for the API Gateway.

Owns GET /v1/signals/ai — the dashboard "AI SIGNALS" feed.

WHY THIS FILE EXISTS (2026-06-10 AI-Signals overhaul): the original handler in
``routes/market.py`` proxied S6 ``GET /api/v1/signals`` and dropped most of the
useful payload (``signal_type``, ``polarity``, ``market_impact_score``) while
also passing duplicate rows straight through. The live widget therefore showed
cryptic UUID-prefix labels ("9ECB"), unexplained percentages, and the same
ticker 3x with no differentiation. This module is the enriched replacement:

1. **Dedup** — S6 emits one ``nlp.signal.detected.v1`` outbox row per extracted
   claim, so a single article about one entity routinely produces 2-4 rows
   (e.g. GILD POSITIVE 0.95 + POSITIVE 0.90 + NEUTRAL 0.95 for the same doc).
   We collapse to one signal per (entity_id, doc_id), keeping the most
   informative row (non-neutral polarity first, then highest confidence).
2. **Label resolution** — newer outbox rows carry a real Avro ``polarity``
   field (positive|negative|neutral). We trust it when it is non-neutral and
   only fall back to the signal_type→direction heuristic for neutral/legacy
   rows. (Live 7-day distribution: 756 neutral / 299 positive / 60 negative.)
3. **Entity enrichment** — batch-resolves entity_ids via S7 KG to BOTH
   ``ticker`` AND ``canonical_name`` (the old transform discarded the name,
   which is why unresolvable rows degraded to UUID prefixes in the UI).
   Entities the KG genuinely does not know are dropped (they carry zero
   actionable information for a trader); a KG *outage* degrades gracefully
   and keeps the rows instead.
4. **Article enrichment** — batch-resolves doc_ids via S5 content-store to
   title / url / source / published_at so every signal can show WHY it fired.
5. **Honest semantics** — ``score`` is the LLM *extraction confidence* (how
   sure the model is the event was stated in the article), NOT a price-move
   prediction. ``market_impact_score`` (observed abnormal day-0 price move,
   0.0 when unlabelled) is forwarded separately so the frontend can explain
   each number truthfully.

ROUTE PRECEDENCE: this router is registered BEFORE ``market_router`` in
``routes/__init__.py``. FastAPI resolves routes in registration order, so this
handler supersedes the legacy ``/signals/ai`` handler still present in
``routes/market.py`` (owned by another workstream — the dead handler should be
removed there in a follow-up).

Producing service: S6 nlp-pipeline (outbox topic ``nlp.signal.detected.v1``).
Frontend consumer: apps/worldview-web components/dashboard/AiSignalsWidget.tsx.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from api_gateway.routes.helpers import _auth_headers, _clients
from observability.logging import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/v1")
logger = get_logger(__name__)

# ── signal_type → direction heuristic ────────────────────────────────────────
# Fallback mapping used only when the Avro polarity field is neutral/absent.
# Covers BOTH the legacy broker-event labels and the NLP deep-extraction
# event_type enum observed live (EARNINGS_RELEASE, M_AND_A, CAPITAL_RAISE, …).
_POSITIVE_SIGNAL_TYPES = frozenset(
    {
        "M_AND_A",
        "EARNINGS_BEAT",
        "UPGRADE",
        "BUYBACK",
        "ACQUISITION",
        "DIVIDEND",
        "EXPANSION",
        "PARTNERSHIP",
        "PARTNERSHIPS",
        "JOINT_VENTURE",
        "IPO",
        "REVENUE_BEAT",
        "GUIDANCE_RAISE",
        "CONTRACT_WIN",
        "PRODUCT_LAUNCH",
        "CAPITAL_RAISE",
        "FUNDING",
    },
)
_NEGATIVE_SIGNAL_TYPES = frozenset(
    {
        "EARNINGS_MISS",
        "DOWNGRADE",
        "REGULATORY_ACTION",
        "LAWSUIT",
        "BANKRUPTCY",
        "RESTRUCTURING",
        "GUIDANCE_CUT",
        "REVENUE_MISS",
        "INVESTIGATION",
        "FINE",
        "RECALL",
        "LAYOFF",
        "LEGAL",
        "NATURAL_DISASTER",
        "GEOPOLITICAL",
        "SANCTIONS",
    },
)

# Human-readable labels for the signal_type enum. Falls back to a generic
# underscore→space title-casing for unseen values so new enum members never
# render as raw SHOUTING_SNAKE_CASE in the UI.
_SIGNAL_TYPE_LABELS: dict[str, str] = {
    "EARNINGS_RELEASE": "Earnings",
    "EARNINGS_BEAT": "Earnings beat",
    "EARNINGS_MISS": "Earnings miss",
    "EARNINGS_GUIDANCE": "Guidance",
    "GUIDANCE_RAISE": "Guidance raise",
    "GUIDANCE_CUT": "Guidance cut",
    "ANALYST_RATING": "Analyst rating",
    "UPGRADE": "Upgrade",
    "DOWNGRADE": "Downgrade",
    "M_AND_A": "M&A",
    "MERGER_ACQUISITION": "M&A",
    "ACQUISITION": "Acquisition",
    "PRODUCT_LAUNCH": "Product launch",
    "CAPITAL_RAISE": "Capital raise",
    "BUYBACK": "Buyback",
    "DIVIDEND": "Dividend",
    "IPO": "IPO",
    "REGULATORY_ACTION": "Regulatory",
    "LEGAL": "Legal",
    "LAWSUIT": "Lawsuit",
    "INVESTIGATION": "Investigation",
    "MANAGEMENT_CHANGE": "Mgmt change",
    "EXECUTIVE_CHANGE": "Mgmt change",
    "CORPORATE_ACTION": "Corp action",
    "CONTRACT_WIN": "Contract win",
    "PARTNERSHIP": "Partnership",
    "PARTNERSHIPS": "Partnership",
    "JOINT_VENTURE": "Joint venture",
    "MACRO": "Macro",
    "GEOPOLITICAL": "Geopolitical",
    "SANCTIONS": "Sanctions",
    "NATURAL_DISASTER": "Disaster",
    "LAYOFF": "Layoffs",
    "BANKRUPTCY": "Bankruptcy",
    "RESTRUCTURING": "Restructuring",
    "FUNDING": "Funding",
    "OTHER": "News event",
    "UNKNOWN": "News event",
}

# Entity id S6 substitutes when a claim has neither claimer nor subject —
# carries no information, always dropped.
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


def _signal_type_to_label(signal_type: str) -> str:
    """Map a raw signal_type enum value to POSITIVE/NEGATIVE/NEUTRAL."""
    st = signal_type.upper()
    if st in _POSITIVE_SIGNAL_TYPES:
        return "POSITIVE"
    if st in _NEGATIVE_SIGNAL_TYPES:
        return "NEGATIVE"
    return "NEUTRAL"


def _resolve_label(polarity: str, signal_type: str) -> str:
    """Direction resolution: Avro polarity wins when decisive, else type map.

    WHY polarity-first: polarity is what the extraction LLM judged for the
    specific claim ("Lululemon Cuts Outlook" → negative even though the
    signal_type is the directionless EARNINGS_GUIDANCE). The type map cannot
    encode per-article direction for two-sided types like EARNINGS_RELEASE.
    """
    p = polarity.strip().lower()
    if p == "positive":
        return "POSITIVE"
    if p == "negative":
        return "NEGATIVE"
    return _signal_type_to_label(signal_type)


def _humanize_signal_type(signal_type: str) -> str:
    """Human-readable chip text for a signal_type enum value."""
    st = signal_type.upper().strip()
    if st in _SIGNAL_TYPE_LABELS:
        return _SIGNAL_TYPE_LABELS[st]
    # Generic fallback: "SUPPLY_CHAIN_DISRUPTION" → "Supply chain disruption"
    return st.replace("_", " ").capitalize() if st else "News event"


def _dedup_signals(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate signals to one per (entity_id, doc_id).

    S6 emits one row per extracted claim, so one article about one entity
    yields several near-identical rows. Keep the most informative:
      1. a row whose resolved label is non-NEUTRAL beats a NEUTRAL one
         (direction is the single most valuable bit on the dashboard);
      2. otherwise the higher extraction confidence wins.
    Input order (created_at DESC from S6) is preserved for the survivors.
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for item in items:
        key = (str(item.get("entity_id", "")), str(item.get("doc_id", "")))
        current = best.get(key)
        if current is None:
            best[key] = item
            order.append(key)
            continue
        new_label = _resolve_label(str(item.get("polarity", "")), str(item.get("signal_type", "")))
        cur_label = _resolve_label(str(current.get("polarity", "")), str(current.get("signal_type", "")))
        new_directional = new_label != "NEUTRAL"
        cur_directional = cur_label != "NEUTRAL"
        new_conf = float(item.get("confidence", 0.0))
        cur_conf = float(current.get("confidence", 0.0))
        wins_on_direction = new_directional and not cur_directional
        wins_on_confidence = new_directional == cur_directional and new_conf > cur_conf
        if wins_on_direction or wins_on_confidence:
            best[key] = item
    return [best[key] for key in order]


async def _resolve_entities(
    clients: Any,
    headers: dict[str, str],
    entity_ids: list[str],
) -> tuple[dict[str, dict[str, str | None]], bool]:
    """Batch-resolve entity_ids → {ticker, canonical_name} via S7 KG.

    Returns ``(entity_map, kg_ok)``. ``kg_ok`` is True only when the KG call
    succeeded — callers use it to distinguish "entity unknown to KG" (drop the
    signal) from "KG outage" (keep signals, degrade gracefully).
    """
    entity_map: dict[str, dict[str, str | None]] = {}
    if not entity_ids:
        return entity_map, False
    try:
        resp = await clients.knowledge_graph.post(
            "/api/v1/entities/batch",
            json={"entity_ids": entity_ids},
            headers=headers,
        )
        if resp.status_code != 200:
            return entity_map, False
        body = json.loads(resp.content)
        for ent in body.get("entities", []):
            entity_map[str(ent["entity_id"])] = {
                "ticker": ent.get("ticker"),
                "canonical_name": ent.get("canonical_name"),
            }
    except Exception:
        logger.warning("ai_signals_entity_enrichment_failed", exc_info=True)
        return entity_map, False
    return entity_map, True


async def _resolve_articles(
    clients: Any,
    headers: dict[str, str],
    doc_ids: list[str],
) -> dict[str, dict[str, str | None]]:
    """Batch-resolve doc_ids → article metadata via S5 content-store."""
    article_map: dict[str, dict[str, str | None]] = {}
    if not doc_ids:
        return article_map
    try:
        resp = await clients.content_store.post(
            "/api/v1/documents/batch",
            json={"doc_ids": doc_ids},
            headers=headers,
        )
        if resp.status_code == 200:
            body = json.loads(resp.content)
            for doc in body.get("documents", []):
                article_map[str(doc["doc_id"])] = {
                    "title": doc.get("title"),
                    "url": doc.get("url"),
                    "source_name": doc.get("source_name"),
                    "published_at": doc.get("published_at"),
                }
    except Exception:
        logger.warning("ai_signals_article_enrichment_failed", exc_info=True)
    return article_map


@router.get("/signals/ai")
async def ai_signals(
    request: Request,
    limit: int = Query(default=8, ge=1, le=50),
) -> Any:
    """Enriched AI-signals feed for the dashboard widget.

    Pipeline: S6 raw claims → drop nil-entity rows → dedup per (entity, doc)
    → KG + content-store batch enrichment → drop KG-unknown entities → trim.

    Response items carry (additive superset of the legacy shape):
      signal_id, entity_id, ticker, entity_name, label, polarity, signal_type,
      signal_type_label, score (extraction confidence 0-1),
      market_impact_score (observed day-0 abnormal move, 0 when unlabelled),
      article_title, article_url, source_name, published_at, created_at.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)

    # Over-fetch: dedup + entity-drop typically removes 40-60% of raw rows
    # (live measurement, 2026-06-10), so request 4x the display budget.
    s6_limit = min(limit * 4, 200)
    resp = await clients.nlp_pipeline.get(
        "/api/v1/signals",
        params={"limit": s6_limit, "offset": 0},
        headers=headers,
    )
    if resp.status_code != 200:
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    try:
        body = json.loads(resp.content)
        raw_items = body.get("items", [])

        # 1. Drop rows whose entity is the nil-UUID placeholder (no claimer
        #    and no subject) — there is nothing to display or navigate to.
        items = [item for item in raw_items if str(item.get("entity_id", "")) not in ("", _NIL_UUID)]

        # 2. Dedup per (entity, doc) — see _dedup_signals.
        items = _dedup_signals(items)

        # 3. Batch enrichment (entity + article) — two downstream calls total.
        entity_ids = list({str(item["entity_id"]) for item in items})
        doc_ids = list({str(item.get("doc_id", "")) for item in items if item.get("doc_id")})
        entity_map, kg_ok = await _resolve_entities(clients, headers, entity_ids)
        article_map = await _resolve_articles(clients, headers, doc_ids)

        signals: list[dict[str, Any]] = []
        dropped_unknown = 0
        for item in items:
            entity_id = str(item["entity_id"])
            entity = entity_map.get(entity_id)
            # 4. When the KG answered authoritatively and does not know this
            #    entity, the row would render as a UUID stub ("9ECB") — drop
            #    it. When the KG call failed we keep the row (kg_ok False)
            #    so a KG outage degrades the labels, not the feed.
            if kg_ok and entity is None:
                dropped_unknown += 1
                continue
            signal_type = str(item.get("signal_type", ""))
            polarity = str(item.get("polarity", "neutral"))
            article = article_map.get(str(item.get("doc_id", "")), {})
            signals.append(
                {
                    "signal_id": str(item.get("signal_id", "")),
                    "entity_id": entity_id,
                    "ticker": (entity or {}).get("ticker"),
                    "entity_name": (entity or {}).get("canonical_name"),
                    "label": _resolve_label(polarity, signal_type),
                    "polarity": polarity,
                    "signal_type": signal_type,
                    "signal_type_label": _humanize_signal_type(signal_type),
                    "score": float(item.get("confidence", 0.0)),
                    "market_impact_score": float(item.get("market_impact_score", 0.0) or 0.0),
                    "article_title": article.get("title"),
                    "article_url": article.get("url"),
                    "source_name": article.get("source_name"),
                    "published_at": article.get("published_at"),
                    "created_at": str(item.get("detected_at", "")),
                },
            )
            if len(signals) >= limit:
                break

        if dropped_unknown:
            logger.info(
                "ai_signals_dropped_unresolvable_entities",
                dropped=dropped_unknown,
                returned=len(signals),
            )
        return {"signals": signals}
    except Exception:
        # Transform must never 500 the dashboard — fall back to the raw S6
        # payload (the frontend treats an unexpected shape as empty).
        logger.warning("ai_signals_transform_failed", exc_info=True)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
