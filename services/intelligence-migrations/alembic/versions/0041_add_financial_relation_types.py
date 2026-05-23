"""Add 5 financial relation types to relation_type_registry — PLAN-0089 taxonomy expansion.

Revision ID: 0041
Revises: 0040
Create Date: 2026-05-22

WHY THIS MIGRATION EXISTS:
  The relation taxonomy shipped in migrations 0001, 0002, and 0004 covers 27 canonical
  types.  Five high-value financial relation types are absent; events of these kinds
  currently fall into catch-all buckets (OTHER event type, sentiment_signal predicate)
  and generate no actionable relation edge in the knowledge graph:

    reported_revenue_of  — revenue figures for specific segments/geographies
    filed_lawsuit_against — legal actions (frequently market-moving)
    appointed_as         — executive appointments (investor-facing, high confidence)
    divested_from        — divestitures / spin-offs (structural capital events)
    downgraded_by        — analyst/rating-agency downgrades (FAST temporal claim)

  Adding them to the registry enables:
    (a) Exact-match canonicalization (Step 1, no ANN needed) for extractions that
        already use the correct predicate label.
    (b) ANN soft-map (Step 2) for free-text predicates that are semantically close
        (e.g. "sold stake in" → divested_from, "sued" → filed_lawsuit_against).
    (c) S7 Block 11 enriched-consumer write path — relation edges will be persisted
        in ``relations`` instead of emitting a ``relation.type.proposed.v1`` event.

SEMANTIC CLASSIFICATION:
  - reported_revenue_of  → TEMPORAL_CLAIM / MEDIUM   (point-in-time financial report)
  - filed_lawsuit_against → TEMPORAL_CLAIM / SLOW    (legal state evolves over months)
  - appointed_as          → RELATION_STATE / DURABLE  (executive tenure: years)
  - divested_from         → TEMPORAL_CLAIM / PERMANENT (completed transaction, historical)
  - downgraded_by         → TEMPORAL_CLAIM / FAST     (analyst rating, EPHEMERAL score)

QW-1 — Registry embedding audit:
  Migration 0013 seeds bge-large embeddings for all registry rows.  If Ollama was
  unavailable during that migration, embeddings for ALL rows (including these 5 new
  ones) remain NULL and S7 Block 11 Step 2 (ANN soft-map) is permanently bypassed.

  Diagnostic query (run manually to check):
    SELECT canonical_type, embedding IS NOT NULL AS has_embedding
    FROM relation_type_registry
    ORDER BY canonical_type;

  If any rows show has_embedding = false, re-seed by downgrading to migration 0012
  and upgrading to head (which re-runs 0013's Ollama embedding loop).  Alternatively,
  run the standalone seeder:
    python -m knowledge_graph.infrastructure.scripts.seed_registry_embeddings

DATA REPAIR — wrong-direction has_executive/employs rows:
  The enriched consumer (Block 11, BP-521) normalises subject/object direction for
  has_executive / employs at write time.  Existing rows ingested BEFORE BP-521 may
  have the direction inverted (person as subject, company as object).

  OPERATOR ACTION REQUIRED (not auto-executed — verify entity_type values first):
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  UPDATE relations r                                                         │
  │  SET subject_entity_id = r.object_entity_id,                               │
  │      object_entity_id  = r.subject_entity_id                               │
  │  FROM canonical_entities sub                                                │
  │  JOIN canonical_entities obj ON obj.entity_id = r.object_entity_id        │
  │  WHERE r.canonical_type IN ('has_executive', 'employs')                    │
  │    AND sub.entity_id    = r.subject_entity_id                              │
  │    AND sub.entity_type  = 'person'                                         │
  │    AND obj.entity_type IN ('financial_instrument', 'organization');         │
  └─────────────────────────────────────────────────────────────────────────────┘

IDEMPOTENCY:
  INSERT uses ON CONFLICT (canonical_type) DO NOTHING — safe to re-run.

FORWARD-COMPATIBILITY (R5):
  No columns removed or renamed.  Five new registry rows; existing rows untouched.

AGE EDGE LABELS:
  Five new AGE edge labels must be created in worldview_graph before AgeSyncWorker
  can sync relations of these types.  The labels are created inside a DO $$ block
  so environments without the AGE shared library (e.g. pgvector-only CI) can run
  this migration without error (AGE features simply remain disabled).

DOWNGRADE:
  Deletes the 5 new registry rows and drops the 5 AGE edge labels (best-effort).
  Existing relation rows of these types are NOT deleted — downgrade only removes
  the registry definitions.  If clean removal of relation data is required, delete
  from ``relations`` WHERE canonical_type IN (...) before running downgrade.
"""

from __future__ import annotations

from alembic import op

revision: str = "0041"
down_revision: str = "0040"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# New relation types — taxonomy expansion (Lever-4 financial events)
# ---------------------------------------------------------------------------
# Column shape matches relation_type_registry as of migration 0023:
#   canonical_type  VARCHAR(100) UNIQUE NOT NULL
#   semantic_mode   VARCHAR(20)  NOT NULL  — 'RELATION_STATE' | 'TEMPORAL_CLAIM'
#   decay_class     VARCHAR(20)  NOT NULL FK → decay_class_config.decay_class
#   base_confidence FLOAT        NOT NULL DEFAULT 0.5
#   description     TEXT
#   data_source     TEXT NULL    — added by migration 0023 (NULL for LLM-sourced types)
#   source_field    TEXT NULL    — added by migration 0023 (NULL for LLM-sourced types)
# embedding is populated by migration 0013 pattern (Ollama, best-effort).

_NEW_TYPES_SQL = """
INSERT INTO relation_type_registry
    (canonical_type, semantic_mode, decay_class, base_confidence, description)
VALUES
    ('appointed_as',
     'RELATION_STATE',
     'DURABLE',
     0.85,
     'Person was formally appointed to a new role: subject=COMPANY, object=PERSON '
     '(mirrors has_executive direction convention — company is always subject)'),

    ('divested_from',
     'TEMPORAL_CLAIM',
     'PERMANENT',
     0.80,
     'Company divested, sold, or spun off a business unit or equity stake: '
     'subject=divesting company, object=divested entity'),

    ('downgraded_by',
     'TEMPORAL_CLAIM',
     'FAST',
     0.75,
     'Company was downgraded by an analyst or rating agency: '
     'subject=company, object=analyst firm or rating agency'),

    ('filed_lawsuit_against',
     'TEMPORAL_CLAIM',
     'SLOW',
     0.80,
     'Entity filed legal action against another entity: '
     'subject=plaintiff, object=defendant'),

    ('reported_revenue_of',
     'TEMPORAL_CLAIM',
     'MEDIUM',
     0.85,
     'Company reported a specific revenue figure for a segment, product, or geography: '
     'subject=company, object=segment/geography entity')

ON CONFLICT (canonical_type) DO NOTHING
"""

# ---------------------------------------------------------------------------
# AGE edge labels — create inside a DO block so CI without AGE silently skips
# ---------------------------------------------------------------------------
_CREATE_AGE_LABELS = """
DO $$
BEGIN
    LOAD 'age';
    SET search_path = ag_catalog, "$user", public;
    PERFORM create_elabel('worldview_graph', 'APPOINTED_AS');
    PERFORM create_elabel('worldview_graph', 'DIVESTED_FROM');
    PERFORM create_elabel('worldview_graph', 'DOWNGRADED_BY');
    PERFORM create_elabel('worldview_graph', 'FILED_LAWSUIT_AGAINST');
    PERFORM create_elabel('worldview_graph', 'REPORTED_REVENUE_OF');
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING
        'AGE extension not available (%) — new edge labels not created. '
        'Install AGE and re-run migration 0041 to enable graph sync for these types.',
        SQLERRM;
END;
$$
"""

# ---------------------------------------------------------------------------
# Downgrade helpers
# ---------------------------------------------------------------------------
_DELETE_NEW_TYPES_SQL = """
DELETE FROM relation_type_registry
WHERE canonical_type IN (
    'appointed_as',
    'divested_from',
    'downgraded_by',
    'filed_lawsuit_against',
    'reported_revenue_of'
)
"""

_DROP_AGE_LABELS = """
DO $$
BEGIN
    LOAD 'age';
    SET search_path = ag_catalog, "$user", public;
    PERFORM drop_elabel('worldview_graph', 'APPOINTED_AS',        true);
    PERFORM drop_elabel('worldview_graph', 'DIVESTED_FROM',       true);
    PERFORM drop_elabel('worldview_graph', 'DOWNGRADED_BY',       true);
    PERFORM drop_elabel('worldview_graph', 'FILED_LAWSUIT_AGAINST', true);
    PERFORM drop_elabel('worldview_graph', 'REPORTED_REVENUE_OF', true);
EXCEPTION WHEN OTHERS THEN
    RAISE WARNING
        'AGE extension not available or labels already absent (%) — skipping edge-label drop.',
        SQLERRM;
END;
$$
"""


def upgrade() -> None:
    """Insert 5 new financial relation types and create their AGE edge labels."""
    # ── 1. Registry rows ──────────────────────────────────────────────────────
    op.execute(_NEW_TYPES_SQL)

    # ── 2. AGE edge labels (best-effort — silently skips if AGE absent) ───────
    op.execute(_CREATE_AGE_LABELS)

    # ── 3. Embedding seeding ──────────────────────────────────────────────────
    # The 5 new rows start with embedding = NULL.  Migration 0013 seeds embeddings
    # for all rows WHERE embedding IS NULL — but 0013 already ran before this
    # migration exists.  The QW-1 startup check in knowledge_graph.app.lifespan
    # logs a warning if NULL embeddings are detected so operators know to re-seed.
    #
    # To seed embeddings for the new rows only, connect to the DB and run:
    #   UPDATE relation_type_registry SET embedding = NULL
    #   WHERE canonical_type IN (
    #       'appointed_as', 'divested_from', 'downgraded_by',
    #       'filed_lawsuit_against', 'reported_revenue_of'
    #   );
    # Then downgrade to 0012 and upgrade to head (which triggers 0013's Ollama loop).
    # Or run: python -m knowledge_graph.infrastructure.scripts.seed_registry_embeddings


def downgrade() -> None:
    """Remove the 5 new relation types and their AGE edge labels."""
    # Drop AGE labels first (they reference the registry types by convention)
    op.execute(_DROP_AGE_LABELS)
    # Delete registry rows
    op.execute(_DELETE_NEW_TYPES_SQL)
