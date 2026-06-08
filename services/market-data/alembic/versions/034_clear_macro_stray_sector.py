"""Clear stray 'Macro' sector tag on macro indicators.

Open issue #5 (Sector Performance dashboard cleanup):

The seed file ``infra/seeds/universe.json`` historically assigned
``sector='Macro'`` to 12 non-equity instruments (7 indices on the
``INDX`` exchange + 5 FX/precious-metal spot pairs on the ``FOREX``
exchange). ``Macro`` is not a real GICS sector and pollutes the
Sector Performance heatmap by adding a phantom 14th bucket holding
S&P 500, NASDAQ, VIX, EUR/USD, Gold, etc.

The seed file has been updated in the same change to emit ``null``
sector for these instruments going forward. This migration cleans
up the existing rows in ``market_data_db.instruments`` so the
dashboard immediately drops the spurious bucket.

The predicate is intentionally narrow: ``sector = 'Macro'``. Today
all 12 affected rows are INDX/FOREX exchanges, but constraining on
``sector`` alone is safe because no legitimate GICS taxonomy uses
the literal string ``Macro``.

Downgrade is a no-op: the original (incorrect) classification is
not recoverable and there is no need to restore it.

Chains to migration 033 (``033_ix_ohlcv_bars_instr_bar_date_daily``)
which lives on ``main`` but not yet on this feature branch — the
``down_revision='033'`` is correct because the deployed database
will already be at 033 once this branch is merged.
"""

from alembic import op

# Alembic identifiers ---------------------------------------------------------
revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Null out the stray 'Macro' sector value on macro instruments."""
    op.execute("UPDATE instruments SET sector = NULL WHERE sector = 'Macro'")


def downgrade() -> None:
    """No-op — the original (incorrect) classification is not recoverable."""
    pass
