"""Bootstrap enrichment pipeline for seeded financial_instrument entities — BP-543.

Revision ID: 0043
Revises: 0042
Create Date: 2026-05-23

WHY THIS MIGRATION EXISTS:
  The 10 most-important financial_instrument canonicals were inserted via Alembic
  seed migrations (pre-0009) before the enrichment pipeline existed:

    AAPL  Apple Inc.
    NVDA  NVIDIA Corporation
    MSFT  Microsoft Corporation
    GOOGL Alphabet Inc Class A
    AMZN  Amazon.com Inc
    META  Meta Platforms Inc.
    TSLA  Tesla Inc
    BRK.B Berkshire Hathaway
    NFLX  Netflix, Inc.         (added in migration 0038)
    JPM   JPMorgan Chase & Co

  These entities were missing the conditions that let DefinitionRefreshWorker
  and StructuredEnrichmentWorker pick them up automatically:

    1. ``entity_embedding_state`` rows with ``source_text`` populated for the
       'definition' view — the worker skips rows where source_text IS NULL
       (nothing to embed).

    2. ``data_completeness = NULL`` (and ``enriched_at = NULL``) — the structured
       enrichment sweep query is:
           WHERE (enriched_at IS NULL OR data_completeness < 0.5)
             AND enrichment_attempts < 3
       These entities qualify (enrichment_attempts = 0, enriched_at = NULL)
       but without a description they produce empty enrichment output, so the
       sweep stalls.

  A one-time SQL fix was applied manually in the 2026-05-23 session for 8 of
  these entities (real EODHD descriptions → entity_embedding_state.source_text
  and canonical_entities.description).  This migration makes the fix permanent
  and idempotent so that:
    (a) A fresh ``alembic upgrade head`` on a new deployment gets the same state.
    (b) The entities are immediately queued for embedding + enrichment on the
        next worker cycle (next_refresh_at = NOW() - INTERVAL '1 hour').

WHAT THIS MIGRATION DOES:
  Step 1 — entity_embedding_state 'definition' rows:
    For seeded entities that have a description, upsert a 'definition' EES row
    copying description → source_text, with next_refresh_at set 1 hour in the
    past so DefinitionRefreshWorker picks them up on the very next sweep.
    ON CONFLICT: if the row already exists and source_text IS NULL, overwrite
    source_text from the canonical's description and reset next_refresh_at.
    If source_text is already populated, leave it alone (DO NOTHING path via
    WHERE guard on the DO UPDATE SET clause).

  Step 2 — entity_embedding_state 'narrative' rows:
    For seeded entities that already have a narrative EES row but whose
    next_refresh_at is not past-due, reset it to 1 hour in the past.
    For entities missing a narrative row entirely, insert one.
    Both ensure NarrativeRefreshWorker processes them next cycle.

  Step 3 — data_completeness = 0.5:
    Update canonical_entities rows where description IS NOT NULL but
    data_completeness IS NULL (or < 0.5), setting data_completeness = 0.5.
    The sweep threshold is < 0.5; 0.5 means "has a description, structurally
    complete but not EODHD-enriched".  This prevents an infinite enrichment
    loop (the worker won't re-try entities already at ≥ 0.5).

IDEMPOTENCY:
  All three steps use ON CONFLICT DO UPDATE / WHERE guards or UPDATE … WHERE
  filters.  Running upgrade() twice produces the same state as running it once.

DOWNGRADE:
  No-op.  The rows are re-created by the worker on the next cycle anyway, and
  deleting them risks disrupting an already-running enrichment pipeline.
  The canonical seed rows themselves (from pre-0009 + 0038 migrations) are not
  touched; only entity_embedding_state and data_completeness are modified.

TICKETS: BP-543
"""

from __future__ import annotations

from alembic import op

revision: str = "0043"
down_revision: str = "0042"
branch_labels = None
depends_on = None

# ── Ticker list ───────────────────────────────────────────────────────────────
# The 10 seeded financial instruments.  BRK.B is stored as 'BRK.B' in the
# ticker column (the canonical form used at insert time).  NFLX was added
# by migration 0038.
_TICKERS = ("AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "BRK.B", "NFLX", "JPM")

# SQL-safe tuple literal for use in IN(...) clauses.
_TICKERS_SQL = ", ".join(f"'{t}'" for t in _TICKERS)


def upgrade() -> None:
    """Bootstrap enrichment pipeline state for the 10 seeded entities."""

    # ── Step 1: entity_embedding_state 'definition' rows ─────────────────────
    #
    # For each seeded entity that has a description:
    #   • If no EES row exists → INSERT with source_text = description and
    #     next_refresh_at 1 hour in the past (immediately due).
    #   • If an EES row exists with source_text IS NULL → UPDATE source_text
    #     and reset next_refresh_at so DefinitionRefreshWorker re-processes it.
    #   • If an EES row exists with source_text IS NOT NULL → leave it alone
    #     (DO UPDATE WHERE source_text IS NULL guard makes this a no-op).
    #
    # The DO UPDATE clause on ON CONFLICT fires only when the row already exists.
    # The extra WHERE in the DO UPDATE means the SET runs only when source_text
    # is currently NULL — if it's already populated the UPDATE is skipped, making
    # this safe to re-run against a partially-backfilled DB.
    op.execute(
        f"""
INSERT INTO entity_embedding_state
    (entity_id, view_type, source_text, next_refresh_at, last_refreshed_at, refresh_count)
SELECT
    ce.entity_id,
    'definition',
    ce.description,
    NOW() - INTERVAL '1 hour',
    NOW(),
    0
FROM canonical_entities ce
WHERE ce.ticker IN ({_TICKERS_SQL})
  AND ce.description IS NOT NULL
ON CONFLICT (entity_id, view_type) DO UPDATE
    SET source_text     = EXCLUDED.source_text,
        next_refresh_at = EXCLUDED.next_refresh_at
    WHERE entity_embedding_state.source_text IS NULL
"""
    )

    # ── Step 2: entity_embedding_state 'narrative' rows ───────────────────────
    #
    # Narrative embeddings require the worker to build a narrative blob first
    # (recent news + relations context).  We just need a row to exist with a
    # past-due next_refresh_at so NarrativeRefreshWorker picks it up.
    #
    # • If no row exists → INSERT with source_text = NULL (worker fills it in),
    #   next_refresh_at 1 hour past.
    # • If a row exists but next_refresh_at is in the future (worker hasn't
    #   reached it yet) → update to force it to be immediately due.
    # • If a row exists and is already past-due → DO NOTHING (no WHERE guard
    #   needed; the ON CONFLICT DO UPDATE WHERE next_refresh_at > NOW() means
    #   past-due rows are untouched).
    op.execute(
        f"""
INSERT INTO entity_embedding_state
    (entity_id, view_type, source_text, next_refresh_at, last_refreshed_at, refresh_count)
SELECT
    ce.entity_id,
    'narrative',
    NULL,
    NOW() - INTERVAL '1 hour',
    NOW(),
    0
FROM canonical_entities ce
WHERE ce.ticker IN ({_TICKERS_SQL})
ON CONFLICT (entity_id, view_type) DO UPDATE
    SET next_refresh_at = EXCLUDED.next_refresh_at
    WHERE entity_embedding_state.next_refresh_at > NOW()
"""
    )

    # ── Step 3: data_completeness = 0.5 ──────────────────────────────────────
    #
    # The structured enrichment sweep selects entities WHERE:
    #   (enriched_at IS NULL OR data_completeness < 0.5) AND enrichment_attempts < 3
    #
    # Without a description the enrichment worker will produce no output and
    # increment enrichment_attempts (up to cap = 3), permanently blocking the
    # entity from future re-tries.  Setting data_completeness = 0.5 for entities
    # that have a description signals "partial — has text, not fully EODHD-rich"
    # and prevents the infinite retry loop for entities that aren't in EODHD
    # (e.g. BRK.B class-B shares may not have a perfect EODHD record).
    #
    # Only entities WITH a description get this treatment:
    #   - description IS NOT NULL → at least 0.5 completion (has a blurb)
    #   - data_completeness IS NULL OR < 0.5 → only update those that need it
    # Idempotent: running twice leaves the same value (0.5 is not < 0.5).
    op.execute(
        f"""
UPDATE canonical_entities
SET    data_completeness = 0.5
WHERE  ticker IN ({_TICKERS_SQL})
  AND  description IS NOT NULL
  AND  (data_completeness IS NULL OR data_completeness < 0.5)
"""
    )


def downgrade() -> None:
    """No-op — rows will be re-created by the enrichment workers on the next cycle.

    We intentionally do NOT delete the entity_embedding_state rows or reset
    data_completeness here.  The migration is a bootstrap-only fix; reversing
    it would leave the seeded entities without EES rows, causing DefinitionRefresh
    and NarrativeRefreshWorker to skip them on the next cycle — exactly the BP-543
    bug this migration fixes.  The correct remediation for a rollback scenario is
    to let the workers re-process the entities naturally.
    """
