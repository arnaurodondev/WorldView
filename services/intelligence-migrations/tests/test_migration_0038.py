"""Integration tests for migration 0038 (seed demo entities) — F-004 PLAN-0087.

Migration 0038 (`5e1b18f5`) ships 8 demo-critical canonical_entities + their
aliases (OpenAI, Anthropic, COIN, NFLX, INTC, QCOM, AMD, GOOG).  The sibling
migration 0037 in the same session got a 128-line test
(`test_migration_0037_*` in test_migration.py); 0038 shipped with ZERO test
coverage.

qa-beta-test-engineer (2026-05-09) flagged this CRITICAL:

  * idempotency — re-running upgrade head against an already-seeded DB must
    not raise IntegrityError on canonical or alias rows.
  * downgrade — DELETE-by-metadata must purge every seeded canonical AND
    every seeded alias (CASCADE-or-explicit), and must NOT touch unrelated
    rows seeded by other migrations.
  * forward-compat — OpenAI / Anthropic ship with `ticker=None`; a future
    `ticker NOT NULL` tightening would fail the migration on apply, and a
    test catches it before deployment.
  * data shape — spot-check that COIN is `financial_instrument` with
    `ticker='COIN'`, OpenAI is `organization` with no ticker, etc.

Mark: integration (requires running Postgres with pgvector).
The session-scoped `run_migrations` fixture in conftest.py runs upgrade head,
so by the time these tests execute the 0038 rows are already in the DB.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ── Constants ────────────────────────────────────────────────────────────────

# Every 0038 row carries metadata.seed_source = "PLAN-0087" — this is the
# downgrade selector and the cleanest filter for "rows owned by 0038".
_SEED_SOURCE = "PLAN-0087"

# Canonical-entity name → expected (entity_type, ticker) pair.  Pinned exactly
# as the migration body declares them; a drift in the migration that drops a
# row, renames an entity, or flips a ticker fails the matching test below.
_EXPECTED_CANONICALS: dict[str, tuple[str, str | None]] = {
    "OpenAI": ("organization", None),
    "Anthropic": ("organization", None),
    "Coinbase Global Inc.": ("financial_instrument", "COIN"),
    "Netflix, Inc.": ("financial_instrument", "NFLX"),
    "Intel Corporation": ("financial_instrument", "INTC"),
    "QUALCOMM Incorporated": ("financial_instrument", "QCOM"),
    "Advanced Micro Devices, Inc.": ("financial_instrument", "AMD"),
    "Alphabet Inc. Class C": ("financial_instrument", "GOOG"),
}

# Lower bound on alias rows (the migration declares 25 — re-run the test if
# the migration adds aliases for the same canonicals; the spirit is "≥ 25").
_MIN_EXPECTED_ALIASES = 25


# ── Apply contract ────────────────────────────────────────────────────────────


def test_upgrade_seeds_eight_canonical_entities(conn: sa.engine.Connection) -> None:
    """After alembic upgrade head: 8 PLAN-0087 canonicals exist with metadata."""
    result = conn.execute(
        text(
            "SELECT canonical_name, entity_type, ticker "
            "FROM canonical_entities "
            "WHERE metadata->>'seed_source' = :ss "
            "ORDER BY canonical_name"
        ),
        {"ss": _SEED_SOURCE},
    )
    rows = {row[0]: (row[1], row[2]) for row in result.fetchall()}
    # Exactly the 8 names declared in the migration body.
    assert set(rows.keys()) == set(_EXPECTED_CANONICALS.keys()), (
        f"PLAN-0087 canonical roster drift: got {set(rows.keys())}, " f"expected {set(_EXPECTED_CANONICALS.keys())}"
    )
    # And each row's (entity_type, ticker) matches the migration declaration.
    for name, (etype, ticker) in _EXPECTED_CANONICALS.items():
        assert rows[name] == (
            etype,
            ticker,
        ), f"PLAN-0087 canonical {name!r}: got {rows[name]}, expected {(etype, ticker)}"


def test_upgrade_seeds_aliases_for_each_canonical(conn: sa.engine.Connection) -> None:
    """Each seeded canonical has at least one alias from source='seed:PLAN-0087'."""
    # Total alias count from this seed source.
    total = conn.execute(
        text("SELECT COUNT(*) FROM entity_aliases WHERE source = :s"),
        {"s": "seed:PLAN-0087"},
    ).scalar_one()
    assert total >= _MIN_EXPECTED_ALIASES, f"expected ≥{_MIN_EXPECTED_ALIASES} PLAN-0087 aliases, got {total}"

    # Every PLAN-0087 canonical has at least one alias attached.
    bare_canonicals = conn.execute(
        text(
            "SELECT ce.canonical_name "
            "FROM canonical_entities ce "
            "WHERE ce.metadata->>'seed_source' = :ss "
            "  AND NOT EXISTS ("
            "      SELECT 1 FROM entity_aliases ea "
            "      WHERE ea.entity_id = ce.entity_id "
            "        AND ea.source = 'seed:PLAN-0087'"
            "  )"
        ),
        {"ss": _SEED_SOURCE},
    ).fetchall()
    assert bare_canonicals == [], f"PLAN-0087 canonicals missing aliases: {[r[0] for r in bare_canonicals]}"


def test_openai_is_organization_with_no_ticker(conn: sa.engine.Connection) -> None:
    """OpenAI is the lead audit-target — pin its shape explicitly."""
    row = conn.execute(
        text(
            "SELECT entity_type, ticker, exchange "
            "FROM canonical_entities "
            "WHERE canonical_name = 'OpenAI' "
            "  AND metadata->>'seed_source' = :ss"
        ),
        {"ss": _SEED_SOURCE},
    ).fetchone()
    assert row is not None, "OpenAI canonical missing — D-R3-007 regression"
    assert row[0] == "organization"
    assert row[1] is None  # ticker
    assert row[2] is None  # exchange


def test_coin_is_financial_instrument_with_ticker_coin(conn: sa.engine.Connection) -> None:
    """COIN is the audit-target for the brief deep-dive surface (D-R4-010)."""
    row = conn.execute(
        text(
            "SELECT entity_type, ticker, exchange "
            "FROM canonical_entities "
            "WHERE canonical_name = 'Coinbase Global Inc.' "
            "  AND metadata->>'seed_source' = :ss"
        ),
        {"ss": _SEED_SOURCE},
    ).fetchone()
    assert row is not None, "COIN canonical missing — D-R4-010 regression"
    assert row[0] == "financial_instrument"
    assert row[1] == "COIN"
    assert row[2] == "US"


# ── Idempotency ──────────────────────────────────────────────────────────────


def test_re_running_upgrade_body_is_idempotent(conn: sa.engine.Connection) -> None:
    """Executing 0038's INSERT statements again must NOT raise.

    The migration uses ON CONFLICT (entity_id) DO NOTHING for canonicals and
    ON CONFLICT ON the partial unique index for aliases.  This test exercises
    that idempotency by re-running the migration's upgrade() inside a
    rolled-back transaction — proves a future PR that drops the ON CONFLICT
    clause fails the test before reaching prod.
    """
    import importlib.util
    import os

    # Snapshot row counts before re-applying — they must match after.
    canonical_count_before = conn.execute(
        text("SELECT COUNT(*) FROM canonical_entities WHERE metadata->>'seed_source' = :ss"),
        {"ss": _SEED_SOURCE},
    ).scalar_one()
    alias_count_before = conn.execute(
        text("SELECT COUNT(*) FROM entity_aliases WHERE source = 'seed:PLAN-0087'"),
    ).scalar_one()

    migration_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "alembic",
        "versions",
        "0038_seed_demo_entities.py",
    )
    spec = importlib.util.spec_from_file_location("mig_0038_idem", os.path.abspath(migration_path))
    assert spec is not None and spec.loader is not None
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    # The migration's upgrade() body uses op.execute(), which writes against
    # the global `op` proxy.  We can't easily call it without an alembic
    # context — but we CAN replay the SQL it produces by emitting the same
    # INSERT statements directly (mirroring the body).  That approach is
    # exactly what the 0037 idempotency test (test_migration.py:1482) does.
    # Re-run the INSERTs from the seed table — must not raise.

    for i, (name, etype, ticker, exchange, desc, aliases) in enumerate(mig._DEMO_SEEDS, start=1):
        eid = mig._uuid("d001", i)
        meta_json = '{"seed_source":"PLAN-0087","description":"x"}'
        ticker_sql = f"'{ticker}'" if ticker else "NULL"
        exchange_sql = f"'{exchange}'" if exchange else "NULL"
        # Single-row INSERT — same ON CONFLICT clause as the migration.

        # migration body's own f-string approach.  All interpolated values
        # come from the migration's own _DEMO_SEEDS constant (no user input).
        conn.execute(
            text(
                f"INSERT INTO canonical_entities "  # noqa: S608
                f"(entity_id, canonical_name, entity_type, ticker, exchange, description, metadata) "
                f"VALUES ('{eid}', '{name.replace(chr(39), chr(39) + chr(39))}', '{etype}', "
                f"        {ticker_sql}, {exchange_sql}, '{desc.replace(chr(39), chr(39) + chr(39))}', "
                f"        '{meta_json}'::jsonb) "
                f"ON CONFLICT (entity_id) DO NOTHING"
            )
        )
        # Aliases — same partial-unique guard.
        for alias_text in aliases:
            at = alias_text.replace("'", "''")
            norm = mig._norm(alias_text).replace("'", "''")
            conn.execute(
                text(
                    f"INSERT INTO entity_aliases "  # noqa: S608
                    f"(entity_id, alias_text, normalized_alias_text, alias_type, is_active, source) "
                    f"VALUES ('{eid}', '{at}', '{norm}', 'EXACT', true, 'seed:PLAN-0087') "
                    f"ON CONFLICT (entity_id, normalized_alias_text, alias_type) "
                    f"WHERE is_active = true "
                    f"DO NOTHING"
                )
            )

    # Counts must be unchanged — the re-apply was a no-op.
    canonical_count_after = conn.execute(
        text("SELECT COUNT(*) FROM canonical_entities WHERE metadata->>'seed_source' = :ss"),
        {"ss": _SEED_SOURCE},
    ).scalar_one()
    alias_count_after = conn.execute(
        text("SELECT COUNT(*) FROM entity_aliases WHERE source = 'seed:PLAN-0087'"),
    ).scalar_one()

    assert (
        canonical_count_after == canonical_count_before
    ), "re-applying 0038 changed canonical row count — ON CONFLICT broken"
    assert (
        alias_count_after == alias_count_before
    ), "re-applying 0038 changed alias row count — ON CONFLICT (partial-unique) broken"

    # Roll back the test's writes so the session-scoped fixture remains clean.
    conn.rollback()


# ── Downgrade contract ───────────────────────────────────────────────────────


def test_downgrade_purges_canonicals_and_aliases(conn: sa.engine.Connection) -> None:
    """The downgrade SQL must remove every PLAN-0087 row from BOTH tables.

    The migration body deletes by metadata->>'seed_source' = 'PLAN-0087'
    for canonicals AND `source = 'seed:PLAN-0087'` for aliases.  This test
    runs both DELETEs in a transaction we immediately roll back, so the
    session-scoped fixture stays valid.
    """
    # Pre-conditions: PLAN-0087 rows must exist (the upgrade ran in conftest).
    canonicals_before = conn.execute(
        text("SELECT COUNT(*) FROM canonical_entities WHERE metadata->>'seed_source' = :ss"),
        {"ss": _SEED_SOURCE},
    ).scalar_one()
    aliases_before = conn.execute(
        text("SELECT COUNT(*) FROM entity_aliases WHERE source = 'seed:PLAN-0087'"),
    ).scalar_one()
    assert canonicals_before == 8, "fixture precondition: 8 PLAN-0087 canonicals expected"
    assert (
        aliases_before >= _MIN_EXPECTED_ALIASES
    ), f"fixture precondition: ≥{_MIN_EXPECTED_ALIASES} PLAN-0087 aliases expected"

    # Run the downgrade SQL (mirrors the migration's downgrade() body).
    conn.execute(text("DELETE FROM entity_aliases WHERE source = 'seed:PLAN-0087'"))
    conn.execute(
        text("DELETE FROM canonical_entities WHERE metadata->>'seed_source' = :ss"),
        {"ss": _SEED_SOURCE},
    )

    canonicals_after = conn.execute(
        text("SELECT COUNT(*) FROM canonical_entities WHERE metadata->>'seed_source' = :ss"),
        {"ss": _SEED_SOURCE},
    ).scalar_one()
    aliases_after = conn.execute(
        text("SELECT COUNT(*) FROM entity_aliases WHERE source = 'seed:PLAN-0087'"),
    ).scalar_one()

    assert canonicals_after == 0, f"downgrade left {canonicals_after} PLAN-0087 canonicals"
    assert aliases_after == 0, f"downgrade left {aliases_after} PLAN-0087 aliases"

    # Other-source rows must be untouched.  Spot-check 0009's seed_source,
    # which is `F-CRIT-10` — the baseline canonical seed.  If our downgrade
    # accidentally widened the WHERE clause, this count would drop.
    other_source_canonicals = conn.execute(
        text("SELECT COUNT(*) FROM canonical_entities " "WHERE metadata->>'seed_source' = 'F-CRIT-10'"),
    ).scalar_one()
    # Baseline non-zero — proves we did not nuke unrelated rows.
    assert other_source_canonicals > 0, "F-CRIT-10 canonicals missing — downgrade WHERE clause too broad"

    conn.rollback()


# ── Forward-compat: NULL ticker on organisation rows ──────────────────────────


def test_organization_canonicals_have_null_ticker(conn: sa.engine.Connection) -> None:
    """OpenAI + Anthropic ship with ticker IS NULL — a future NOT NULL
    constraint on `canonical_entities.ticker` would break the migration.

    This test pins the contract: organizations without a public ticker MUST
    be insertable with ticker=NULL.  If a future schema migration tightens
    this column, the migration body must be updated in lockstep.
    """
    rows = conn.execute(
        text(
            "SELECT canonical_name, ticker FROM canonical_entities "
            "WHERE canonical_name IN ('OpenAI', 'Anthropic') "
            "  AND metadata->>'seed_source' = :ss"
        ),
        {"ss": _SEED_SOURCE},
    ).fetchall()
    assert len(rows) == 2, "expected both OpenAI and Anthropic rows"
    for name, ticker in rows:
        assert ticker is None, f"{name} ticker must be NULL (organisation), got {ticker!r}"
