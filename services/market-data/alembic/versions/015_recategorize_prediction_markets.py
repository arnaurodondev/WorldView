"""Backfill prediction_markets.category using title-keyword heuristics.

Revision ID: 015
Revises: 014
Create Date: 2026-05-03

PLAN-0068 Wave C-1 — C-1-01.

WHY THIS MIGRATION EXISTS:
All 102 currently-stored prediction markets carry category = 'sports' because
the Polymarket Gamma API returns "Sports" as the top-level `category` string
for most open markets, and the S3 content-ingestion consumer normalised this
to 'sports' via `_normalize_category()`. Historical rows were persisted before
the title-keyword heuristic (`_categorize_by_title`) was applied to the CASE
where Gamma mis-categorises a non-sports market as "Sports".

The fix is a one-time SQL backfill that re-runs the title-keyword heuristic
(mirroring `_TITLE_HEURISTIC_RULES` in content_ingestion/domain/entities.py)
against all rows where category = 'sports' or category IS NULL, and updates
them to the correct canonical bucket.

IMPORTANT: The CASE checks run in priority order (macro first) to match the
Python heuristic — a market about "Fed and BTC" is tagged macro, not crypto.

KEYWORD PARITY: The LIKE ANY(ARRAY[...]) patterns MUST stay in sync with
`_TITLE_HEURISTIC_RULES` in `content-ingestion`. A divergence test
(C-1-03) verifies this.

DATA MIGRATION: The downgrade is intentionally a no-op. Category values are
derived data that can be recomputed from the question text; a rollback would
regenerate the old wrong data, which is not useful. Alembic supports this
pattern for one-way data migrations (see BP-126 note: column is already
NULLABLE so no NOT NULL risk here).
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Re-categorise prediction_markets rows using title-keyword heuristics.

    The UPDATE only targets rows where category = 'sports' or category IS NULL
    (i.e. rows that are either clearly mis-categorised by the Gamma API or have
    no category at all). Rows already carrying 'macro', 'politics', 'crypto', or
    'general' from a correct prior ingest are left untouched.

    CASE priority:
      1. macro   — economic / monetary policy keywords
      2. politics — electoral / legislative keywords
      3. sports  — league / event keywords
      4. crypto  — cryptocurrency keywords
      5. ELSE    — 'general' for anything that doesn't match (replaces 'sports' default)

    WHY lower(question): Polymarket question text may be Title Case or sentence
    case — lowercasing before the LIKE comparison avoids missing "Fed" vs "fed"
    or "NFL" vs "nfl".
    """
    op.execute(
        """
        UPDATE prediction_markets
        SET category = CASE
            -- Macro: monetary policy, economic indicators, trade policy
            WHEN lower(question) LIKE ANY(ARRAY[
                '%fed%', '%rate%', '%inflation%', '%gdp%', '%cpi%',
                '%unemployment%', '%recession%', '%fomc%', '%payroll%',
                '%pce%', '%treasury%', '%yield%', '%deficit%',
                '%tariff%', '%economic%', '%fiscal%', '%monetary%', '%pmi%'
            ]) THEN 'macro'

            -- Politics: elections, legislation, government
            WHEN lower(question) LIKE ANY(ARRAY[
                '%election%', '%president%', '%presidential%',
                '%senate%', '%congress%', '%vote%', '%primary%',
                '%governor%', '%supreme court%', '%impeach%'
            ]) THEN 'politics'

            -- Sports: league names, tournaments
            WHEN lower(question) LIKE ANY(ARRAY[
                '%nba%', '%nfl%', '%mlb%', '%nhl%',
                '%superbowl%', '%super bowl%', '%world cup%',
                '%olympics%', '%champion%', '%f1%', '%fifa%', '%uefa%'
            ]) THEN 'sports'

            -- Crypto: major coins and general crypto
            WHEN lower(question) LIKE ANY(ARRAY[
                '%bitcoin%', '%ethereum%', '%btc%', '%eth%',
                '%crypto%', '%solana%', '%sol%', '%altcoin%'
            ]) THEN 'crypto'

            -- General: catch-all for anything that doesn't match the above
            ELSE 'general'
        END
        WHERE category = 'sports' OR category IS NULL
        """
    )


def downgrade() -> None:
    """No-op downgrade — category is derived data from the question text.

    WHY no-op: Rolling back this migration would require restoring the old
    incorrect 'sports' category values, which provides no value. The correct
    categories can always be recomputed by re-running the upgrade(). This is
    standard practice for one-way data migrations that fix corrupted derived
    data (similar pattern to BP-126 server_default-free nullable column).
    """
