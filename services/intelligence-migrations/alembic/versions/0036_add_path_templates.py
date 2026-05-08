"""Add ``path_templates`` table and seed 3 manufacturing-chain templates.

Revision ID: 0036
Revises: 0035
Create Date: 2026-05-08

WHY (T-A-06 — PRD-0074 §11 ADR-0074-007, §16):
  PathInsightWorker scores paths using a composite formula:
    composite = harmonic*0.4 + diversity*0.35 + surprise*0.25
              + (0.1 if template_match else 0.0)   # clamped to 1.0

  The template_match bonus rewards paths that follow known high-value
  structural patterns (e.g., manufacturing supply chains, financial holding
  chains).  Templates are stored in ``path_templates`` so operators can add,
  disable, or reconfigure them without a code deploy.

  Seed data: 3 templates covering the most common multi-hop patterns:
    1. supply_chain_3hop          — company → company → company via SUPPLIES_TO / MANUFACTURES_FOR
    2. financial_holding_chain    — company → company → person via OWNS / EMPLOYED_BY
    3. sector_supply_chain        — company → company → company via COMPETES_WITH + SUPPLIES_TO

  Template IDs are hard-coded UUIDv7 values generated at plan-write time so the
  seed is idempotent (ON CONFLICT DO NOTHING on the UNIQUE ``template_name``
  index means re-applying this migration does not create duplicates).

FORWARD-COMPATIBILITY (R5):
  New table and seed rows — no existing tables modified.

DOWNGRADE:
  Drops the table CASCADE.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

# Hard-coded UUIDv7 seed IDs — stable across migrations, generated 2026-05-08.
_SEED_SUPPLY_CHAIN_3HOP = "019e09b1-79d7-7f46-8c3f-06d1052aa995"
_SEED_FINANCIAL_HOLDING = "019e09b1-79d8-7ac1-92bd-8461c85b47f6"
_SEED_SECTOR_SUPPLY_CHAIN = "019e09b1-79d9-7b7c-80db-2bfc30baff94"


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Create path_templates table
    # -------------------------------------------------------------------------
    op.execute("""
CREATE TABLE path_templates (
    template_id            UUID        NOT NULL DEFAULT new_uuid7(),
    template_name          TEXT        NOT NULL,
    entity_type_sequence   JSONB       NOT NULL,
    relation_type_sequence JSONB       NOT NULL,
    description            TEXT,
    enabled                BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (template_id),
    UNIQUE (template_name),
    CONSTRAINT chk_path_template_sequences_are_arrays CHECK (
        jsonb_typeof(entity_type_sequence)   = 'array' AND
        jsonb_typeof(relation_type_sequence) = 'array'
    )
)
""")

    # -------------------------------------------------------------------------
    # 2. Seed 3 manufacturing-chain templates
    # ON CONFLICT DO NOTHING makes re-application idempotent.
    # -------------------------------------------------------------------------
    bind = op.get_bind()
    bind.execute(
        sa.text("""
INSERT INTO path_templates
    (template_id, template_name, entity_type_sequence, relation_type_sequence, description, enabled)
VALUES
    (:id1, :name1, :ets1::jsonb, :rts1::jsonb, :desc1, TRUE),
    (:id2, :name2, :ets2::jsonb, :rts2::jsonb, :desc2, TRUE),
    (:id3, :name3, :ets3::jsonb, :rts3::jsonb, :desc3, TRUE)
ON CONFLICT (template_name) DO NOTHING
"""),
        {
            # Template 1: Three-hop manufacturing supply chain
            "id1": _SEED_SUPPLY_CHAIN_3HOP,
            "name1": "supply_chain_3hop",
            "ets1": json.dumps(["company", "company", "company"]),
            "rts1": json.dumps(["SUPPLIES_TO|MANUFACTURES_FOR", "SUPPLIES_TO|MANUFACTURES_FOR"]),
            "desc1": "Three-company manufacturing supply chain",
            # Template 2: Financial holding with key executive
            "id2": _SEED_FINANCIAL_HOLDING,
            "name2": "financial_holding_chain",
            "ets2": json.dumps(["company", "company", "person"]),
            "rts2": json.dumps(["OWNS|ACQUIRED", "EMPLOYED_BY|LEADS"]),
            "desc2": "Financial holding with key executive",
            # Template 3: Sector-level supply chain via competition + distribution
            "id3": _SEED_SECTOR_SUPPLY_CHAIN,
            "name3": "sector_supply_chain",
            "ets3": json.dumps(["company", "company", "company"]),
            "rts3": json.dumps(["COMPETES_WITH|PARTNERS_WITH", "SUPPLIES_TO|DISTRIBUTES_FOR"]),
            "desc3": "Sector-level supply chain",
        },
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS path_templates CASCADE")
