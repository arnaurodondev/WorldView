"""Fix EODHD seed symbols that 404 against the provider API.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-11

Background
----------
Three seed-data mistakes cause permanent EODHD 404s (tasks fail, retry, and
pile up as ``failed``):

1. ``CCMP.INDX`` / ``INDU.INDX`` — Bloomberg index codes. EODHD uses
   ``IXIC.INDX`` (Nasdaq Composite) and ``DJI.INDX`` (Dow Jones Industrial
   Average).
2. ``000001.SS`` with exchange ``SHG`` — the EODHD adapter's
   ``_build_ticker`` appends the exchange, producing the double-suffixed
   ticker ``000001.SS.SHG``. The symbol must be the bare ``000001`` so the
   built ticker becomes ``000001.SHG``.
3. Macro indicator ``unemployment_total_pct`` — EODHD's indicator name is
   ``unemployment_total_percent``. Policy symbols embed the indicator as
   ``USA.unemployment_total_pct``.

This migration renames the affected ``polling_policies`` rows (ALL
timeframes/datasets for the index symbols, not just 1mo) and deletes the
accumulated ``failed`` tasks for the old symbols.

Why DELETE instead of ``status='cancelled'``
--------------------------------------------
``contracts.enums.IngestionTaskStatus`` has no CANCELLED member
(pending/claimed/running/succeeded/retry/failed) and
``task_repository.py`` hydrates rows via ``IngestionTaskStatus(row.status)``
— writing an out-of-enum string would crash every task read. ``failed`` is
terminal, so the rows are pure noise for symbols that will never be polled
again; deleting them is the safe equivalent of cancellation.

Forward-compat (R5)
-------------------
Data-only UPDATE/DELETE — no schema changes. Downgrade reverses the symbol
renames; deleted failed tasks are not resurrected (they were terminal noise).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

# (old_symbol, new_symbol) pairs applied to polling_policies. Exchange is
# untouched: IXIC/DJI keep INDX, 000001 keeps SHG.
_SYMBOL_RENAMES: list[tuple[str, str]] = [
    ("CCMP", "IXIC"),
    ("INDU", "DJI"),
    ("000001.SS", "000001"),
    ("USA.unemployment_total_pct", "USA.unemployment_total_percent"),
]

# Old symbols whose terminal failed tasks are deleted (see docstring).
_OLD_SYMBOLS = [old for old, _new in _SYMBOL_RENAMES]


def upgrade() -> None:
    conn = op.get_bind()
    for old, new in _SYMBOL_RENAMES:
        conn.execute(
            sa.text("UPDATE polling_policies SET symbol = :new, updated_at = NOW() WHERE symbol = :old"),
            {"old": old, "new": new},
        )
    conn.execute(
        sa.text("DELETE FROM ingestion_tasks WHERE symbol = ANY(:symbols) AND status = 'failed'"),
        {"symbols": _OLD_SYMBOLS},
    )


def downgrade() -> None:
    conn = op.get_bind()
    for old, new in _SYMBOL_RENAMES:
        conn.execute(
            sa.text("UPDATE polling_policies SET symbol = :old, updated_at = NOW() WHERE symbol = :new"),
            {"old": old, "new": new},
        )
