"""Add a SHARE-CLASS-AWARE unique index on financial_instrument canonicals — FR-11.

Revision ID: 0054
Revises: 0053
Create Date: 2026-06-13

WHY THIS MIGRATION EXISTS (FR-11 — ticker-bearing exact-name duplicates):
  Migration 0026 created a PARTIAL unique index on ``lower(canonical_name)`` that
  *excludes* ``financial_instrument`` (``WHERE entity_type != 'financial_instrument'``).
  It was scoped that way deliberately: two FI canonicals can legitimately share
  the same ``canonical_name`` because a company lists MULTIPLE securities under
  one corporate name — different SHARE CLASSES (Berkshire Hathaway Class A vs
  Class B, distinct ISINs US0846701086 vs US0846707026) and dual listings.  A
  blanket ``UNIQUE(lower(canonical_name))`` would refuse the second share class.

  The FR-11 investigation (docs/audits/2026-06-13-fr11-duplicate-canonical-
  investigation.md) recommended eventually making the name index UNCONDITIONAL
  to also catch the residual exact-name FI dups ("berkshire hathaway inc" x4,
  "brown-forman corporation" x2).  Live inspection (2026-06-13) showed that is
  the WRONG fix: those clusters are a MIX of —
    * genuinely DISTINCT share classes (BRK-A ISIN US0846701086 vs BRK-B ISIN
      US0846707026 — must NEVER be merged), and
    * ticker-NOTATION duplicates of the SAME security (BRK-A vs BRK.A, both ISIN
      US0846701086; BF-B vs BF.B, both ISIN US1156372096) — true dups owned by
      the ticker-merge path, NOT by a name index.
  An unconditional ``lower(canonical_name)`` unique index would (a) reject the
  legitimate Class A / Class B pair and (b) also reject FI-vs-index type splits
  ("CBOE Volatility Index", "Dow Jones Industrial Average", "S&P 500 Index" each
  exist once as ``financial_instrument`` and once as ``index``).  Both are
  CORRECT data that the index would forbid.  Forcing it would be a regression.

WHAT 0054 DOES (the correct, share-class-aware guard):
  A PARTIAL UNIQUE index on the COMPOSITE key
  ``(lower(canonical_name), coalesce(ticker, ''))`` scoped to
  ``financial_instrument`` only::

      CREATE UNIQUE INDEX uq_canonical_entities_name_ticker_fi
        ON canonical_entities (lower(canonical_name), coalesce(ticker, ''))
        WHERE entity_type = 'financial_instrument';

  This treats each (name, ticker) pair as a distinct security, so:
    * BRK Class A and Class B (different tickers) stay separate — CORRECT;
    * a SECOND "Berkshire Hathaway Inc" with the SAME ticker can no longer be
      minted — the dup class FR-11 actually wants to prevent;
    * FI-vs-index name collisions are out of scope (the predicate is FI-only),
      so they are untouched.

  It is COMPLEMENTARY to:
    * migration 0026 — ``lower(canonical_name)`` partial index for NON-FI types
      (the one ``create_or_get``'s ON CONFLICT binds to — NOT modified here);
    * migration 0051 — ``UNIQUE(ticker) WHERE entity_type='financial_instrument'``
      (catches exact same-ticker dups; this 0054 index additionally pins the
      NULL-ticker FI rows by name, which 0051's ``ticker IS NOT NULL`` predicate
      cannot).

WHY NOT TOUCH 0026's index / the ON CONFLICT contract:
  ``CanonicalEntityRepository.create_or_get`` writes
  ``ON CONFLICT (lower(canonical_name)) WHERE entity_type != 'financial_instrument'``
  bound to the 0026 partial index.  Widening or dropping that index would break
  the inferred conflict target and raise "no unique or exclusion constraint
  matching the ON CONFLICT specification" on every non-FI insert.  We therefore
  ADD a SEPARATE FI-scoped index and leave 0026 alone.  (FI inserts go through
  the ticker pre-lookup + 0051 ticker index, not this ON CONFLICT path.)

PRE-FLIGHT ASSERTION (FAIL LOUD — BP-688):
  A plain ``CREATE UNIQUE INDEX`` over residual dups would abort with a generic
  "could not create unique index … is duplicated" naming one arbitrary key.
  Before creating, we COUNT FI rows that share BOTH ``lower(canonical_name)`` AND
  ``coalesce(ticker,'')`` and, if any remain, RAISE EXCEPTION listing them — so
  the operator knows to run ``scripts/data/merge_ticker_duplicates.py`` (the
  notation-dup BRK-A/BRK.A, BF-B/BF.B cases) first.  At authoring time live count
  on this composite key was already 0, so the index builds cleanly; the guard
  protects environments where those merges have not yet run.

BP-393 — NO ``CONCURRENTLY``:
  ``canonical_entities`` is unpartitioned and small; plain (in-transaction)
  ``CREATE UNIQUE INDEX`` is correct (CONCURRENTLY cannot run in a migration
  transaction).

FORWARD-COMPATIBILITY (R5 / R11):
  Purely additive — one index, no column/table removed or renamed.  Existing
  readers/writers are unaffected except that a genuinely duplicate FI INSERT
  (same name + same ticker) now errors (the intent; mint paths dedupe-and-reuse).

DOWNGRADE:
  Drops the index only (row data untouched).
"""

from __future__ import annotations

from alembic import op

revision: str = "0054"
down_revision: str = "0053"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Upgrade DDL — assert zero (name, ticker) FI duplicates remain, then create the
# share-class-aware partial UNIQUE index, then ASSERT it materialised (FAIL LOUD).
#
# coalesce(ticker, '') folds NULL-ticker FI rows into a single empty-string key so
# two NULL-ticker FI canonicals with the same name ALSO conflict (Postgres treats
# raw NULLs as distinct, which would let "SpaceX" duplicate freely otherwise).
# ---------------------------------------------------------------------------
_CREATE_NAME_TICKER_FI_INDEX = """
DO $$
DECLARE
    _dups TEXT;
    _index_exists BOOLEAN;
BEGIN
    -- 1. Pre-flight: refuse (with a precise message) if FI rows still share both
    --    lower(canonical_name) AND coalesce(ticker,''), rather than letting
    --    CREATE UNIQUE INDEX abort with a generic single-key error.
    SELECT string_agg(format('%L (ticker=%L) x%s', ln, tk, c), ', ')
      INTO _dups
      FROM (
          SELECT lower(canonical_name) AS ln,
                 coalesce(ticker, '')  AS tk,
                 count(*)              AS c
          FROM canonical_entities
          WHERE entity_type = 'financial_instrument'
          GROUP BY lower(canonical_name), coalesce(ticker, '')
          HAVING count(*) > 1
      ) d;

    IF _dups IS NOT NULL THEN
        RAISE EXCEPTION
            'Migration 0054 ABORTED: financial_instrument duplicates still share '
            'the same (lower(canonical_name), ticker): [%]. These are usually '
            'ticker-NOTATION dups of the same security (e.g. BRK-A vs BRK.A, both '
            'ISIN US0846701086) — run scripts/data/merge_ticker_duplicates.py to '
            'consolidate them, then re-run this migration (FR-11 / BP-459 / BP-688). '
            'Do NOT merge genuinely distinct share classes (BRK-A vs BRK-B).', _dups;
    END IF;

    -- 2. Create the share-class-aware partial UNIQUE index (PLAIN — BP-393).
    CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_entities_name_ticker_fi
        ON canonical_entities (lower(canonical_name), coalesce(ticker, ''))
        WHERE entity_type = 'financial_instrument';

    -- 3. ASSERT the index exists — never report success on a silent no-op.
    SELECT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'uq_canonical_entities_name_ticker_fi'
          AND c.relkind = 'i'
    ) INTO _index_exists;

    IF NOT _index_exists THEN
        RAISE EXCEPTION
            'Migration 0054 FAILED: uq_canonical_entities_name_ticker_fi was not '
            'materialised after CREATE UNIQUE INDEX (BP-688 silent-swallow class).';
    END IF;

    RAISE NOTICE
        'Created/verified share-class-aware UNIQUE index '
        'uq_canonical_entities_name_ticker_fi — a financial_instrument with the '
        'same name AND ticker can no longer be duplicated, while distinct share '
        'classes (BRK-A vs BRK-B) remain legal (FR-11).';
END;
$$
"""

_DROP_NAME_TICKER_FI_INDEX = """
DROP INDEX IF EXISTS uq_canonical_entities_name_ticker_fi;
"""


def upgrade() -> None:
    """Add the share-class-aware (name, ticker) UNIQUE index for FI (FR-11)."""
    op.execute(_CREATE_NAME_TICKER_FI_INDEX)


def downgrade() -> None:
    """Drop the share-class-aware UNIQUE index (row data preserved)."""
    op.execute(_DROP_NAME_TICKER_FI_INDEX)
