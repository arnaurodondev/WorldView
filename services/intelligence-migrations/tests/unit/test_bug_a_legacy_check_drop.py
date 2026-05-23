"""Static regression test for BUG-A (fresh-DB upgrade failure at migration 0038).

BUG-A surfaced from the W3-01 R24/migration integration suite: migration
0021 added the legacy CHECK constraint ``ck_canonical_entity_type`` whose
allowed-values list does NOT include ``'unknown'``. Migration 0038 then
INSERTs OpenAI/Anthropic with ``entity_type='unknown'``. On a fresh DB
``alembic upgrade head`` failed at 0038 with a check-constraint violation
(migration 0039 — which loosens the constraint to include ``'unknown'`` —
hadn't run yet).

The fix (commit ``07a0aad2``) adds a defensive ``DROP CONSTRAINT IF EXISTS
ck_canonical_entity_type`` at the top of 0038's ``upgrade()``. This works
for both fresh DBs (drops the just-installed legacy constraint before the
INSERTs run) and prod DBs (no-op via ``IF EXISTS``).

The dynamic regression coverage lives in
``tests/integration/test_migration_apply.py`` but it skips without live
Postgres. This file provides a static-only mirror that runs on every CI
path without infra: it inspects the migration source and asserts the DROP
CONSTRAINT line appears BEFORE any seed INSERT.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"
_MIGRATION_0038 = _MIGRATIONS_DIR / "0038_seed_demo_entities.py"


def test_bug_a_drop_constraint_precedes_seed_inserts() -> None:
    """0038's upgrade() drops ``ck_canonical_entity_type`` before seed inserts."""
    source = _MIGRATION_0038.read_text(encoding="utf-8")

    drop_marker = "DROP CONSTRAINT IF EXISTS ck_canonical_entity_type"
    insert_marker = "INSERT INTO canonical_entities"

    drop_index = source.find(drop_marker)
    insert_index = source.find(insert_marker)

    assert drop_index >= 0, (
        "BUG-A regression: migration 0038 no longer drops the legacy "
        "ck_canonical_entity_type constraint before seeding. Fresh DB "
        "upgrade head will fail with check-constraint violation. "
        "See commit 07a0aad2 (BUG-A fix from W3-01)."
    )
    assert insert_index >= 0, "Migration 0038 INSERT INTO canonical_entities marker is missing — schema drift."
    assert drop_index < insert_index, (
        f"BUG-A regression: DROP CONSTRAINT line ({drop_index}) appears AFTER "
        f"INSERT INTO canonical_entities ({insert_index}). The drop must "
        f"precede the inserts or fresh DB upgrade will fail."
    )


def test_bug_a_drop_is_idempotent() -> None:
    """The DROP must use IF EXISTS so prod DBs (where 0039 already cleared it) don't error."""
    source = _MIGRATION_0038.read_text(encoding="utf-8")
    assert "DROP CONSTRAINT IF EXISTS ck_canonical_entity_type" in source, (
        "BUG-A regression: the DROP CONSTRAINT must be ``IF EXISTS`` so it's "
        "idempotent against prod DBs whose ordering already cleared the legacy "
        "constraint via migration 0039."
    )
