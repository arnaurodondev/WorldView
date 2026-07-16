"""CanonicalEntity repository for S7 — read-only access (PRD §6.4.4).

Uses raw SQL via ``text()`` — S7 does not own intelligence_db DDL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.repositories import CanonicalEntityRepositoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.domain.models import CanonicalEntity


# Corporate-suffix + punctuation stripper — kept VERBATIM in sync with the
# cleanup migration (``scripts/kg_merge_org_fi_duplicates.py`` ``_NORM_SQL``) so
# the runtime org→FI fold guard and the backfill can never disagree on what
# counts as the same company name (``Apple`` == ``Apple Inc.``).
_ENTITY_SUFFIX_RE = (
    r"\y(inc|incorporated|corp|corporation|company|co|plc|ltd|limited"
    r"|group|holdings|holding|nv|sa|ag|the|class [abc])\y"
)


def _normalized_name_sql(col: str) -> str:
    """Return a SQL expression normalizing ``col`` to a suffix/punctuation-free key.

    ``col`` is always a hardcoded column reference or a bound-param placeholder
    (``:canonical_name``), never user input.
    """
    return (
        f"btrim(regexp_replace(regexp_replace(regexp_replace(lower({col}), "
        f"'[^a-z0-9]+', ' ', 'g'), '{_ENTITY_SUFFIX_RE}', ' ', 'g'), '\\s+', ' ', 'g'))"
    )


class CanonicalEntityRepository(CanonicalEntityRepositoryPort):
    """Read-only repository for ``canonical_entities`` in intelligence_db."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, entity_id: UUID) -> dict[str, object] | None:
        """Fetch a canonical entity by ID.

        PLAN-0099 (Intelligence tab detail): description + sector/industry are
        included so the graph endpoint's *center* EntitySummary carries the
        same rich fields as the neighbours fetched via ``get_batch`` — the
        center node previously rendered with ``description=null`` even though
        the column was populated (silent drop at the repo layer).
        """
        result = await self._session.execute(
            text("""
SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange,
       metadata, description, metadata->>'sector' AS sector,
       metadata->>'industry' AS industry
FROM canonical_entities
WHERE entity_id = :entity_id
"""),
            {"entity_id": str(entity_id)},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "entity_id": UUID(str(row[0])),
            "canonical_name": row[1],
            "entity_type": row[2],
            "isin": row[3],
            "ticker": row[4],
            "exchange": row[5],
            "metadata": row[6],
            "description": row[7],
            "sector": row[8],
            "industry": row[9],
        }

    async def exists(self, entity_id: UUID) -> bool:
        """Check whether a canonical entity exists."""
        result = await self._session.execute(
            text("SELECT 1 FROM canonical_entities WHERE entity_id = :entity_id"),
            {"entity_id": str(entity_id)},
        )
        return result.fetchone() is not None

    async def get_batch(self, entity_ids: list[UUID]) -> list[dict[str, object]]:
        """Fetch multiple canonical entities in one query.

        Returns only entities that exist; missing IDs are omitted silently.
        """
        if not entity_ids:
            return []
        # F-101: include description + metadata->>'sector' so EntitySummary
        # carries the rich fields and the internal sectors endpoint can
        # resolve sector without a second round-trip.
        # PLAN-0099: industry surfaced alongside sector so EntitySummary can
        # carry it (PLAN-0091 T-A-1-03 contract — previously the S9 gateway
        # read `industry` from graph nodes but S7 never sent it).
        result = await self._session.execute(
            text("""
SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange,
       metadata, description, metadata->>'sector' AS sector,
       metadata->>'industry' AS industry
FROM canonical_entities
WHERE entity_id = ANY(:ids)
"""),
            {"ids": [str(eid) for eid in entity_ids]},
        )
        return [
            {
                "entity_id": UUID(str(row[0])),
                "canonical_name": row[1],
                "entity_type": row[2],
                "isin": row[3],
                "ticker": row[4],
                "exchange": row[5],
                "metadata": row[6],
                "description": row[7],
                "sector": row[8],
                "industry": row[9],
            }
            for row in result.fetchall()
        ]

    async def get_by_id(self, entity_id: UUID) -> CanonicalEntity | None:
        """Fetch a canonical entity with enrichment columns for the detail endpoint.

        Selects all columns needed by GetEntityDetailUseCase (PRD-0073 §9.6).
        Returns None when the entity does not exist.
        """
        from knowledge_graph.domain.models import CanonicalEntity

        result = await self._session.execute(
            text("""
SELECT entity_id, canonical_name, entity_type, ticker, isin, exchange,
       metadata, enrichment_attempts, description, data_completeness, enriched_at,
       health_score
FROM canonical_entities
WHERE entity_id = :entity_id
"""),
            {"entity_id": str(entity_id)},
        )
        row = result.fetchone()
        if row is None:
            return None
        return CanonicalEntity(
            entity_id=UUID(str(row[0])),
            canonical_name=str(row[1]),
            entity_type=str(row[2]),
            ticker=row[3],
            isin=row[4],
            exchange=row[5],
            metadata=dict(row[6]) if row[6] else {},
            enrichment_attempts=int(row[7]),
            description=row[8],
            data_completeness=float(row[9]) if row[9] is not None else None,
            enriched_at=row[10],
            health_score=float(row[11]) if row[11] is not None else None,
        )

    async def find_by_name_and_type(self, canonical_name: str, entity_type: str) -> UUID | None:
        """Find entity_id by exact canonical_name + entity_type match.

        Used by FundamentalsRefreshWorker to resolve GICS sector/industry entities.
        Returns None if not found (e.g. unsupported sector name, seed not applied).
        """
        result = await self._session.execute(
            text("""
SELECT entity_id FROM canonical_entities
WHERE canonical_name = :canonical_name AND entity_type = :entity_type
"""),
            {"canonical_name": canonical_name, "entity_type": entity_type},
        )
        row = result.fetchone()
        return UUID(str(row[0])) if row else None

    async def patch_metadata(self, entity_id: UUID, patch: dict[str, object]) -> None:
        """Shallow-merge ``patch`` into ``canonical_entities.metadata`` (JSONB).

        Existing keys are overwritten by ``patch`` keys; all other keys are
        preserved. No-op when ``patch`` is empty. Does NOT commit — the caller
        owns the surrounding transaction (the fundamentals-refresh worker writes
        the metadata patch and the sector relation in the same unit of work).

        PLAN-0103 W19 / BP-637: FundamentalsRefreshWorker mirrors the EODHD GICS
        sector + industry into ``metadata`` so the rag-chat risk aggregator and
        the ``/internal/v1/sectors`` endpoint (which read ``metadata->>'sector'``)
        resolve the value. The call site shipped but this method was missing from
        the repository, so the worker crashed every cycle with ``AttributeError``
        and the ``fundamentals_ohlcv`` embedding view stayed empty. Mirrors
        ``EntityRepository.update_metadata``.
        """
        if not patch:
            return
        import json

        await self._session.execute(
            text("""
UPDATE canonical_entities
SET metadata = COALESCE(metadata, '{}'::jsonb) || cast(:patch AS jsonb)
WHERE entity_id = :entity_id
"""),
            {"entity_id": str(entity_id), "patch": json.dumps(patch)},
        )

    async def find_by_ticker(self, ticker: str) -> dict[str, object] | None:
        """Find entity by ticker symbol (case-insensitive exact match).

        Returns the entity dict or None when no entity is seeded for that ticker.
        Used by the gateway to resolve instrument_id → KG entity_id via ticker.
        """
        result = await self._session.execute(
            text("""
SELECT entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata
FROM canonical_entities
WHERE UPPER(ticker) = UPPER(:ticker)
LIMIT 1
"""),
            {"ticker": ticker},
        )
        row = result.fetchone()
        if row is None:
            return None
        return {
            "entity_id": row[0],
            "canonical_name": row[1],
            "entity_type": row[2],
            "isin": row[3],
            "ticker": row[4],
            "exchange": row[5],
            "metadata": row[6],
        }

    async def find_financial_instrument_for_company(
        self,
        *,
        ticker: str | None,
        canonical_name: str,
    ) -> UUID | None:
        """Return the ``financial_instrument`` canonical that IS this company, if any.

        Design intent (nlp-pipeline ``entity_resolution.py``): for a *public*
        company the ``financial_instrument`` row is the canonical — an
        ``organization`` mention of the same company is meant to resolve TO it,
        never to mint a second canonical.  Every existing dedup guard in the
        provisional-promotion path is gated on
        ``entity_type == 'financial_instrument'`` (M-017 anchoring, the BP-459
        ticker pre-lookup, the FR-11 token-superset fold), so an
        ``organization``-classed company (GLiNER tags Apple/Tesla/Nvidia as
        ``organization``) slips past all of them and creates a duplicate ORG
        canonical alongside the FI — fragmenting relations across two nodes
        (2026-07 KG dedup audit: 65 org↔FI duplicates, ~16% of relations hung
        off the wrong node).

        This is the missing cross-type lookup used by the promotion guard: given
        the incoming ORG's ticker and/or name, find the FI that already owns the
        same company by, in priority order:
          1. exact ticker (case-insensitive) — the strongest identity key; and
          2. exact NORMALIZED canonical_name — strips corporate suffixes
             (Inc / Corp / Company / plc / Ltd / Group / Holdings / Class A …)
             and punctuation so ``Apple`` == ``Apple Inc.`` and
             ``NVIDIA Corporation`` == ``Nvidia``.

        The normalization SQL below is intentionally IDENTICAL to the cleanup
        migration (``scripts/kg_merge_org_fi_duplicates.py`` ``_NORM_SQL``) so a
        row this guard would fold is exactly a row the migration would merge —
        guard and backfill can never diverge.  Returns the FI ``entity_id`` (the
        canonical to reuse) or ``None`` when no financial_instrument matches.
        """
        # Normalized-name equality: apply the SAME normalization
        # (``_normalized_name_sql``) to the stored FI canonical_name and to the
        # incoming name so suffix/punctuation variants collapse.  Normalization
        # happens in SQL (not Python) on both sides so there is one deterministic
        # definition, shared verbatim with the cleanup migration.  Only entity
        # identifiers (column names) are interpolated — from module constants,
        # never user input — so this is injection-safe (S608 suppressed).
        sql = (  # — identifiers are module constants, values are bound params
            "WITH incoming AS (SELECT " + _normalized_name_sql(":canonical_name") + " AS nkey) "
            "SELECT c.entity_id FROM canonical_entities c, incoming "
            "WHERE c.entity_type = 'financial_instrument' AND ("
            "(:ticker IS NOT NULL AND UPPER(c.ticker) = UPPER(:ticker)) "
            "OR (incoming.nkey <> '' AND " + _normalized_name_sql("c.canonical_name") + " = incoming.nkey)) "
            # Prefer a ticker match over a name-only match; then lowest entity_id
            # (deterministic tie-break, matches the migration's FI selection).
            "ORDER BY (CASE WHEN :ticker IS NOT NULL AND UPPER(c.ticker) = UPPER(:ticker) THEN 0 ELSE 1 END), "
            "c.entity_id LIMIT 1"
        )
        result = await self._session.execute(
            text(sql),
            {"ticker": ticker, "canonical_name": canonical_name},
        )
        row = result.fetchone()
        return UUID(str(row[0])) if row else None

    async def create_or_get(
        self,
        canonical_name: str,
        entity_type: str,
        *,
        entity_id: UUID | None = None,
        isin: str | None = None,
        ticker: str | None = None,
        exchange: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> tuple[UUID, bool]:
        """Atomic idempotent INSERT — DEF-014 / BP-384 dedup race fix.

        Behaviour:
            1. Attempt ``INSERT ... ON CONFLICT (lower(canonical_name)) DO NOTHING
               RETURNING entity_id``.
            2. If the conflict fired (no RETURNING row), re-SELECT the existing
               row by ``WHERE lower(canonical_name) = lower(:canonical_name)``.
               This makes the operation fully atomic — no TOCTOU window between
               read and write.
            3. Returns ``(entity_id, was_created)``: ``was_created=True`` when
               this call inserted the row, ``False`` when a conflict path found
               an existing row.

        Conflict target ``lower(canonical_name)`` matches the functional UNIQUE
        INDEX added by migration 0026 (``idx_canonical_entities_lower_name``);
        the index MUST exist in the target database for the ON CONFLICT clause
        to bind.

        IMPORTANT: this method is intentionally a "thin" idempotent insert and
        does NOT co-insert the EXACT self-alias that the legacy ``create()``
        method writes.  Call sites that previously relied on the side-effecting
        ``create()`` (e.g. ``CreateCanonicalEntityUseCase``) MUST keep using
        ``create()``; ``create_or_get`` is intended for high-concurrency
        ingestion paths (``persist_enrichment``) where the caller writes its
        own alias rows and dedup is the dominant concern.
        """
        import json

        params: dict[str, object | None] = {
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "isin": isin,
            "ticker": ticker,
            "exchange": exchange,
            "metadata": json.dumps(metadata) if metadata else None,
        }
        # PLAN-0076 QA fix — the partial unique index added by migration 0026
        # excludes ``entity_type='financial_instrument''`` rows (legitimate
        # dual-listed instruments).  Postgres requires the ON CONFLICT
        # specifier to repeat the index predicate verbatim for partial
        # indexes; without it the planner refuses inference and the INSERT
        # raises ``ERROR: there is no unique or exclusion constraint matching
        # the ON CONFLICT specification`` on every call.  See migration 0026
        # docstring (STEP 2 / "ON CONFLICT BINDING") for the contract.
        if entity_id is not None:
            sql = """
INSERT INTO canonical_entities
    (entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata)
VALUES (:entity_id, :canonical_name, :entity_type, :isin, :ticker, :exchange, :metadata)
ON CONFLICT (lower(canonical_name)) WHERE entity_type != 'financial_instrument'
DO NOTHING
RETURNING entity_id
"""
            params["entity_id"] = str(entity_id)
        else:
            sql = """
INSERT INTO canonical_entities
    (canonical_name, entity_type, isin, ticker, exchange, metadata)
VALUES (:canonical_name, :entity_type, :isin, :ticker, :exchange, :metadata)
ON CONFLICT (lower(canonical_name)) WHERE entity_type != 'financial_instrument'
DO NOTHING
RETURNING entity_id
"""
        result = await self._session.execute(text(sql), params)
        row = result.fetchone()
        if row is not None:
            # Happy path — INSERT succeeded.
            return UUID(str(row[0])), True

        # Conflict path — fetch the existing row by lower(canonical_name).
        # Single round-trip, fully atomic relative to the failed INSERT.
        #
        # PLAN-0076 QA fix: the partial unique index excludes
        # ``entity_type='financial_instrument'`` rows, so a duplicate-name
        # ``company`` row + an unrelated ``financial_instrument`` row may
        # legitimately co-exist (e.g. "Apple Inc." as both a tracked equity
        # instrument and as a parent company entity).  We mirror the index
        # predicate in the recovery SELECT so we always re-fetch the same row
        # the conflict would have hit — never silently picking a financial
        # instrument when the caller's INSERT was for a non-instrument type.
        select_result = await self._session.execute(
            text(
                "SELECT entity_id FROM canonical_entities "
                "WHERE lower(canonical_name) = lower(:canonical_name) "
                "AND entity_type != 'financial_instrument'",
            ),
            {"canonical_name": canonical_name},
        )
        existing = select_result.fetchone()
        if existing is None:
            # Should never happen — the ON CONFLICT fired but the row vanished.
            # Most plausible cause is a concurrent DELETE in between, which is
            # not part of any production flow.  Raise so the caller fails loudly
            # rather than silently returning a wrong ID.
            msg = (
                f"create_or_get: ON CONFLICT fired for canonical_name={canonical_name!r} "
                "but no existing row was found on re-SELECT — possible concurrent DELETE."
            )
            raise RuntimeError(msg)
        return UUID(str(existing[0])), False

    async def create(
        self,
        canonical_name: str,
        entity_type: str,
        *,
        entity_id: UUID | None = None,
        isin: str | None = None,
        ticker: str | None = None,
        exchange: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> UUID:
        """Insert a new canonical entity, returning the generated entity_id.

        PLAN-0057 Wave C-5 (T-C-5-01): co-inserts an EXACT self-alias row in the
        same transaction. Without this, callers that bypass the dedicated
        instrument/provisional consumers (e.g. `CreateCanonicalEntityUseCase`)
        would leave the canonical without a Stage-1 alias-exact match for its
        own canonical name. Idempotent via the
        ``uidx_entity_aliases_entity_norm_type`` partial UNIQUE index added by
        migration 0008 (Wave A-2).

        PLAN-0057 QA-iter1 F-DS-03 / F-DATA-04 / F-ARCH-06: callers may pass an
        explicit ``entity_id`` to preserve cross-service stable IDs (M-017).
        For instruments, the canonical's ``entity_id`` MUST equal the
        ``instrument_id`` so portfolio's InstrumentRef.id and KG's canonical
        line up across replays. When omitted we let the column default
        (``gen_random_uuid()``) generate one, which is appropriate for
        non-instrument entities (e.g. provisional canonicals) where there is
        no upstream stable ID.

        PLAN-0057 QA-iter1 F-DS-05 / F-DATA-07: the self-alias INSERT runs
        inside a SAVEPOINT so a collision against the legacy cross-entity
        ``uidx_entity_aliases_normalized`` index (different conflict target
        than the per-entity index referenced by ON CONFLICT) does not abort
        the outer transaction and roll back the canonical we just created.
        """
        import json

        params: dict[str, object | None] = {
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "isin": isin,
            "ticker": ticker,
            "exchange": exchange,
            "metadata": json.dumps(metadata) if metadata else None,
        }
        if entity_id is not None:
            sql = """
INSERT INTO canonical_entities
    (entity_id, canonical_name, entity_type, isin, ticker, exchange, metadata)
VALUES (:entity_id, :canonical_name, :entity_type, :isin, :ticker, :exchange, :metadata)
ON CONFLICT (entity_id) DO NOTHING
RETURNING entity_id
"""
            params["entity_id"] = str(entity_id)
        else:
            sql = """
INSERT INTO canonical_entities (canonical_name, entity_type, isin, ticker, exchange, metadata)
VALUES (:canonical_name, :entity_type, :isin, :ticker, :exchange, :metadata)
RETURNING entity_id
"""
        result = await self._session.execute(text(sql), params)
        row = result.fetchone()
        if row is None:
            # ON CONFLICT (entity_id) DO NOTHING fired — caller supplied an
            # entity_id that already exists. Return it; the self-alias INSERT
            # below is itself idempotent.
            assert entity_id is not None  # invariant: only ON CONFLICT path with entity_id
            resolved_entity_id = entity_id
        else:
            resolved_entity_id = UUID(str(row[0]))

        # ── EXACT self-alias (PLAN-0057 C-5 / Fix-B.2) ────────────────────────
        # Note: ON CONFLICT target matches the partial UNIQUE index installed by
        # migration 0008 — we MUST repeat the index's WHERE clause for Postgres
        # to use the partial-index path. SAVEPOINT-wrap so a cross-entity EXACT
        # collision against the legacy ``uidx_entity_aliases_normalized`` index
        # cannot poison the outer transaction.
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    text("""
INSERT INTO entity_aliases
    (entity_id, alias_text, normalized_alias_text, alias_type, is_active, source)
VALUES (:eid, :alias, :norm, 'EXACT', true, 'canonical_entity_create')
ON CONFLICT (entity_id, normalized_alias_text, alias_type)
WHERE is_active = true
DO NOTHING
"""),
                    {
                        "eid": str(resolved_entity_id),
                        "alias": canonical_name,
                        "norm": canonical_name.lower().strip(),
                    },
                )
        except Exception:  # noqa: S110 — cross-entity EXACT collision is recoverable
            # The canonical was successfully created and the cross-entity EXACT
            # alias just couldn't be inserted; that's an acceptable degraded
            # state (the canonical is reachable by entity_id, just not by
            # exact-alias text match against this exact spelling).
            pass
        return resolved_entity_id
