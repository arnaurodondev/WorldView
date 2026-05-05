"""Add entity_type CHECK constraint to canonical_entities.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-05

Changes:
  canonical_entities:
    - ADD CONSTRAINT ck_canonical_entity_type CHECK (entity_type IN (...))

WHY:
  PLAN-0072 T-72-3-02 adds code-level normalisation of entity_type values in
  provisional_enrichment_core.py — unrecognised types default to 'other'.
  This migration adds a complementary DB-level CHECK constraint so that any
  future code path that bypasses the application layer cannot insert an invalid
  type silently.

  The constraint is enforcement, not repair.  On a fresh-start cluster all
  existing rows in canonical_entities have valid entity_types (seeded by
  migration 0001 with exact values from the canonical set).

  Canonical entity types (migration 0001 seed):
    company, financial_instrument, person, organization, country, currency,
    commodity, index, sector, concept, event, other

FORWARD-COMPATIBILITY (R5):
  Additive constraint. Existing application code that writes valid entity_types
  is unaffected. New code enforcing normalisation (T-72-3-02) writes only valid
  types so no NEW violations will be introduced after deployment.

DOWNGRADE:
  Drop the constraint. Rows with previously-invalid types (inserted before
  T-72-3-02 code was deployed) remain; they will pass the next normalisation
  pass when their entities are re-enriched.
"""

from __future__ import annotations

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE canonical_entities
    ADD CONSTRAINT ck_canonical_entity_type
    CHECK (entity_type IN (
        'company', 'financial_instrument', 'person', 'organization',
        'country', 'currency', 'commodity', 'index',
        'sector', 'concept', 'event', 'other'
    ))
""")


def downgrade() -> None:
    op.execute("""
ALTER TABLE canonical_entities
    DROP CONSTRAINT IF EXISTS ck_canonical_entity_type
""")
