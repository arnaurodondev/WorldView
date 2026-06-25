"""Backfill instruments.entity_id := id to satisfy M-017 (data-only).

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-14

2026-06-14 follow-up (issue: dashboard "Portfolio News" showed zero news).

ROOT CAUSE: 10 demo-seeded instruments (AAPL/MSFT/NVDA/AMZN/TSLA/GOOGL/META/
JPM/NFLX/DIS) carried a placeholder ``entity_id`` (``11111111-000X-7000-8000-…``)
that exists NOWHERE in the knowledge graph. The M-017 invariant requires, for a
tradable security, ``instruments.entity_id == instruments.id`` (the canonical KG
entity id IS the instrument id, and that is where news mentions resolve). The
holdings read-model JOINs ``instruments`` to expose ``entity_id``; the dashboard
Portfolio News widget fanned out per-holding news on that orphan id → 404 / 0
articles for every holding, hence "No recent news". (All other 657 instruments,
created by the real market-data instrument sync, already satisfy M-017.)

The frontend was made robust separately (it now fans out on ``instrument_id``).
This migration fixes the DATA at the source so the ``entity_id`` column is
correct for EVERY consumer (holdings, watchlist, internal watcher lookups) — not
just the one widget that was patched.

WHAT IT DOES: ``UPDATE instruments SET entity_id = id WHERE entity_id IS DISTINCT
FROM id`` — aligns every mismatched row to M-017. Data-only, idempotent (the
WHERE clause matches nothing on a clean DB / second run), no DDL.

WHY id (not a lookup): per M-017 the instrument's own id IS its canonical KG
entity id; the orphan ``11111111-*`` values were legacy demo seed data that no
current sync path produces (the M-017-compliant instrument sync sets
entity_id = id). Verified live: after this backfill, ``/v1/holdings/{id}`` exposes
entity_id == instrument_id and ``/v1/news/entity/{entity_id}`` returns the
holding's articles (AAPL 278).

DOWNGRADE: no-op — the original orphan ids cannot be reconstructed and were
invalid anyway; the aligned values are correct under any revision.
"""

from __future__ import annotations

from alembic import op

revision: str = "0023"
down_revision: str = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Align instruments.entity_id to id (M-017) for any mismatched rows."""
    op.execute("UPDATE instruments SET entity_id = id WHERE entity_id IS DISTINCT FROM id")


def downgrade() -> None:
    """No-op — the aligned entity_id values are correct under any revision."""
