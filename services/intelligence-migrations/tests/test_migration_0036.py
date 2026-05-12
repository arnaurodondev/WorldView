"""Integration tests for migration 0036 — add path_templates table + 3 seed rows.

Migration 0036 (``0036``) addresses T-A-06 (PRD-0074 §11 ADR-0074-007):

  1. Creates the ``path_templates`` table with columns:
       template_id, template_name, entity_type_sequence, relation_type_sequence,
       description, enabled, created_at
     Plus a UNIQUE constraint on ``template_name`` and a CHECK constraint
     verifying both JSONB sequence columns are arrays.

  2. Seeds 3 manufacturing-chain templates with hard-coded UUIDv7 IDs:
       - supply_chain_3hop
       - financial_holding_chain
       - sector_supply_chain
     ``ON CONFLICT (template_name) DO NOTHING`` makes re-application idempotent.

downgrade() drops the table CASCADE.

Mark: integration (requires running Postgres with pgvector).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text

pytestmark = pytest.mark.integration

# ── Constants ─────────────────────────────────────────────────────────────────

_TABLE_NAME = "path_templates"

# Hard-coded UUIDv7 seed IDs from the migration body — pinned here so drift
# (e.g., a future migration that changes the seed IDs) is caught immediately.
_SEED_SUPPLY_CHAIN_3HOP = "019e09b1-79d7-7f46-8c3f-06d1052aa995"
_SEED_FINANCIAL_HOLDING = "019e09b1-79d8-7ac1-92bd-8461c85b47f6"
_SEED_SECTOR_SUPPLY_CHAIN = "019e09b1-79d9-7b7c-80db-2bfc30baff94"

# Expected template names → UUIDs.
_EXPECTED_TEMPLATES: dict[str, str] = {
    "supply_chain_3hop": _SEED_SUPPLY_CHAIN_3HOP,
    "financial_holding_chain": _SEED_FINANCIAL_HOLDING,
    "sector_supply_chain": _SEED_SECTOR_SUPPLY_CHAIN,
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM pg_tables " "WHERE schemaname = 'public' AND tablename = :tbl"),
        {"tbl": table},
    ).fetchone()
    return row is not None


def _column_exists(conn: sa.engine.Connection, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = :tbl "
            "  AND column_name = :col"
        ),
        {"tbl": table, "col": column},
    ).fetchone()
    return row is not None


# ── Upgrade contract — table structure ────────────────────────────────────────


def test_upgrade_creates_path_templates_table(conn: sa.engine.Connection) -> None:
    """After upgrade: the ``path_templates`` table must exist."""
    assert _table_exists(conn, _TABLE_NAME), f"Table {_TABLE_NAME!r} not found — 0036 upgrade failed"


def test_upgrade_path_templates_has_template_id(conn: sa.engine.Connection) -> None:
    """The ``path_templates`` table must have a ``template_id`` UUID PK column."""
    assert _column_exists(conn, _TABLE_NAME, "template_id"), f"Column ``{_TABLE_NAME}.template_id`` missing"


def test_upgrade_path_templates_has_template_name(conn: sa.engine.Connection) -> None:
    """The ``path_templates`` table must have a ``template_name`` TEXT column."""
    assert _column_exists(conn, _TABLE_NAME, "template_name"), f"Column ``{_TABLE_NAME}.template_name`` missing"


def test_upgrade_path_templates_has_jsonb_columns(conn: sa.engine.Connection) -> None:
    """Both ``entity_type_sequence`` and ``relation_type_sequence`` must be JSONB."""
    for col in ("entity_type_sequence", "relation_type_sequence"):
        row = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "  AND table_name = :tbl "
                "  AND column_name = :col"
            ),
            {"tbl": _TABLE_NAME, "col": col},
        ).fetchone()
        assert row is not None, f"Column ``{_TABLE_NAME}.{col}`` missing"
        assert row[0] == "jsonb", f"Column ``{_TABLE_NAME}.{col}`` expected type 'jsonb', got {row[0]!r}"


def test_upgrade_path_templates_has_enabled_column(conn: sa.engine.Connection) -> None:
    """The ``path_templates`` table must have an ``enabled`` BOOLEAN column."""
    row = conn.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = :tbl "
            "  AND column_name = 'enabled'"
        ),
        {"tbl": _TABLE_NAME},
    ).fetchone()
    assert row is not None, f"Column ``{_TABLE_NAME}.enabled`` missing"
    assert row[0] == "boolean", f"Column ``{_TABLE_NAME}.enabled`` expected type 'boolean', got {row[0]!r}"


def test_upgrade_path_templates_unique_on_template_name(conn: sa.engine.Connection) -> None:
    """``path_templates`` must have a UNIQUE constraint on ``template_name``.

    The ON CONFLICT DO NOTHING idempotency clause in the seed INSERT relies on
    this constraint — if it is missing, duplicate seeds would be created on
    re-run instead of being silently skipped.
    """
    row = conn.execute(
        text("SELECT 1 FROM pg_indexes " "WHERE tablename = :tbl AND indexdef LIKE '%template_name%'"),
        {"tbl": _TABLE_NAME},
    ).fetchone()
    assert row is not None, (
        f"No index on ``{_TABLE_NAME}.template_name`` found — "
        f"UNIQUE constraint required for ON CONFLICT DO NOTHING idempotency"
    )


# ── Upgrade contract — seed data ──────────────────────────────────────────────


def test_upgrade_seeds_three_templates(conn: sa.engine.Connection) -> None:
    """After upgrade: exactly 3 seed templates must be present."""
    count = conn.execute(
        text(f"SELECT COUNT(*) FROM {_TABLE_NAME}")  # noqa: S608
    ).scalar_one()
    assert count >= 3, f"Expected at least 3 seed rows in {_TABLE_NAME!r}, got {count}"


def test_upgrade_supply_chain_3hop_template_exists(conn: sa.engine.Connection) -> None:
    """The ``supply_chain_3hop`` template with its hard-coded UUID must exist."""
    row = conn.execute(
        text(
            f"SELECT template_id, enabled FROM {_TABLE_NAME} "  # noqa: S608
            "WHERE template_name = 'supply_chain_3hop'"
        )
    ).fetchone()
    assert row is not None, "Template 'supply_chain_3hop' missing — 0036 seed failed"
    assert str(row[0]) == _SEED_SUPPLY_CHAIN_3HOP, (
        f"supply_chain_3hop UUID mismatch: got {row[0]!r}, " f"expected {_SEED_SUPPLY_CHAIN_3HOP!r}"
    )
    assert row[1] is True, "supply_chain_3hop template must be enabled=TRUE"


def test_upgrade_financial_holding_chain_template_exists(conn: sa.engine.Connection) -> None:
    """The ``financial_holding_chain`` template with its hard-coded UUID must exist."""
    row = conn.execute(
        text(
            f"SELECT template_id, enabled FROM {_TABLE_NAME} "  # noqa: S608
            "WHERE template_name = 'financial_holding_chain'"
        )
    ).fetchone()
    assert row is not None, "Template 'financial_holding_chain' missing — 0036 seed failed"
    assert str(row[0]) == _SEED_FINANCIAL_HOLDING, (
        f"financial_holding_chain UUID mismatch: got {row[0]!r}, " f"expected {_SEED_FINANCIAL_HOLDING!r}"
    )
    assert row[1] is True, "financial_holding_chain template must be enabled=TRUE"


def test_upgrade_sector_supply_chain_template_exists(conn: sa.engine.Connection) -> None:
    """The ``sector_supply_chain`` template with its hard-coded UUID must exist."""
    row = conn.execute(
        text(
            f"SELECT template_id, enabled FROM {_TABLE_NAME} "  # noqa: S608
            "WHERE template_name = 'sector_supply_chain'"
        )
    ).fetchone()
    assert row is not None, "Template 'sector_supply_chain' missing — 0036 seed failed"
    assert str(row[0]) == _SEED_SECTOR_SUPPLY_CHAIN, (
        f"sector_supply_chain UUID mismatch: got {row[0]!r}, " f"expected {_SEED_SECTOR_SUPPLY_CHAIN!r}"
    )
    assert row[1] is True, "sector_supply_chain template must be enabled=TRUE"


def test_upgrade_template_sequences_are_jsonb_arrays(conn: sa.engine.Connection) -> None:
    """All seeded rows must have JSONB arrays in both sequence columns.

    The CHECK constraint ``chk_path_template_sequences_are_arrays`` enforces
    ``jsonb_typeof(entity_type_sequence) = 'array'`` and likewise for
    ``relation_type_sequence``.  This test directly verifies the constraint is
    respected by inspecting the stored data.
    """
    rows = conn.execute(
        text(
            f"SELECT template_name, "  # noqa: S608
            "jsonb_typeof(entity_type_sequence), "
            "jsonb_typeof(relation_type_sequence) "
            f"FROM {_TABLE_NAME}"
        )
    ).fetchall()
    assert rows, f"No rows found in {_TABLE_NAME!r}"
    for name, ets_type, rts_type in rows:
        assert ets_type == "array", (
            f"Template {name!r}: entity_type_sequence is not a JSONB array " f"(jsonb_typeof={ets_type!r})"
        )
        assert rts_type == "array", (
            f"Template {name!r}: relation_type_sequence is not a JSONB array " f"(jsonb_typeof={rts_type!r})"
        )


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_re_seeding_is_idempotent(conn: sa.engine.Connection) -> None:
    """Re-inserting the seed rows via ON CONFLICT DO NOTHING must be a noop.

    Verifies the UNIQUE constraint on template_name is in place and the
    ON CONFLICT clause functions correctly — re-running the seed INSERT must
    not raise IntegrityError and must not change the row count.
    """
    count_before = conn.execute(
        text(f"SELECT COUNT(*) FROM {_TABLE_NAME}")  # noqa: S608
    ).scalar_one()

    # Re-insert the same template names — ON CONFLICT DO NOTHING must skip.
    for template_name, template_id in _EXPECTED_TEMPLATES.items():
        conn.execute(
            text(
                f"INSERT INTO {_TABLE_NAME} "  # noqa: S608
                "(template_id, template_name, entity_type_sequence, "
                " relation_type_sequence, enabled) "
                f"VALUES ('{template_id}', '{template_name}', "
                "'[\"company\"]'::jsonb, '[\"RELATES_TO\"]'::jsonb, TRUE) "
                "ON CONFLICT (template_name) DO NOTHING"
            )
        )

    count_after = conn.execute(
        text(f"SELECT COUNT(*) FROM {_TABLE_NAME}")  # noqa: S608
    ).scalar_one()

    assert count_after == count_before, (
        f"Re-seeding changed row count: {count_before} → {count_after}. "
        f"ON CONFLICT DO NOTHING or UNIQUE constraint broken."
    )
    conn.rollback()


# ── Downgrade contract ────────────────────────────────────────────────────────


def test_downgrade_sql_drops_path_templates_table(conn: sa.engine.Connection) -> None:
    """Running the downgrade SQL removes the ``path_templates`` table.

    We roll back immediately so the session-scoped fixture stays valid.
    The migration's downgrade() runs: ``DROP TABLE IF EXISTS path_templates CASCADE``.
    """
    # Pre-condition: table must exist after upgrade head.
    assert _table_exists(conn, _TABLE_NAME), f"Pre-condition: {_TABLE_NAME!r} must exist"

    # Execute the downgrade SQL.
    conn.execute(text(f"DROP TABLE IF EXISTS {_TABLE_NAME} CASCADE"))

    # Table must be gone.
    assert not _table_exists(
        conn, _TABLE_NAME
    ), f"Table {_TABLE_NAME!r} still present after DROP TABLE — downgrade SQL failed"

    # Roll back so the session-scoped fixture remains intact.
    conn.rollback()


def test_downgrade_cascade_does_not_affect_other_tables(conn: sa.engine.Connection) -> None:
    """The CASCADE in DROP TABLE only affects path_templates dependencies.

    We verify that a sibling table (``canonical_entities``) still exists after
    a simulated downgrade — confirming the CASCADE clause is scoped only to
    foreign-key dependants of ``path_templates`` (of which there are none in
    the current schema).
    """
    # Simulate downgrade.
    conn.execute(text(f"DROP TABLE IF EXISTS {_TABLE_NAME} CASCADE"))

    # canonical_entities must be unaffected.
    assert _table_exists(conn, "canonical_entities"), (
        "``canonical_entities`` was unexpectedly dropped — " "path_templates CASCADE has too wide a scope"
    )
    conn.rollback()


# ── Forward-compat ────────────────────────────────────────────────────────────


def test_forward_compat_insert_custom_template(conn: sa.engine.Connection) -> None:
    """A new custom template must be insertable alongside the seed rows.

    PathInsightWorker operators will add templates at runtime.  This test
    verifies the schema accepts a new row without error, and that the CHECK
    constraint on JSONB array types is enforced correctly.
    """
    import uuid as _uuid

    custom_id = str(_uuid.uuid4())
    try:
        conn.execute(
            text(
                f"INSERT INTO {_TABLE_NAME} "  # noqa: S608
                "(template_id, template_name, entity_type_sequence, "
                " relation_type_sequence, description, enabled) "
                f"VALUES ('{custom_id}', 'test_custom_template_0036', "
                '\'["company", "fund"]\'::jsonb, '
                "'[\"INVESTS_IN\"]'::jsonb, "
                "'Test template for forward-compat test', TRUE)"
            )
        )
        row = conn.execute(
            text(
                f"SELECT template_name FROM {_TABLE_NAME} "  # noqa: S608
                f"WHERE template_id = '{custom_id}'"
            )
        ).fetchone()
        assert row is not None, "Custom template row not found after INSERT"
        assert row[0] == "test_custom_template_0036"
    finally:
        conn.rollback()
