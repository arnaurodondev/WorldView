"""Worker 13K: Re-typing sweep for ``entity_type='unknown'`` canonical entities.

Prod data-quality audits (2026-07-15 / 2026-07-16) found ~150 canonical
entities permanently stuck at ``entity_type='unknown'`` that are clearly
typable — ``Interactive Brokers Group, Inc.`` (organization), ``Coffee`` /
``Palladium`` (product/commodity), ``ISM Services PMI`` (macro_indicator),
``European Commission`` (organization).  Nothing re-classified them: the
provisional-enrichment path types an entity exactly once at promotion and never
revisits the ``unknown`` bucket.  ``unknown`` rows are excluded from
type-filtered retrieval and typed graph traversals, so every one is dead weight.

This worker closes that gap.  Each cycle it claims a bounded batch of
``unknown`` rows, re-runs the extraction LLM (the SAME ``extract_entity_profile``
call the promotion path uses) to infer a real type, and writes back ONLY when
the LLM produces a concrete, valid, non-``unknown`` type.  Rows the LLM still
can't classify are left untouched (no churn) and retried on the next cycle.

Safety / idempotency:
  * Read phase runs on the read replica; write phase is a guarded UPDATE
    (``... AND entity_type='unknown'``) so a row re-typed by another path
    between read and write is never clobbered.
  * The worker only ever moves a row OUT of ``unknown`` — it can never
    re-type an already-typed entity, so a mis-firing sweep cannot corrupt
    existing good classifications.
  * After a successful re-type it seeds the correct ``entity_embedding_state``
    rows for the new type so the entity becomes visible to the definition /
    narrative refresh workers (an ``unknown`` row that was created without
    embedding-state rows would otherwise stay undescribed forever).

3-phase session pattern (ARCH-003): no DB session is held across the LLM I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.tickers import strip_exchange_qualifier  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

# A tickerless company that the LLM types as a coarse "company"/FI class is an
# ``organization`` (FR-12), not a tradable instrument — for the re-typing sweep
# that is a strictly better classification than leaving the row ``unknown``.
_TICKERLESS_COMPANY_FALLBACK = "organization"


class EntityRetypeWorker:
    """Periodic re-classifier for ``entity_type='unknown'`` canonical entities.

    Args:
    ----
        session_factory:      intelligence_db write async_sessionmaker.
        llm_client:           FallbackChainClient (extraction path). Required —
                              without it there is no way to infer a type, so the
                              scheduler only wires this worker when an LLM is
                              configured.
        batch_limit:          Max ``unknown`` rows to process per cycle (bounds
                              LLM spend). Must be > 0.
        read_session_factory: Optional read-replica factory for the Phase-1
                              SELECT (R27). Falls back to ``session_factory``.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        *,
        batch_limit: int = 100,
        read_session_factory: Any = None,
    ) -> None:
        self._sf = session_factory
        self._read_sf: Any = read_session_factory if read_session_factory is not None else session_factory
        self._llm = llm_client
        self._batch_limit = batch_limit if batch_limit > 0 else 100

    async def run(self) -> None:
        """Re-type a bounded batch of ``unknown`` entities (one sweep cycle)."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
            CanonicalEntityRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_embedding_state import (
            EntityEmbeddingStateRepository,
        )

        # ── Phase 1: Read (replica) ──────────────────────────────────────────
        async with self._read_sf() as session:
            rows = await CanonicalEntityRepository(session).list_unknown_entities(self._batch_limit)

        if not rows:
            logger.info("entity_retype_worker_complete", scanned=0, retyped=0, unresolved=0)
            return

        # ── Phase 2: Classify (no DB session held during LLM I/O) ─────────────
        # Collect (entity_id, new_type) for rows the LLM could confidently type.
        resolved: list[tuple[UUID, str]] = []
        unresolved = 0
        for row in rows:
            entity_id: UUID = row["entity_id"]  # type: ignore[assignment]
            canonical_name = str(row.get("canonical_name") or "")
            if not canonical_name:
                unresolved += 1
                continue
            # Feed the existing description (if any) as grounding context — it is
            # our own data, XML-wrapped + truncated inside extract_entity_profile.
            context_snippet = str(row.get("description") or "")
            try:
                profile = await core.extract_entity_profile(
                    self._llm,
                    canonical_name,
                    "unknown",
                    context_snippet,
                )
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "entity_retype_extract_failed",
                    entity_id=str(entity_id),
                    canonical_name=canonical_name,
                    exc_info=True,
                )
                unresolved += 1
                continue

            new_type = self._resolve_type(profile, fallback_ticker=row.get("ticker"))
            if new_type == "unknown":
                # LLM still couldn't classify — leave the row untouched for a
                # future cycle rather than churning it.
                unresolved += 1
                continue
            resolved.append((entity_id, new_type))

        # ── Phase 3: Write (guarded UPDATE + seed embedding-state rows) ───────
        retyped = 0
        if resolved:
            async with self._sf() as session:
                entity_repo = CanonicalEntityRepository(session)
                emb_repo = EntityEmbeddingStateRepository(session)
                for entity_id, new_type in resolved:
                    changed = await entity_repo.retype_unknown_entity(entity_id, new_type)
                    if not changed:
                        # Row was re-typed by another path since Phase 1 — skip.
                        continue
                    # Seed the view rows for the new type so the definition /
                    # narrative refresh workers can now generate a grounded
                    # description for this newly-typed entity.
                    await emb_repo.ensure_rows_exist(entity_id, new_type)
                    retyped += 1
                    logger.info(  # type: ignore[no-any-return]
                        "entity_retyped",
                        entity_id=str(entity_id),
                        new_type=new_type,
                    )
                await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "entity_retype_worker_complete",
            scanned=len(rows),
            retyped=retyped,
            unresolved=unresolved,
        )

    def _resolve_type(self, profile: dict[str, Any] | None, *, fallback_ticker: Any) -> str:
        """Map an extraction profile to a canonical type, or ``"unknown"``.

        Uses the shared :func:`resolve_canonical_entity_type` so the mapping is
        identical to the provisional-enrichment persist path.  A tickerless
        company-class result becomes ``organization`` (see module docstring).
        """
        if not profile:
            return "unknown"
        raw_type = profile.get("entity_type")
        # Prefer a ticker the LLM discovered; fall back to the stored one. Strip
        # any provider exchange suffix (AAPL.US → AAPL) before the tickerless test.
        ticker_raw = profile.get("ticker") or fallback_ticker
        ticker = strip_exchange_qualifier(str(ticker_raw)) if ticker_raw else None
        return core.resolve_canonical_entity_type(
            raw_type,
            ticker=ticker,
            tickerless_company_fallback=_TICKERLESS_COMPANY_FALLBACK,
        )
