"""Enforce ticker uniqueness for financial_instrument canonicals — the DB-level
guard that makes BP-459 same-ticker duplication impossible regardless of which
application image is deployed.

Revision ID: 0051
Revises: 0050
Create Date: 2026-06-13

WHY THIS MIGRATION EXISTS (BP-459 — duplicate canonical entities):
  Two mint pipelines could each create a ``financial_instrument`` canonical for
  the SAME ticker with no ticker-level dedup:
    * market-data instrument seeding (``InstrumentEntityConsumer``) deduped only
      on ``ON CONFLICT (entity_id)`` — never on ticker;
    * news/provisional promotion (``provisional_enrichment_core``) anchored to an
      instrument only if it already existed (a race), the lower(name) unique
      index EXCLUDES ``financial_instrument``, and the fuzzy pre-lookup is
      name-only — so "Shell Plc" (SHEL, no exchange) and "Shell PLC ADR"
      (SHEL, US) coexisted, splitting news mentions from the tradeable
      instrument.  Blast radius at discovery: 451 tickers / 593 excess rows.

  An APPLICATION-level fix shipped (a ``find_by_ticker`` pre-lookup that reuses
  the existing same-ticker canonical).  But a stale per-service worker image
  silently re-introduced two dups (ORCL/CTVA) hours later — proving that an
  app-level guard is only as good as its deployment.  This migration adds the
  belt-and-suspenders DB constraint so the bug cannot recur EVEN IF a future
  deploy ships pre-fix code: a duplicate INSERT now fails loudly with a unique
  violation instead of silently creating a twin (the mint paths catch that
  violation and reuse the existing entity — see provisional_enrichment_core /
  instrument_consumer).

WHAT IT DOES:
  A PARTIAL UNIQUE index on ``ticker`` scoped to ``financial_instrument`` only::

      CREATE UNIQUE INDEX uq_canonical_entities_ticker_fi
        ON canonical_entities (ticker)
        WHERE ticker IS NOT NULL AND entity_type = 'financial_instrument';

  WHY PARTIAL + scoped to financial_instrument:
    * Non-instrument entities (person/place/event/…) never carry a ticker, and
      we must NOT constrain them.
    * Two different entity TYPES sharing a ticker string (e.g. a future
      ``index`` row) are intentionally out of scope — this guard targets the
      exact dup class observed (two ``financial_instrument`` rows, same ticker).
    * ``ticker IS NOT NULL`` keeps NULL-ticker rows unconstrained (Postgres
      treats NULLs as distinct anyway, but the partial predicate is explicit).

PRE-FLIGHT ASSERTION (FAIL LOUD — BP-688 lesson):
  A plain ``CREATE UNIQUE INDEX`` over existing dups would abort with a generic
  "could not create unique index … contains duplicated values" error that names
  one arbitrary key.  Before creating, we COUNT the offending tickers and, if
  any remain, RAISE EXCEPTION listing them — so the operator knows to run
  ``scripts/data/merge_ticker_duplicates.py`` first.  (At authoring time the
  platform-wide dup count was already merged to 0.)

BP-393 — NO ``CONCURRENTLY``:
  Plain (non-concurrent) ``CREATE UNIQUE INDEX`` only.  ``CONCURRENTLY`` cannot
  run inside a migration transaction (BP-393); ``canonical_entities`` is small
  (low tens of thousands) and builds in well under a second.

FORWARD-COMPATIBILITY (R11):
  Purely additive — one index, no column/table removed or renamed.  Existing
  readers/writers are unaffected except that a genuinely duplicate same-ticker
  ``financial_instrument`` INSERT now errors (which is the intent; callers
  dedupe-then-reuse on conflict).

DOWNGRADE:
  Drops the index only (row data untouched).
"""

from __future__ import annotations

from alembic import op

revision: str = "0051"
down_revision: str = "0050"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade DDL — assert zero same-ticker financial_instrument duplicates remain,
# then create the partial UNIQUE index, then ASSERT it materialised (FAIL LOUD).
# ---------------------------------------------------------------------------
_CREATE_UNIQUE_TICKER_FI_INDEX = """
DO $$
DECLARE
    _dup_tickers TEXT;
    _index_exists BOOLEAN;
BEGIN
    -- 1. Pre-flight: refuse (with a precise message) if dups still exist, rather
    --    than letting CREATE UNIQUE INDEX abort with a generic single-key error.
    SELECT string_agg(ticker, ', ')
      INTO _dup_tickers
      FROM (
          SELECT ticker
          FROM canonical_entities
          WHERE ticker IS NOT NULL AND entity_type = 'financial_instrument'
          GROUP BY ticker
          HAVING COUNT(*) > 1
      ) d;

    IF _dup_tickers IS NOT NULL THEN
        RAISE EXCEPTION
            'Migration 0051 ABORTED: same-ticker financial_instrument duplicates '
            'still exist for tickers [%]. Run scripts/data/merge_ticker_duplicates.py '
            'to consolidate them, then re-run this migration (BP-459).', _dup_tickers;
    END IF;

    -- 2. Create the partial UNIQUE index (PLAIN / non-concurrent — BP-393).
    CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_entities_ticker_fi
        ON canonical_entities (ticker)
        WHERE ticker IS NOT NULL AND entity_type = 'financial_instrument';

    -- 3. ASSERT the index exists — never report success on a silent no-op.
    SELECT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'uq_canonical_entities_ticker_fi'
          AND c.relkind = 'i'
    ) INTO _index_exists;

    IF NOT _index_exists THEN
        RAISE EXCEPTION
            'Migration 0051 FAILED: uq_canonical_entities_ticker_fi was not '
            'materialised after CREATE UNIQUE INDEX (BP-688 silent-swallow class).';
    END IF;

    RAISE NOTICE
        'Created/verified UNIQUE index uq_canonical_entities_ticker_fi — same-ticker '
        'financial_instrument duplication is now impossible at the DB level (BP-459).';
END;
$$
"""

_DROP_UNIQUE_TICKER_FI_INDEX = """
DROP INDEX IF EXISTS uq_canonical_entities_ticker_fi;
"""


def upgrade() -> None:
    """Add the partial UNIQUE index on (ticker) for financial_instrument (BP-459)."""
    op.execute(_CREATE_UNIQUE_TICKER_FI_INDEX)


def downgrade() -> None:
    """Drop the partial UNIQUE index (row data preserved)."""
    op.execute(_DROP_UNIQUE_TICKER_FI_INDEX)
