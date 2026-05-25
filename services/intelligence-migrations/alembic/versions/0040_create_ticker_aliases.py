"""Create ticker_aliases table — PLAN-0089 F2 Step 1 (M2).

Revision ID: 0040
Revises: 0039
Create Date: 2026-05-20

WHY THIS MIGRATION EXISTS:
  PRD-0089 / PLAN-0089 wave F2 enables ticker-first URL routing
  (``/instruments/AAPL`` rather than ``/instruments/{uuid}``) and must
  transparently redirect legacy tickers to the current canonical form
  (e.g. ``/instruments/FB → /instruments/META``).

  Per F2 plan §2.2, the alias history lives in ``intelligence_db``
  (colloquially "kg_db") — single source of truth for entity identity.
  Aliases are an entity concern, not a market-data ingestion concern.

WHAT THIS MIGRATION DOES:
  1. Creates ``ticker_aliases`` table with the exact column shape from
     F2 plan §2.2.
  2. Adds partial unique index on ``upper(alias)`` WHERE ``is_current=TRUE``
     — guarantees a single live ticker per alias string at any time, while
     allowing multiple historical (``is_current=FALSE``) records to share
     the same alias string across different periods.
  3. Adds non-unique B-tree index on ``entity_id`` for reverse lookups
     (given an entity, list its current + historical tickers).

NO-BACKFILL NOTE (per platform_state: pre-production):
  Table starts EMPTY. PRD-0089 F2 ships the lookup path (gateway middleware
  + alias redirect) but no historical aliases are seeded — only a future
  ticker change recorded by an operator (or by an automated EODHD ingest
  signal) populates rows.

PRIMARY KEY GENERATION:
  Uses ``new_uuid7()`` as the default — this Postgres function was
  registered by migration 0031 and is the canonical UUIDv7 generator for
  ``intelligence_db`` (R7: UUIDv7 only for new tables). Other tables in
  this DB (entity_narrative_versions, path_jobs, path_insights,
  path_templates) use the same default.

TIMESTAMP DEFAULT:
  Uses ``now()`` (Postgres standard, returns ``TIMESTAMPTZ`` in UTC when
  the cluster is configured with ``timezone=UTC``). The repo-wide
  intelligence-migrations convention uses bare ``now()`` consistently —
  no ``utc_now()`` SQL function exists in this DB; the ``utc_now()``
  helper referenced by F2 plan §2.2 is the Python ``common.time.utc_now()``
  helper, not a SQL function. Using ``now()`` here matches every other
  table in this DB (canonical_entities, entity_aliases,
  entity_embedding_state, …).

DOWNGRADE:
  Drops the table. Indexes are dropped automatically by Postgres when
  the parent table is dropped.
"""

from __future__ import annotations

from alembic import op

revision: str = "0040"
down_revision: str = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create ticker_aliases + its two indexes."""
    # ── ticker_aliases table ───────────────────────────────────────────────────
    # Column shape pinned to F2 plan §2.2:
    #   id          UUID PK DEFAULT new_uuid7()
    #   entity_id   UUID NOT NULL FK → canonical_entities.entity_id
    #   alias       VARCHAR(32) — the ticker string itself (e.g. 'FB')
    #   is_current  BOOLEAN — TRUE for the live ticker for this entity
    #   valid_from  TIMESTAMPTZ — when the alias became active
    #   valid_to    TIMESTAMPTZ NULL — NULL means still valid
    #   source      VARCHAR(64) — 'eodhd' | 'manual' | 'sec_form_8k' | …
    #   created_at  TIMESTAMPTZ — row insert audit
    op.execute(
        """
        CREATE TABLE ticker_aliases (
            id          UUID PRIMARY KEY DEFAULT new_uuid7(),
            entity_id   UUID NOT NULL REFERENCES canonical_entities(entity_id) ON DELETE CASCADE,
            alias       VARCHAR(32) NOT NULL,
            is_current  BOOLEAN NOT NULL DEFAULT FALSE,
            valid_from  TIMESTAMPTZ NOT NULL DEFAULT now(),
            valid_to    TIMESTAMPTZ,
            source      VARCHAR(64),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # ── Partial unique index: one live ticker per alias string ────────────────
    # Allows historical (``is_current=FALSE``) rows to repeat alias strings
    # across time (e.g. an old ticker reassigned to a different security
    # decades later) while the LIVE/current row is unique on the upper-cased
    # alias. ``upper(alias)`` matches the gateway lookup path which always
    # upper-cases user input before resolving.
    op.execute(
        """
        CREATE UNIQUE INDEX idx_ticker_aliases_alias_current
          ON ticker_aliases (upper(alias))
          WHERE is_current = TRUE
        """
    )

    # ── Reverse-lookup index: given an entity, list aliases ───────────────────
    # Non-unique B-tree — same entity may have multiple historical aliases.
    op.execute("CREATE INDEX idx_ticker_aliases_entity ON ticker_aliases (entity_id)")


def downgrade() -> None:
    """Drop ticker_aliases (cascades to its indexes)."""
    op.execute("DROP TABLE IF EXISTS ticker_aliases")
