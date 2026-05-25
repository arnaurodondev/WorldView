"""Add fiscal_year_end_month to instruments + seed major US tickers — FIX-LIVE-P.

Revision ID: 018
Revises: 017
Create Date: 2026-05-25

WHY THIS MIGRATION EXISTS:
  ``GetFundamentalsHistoryUseCase._period_label()`` historically computed the
  fiscal quarter purely from the calendar month of ``report_date``. This breaks
  for any issuer whose fiscal year does not align with the calendar:

    * NVIDIA   — fiscal year ends late January  (FY26 ends 2026-01-31, fiscal Q4)
    * Apple    — fiscal year ends late September (FY26 ends 2026-09-30, fiscal Q4)
    * Microsoft — fiscal year ends June 30      (FY26 ends 2026-06-30, fiscal Q4)

  Without a fiscal-year-end reference, NVDA's Q4FY26 was rendered as ``Q1 2026``
  and AAPL's Q4FY26 as ``Q3 2026``, causing RAG to hand the LLM mismatched
  quarter labels (live-QA finding INV-LIVE-P / FIX-LIVE-P).

  Adding ``fiscal_year_end_month`` (1-12) on the ``instruments`` table is the
  minimum schema required for the use case to compute fiscal quarters correctly
  without crossing service boundaries.  The existing ``company_profiles.fiscal_year_end``
  column is a free-text string ("September" / "12-31") that is never read today
  and would require its own parser; an integer month is simpler and addresses
  the bug directly.

WHAT THIS MIGRATION DOES:
  1. Adds nullable ``fiscal_year_end_month INT`` to ``instruments``.
  2. Seeds the six major US tickers that the re-QA hits today so the fix is
     visible without waiting for a separate enrichment pass.

SEED VALUES (verified against public 10-K / 10-Q filings):
  * AAPL  — last Saturday of September → month 9
  * MSFT  — June 30 → month 6
  * NVDA  — last Sunday of January → month 1
  * AMD   — last Saturday of December → month 12
  * GOOGL — December 31 → month 12
  * META  — December 31 → month 12

  The UPDATE matches on ``symbol`` only (case-insensitive). A given ticker
  may exist on multiple exchanges in the test/prod data but the fiscal year
  is a company-level attribute, not exchange-level, so all matching rows
  receive the same value.

IDEMPOTENCY:
  ``add_column`` raises if the column already exists; this is fine for a fresh
  migration. The UPDATE statements are idempotent — they overwrite to the same
  value on re-run.

DOWNGRADE:
  Drops the column. The seed values are lost; that's acceptable because the
  column itself is gone.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


# Company → fiscal-year-end month. Sourced from public SEC filings (10-K) as of
# 2026-05. Kept as a module-level constant so the seed step is auditable.
_SEED_FISCAL_YEAR_END: dict[str, int] = {
    "AAPL": 9,
    "MSFT": 6,
    "NVDA": 1,
    "AMD": 12,
    "GOOGL": 12,
    "META": 12,
}


def upgrade() -> None:
    """Add the nullable column and seed known issuers."""
    op.add_column(
        "instruments",
        sa.Column("fiscal_year_end_month", sa.Integer(), nullable=True),
    )

    # Seed in a single statement per ticker so a failed update on one row
    # (e.g. unseeded test DB without AAPL) does not block the others.
    for symbol, month in _SEED_FISCAL_YEAR_END.items():
        op.execute(
            sa.text("UPDATE instruments SET fiscal_year_end_month = :month WHERE upper(symbol) = :symbol").bindparams(
                month=month, symbol=symbol
            )
        )


def downgrade() -> None:
    """Drop the column (seed values are lost — acceptable for a structural revert)."""
    op.drop_column("instruments", "fiscal_year_end_month")
