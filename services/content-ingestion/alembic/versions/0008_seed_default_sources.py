"""Seed 5 default content sources.

Revision ID: 0008_seed_default_sources
Revises: 0007_add_tenant_document_uploads
Create Date: 2026-06-06

WHY (PLAN-0106 Wave B-1): Fresh deployments start with an empty ``sources``
table, so the scheduler has nothing to poll on its very first tick.  This
migration inserts the 5 canonical content sources (EODHD, Finnhub, NewsAPI,
SEC EDGAR, Polymarket) so a plain ``docker compose up`` is production-ready
without any manual data-seeding step.

IDs are derived deterministically from a stable seed string via SHA-256 so
``upgrade`` is truly idempotent across re-runs on the same cluster: if the
row already exists by ``uq_sources_dedup`` (source_type, config_hash), the
INSERT silently no-ops.

We cannot use ``ON CONFLICT (source_type, config_hash) DO NOTHING`` because
``config_hash`` is a GENERATED ALWAYS AS column — PostgreSQL rejects explicit
references to generated columns in ON CONFLICT target lists.  We reference the
named constraint ``uq_sources_dedup`` instead (added by migration 0006).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0008_seed_default_sources"
down_revision: str = "0007_add_tenant_document_uploads"
branch_labels = None
depends_on = None


def _ulid_from_seed(seed: str) -> str:
    """Derive a deterministic ULID-shaped ID from ``seed`` via SHA-256.

    Format: "01HX" prefix + 22 uppercase hex characters (total 26 chars).
    This is the same helper pattern used in other seed migrations in the repo
    so that IDs are stable across re-deploys.  The hex output is intentionally
    NOT a spec-compliant ULID; it is a stable opaque identifier that fits the
    UUID-like primary key column (stored as TEXT in the sources table after
    0001, but cast to UUID by SQLAlchemy).
    """
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    # Return a UUID-formatted string derived from the digest so it fits
    # the UUID primary key column (first 32 hex chars → 8-4-4-4-12 groups).
    h = digest[:32]
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# Deterministic IDs — stable across re-deploys (same seed = same ID).
_DEFAULT_SOURCES = [
    {
        "id": _ulid_from_seed("source:eodhd:global-news"),
        "name": "eodhd-news",
        "source_type": "eodhd",
        "config": json.dumps({"max_pages_per_cycle": 3}),
        "enabled": True,
    },
    {
        "id": _ulid_from_seed("source:finnhub:news"),
        "name": "finnhub-news",
        "source_type": "finnhub",
        "config": json.dumps({}),
        "enabled": True,
    },
    {
        "id": _ulid_from_seed("source:newsapi:news"),
        "name": "newsapi-news",
        "source_type": "newsapi",
        "config": json.dumps({}),
        "enabled": True,
    },
    {
        "id": _ulid_from_seed("source:sec_edgar:filings"),
        "name": "sec-edgar-filings",
        "source_type": "sec_edgar",
        "config": json.dumps({"user_agent": "worldview/1.0"}),
        "enabled": True,
    },
    {
        "id": _ulid_from_seed("source:polymarket:predictions"),
        "name": "polymarket-predictions",
        "source_type": "polymarket",
        "config": json.dumps({}),
        "enabled": True,
    },
]


def upgrade() -> None:
    now = datetime.now(tz=UTC)

    for src in _DEFAULT_SOURCES:
        # ON CONFLICT ON CONSTRAINT is required here because ``config_hash`` is a
        # GENERATED ALWAYS AS column — Postgres rejects it in ON CONFLICT target
        # lists.  The named constraint ``uq_sources_dedup`` (source_type, config_hash)
        # was added by migration 0006 and is stable.
        # NOTE: use ``CAST(:config AS jsonb)`` rather than the ``:config::jsonb``
        # shorthand. SQLAlchemy's text() bind-parameter tokenizer interprets the
        # double colon as a continuation of the parameter name on some versions,
        # producing at migrate-time:
        #     ArgumentError: This text() construct doesn't define a bound
        #     parameter named 'config'
        # The explicit CAST form is portable and avoids that parser ambiguity.
        op.execute(
            sa.text(
                """
                INSERT INTO sources (id, name, source_type, config, enabled, created_at)
                VALUES (:id, :name, :source_type, CAST(:config AS jsonb), :enabled, :created_at)
                ON CONFLICT ON CONSTRAINT uq_sources_dedup DO NOTHING
                """
            ).bindparams(
                id=src["id"],
                name=src["name"],
                source_type=src["source_type"],
                config=src["config"],
                enabled=src["enabled"],
                created_at=now,
            )
        )


def downgrade() -> None:
    ids = [src["id"] for src in _DEFAULT_SOURCES]
    for source_id in ids:
        op.execute(sa.text("DELETE FROM sources WHERE id = :id").bindparams(id=source_id))
