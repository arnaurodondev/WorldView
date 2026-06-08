"""Remove finnhub sources that have no symbol configured.

Revision ID: 0009_remove_finnhub_global_news
Revises: 0008_seed_default_sources
Create Date: 2026-06-08

WHY: Migration 0008 accidentally seeded a ``finnhub-news`` source with
``config={}`` (no ``symbol`` key).  Finnhub's ``company-news`` endpoint is
per-ticker only — there is no global-feed endpoint on the free tier — so
every scheduler tick triggered HTTP 422 and 3x retry waste.

This migration removes:
1. Any ``sources`` row where ``source_type='finnhub'`` AND the ``config``
   JSONB has no ``symbol`` key (or the value is an empty string).
2. Any orphaned ``ingestion_tasks`` rows for those sources (FK cascade may
   not be configured; delete explicitly to be safe).

The per-ticker sources (e.g. ``Finnhub-AAPL``, ``config={"symbol":"AAPL"}``)
are intentionally left untouched.

Downgrade: re-inserts the bad row so the schema chain stays intact, but
leaves it disabled so it cannot cause further damage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0009_remove_finnhub_global_news"
down_revision: str = "0008_seed_default_sources"
branch_labels = None
depends_on = None


def _ulid_from_seed(seed: str) -> str:
    """Derive a deterministic UUID-shaped ID from ``seed`` via SHA-256.

    Mirrors the helper in 0008_seed_default_sources so we can reference the
    exact same primary-key value for the downgrade re-insert.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    h = digest[:32]
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# The stable ID that 0008 would have used for this bad seed row.
_BAD_SOURCE_ID = _ulid_from_seed("source:finnhub:news")


def upgrade() -> None:
    """Delete finnhub sources missing a valid symbol, and their tasks."""
    # Step 1 — delete orphaned tasks first (avoids FK violation if cascade is not set).
    op.execute(
        sa.text(
            """
            DELETE FROM ingestion_tasks
            WHERE source_id IN (
                SELECT id FROM sources
                WHERE source_type = 'finnhub'
                  AND (
                      config->>'symbol' IS NULL
                      OR TRIM(config->>'symbol') = ''
                  )
            )
            """,
        )
    )

    # Step 2 — delete the bad source rows.
    op.execute(
        sa.text(
            """
            DELETE FROM sources
            WHERE source_type = 'finnhub'
              AND (
                  config->>'symbol' IS NULL
                  OR TRIM(config->>'symbol') = ''
              )
            """,
        )
    )


def downgrade() -> None:
    """Re-insert the bad seed row in a disabled state so the chain is intact.

    The row is inserted with ``enabled=false`` so it cannot trigger further
    HTTP 422 errors if this migration is rolled back during development.
    """
    now = datetime.now(tz=UTC)
    op.execute(
        sa.text(
            """
            INSERT INTO sources (id, name, source_type, config, enabled, created_at)
            VALUES (
                CAST(:id AS uuid),
                :name,
                :source_type,
                CAST(:config AS jsonb),
                :enabled,
                :created_at
            )
            ON CONFLICT ON CONSTRAINT uq_sources_dedup DO NOTHING
            """,
        ).bindparams(
            id=_BAD_SOURCE_ID,
            name="finnhub-news",
            source_type="finnhub",
            config=json.dumps({}),
            enabled=False,  # disabled — prevents re-triggering the bug
            created_at=now,
        )
    )
