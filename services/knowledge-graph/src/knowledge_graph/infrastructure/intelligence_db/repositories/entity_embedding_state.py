"""EntityEmbeddingState repository (PRD §6.7 Block 13D).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.

View-row allocation per entity type (PRD-0017 §6.5):
  - financial_instrument  → 3 rows: definition, narrative, fundamentals_ohlcv
  - all other types       → 2 rows: definition, narrative only

Non-company entities have no structured fundamentals data; creating a
fundamentals_ohlcv row for them wastes storage and pollutes ANN results.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# View type constants
VIEW_DEFINITION = "definition"
VIEW_NARRATIVE = "narrative"
VIEW_FUNDAMENTALS = "fundamentals_ohlcv"

# All 3 view types (for financial_instrument entities and internal iteration)
ALL_VIEW_TYPES = (VIEW_DEFINITION, VIEW_NARRATIVE, VIEW_FUNDAMENTALS)

# Non-company entities get only definition + narrative (no fundamentals data)
COMPANY_VIEW_TYPES = ALL_VIEW_TYPES
NON_COMPANY_VIEW_TYPES = (VIEW_DEFINITION, VIEW_NARRATIVE)

# Entity types that receive fundamentals_ohlcv embeddings
COMPANY_ENTITY_TYPES: frozenset[str] = frozenset({"financial_instrument"})


def get_view_types_for_entity_type(entity_type: str) -> tuple[str, ...]:
    """Return the view types to provision for a given entity type.

    - ``financial_instrument`` → (definition, narrative, fundamentals_ohlcv)
    - all other types          → (definition, narrative)
    """
    if entity_type in COMPANY_ENTITY_TYPES:
        return COMPANY_VIEW_TYPES
    return NON_COMPANY_VIEW_TYPES


def sha256_hex(text_content: str) -> str:
    """Return SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text_content.encode()).hexdigest()


class EntityEmbeddingStateRepository:
    """Read/write repository for ``entity_embedding_state`` (multi-view embeddings)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        entity_id: UUID,
        view_type: str,
        *,
        embedding: list[float] | None,
        model_id: str | None,
        source_text: str | None,
        source_hash: str | None,
        next_refresh_at: datetime | None,
        touch_last_refreshed: bool = True,
    ) -> None:
        """Upsert an embedding row for (entity_id, view_type).

        Increments ``refresh_count`` on each update.

        ``touch_last_refreshed`` (default ``True``): when ``True`` the row's
        ``last_refreshed_at`` is advanced to ``now()`` — the correct behaviour
        for a real refresh that actually (re)computed a source_text/embedding.

        Pass ``False`` for *bookkeeping* upserts that only push
        ``next_refresh_at`` forward while writing **no** source_text/embedding
        (the ``fundamentals_ohlcv`` genuine-miss 30-day defer and the backoff
        skip). Otherwise those write-nothing defers stamp ``last_refreshed_at =
        now()`` and make a permanently-empty row look freshly refreshed — the
        exact D1 silent-success signature (all 713 ``fundamentals_ohlcv`` rows
        ``last_refreshed_at`` current yet source_text/embedding NULL). Keeping the
        timestamp truthful lets monitoring alert on "embeddings gone stale".
        """
        # asyncpg cannot serialize list[float] → pgvector vector(1024) automatically.
        # Convert to pgvector text format ("[x,y,z]") and use CAST in SQL.
        # COALESCE(CAST(NULL AS vector), existing) preserves existing embedding when
        # embedding=None is passed (unchanged-hash branch).
        embedding_str: str | None = "[" + ",".join(str(x) for x in embedding) + "]" if embedding is not None else None
        # When ``touch_last_refreshed`` is False, keep the existing timestamp on
        # the UPDATE branch (a first INSERT still stamps now() — a brand-new row
        # has never been refreshed so now() is the only sensible seed).
        last_refreshed_update = "now()" if touch_last_refreshed else "entity_embedding_state.last_refreshed_at"
        await self._session.execute(
            text(f"""
INSERT INTO entity_embedding_state (
    entity_id, view_type, embedding, model_id, source_text, source_hash,
    last_refreshed_at, next_refresh_at, refresh_count
) VALUES (
    :entity_id, :view_type, CAST(:embedding AS vector), :model_id, :source_text, :source_hash,
    now(), :next_refresh_at, 0
)
ON CONFLICT (entity_id, view_type) DO UPDATE SET
    embedding         = COALESCE(CAST(EXCLUDED.embedding AS vector), entity_embedding_state.embedding),
    model_id          = COALESCE(EXCLUDED.model_id, entity_embedding_state.model_id),
    source_text       = EXCLUDED.source_text,
    source_hash       = EXCLUDED.source_hash,
    last_refreshed_at = {last_refreshed_update},
    next_refresh_at   = EXCLUDED.next_refresh_at,
    refresh_count     = entity_embedding_state.refresh_count + 1
"""),
            {
                "entity_id": str(entity_id),
                "view_type": view_type,
                "embedding": embedding_str,
                "model_id": model_id,
                "source_text": source_text,
                "source_hash": source_hash,
                "next_refresh_at": next_refresh_at,
            },
        )

    async def get(self, entity_id: UUID, view_type: str) -> dict[str, object] | None:
        """Fetch a single embedding row by primary key."""
        result = await self._session.execute(
            text("""
SELECT entity_id, view_type, model_id, source_hash,
       last_refreshed_at, next_refresh_at, refresh_count
FROM entity_embedding_state
WHERE entity_id = :entity_id AND view_type = :view_type
"""),
            {"entity_id": str(entity_id), "view_type": view_type},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "entity_id": UUID(str(row[0])),
            "view_type": row[1],
            "model_id": row[2],
            "source_hash": row[3],
            "last_refreshed_at": row[4],
            "next_refresh_at": row[5],
            "refresh_count": int(row[6]),
        }

    async def count_for_entity(self, entity_id: UUID) -> int:
        """Count rows for an entity (2 for non-company entities, 3 for financial_instrument)."""
        result = await self._session.execute(
            text("SELECT COUNT(*) FROM entity_embedding_state WHERE entity_id = :entity_id"),
            {"entity_id": str(entity_id)},
        )
        row = result.fetchone()
        return int(row[0]) if row else 0  # type: ignore[index]

    async def ensure_rows_exist(self, entity_id: UUID, entity_type: str) -> None:
        """Ensure the correct view-type rows exist for an entity (null embeddings ok).

        - ``financial_instrument``: 3 rows (definition, narrative, fundamentals_ohlcv)
        - all other types:          2 rows (definition, narrative)

        Uses ``ON CONFLICT DO NOTHING`` for idempotency.
        """
        for vt in get_view_types_for_entity_type(entity_type):
            await self._session.execute(
                text("""
INSERT INTO entity_embedding_state (entity_id, view_type, last_refreshed_at, next_refresh_at, refresh_count)
VALUES (:entity_id, :view_type, now(), now(), 0)
ON CONFLICT (entity_id, view_type) DO NOTHING
"""),
                {"entity_id": str(entity_id), "view_type": vt},
            )

    async def get_due_for_refresh(
        self,
        view_type: str,
        limit: int = 0,
        *,
        backfill_missing_description: bool = False,
    ) -> list[dict[str, object]]:
        """Fetch entities whose embedding is due for refresh (next_refresh_at < now()).

        When ``limit == 0`` (the default), a practical ceiling of 100 000 rows is
        applied so workers always drain the full due-queue in one cycle.  Pass an
        explicit positive integer to cap the result set.

        ``backfill_missing_description`` (definition view only) widens the
        selection to ALSO include rows whose linked ``canonical_entities.description``
        is NULL/empty, regardless of ``next_refresh_at``.  This unblocks the
        empty-description backfill (2026-07-15 RC): the provisional-enrichment
        promotion path (``_write_embedding``) seeds every non-FI definition row
        with ``source_text = bare canonical_name`` and ``next_refresh_at = now()
        + 90 days`` and never writes ``canonical_entities.description``.  Because
        those rows are not "due" for 90 days, ``DefinitionRefreshWorker`` — the
        ONLY path that generates a real (news-grounded) description and writes it
        back to ``canonical_entities.description`` — never selects them, so ~1500
        entities (610 organizations, 265 persons, …) stay permanently
        undescribed.  With the flag on, those rows are picked up on the next
        cycle; once a (non-empty) description is written back they naturally drop
        out of the backfill set, so the selection self-converges.
        """
        # 0 means "unlimited" — use a practical ceiling to avoid unbounded scans.
        effective_limit = limit if limit > 0 else 100_000
        # PLAN-0093 T-C-4-02 (F-REF-004 / F-REF-005): prioritise rows whose
        # embedding column is NULL. These are the rows that have been "stuck"
        # — they were scheduled for refresh but the previous attempt never
        # produced an embedding (e.g. ML provider down, source_text NULL).
        # Without this ordering they sit behind the queue of routine refreshes
        # forever. ``(embedding IS NULL) DESC`` makes the boolean TRUE (=1)
        # sort first, then we fall back to FIFO ``next_refresh_at`` within each
        # bucket so non-stuck rows still drain in age order.
        #
        # PLAN-0093 T-C-4-03 (F-REF-003 / F-DB-005): when querying the
        # ``fundamentals_ohlcv`` view type, additionally restrict to
        # entity_type='financial_instrument'. Audit 2026-05-23 found 2,197
        # stale rows for non-equity types (product/event/macro_indicator)
        # which by definition have no OHLCV data and can never be embedded.
        # Without the filter the worker burns cycles + retries on rows that
        # will permanently stay NULL.
        entity_type_filter = "  AND ce.entity_type = 'financial_instrument'\n" if view_type == VIEW_FUNDAMENTALS else ""
        # The base "due" predicate: next_refresh_at is set and has elapsed.
        due_predicate = "(ees.next_refresh_at IS NOT NULL AND ees.next_refresh_at < now())"
        if backfill_missing_description:
            # Also claim rows whose entity has no description yet (see docstring).
            # ``btrim`` collapses whitespace-only descriptions to '' so they count
            # as missing. A row leaves this set as soon as the worker writes a
            # non-empty description back, so backfill is self-limiting.
            due_predicate = f"({due_predicate} OR ce.description IS NULL OR btrim(ce.description) = '')"
        result = await self._session.execute(
            text(f"""
SELECT ees.entity_id, ees.source_hash, ees.source_text, ce.canonical_name,
       ce.entity_type, ce.ticker, ce.isin, ce.exchange,
       ees.model_id IS NOT NULL AS has_embedding
FROM entity_embedding_state ees
JOIN canonical_entities ce ON ce.entity_id = ees.entity_id
WHERE ees.view_type       = :view_type
  AND {due_predicate}
{entity_type_filter}ORDER BY (ees.embedding IS NULL) DESC, ees.next_refresh_at
LIMIT :limit
FOR UPDATE OF ees SKIP LOCKED
"""),
            {"view_type": view_type, "limit": effective_limit},
        )
        rows = result.fetchall()
        return [
            {
                "entity_id": UUID(str(r[0])),
                "source_hash": r[1],
                "source_text": r[2],
                "canonical_name": r[3],
                "entity_type": r[4],
                "ticker": r[5],
                "isin": r[6],
                "exchange": r[7],
                "has_embedding": bool(r[8]),
            }
            for r in rows
        ]
