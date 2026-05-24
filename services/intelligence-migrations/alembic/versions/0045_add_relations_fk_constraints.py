"""Add FK constraints to relations.subject_entity_id + object_entity_id.

Revision ID: 0045
Revises: 0044
Create Date: 2026-05-23

PLAN-0093 Wave B-2 T-B-2-02.

WHY THIS MIGRATION EXISTS:
  Today ``relations.subject_entity_id`` and ``relations.object_entity_id`` are
  declared UUID NOT NULL but have NO foreign-key constraint to
  ``canonical_entities.entity_id``.  The extraction pipeline can therefore
  write a relation pointing at an entity that does not exist — and we
  observed exactly that pattern with the macro-sentinel fallback
  (F-DB-012 / F-KG-PERSIST-002).

WHAT IT DOES:
  Per the PLAN-0093 "Pre-Prod Simplifications" preamble (no data to
  preserve), this migration TRUNCATEs the relations + relation_evidence_raw
  + relation_summaries + relation_contradiction_links tables and then adds
  DEFERRABLE INITIALLY DEFERRED foreign keys on subject_entity_id and
  object_entity_id.  Deferring lets the outbox pattern insert a brand-new
  ``canonical_entities`` row + a relation pointing at it in the same
  transaction (commit-time check).

DOWNGRADE:
  Drops both FK constraints.  Data is not restored — this is a one-way
  pre-prod cleanup.
"""

from __future__ import annotations

import os

from alembic import op

revision: str = "0045"
down_revision: str = "0044"
branch_labels = None
depends_on = None


# PLAN-0093 Phase 5 (QA-4 A.4.1) — production TRUNCATE guard.
# Prefer the shared helper at ``alembic/_guards.py`` (so a single source of
# truth governs every destructive migration), but inline a fallback in case
# the alembic runtime's ``sys.path`` does not expose sibling modules in some
# CI configuration.  Both implementations behave identically.
try:  # pragma: no cover - import path varies by alembic invocation mode
    from _guards import assert_truncate_allowed  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback path

    def assert_truncate_allowed(table: str) -> None:
        """Inline fallback — see alembic/_guards.py for the canonical version."""
        if (
            os.environ.get("APP_ENV", "").lower() == "production"
            and os.environ.get("ALLOW_DESTRUCTIVE_MIGRATION") != "1"
        ):
            raise RuntimeError(
                f"Refusing to TRUNCATE {table!r} in APP_ENV=production. "
                "Set ALLOW_DESTRUCTIVE_MIGRATION=1 to override (requires SRE sign-off)."
            )


# Helper child tables that hold FKs / data tied to specific relations.
# All of these are truncated under CASCADE before the FK add because pre-prod
# data is disposable and we want a clean state for the new constraints.
_DEPENDENT_TABLES = (
    "relation_contradiction_links",
    "relation_summaries",
    "relation_evidence_raw",
    "relations",
)


def upgrade() -> None:
    """TRUNCATE legacy data + add FKs (deferrable for outbox pattern)."""

    # ── Step 0: production safety guard ───────────────────────────────────────
    # Refuses to run in APP_ENV=production unless ALLOW_DESTRUCTIVE_MIGRATION=1.
    # The migration was designed for pre-prod cleanup; a stray prod replay
    # would silently destroy ``relations`` + its dependents.
    assert_truncate_allowed("relations + dependents")

    # ── Step 1: nuke pre-prod data so FKs can be added clean ──────────────────
    # CASCADE so any partitioned-child or trigger-dependent rows also drop.
    # PLAN-0093 preamble explicitly allows this — there is no data we need to
    # preserve at this stage of the project.
    for table in _DEPENDENT_TABLES:
        op.execute(f"TRUNCATE TABLE {table} CASCADE")

    # ── Step 2: add the two FKs ──────────────────────────────────────────────
    # DEFERRABLE INITIALLY DEFERRED — the outbox writer often inserts the
    # canonical_entities row + the relation row in the same transaction; the
    # FK check therefore must happen at commit time, not at insert time.
    op.execute(
        """
        ALTER TABLE relations
            ADD CONSTRAINT fk_relations_subject_entity
            FOREIGN KEY (subject_entity_id)
            REFERENCES canonical_entities (entity_id)
            DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        """
        ALTER TABLE relations
            ADD CONSTRAINT fk_relations_object_entity
            FOREIGN KEY (object_entity_id)
            REFERENCES canonical_entities (entity_id)
            DEFERRABLE INITIALLY DEFERRED
        """
    )

    # ── Step 3: CHECK constraint — no self-loops on real entities ─────────────
    # System sentinels (is_system = true) are explicitly allowed to self-loop
    # (they're placeholders).  Real entities self-looping is always a bug
    # (BP-385 regression guard).  We can't reference a sub-query in a CHECK,
    # so we encode the 5 sentinel UUIDs directly.
    #
    # SYNC INVARIANT (PLAN-0093 QA-4 A.4.2):
    #   The five UUID literals below MUST stay identical to the entity_ids in
    #   ``services/intelligence-migrations/alembic/versions/
    #   0044_seed_kg_system_entities.py::_SENTINELS``.
    #   The regression test
    #   ``tests/migrations/test_sentinel_check_constraint_sync.py``
    #   re-parses both files and asserts set-equality.  Update both files
    #   together whenever a sentinel is added, removed, or renumbered.
    op.execute(
        """
        ALTER TABLE relations
            ADD CONSTRAINT chk_relations_no_self_loop
            CHECK (
                subject_entity_id != object_entity_id
                OR subject_entity_id IN (
                    '11111111-0004-7000-8000-000000000001'::uuid,
                    '11111111-0004-7000-8000-000000000002'::uuid,
                    '11111111-0004-7000-8000-000000000003'::uuid,
                    '11111111-0004-7000-8000-000000000004'::uuid,
                    '11111111-0004-7000-8000-000000000005'::uuid
                )
            )
        """
    )


def downgrade() -> None:
    """Drop the two FKs + the CHECK constraint."""
    op.execute("ALTER TABLE relations DROP CONSTRAINT IF EXISTS chk_relations_no_self_loop")
    op.execute("ALTER TABLE relations DROP CONSTRAINT IF EXISTS fk_relations_object_entity")
    op.execute("ALTER TABLE relations DROP CONSTRAINT IF EXISTS fk_relations_subject_entity")
