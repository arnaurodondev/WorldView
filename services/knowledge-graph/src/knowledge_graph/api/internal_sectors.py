"""GET /internal/v1/entities/sectors — batch sector/industry lookup (PLAN-0102 W2 T-W2-02).

Purpose:
    Lets rag-chat's BriefingContextGatherer fetch ``{entity_id: sector}``
    in one round-trip so the morning brief can show a sector-exposure
    line ("Tech 65% of portfolio | Energy 18% | Financials 12%").

Reads from ``canonical_entities``:
    * ``sector`` lives at ``metadata->>'sector'`` (jsonb).
    * ``industry`` lives at ``metadata->>'industry'`` (jsonb).

Auth: ``X-Internal-JWT`` validated by ``InternalJWTMiddleware`` at the app
level. No further per-route ownership checks (entity sectors are not
user-scoped data).

Cache: 1 hour Valkey — sectors change at most a handful of times per year.

Wire shape (matches PLAN-0102 §T-W2-02):
    {"results": [{"entity_id": "uuid", "sector": "...", "industry": "..."}, ...]}

Why list-of-objects (not a dict): preserves request order and is friendlier
to forward-compat field additions (e.g. ``sub_industry``) without
changing the envelope.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from knowledge_graph.api.dependencies import ReadOnlyDbSessionDep
from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
    CanonicalEntityRepository,
)
from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/internal/v1", tags=["internal-sectors"])

# Cap the batch at 100 ids — same defensive limit as the watchlist
# batch-lookup on S1; protects the DB from accidental N=10k requests.
_MAX_BATCH = 100

_CACHE_KEY_PREFIX = "sectors:v1"
_CACHE_TTL_SEC = 3600  # 1 hour


# ── Wire schemas ──────────────────────────────────────────────────────────────


class SectorLabel(BaseModel):
    """One row in the response — sector + industry per entity."""

    entity_id: UUID
    sector: str | None = None
    industry: str | None = None


class SectorsBatchResponse(BaseModel):
    """Top-level response: ``{results: [...]}``."""

    results: list[SectorLabel]


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.get(
    "/entities/sectors",
    response_model=SectorsBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch sector/industry lookup for entities",
)
async def get_sectors(
    request: Request,
    session: ReadOnlyDbSessionDep,
    entity_ids: Annotated[
        list[UUID],
        Query(
            description="Up to 100 entity UUIDs to resolve",
            min_length=1,
            max_length=_MAX_BATCH,
        ),
    ],
) -> SectorsBatchResponse:
    """Return ``{entity_id: sector, industry}`` for the requested ids.

    Missing entities are silently omitted from ``results`` (R9 safe
    degradation). The caller can detect them by comparing requested ids
    against returned ids.
    """
    if not entity_ids:
        raise HTTPException(status_code=400, detail="entity_ids must not be empty")

    # ── Cache read ─────────────────────────────────────────────────────────────
    valkey = getattr(request.app.state, "valkey_client", None)
    # Cache per individual entity_id so partial overlap across calls still
    # gives hits (vs. caching the whole request payload, which would miss
    # any time even one id differs).
    cache_hits: dict[UUID, SectorLabel] = {}
    miss_ids: list[UUID] = []
    if valkey is not None:
        for eid in entity_ids:
            try:
                raw = await valkey.get(f"{_CACHE_KEY_PREFIX}:{eid}")
            except Exception as exc:
                logger.warning("sectors_cache_read_error", entity_id=str(eid), error=str(exc))
                raw = None
            if raw is None:
                miss_ids.append(eid)
            else:
                try:
                    cache_hits[eid] = SectorLabel.model_validate_json(raw)
                except Exception as exc:
                    # Cache poisoning — drop the row and refetch.
                    logger.warning("sectors_cache_decode_error", entity_id=str(eid), error=str(exc))
                    miss_ids.append(eid)
    else:
        miss_ids = list(entity_ids)

    # ── DB fetch for misses ────────────────────────────────────────────────────
    fetched: list[SectorLabel] = []
    if miss_ids:
        repo = CanonicalEntityRepository(session)
        rows = await repo.get_batch(miss_ids)
        for row in rows:
            # ``metadata`` is jsonb — may be dict-shaped or None depending on
            # the row. We dig out both sector + industry; sector falls back
            # to the dedicated column already extracted by ``get_batch``.
            metadata = row.get("metadata") or {}
            industry = metadata.get("industry") if isinstance(metadata, dict) else None
            sector_value = row.get("sector")
            # ── ETF fallback (PLAN-0103 W8 / BP-629) ────────────────────────────
            # Some ETF rows have no sector tag at all because the equities
            # fundamentals path that writes ``metadata->>'sector'`` doesn't
            # run for funds. Without a value here the rag-chat risk
            # aggregator silently drops the row from ``sector_breakdown``
            # and the morning brief reports ``concentration_score=0``. To
            # avoid that dead-end we synthesise a generic ``"Equity ETF"``
            # bucket whenever:
            #   * the entity declares itself an ETF in metadata
            #     (``asset_class == "ETF"``), OR
            #   * the canonical row has no sector AND the ticker matches a
            #     well-known sector / index ETF prefix (XL?, ARK?, …) so we
            #     can at least keep the row in the aggregator.
            if sector_value is None and isinstance(metadata, dict):
                asset_class = metadata.get("asset_class")
                ticker = row.get("ticker")
                if asset_class == "ETF" or (
                    isinstance(ticker, str)
                    and (
                        ticker.upper().startswith(("XL", "ARK"))
                        or ticker.upper() in {"SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "VEA", "VWO", "IBIT", "GLD"}
                    )
                ):
                    sector_value = "Equity ETF"
            label = SectorLabel(
                entity_id=row["entity_id"],  # type: ignore[arg-type]
                sector=sector_value,  # type: ignore[arg-type]
                industry=industry,
            )
            fetched.append(label)
            # Write through to cache.
            if valkey is not None:
                try:
                    await valkey.setex(
                        f"{_CACHE_KEY_PREFIX}:{label.entity_id}",
                        _CACHE_TTL_SEC,
                        label.model_dump_json(),
                    )
                except Exception as exc:
                    logger.warning(
                        "sectors_cache_write_error",
                        entity_id=str(label.entity_id),
                        error=str(exc),
                    )

    # Merge cache hits + freshly fetched rows preserving request order.
    by_eid: dict[UUID, SectorLabel] = {**cache_hits}
    for f in fetched:
        by_eid[f.entity_id] = f
    results: list[SectorLabel] = [by_eid[eid] for eid in entity_ids if eid in by_eid]

    return SectorsBatchResponse(results=results)
