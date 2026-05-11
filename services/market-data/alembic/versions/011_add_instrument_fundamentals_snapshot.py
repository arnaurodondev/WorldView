"""Add instrument_fundamentals_snapshot table.

Revision ID: 011
Revises: 010
Create Date: 2026-04-29

WHY: The market-data service stores fundamentals in 18 section-specific tables
(JSONB blobs) plus a key-value projection table (fundamental_metrics).  Both
are optimised for timeseries / screener queries, not for serving a single-row
"all current metrics" snapshot to the frontend.

PLAN-0050 Wave D adds 10 new display-critical fields that the FundamentalsTab
and InstrumentKeyMetrics panel currently show as "—" placeholders:
  - eps_ttm              (Earnings Per Share, trailing twelve months)
  - beta                 (market beta from EODHD Technicals section)
  - avg_volume_30d       (30-day average daily volume)
  - operating_cash_flow  (most recent annual operating cash flow)
  - capex                (capital expenditures — negative in EODHD CF statements)
  - free_cash_flow       (derived: operating_cf - capex)
  - fcf_margin           (derived: fcf / revenue)
  - interest_coverage    (derived: ebit / interest_expense)
  - net_debt_to_ebitda   (derived: (total_debt - cash) / ebitda)
  - credit_rating        (S&P/Moody's rating string from EODHD CreditRating field)

WHY a separate snapshot table (not columns on fundamental_metrics):
  - fundamental_metrics is a narrow key-value table (instrument_id, metric, value)
    — adding typed columns would break the homogeneous schema.
  - A one-row-per-instrument snapshot table allows the API to serve a typed
    flat response without pivoting hundreds of key-value rows at query time.
  - Forward-compatible: new columns can be added as nullable NOPs (BP-126).

WHY all nullable / NO server_default (BP-126):
  - NULL = "not yet computed" — no column-level default avoids a full-table
    rewrite on future ALTER TABLE ADD COLUMN statements.
  - The API layer treats NULL as "data unavailable" → displays "—".
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One-row-per-instrument snapshot of key display metrics.
    # Use IF NOT EXISTS so re-runs on partially-applied dev volumes are no-ops.
    op.execute("""
        CREATE TABLE IF NOT EXISTS instrument_fundamentals_snapshot (
            instrument_id   UUID        NOT NULL
                            REFERENCES instruments (id) ON DELETE CASCADE,
            -- Earnings Per Share (trailing twelve months) from EODHD Highlights
            eps_ttm         NUMERIC     NULL,
            -- Market beta (52-week, market = S&P 500) from EODHD Technicals
            beta            NUMERIC     NULL,
            -- 30-day average daily trading volume from EODHD Technicals
            avg_volume_30d  BIGINT      NULL,
            -- Most recent annual operating cash flow (USD) from EODHD CashFlow
            operating_cash_flow  NUMERIC NULL,
            -- Capital expenditures (USD, negative in EODHD CF statements)
            capex           NUMERIC     NULL,
            -- Free cash flow = operating_cf - |capex| (derived)
            free_cash_flow  NUMERIC     NULL,
            -- FCF margin = fcf / revenue (derived, NULL if revenue = 0)
            fcf_margin      NUMERIC     NULL,
            -- Interest coverage ratio = EBIT / interest_expense (derived)
            interest_coverage    NUMERIC NULL,
            -- Net debt / EBITDA = (total_debt - cash) / ebitda (derived)
            net_debt_to_ebitda   NUMERIC NULL,
            -- Credit rating string, e.g. "A+" from EODHD
            credit_rating   VARCHAR(10) NULL,
            -- Timestamp of last backfill run (UTC)
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (instrument_id)
        )
    """)

    # Index on updated_at to find stale snapshots efficiently during backfill.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ifundamentals_snapshot_updated_at "
        "ON instrument_fundamentals_snapshot (updated_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ifundamentals_snapshot_updated_at")
    op.execute("DROP TABLE IF EXISTS instrument_fundamentals_snapshot")
