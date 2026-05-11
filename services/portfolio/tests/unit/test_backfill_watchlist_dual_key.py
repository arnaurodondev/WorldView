"""Unit tests for the dual-key resolution logic in
``backfill_watchlist_member_denorm``.

F-304 (QA iter-3 2026-04-28): the original script joined exclusively on
``instruments.entity_id``, which never matched seed-style rows whose
``watchlist_members.entity_id`` actually held the ``instruments.id`` PK.
The fix runs TWO UPDATE-FROMs — primary on entity_id, fallback on id —
so both data shapes resolve. These tests verify both queries are
emitted in the correct order with the right keys.

We don't spin up a real Postgres in this unit test (the script's
behaviour against live data is exercised by the integration ops run in
the deploy pipeline). Instead we verify the SQL strings the script
issues, which is the lowest-cost regression guard against accidentally
removing one half of the dual-key pass.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── Module load via importlib (avoids needing portfolio.scripts on path) ────


def _load_script_module():
    """Load the backfill script as a module so we can poke at ``_run``.

    The script lives under ``services/portfolio/scripts/`` which is NOT
    in any Python package, so we import it directly from the file path.
    """
    script_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "backfill_watchlist_member_denorm.py"
    spec = importlib.util.spec_from_file_location("_backfill_watchlist", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so ``@dataclass`` can find the module via
    # ``sys.modules.get(cls.__module__)`` (Python 3.12 dataclass internals
    # walk module __dict__ to identify KW_ONLY etc.).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ── Fakes / helpers ──────────────────────────────────────────────────────────


def _make_mock_session(
    *,
    null_count: int,
    resolvable: int,
    updated_primary: int,
    updated_fallback: int,
) -> MagicMock:
    """Build a mock SQLAlchemy session that records every ``execute`` call.

    Each call's first arg is a ``TextClause``; we keep a list of the rendered
    SQL strings on the mock so the test can assert ordering and content.
    """
    session = MagicMock()

    # Sequence of return values per execute(): the script issues
    # COUNT(*), COUNT(DISTINCT...), then two UPDATEs.
    return_values = [
        # 1st execute: SELECT COUNT(*) (null_count)
        _scalar_result(null_count),
        # 2nd execute: resolvable count
        _scalar_result(resolvable),
        # 3rd execute: primary UPDATE (rowcount property)
        _rowcount_result(updated_primary),
        # 4th execute: fallback UPDATE
        _rowcount_result(updated_fallback),
    ]
    session.execute = AsyncMock(side_effect=return_values)
    session.commit = AsyncMock()

    # We use this list to capture the SQL each execute saw (set up below).
    return session


def _scalar_result(value: int) -> MagicMock:
    """SQLAlchemy result with .scalar() returning ``value``."""
    result = MagicMock()
    result.scalar = MagicMock(return_value=value)
    return result


def _rowcount_result(value: int) -> MagicMock:
    """SQLAlchemy result with .rowcount returning ``value``."""
    result = MagicMock()
    result.rowcount = value
    return result


class TestDualKeyResolution:
    """Pin the dual-key UPDATE behaviour."""

    @pytest.mark.asyncio
    async def test_runs_two_updates_in_correct_order(self) -> None:
        """The script issues primary (entity_id) then fallback (id) UPDATEs."""
        module = _load_script_module()

        session = _make_mock_session(
            null_count=11,
            resolvable=11,
            updated_primary=2,
            updated_fallback=9,
        )

        # Patch the factory builder so ``_run`` uses our mock session.
        # ``_build_factories`` returns a 4-tuple; the 3rd is the write
        # factory used inside ``async with write_factory() as session``.
        async_cm = MagicMock()
        async_cm.__aenter__ = AsyncMock(return_value=session)
        async_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=async_cm)

        with patch.object(
            module,
            "_build_factories",
            return_value=(MagicMock(), MagicMock(), write_factory, MagicMock()),
        ):
            settings = MagicMock()
            report = await module._run(settings, dry_run=False)

        # Total updated = primary + fallback
        assert report.rows_updated == 11
        assert report.rows_with_null_ticker == 11
        assert report.rows_resolvable == 11

        # Pull the rendered SQL strings out of every call to execute().
        sql_calls = [str(call.args[0]) for call in session.execute.await_args_list]
        assert len(sql_calls) == 4  # 2 counts + 2 updates

        # 3rd call: primary UPDATE keyed on entity_id
        assert "i.entity_id = wm.entity_id" in sql_calls[2]
        assert "UPDATE watchlist_members" in sql_calls[2]

        # 4th call: fallback UPDATE keyed on id
        assert "i.id = wm.entity_id" in sql_calls[3]
        assert "UPDATE watchlist_members" in sql_calls[3]

        # Fallback runs AFTER primary so primary's ticker writes filter
        # out via ``WHERE wm.ticker IS NULL`` in the second pass.
        assert "wm.ticker IS NULL" in sql_calls[3]

    @pytest.mark.asyncio
    async def test_resolvable_count_uses_dual_key_or(self) -> None:
        """Pre-flight count uses an OR predicate covering both join keys."""
        module = _load_script_module()

        session = _make_mock_session(
            null_count=5,
            resolvable=5,
            updated_primary=0,
            updated_fallback=0,
        )

        async_cm = MagicMock()
        async_cm.__aenter__ = AsyncMock(return_value=session)
        async_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=async_cm)

        with patch.object(
            module,
            "_build_factories",
            return_value=(MagicMock(), MagicMock(), write_factory, MagicMock()),
        ):
            settings = MagicMock()
            await module._run(settings, dry_run=True)

        sql_calls = [str(call.args[0]) for call in session.execute.await_args_list]
        # 2nd execute is the resolvable-count SELECT — must reference both
        # keys with OR so dry-run accurately reports rows the live pass
        # will actually update.
        resolvable_sql = sql_calls[1]
        assert "i.entity_id = wm.entity_id" in resolvable_sql
        assert "i.id = wm.entity_id" in resolvable_sql
        assert "OR" in resolvable_sql.upper()

    @pytest.mark.asyncio
    async def test_dry_run_short_circuits_before_updates(self) -> None:
        """``--dry-run`` must NEVER issue UPDATE statements."""
        module = _load_script_module()

        session = _make_mock_session(
            null_count=3,
            resolvable=3,
            # Even if updates somehow ran, these values shouldn't surface
            updated_primary=99,
            updated_fallback=99,
        )

        async_cm = MagicMock()
        async_cm.__aenter__ = AsyncMock(return_value=session)
        async_cm.__aexit__ = AsyncMock(return_value=None)
        write_factory = MagicMock(return_value=async_cm)

        with patch.object(
            module,
            "_build_factories",
            return_value=(MagicMock(), MagicMock(), write_factory, MagicMock()),
        ):
            settings = MagicMock()
            report = await module._run(settings, dry_run=True)

        assert report.dry_run is True
        assert report.rows_updated == 0
        # Only 2 reads (null_count + resolvable) — no UPDATE issued.
        assert session.execute.await_count == 2
        session.commit.assert_not_called()
