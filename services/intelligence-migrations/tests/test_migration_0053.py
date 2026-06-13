"""Integration tests for migration 0053 — add 'exchange' entity_type (FR-12).

Migration 0053 widens ``ck_canonical_entities_entity_type`` from 11 values to 12
by adding ``exchange`` (so NYSE/NASDAQ-class venues have a correct home).

The session-scoped ``run_migrations`` fixture applies ``alembic upgrade head``
before these tests run, so the upgrade-contract tests verify post-upgrade state.
The apply+rollback round-trip drives the 0052↔0053 transition explicitly.

Mark: integration (requires running Postgres with pgvector + AGE).
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import text

pytestmark = pytest.mark.integration

_CONSTRAINT = "ck_canonical_entities_entity_type"


def _check_def(conn: sa.engine.Connection) -> str | None:
    """Return the current entity_type CHECK constraint definition (or None)."""
    row = conn.execute(
        text(
            "SELECT pg_get_constraintdef(c.oid) " "FROM pg_constraint c " "WHERE c.conname = :name AND c.contype = 'c'"
        ),
        {"name": _CONSTRAINT},
    ).fetchone()
    return row[0] if row else None


# ── Upgrade contract ───────────────────────────────────────────────────────────


def test_check_constraint_includes_exchange(conn: sa.engine.Connection) -> None:
    definition = _check_def(conn)
    assert definition is not None, f"{_CONSTRAINT} missing after 0053"
    assert "exchange" in definition, "0053 did not add 'exchange' to the CHECK"


def test_exchange_row_accepted(conn: sa.engine.Connection) -> None:
    """An entity_type='exchange' row must INSERT cleanly post-0053."""
    eid = "01910000-0000-7000-8000-000000053001"
    conn.execute(
        text(
            "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type, created_at, updated_at) "
            "VALUES (:eid, 'New York Stock Exchange', 'exchange', NOW(), NOW()) "
            "ON CONFLICT (entity_id) DO NOTHING"
        ),
        {"eid": eid},
    )
    row = conn.execute(
        text("SELECT entity_type FROM canonical_entities WHERE entity_id = :eid"),
        {"eid": eid},
    ).fetchone()
    assert row is not None and row[0] == "exchange"
    conn.rollback()


def test_original_values_still_valid(conn: sa.engine.Connection) -> None:
    """0053 only WIDENS the domain — the original values must still INSERT."""
    eid = "01910000-0000-7000-8000-000000053002"
    conn.execute(
        text(
            "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type, created_at, updated_at) "
            "VALUES (:eid, 'Some Stock', 'financial_instrument', NOW(), NOW()) "
            "ON CONFLICT (entity_id) DO NOTHING"
        ),
        {"eid": eid},
    )
    row = conn.execute(
        text("SELECT entity_type FROM canonical_entities WHERE entity_id = :eid"),
        {"eid": eid},
    ).fetchone()
    assert row is not None and row[0] == "financial_instrument"
    conn.rollback()


def test_invalid_value_still_rejected(conn: sa.engine.Connection) -> None:
    """A value outside the 12-value domain must still violate the CHECK."""
    eid = "01910000-0000-7000-8000-000000053003"
    with pytest.raises(sa.exc.IntegrityError):
        conn.execute(
            text(
                "INSERT INTO canonical_entities (entity_id, canonical_name, entity_type, created_at, updated_at) "
                "VALUES (:eid, 'Bogus', 'not_a_real_type', NOW(), NOW())"
            ),
            {"eid": eid},
        )
    conn.rollback()


# ── Apply + rollback round-trip (0052 ↔ 0053) ─────────────────────────────────


def test_apply_and_rollback_round_trip(db_url: str) -> None:
    """Drive 0053 down→up explicitly.

    Downgrade to 0052 restores the narrow 11-value CHECK (exchange rejected);
    upgrade back to 0053 re-adds the exchange value.  Leaves the DB at head
    (0053) for the remaining session-scoped tests.
    """
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    os.environ["INTELLIGENCE_DB_URL"] = db_url
    engine = sa.create_engine(db_url, pool_pre_ping=True)

    # Downgrade 0053 → 0052: exchange no longer in the CHECK.
    command.downgrade(cfg, "0052")
    with engine.connect() as conn:
        definition = _check_def(conn)
        assert definition is not None, "entity_type CHECK should still exist at 0052"
        assert "exchange" not in definition, "exchange must be removed on downgrade to 0052"

    # Upgrade back 0052 → 0053: exchange restored.
    command.upgrade(cfg, "0053")
    with engine.connect() as conn:
        definition = _check_def(conn)
        assert definition is not None and "exchange" in definition
    engine.dispose()
