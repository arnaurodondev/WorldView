"""TASK-W3-01 Test 4 — ``alembic upgrade head`` is idempotent.

After the session fixture has already applied head, calling ``upgrade head``
again must be a no-op:

  * The ``alembic_version`` row is unchanged.
  * No additional rows are inserted into any seed table (we check
    ``decay_class_config``, ``relation_type_registry`` and ``path_templates``
    as representative seed targets).

Requires a live Postgres; skipped gracefully when unreachable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from alembic import command
from sqlalchemy import text

if TYPE_CHECKING:
    import sqlalchemy as sa
    from alembic.config import Config

pytestmark = pytest.mark.integration


_SEED_TABLES = (
    "decay_class_config",
    "relation_type_registry",
    "path_templates",
    "source_trust_weights",
)


def test_upgrade_head_is_noop_when_already_at_head(
    live_db_ready: None,
    alembic_cfg: Config,
    engine: sa.engine.Engine,
) -> None:
    """Re-running ``upgrade head`` after the session fixture leaves the DB
    in the same state — no extra rows in seed tables, same version_num.
    """
    # Snapshot counts + version before re-running upgrade. Table names come
    # from a hard-coded module-level tuple, not user input — S608 noise.
    with engine.connect() as conn:
        version_before = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        counts_before = {
            t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one()  # noqa: S608 — hard-coded table list
            for t in _SEED_TABLES
        }

    # Second upgrade — should be a no-op.
    command.upgrade(alembic_cfg, "head")

    # Verify nothing moved.
    with engine.connect() as conn:
        version_after = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        counts_after = {
            t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one()  # noqa: S608 — hard-coded table list
            for t in _SEED_TABLES
        }

    assert (
        version_after == version_before
    ), f"version_num changed on no-op upgrade: {version_before!r} → {version_after!r}"
    for table in _SEED_TABLES:
        assert counts_after[table] == counts_before[table], (
            f"Seed table {table} grew on no-op upgrade: {counts_before[table]} → {counts_after[table]} "
            f"— migration is not idempotent."
        )


def test_alembic_version_table_has_exactly_one_row(
    live_db_ready: None,
    engine: sa.engine.Engine,
) -> None:
    """Defensive check: ``alembic_version`` must contain exactly one row.
    Multiple rows would indicate the version table was corrupted by a
    non-idempotent migration."""
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one()
    assert n == 1, f"alembic_version expected exactly 1 row, found {n}"
