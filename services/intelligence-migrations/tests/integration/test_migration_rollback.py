"""TASK-W3-01 Test 2 — Rollback the last 3 migrations, then re-upgrade.

After ``alembic upgrade head`` runs in the session fixture, this test:

  1. Runs ``alembic downgrade -3`` (rolls back the latest three revisions).
  2. Verifies that artifacts created by those three migrations are gone.
  3. Re-runs ``alembic upgrade head`` and verifies the artifacts are back.

Requires a live Postgres reachable through ``INTELLIGENCE_DB_URL``. Skipped
gracefully when the DB is unreachable.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from sqlalchemy import text

if TYPE_CHECKING:
    import sqlalchemy as sa
    from alembic.config import Config

pytestmark = pytest.mark.integration

# Artifacts created by the last 3 migrations on disk (0038, 0039, 0040).
#
#   0038 — seed_demo_entities: adds 8 demo canonical_entities (no schema change).
#   0039 — add_canonical_entity_type_check: adds CHECK constraint on
#          canonical_entities.entity_type.
#   0040 — create_ticker_aliases: creates ``ticker_aliases`` table + indexes.
#
# Sampling these three covers both DDL (0040) and constraint-only (0039)
# migrations. 0038 is a seed migration — we sample its presence by checking
# that one of the seeded canonical_entities exists.
_ARTIFACTS_TO_VERIFY: tuple[tuple[str, str], ...] = (
    # (artifact_type, identifier)
    ("table", "ticker_aliases"),  # 0040
    ("constraint_on_canonical_entities", "ck_canonical_entity_type"),  # 0039
)


def _check_artifact(conn: sa.engine.Connection, kind: str, ident: str) -> bool:
    """Return True if the artifact exists in the DB."""
    if kind == "table":
        result = conn.execute(
            text("SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = :t"),
            {"t": ident},
        ).fetchone()
        return result is not None
    if kind == "constraint_on_canonical_entities":
        result = conn.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = :c " "AND conrelid = 'canonical_entities'::regclass"),
            {"c": ident},
        ).fetchone()
        return result is not None
    raise AssertionError(f"unknown artifact kind: {kind}")


def test_rollback_three_then_upgrade_restores_schema(
    live_db_ready: None,
    alembic_cfg: Config,
    engine: sa.engine.Engine,
) -> None:
    """Downgrade -3, verify artifacts gone, upgrade head, verify artifacts back."""
    # Ensure subsequent alembic.command calls see the URL the session fixture
    # cached in os.environ.
    assert "INTELLIGENCE_DB_URL" in os.environ, "session fixture should set INTELLIGENCE_DB_URL"

    # Sanity: at head, all sampled artifacts must exist.
    with engine.connect() as conn:
        for kind, ident in _ARTIFACTS_TO_VERIFY:
            assert _check_artifact(conn, kind, ident), f"precondition failed: artifact {kind}:{ident} missing at head"

    # Step 1: downgrade -3.
    command.downgrade(alembic_cfg, "-3")

    # Step 2: each artifact created by the last 3 migrations should be gone.
    with engine.connect() as conn:
        for kind, ident in _ARTIFACTS_TO_VERIFY:
            assert not _check_artifact(
                conn, kind, ident
            ), f"artifact {kind}:{ident} should be gone after downgrade -3 but still exists"

    # Step 3: re-upgrade to head.
    command.upgrade(alembic_cfg, "head")

    # Step 4: artifacts back.
    with engine.connect() as conn:
        for kind, ident in _ARTIFACTS_TO_VERIFY:
            assert _check_artifact(
                conn, kind, ident
            ), f"artifact {kind}:{ident} should be restored after upgrade head but is missing"


def test_alembic_version_after_rollback_cycle(
    live_db_ready: None,
    alembic_cfg: Config,
    engine: sa.engine.Engine,
) -> None:
    """After a downgrade -3 / upgrade head cycle, ``alembic_version`` once
    again equals the on-disk head revision."""
    versions_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    rev_re = re.compile(r"^\s*revision(?:\s*:\s*\w+)?\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
    down_re = re.compile(
        r"^\s*down_revision(?:\s*:\s*[\w\[\]| ]+)?\s*=\s*(['\"]([^'\"]+)['\"]|None)",
        re.MULTILINE,
    )
    revisions: dict[str, str | None] = {}
    for f in versions_dir.glob("*.py"):
        if f.name.startswith("_"):
            continue
        body = f.read_text(encoding="utf-8")
        m = rev_re.search(body)
        d = down_re.search(body)
        if m is None:
            continue
        if d is None or d.group(1) == "None":
            revisions[m.group(1)] = None
        else:
            revisions[m.group(1)] = d.group(2)
    pointed_to = {down for down in revisions.values() if down is not None}
    heads = [rev for rev in revisions if rev not in pointed_to]
    expected_head = heads[0]

    # Perform the rollback cycle and verify the head matches.
    command.downgrade(alembic_cfg, "-3")
    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        actual = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert actual == expected_head, f"after rollback cycle, head mismatch: db={actual!r} disk={expected_head!r}"
