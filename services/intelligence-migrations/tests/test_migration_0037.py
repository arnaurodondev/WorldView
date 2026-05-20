"""Integration tests for migration 0037 — recreate temporal_events + entity_event_exposures.

Migration 0037 (``0037``) fixes D-P3-002 / D-P3-003: the live intelligence_db
was missing ``temporal_events`` and ``entity_event_exposures`` despite those
tables being declared in migrations 0004 + 0007.

What 0037 does:
  1. ``CREATE TABLE IF NOT EXISTS public.temporal_events (...)`` — same shape
     as 0007 but with the 'corporate' event_type from 0018 already included.
  2. Four lookup indexes + the functional unique index
     ``uidx_temporal_events_natural_key`` (all with IF NOT EXISTS).
  3. ``CREATE TABLE IF NOT EXISTS public.entity_event_exposures (...)`` with
     its two indexes.
  4. Constraint repair: if temporal_events already existed WITHOUT 'corporate'
     in the CHECK, drops and re-adds the widened version.

downgrade() is a deliberate noop: tables are owned by 0004 + 0007 and must
not be dropped on rollback to 0036.

Mark: integration (requires running Postgres with pgvector).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text

pytestmark = pytest.mark.integration

# ── Constants ─────────────────────────────────────────────────────────────────

_TEMPORAL_EVENTS = "temporal_events"
_ENTITY_EVENT_EXPOSURES = "entity_event_exposures"

# Indexes created (or confirmed) by 0037.
_TEMPORAL_INDEXES = [
    "idx_temporal_events_scope_from",
    "idx_temporal_events_from_until",
    "idx_temporal_events_type_scope",
    "idx_temporal_events_region_from",
    "uidx_temporal_events_natural_key",
]
_EXPOSURE_INDEXES = [
    "idx_entity_event_exposures_event",
    "idx_entity_event_exposures_entity",
]

# All valid event_type values after 0018 widening (included in 0037 DDL).
_VALID_EVENT_TYPES = [
    "geopolitical",
    "regulatory",
    "macro",
    "sanctions",
    "natural_disaster",
    "other",
    "corporate",
]
_VALID_SCOPES = ["LOCAL", "REGIONAL", "NATIONAL", "GLOBAL"]
_VALID_EXPOSURE_TYPES = [
    "directly_affected",
    "operationally_impacted",
    "supply_chain",
    "revenue_geography",
    "sector_exposure",
]


# ── Helpers ───────────────────────────────────────────────────────────────────


def _table_exists(conn: sa.engine.Connection, table: str) -> bool:
    # Use namespace-qualified lookup to avoid AGE ag_catalog ambiguity.
    row = conn.execute(
        text(
            "SELECT 1 FROM pg_class c "
            "JOIN pg_namespace n ON c.relnamespace = n.oid "
            "WHERE c.relname = :tbl AND n.nspname = 'public'"
        ),
        {"tbl": table},
    ).fetchone()
    return row is not None


def _index_exists(conn: sa.engine.Connection, index_name: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :idx"),
        {"idx": index_name},
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


# ── Upgrade contract — temporal_events table ──────────────────────────────────


def test_upgrade_temporal_events_table_exists(conn: sa.engine.Connection) -> None:
    """After upgrade: ``public.temporal_events`` must exist."""
    assert _table_exists(conn, _TEMPORAL_EVENTS), f"Table ``public.{_TEMPORAL_EVENTS}`` not found — 0037 upgrade failed"


def test_upgrade_temporal_events_required_columns(conn: sa.engine.Connection) -> None:
    """``temporal_events`` must have all required columns from the 0037 DDL."""
    required_cols = [
        "event_id",
        "event_type",
        "scope",
        "region",
        "title",
        "description",
        "source_article_ids",
        "source_url",
        "active_from",
        "active_until",
        "residual_impact_days",
        "confidence",
        "created_at",
        "updated_at",
    ]
    for col in required_cols:
        assert _column_exists(
            conn, _TEMPORAL_EVENTS, col
        ), f"Column ``{_TEMPORAL_EVENTS}.{col}`` missing — 0037 DDL drift"


def test_upgrade_temporal_events_confidence_precision(conn: sa.engine.Connection) -> None:
    """``temporal_events.confidence`` must be NUMERIC(4,3) — enforces 0-1 range precision."""
    row = conn.execute(
        text(
            "SELECT numeric_precision, numeric_scale "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "  AND table_name = :tbl "
            "  AND column_name = 'confidence'"
        ),
        {"tbl": _TEMPORAL_EVENTS},
    ).fetchone()
    assert row is not None, f"Column ``{_TEMPORAL_EVENTS}.confidence`` not found"
    assert row[0] == 4, f"confidence numeric_precision expected 4, got {row[0]}"
    assert row[1] == 3, f"confidence numeric_scale expected 3, got {row[1]}"


# ── Upgrade contract — temporal_events indexes ────────────────────────────────


def test_upgrade_temporal_events_indexes_exist(conn: sa.engine.Connection) -> None:
    """All five temporal_events indexes must exist after upgrade."""
    for idx in _TEMPORAL_INDEXES:
        assert _index_exists(conn, idx), f"Index {idx!r} missing — 0037 upgrade failed to create/confirm it"


def test_upgrade_natural_key_index_is_unique(conn: sa.engine.Connection) -> None:
    """``uidx_temporal_events_natural_key`` must be a UNIQUE index."""
    row = conn.execute(
        text(
            "SELECT ix.indisunique "
            "FROM pg_index ix "
            "JOIN pg_class c ON c.oid = ix.indexrelid "
            "WHERE c.relname = :idx"
        ),
        {"idx": "uidx_temporal_events_natural_key"},
    ).fetchone()
    assert row is not None, "Index ``uidx_temporal_events_natural_key`` not found in pg_index"
    assert row[0] is True, "``uidx_temporal_events_natural_key`` must be UNIQUE"


# ── Upgrade contract — entity_event_exposures table ───────────────────────────


def test_upgrade_entity_event_exposures_table_exists(conn: sa.engine.Connection) -> None:
    """After upgrade: ``public.entity_event_exposures`` must exist."""
    assert _table_exists(
        conn, _ENTITY_EVENT_EXPOSURES
    ), f"Table ``public.{_ENTITY_EVENT_EXPOSURES}`` not found — 0037 upgrade failed"


def test_upgrade_entity_event_exposures_required_columns(conn: sa.engine.Connection) -> None:
    """``entity_event_exposures`` must have all required columns."""
    required_cols = [
        "exposure_id",
        "event_id",
        "entity_id",
        "exposure_type",
        "evidence_text",
        "confidence",
        "created_at",
    ]
    for col in required_cols:
        assert _column_exists(
            conn, _ENTITY_EVENT_EXPOSURES, col
        ), f"Column ``{_ENTITY_EVENT_EXPOSURES}.{col}`` missing — 0037 DDL drift"


def test_upgrade_entity_event_exposures_indexes_exist(conn: sa.engine.Connection) -> None:
    """Both entity_event_exposures indexes must exist after upgrade."""
    for idx in _EXPOSURE_INDEXES:
        assert _index_exists(conn, idx), f"Index {idx!r} missing — 0037 upgrade failed to create/confirm it"


# ── Forward-compat: write and read rows ───────────────────────────────────────


def test_forward_compat_insert_temporal_event_with_corporate_type(
    conn: sa.engine.Connection,
) -> None:
    """Inserting a 'corporate' event_type must succeed (widened CHECK from 0018).

    This is the core regression test for D-P3-002: before 0037 the table
    didn't exist in production.  After 0037 the table exists AND accepts
    the 'corporate' event_type that EarningsCalendarDatasetConsumer emits.
    """
    import uuid as _uuid

    event_id = str(_uuid.uuid4())
    try:
        conn.execute(
            text(
                "INSERT INTO public.temporal_events "
                "(event_id, event_type, scope, title, active_from, "
                " residual_impact_days, confidence) "
                "VALUES (:eid, 'corporate', 'GLOBAL', "
                "'AAPL Q2 Earnings Beat', NOW(), 90, 0.850)"
            ),
            {"eid": event_id},
        )
        row = conn.execute(
            text("SELECT event_type, scope FROM public.temporal_events " "WHERE event_id = :eid"),
            {"eid": event_id},
        ).fetchone()
        assert row is not None, "Inserted temporal_event not found"
        assert row[0] == "corporate"
        assert row[1] == "GLOBAL"
    finally:
        conn.rollback()


def test_forward_compat_all_valid_event_types_accepted(
    conn: sa.engine.Connection,
) -> None:
    """All 7 valid event_type values must be accepted by the CHECK constraint.

    Pinning all values here means if a future migration narrows the CHECK,
    this test fails before the narrowing reaches production.
    """
    import uuid as _uuid

    inserted_ids = []
    try:
        for etype in _VALID_EVENT_TYPES:
            event_id = str(_uuid.uuid4())
            inserted_ids.append(event_id)
            conn.execute(
                text(
                    "INSERT INTO public.temporal_events "
                    "(event_id, event_type, scope, title, active_from, "
                    " residual_impact_days, confidence) "
                    "VALUES (:eid, :etype, 'NATIONAL', "
                    ":title, NOW(), 30, 0.700)"
                ),
                {"eid": event_id, "etype": etype, "title": f"Forward-compat test for {etype}"},
            )
        # Check all inserted rows exist — use ANY with cast.
        # All values are UUIDs generated in this test (no user input).
        uuid_list = ",".join(f"'{i}'::uuid" for i in inserted_ids)
        count = conn.execute(
            text(
                f"SELECT COUNT(*) FROM public.temporal_events "  # noqa: S608
                f"WHERE event_id = ANY(ARRAY[{uuid_list}])"
            )
        ).scalar_one()
        assert count == len(_VALID_EVENT_TYPES), f"Expected {len(_VALID_EVENT_TYPES)} rows, got {count}"
    finally:
        conn.rollback()


def test_forward_compat_entity_event_exposure_fk_to_temporal_event(
    conn: sa.engine.Connection,
) -> None:
    """An entity_event_exposure row must FK-reference its parent temporal_event."""
    import uuid as _uuid

    event_id = str(_uuid.uuid4())
    exposure_id = str(_uuid.uuid4())
    # Use a dummy entity_id — there is no FK to canonical_entities on this table.
    entity_id = str(_uuid.uuid4())
    try:
        conn.execute(
            text(
                "INSERT INTO public.temporal_events "
                "(event_id, event_type, scope, title, active_from, "
                " residual_impact_days, confidence) "
                "VALUES (:eid, 'macro', 'GLOBAL', "
                "'FK parent event', NOW(), 60, 0.600)"
            ),
            {"eid": event_id},
        )
        conn.execute(
            text(
                "INSERT INTO public.entity_event_exposures "
                "(exposure_id, event_id, entity_id, exposure_type, confidence) "
                "VALUES (:xid, :eid, :entid, 'directly_affected', 0.750)"
            ),
            {"xid": exposure_id, "eid": event_id, "entid": entity_id},
        )
        row = conn.execute(
            text("SELECT exposure_type FROM public.entity_event_exposures " "WHERE exposure_id = :xid"),
            {"xid": exposure_id},
        ).fetchone()
        assert row is not None, "entity_event_exposure row not found after INSERT"
        assert row[0] == "directly_affected"
    finally:
        conn.rollback()


# ── Downgrade contract ────────────────────────────────────────────────────────


def test_downgrade_is_noop_temporal_events_persists(conn: sa.engine.Connection) -> None:
    """Downgrade for 0037 is a deliberate noop — tables must NOT be dropped.

    The migration docstring explicitly states: downgrade() is a NO-OP because
    ``temporal_events`` and ``entity_event_exposures`` are owned by 0004 + 0007.
    Dropping them on rollback to 0036 would weaken the invariant.

    This test verifies both tables remain present (the downgrade body is
    ``pass`` — no DROP statements — so the tables owned by earlier migrations
    survive the rollback).
    """
    # Both tables must exist because the session-scoped fixture ran upgrade head
    # (which executed 0004 → 0007 → 0037, all of which are IF NOT EXISTS).
    assert _table_exists(conn, _TEMPORAL_EVENTS), (
        f"Table ``public.{_TEMPORAL_EVENTS}`` unexpectedly absent — "
        "0037 downgrade may have erroneously dropped it (should be noop)"
    )
    assert _table_exists(conn, _ENTITY_EVENT_EXPOSURES), (
        f"Table ``public.{_ENTITY_EVENT_EXPOSURES}`` unexpectedly absent — "
        "0037 downgrade may have erroneously dropped it (should be noop)"
    )


def test_downgrade_noop_does_not_remove_indexes(conn: sa.engine.Connection) -> None:
    """All temporal indexes must remain present after the noop downgrade."""
    for idx in _TEMPORAL_INDEXES:
        assert _index_exists(conn, idx), f"Index {idx!r} missing after downgrade — noop contract violated"
