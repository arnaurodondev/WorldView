"""Source-level guards for migration 039 (same-ISIN instrument dedup + unique guard).

WHY THIS TEST EXISTS:
  Migration 039 does two things that MUST stay correct together:
    1. it folds same-ISIN duplicate instruments into a survivor and deletes the
       losers (re-pointing OHLCV first) — the data repair; and
    2. it adds a partial UNIQUE index ``(isin, exchange)`` so the dup class
       cannot recur.
  The constraint build FAILS if the dedup did not run first, and the partial
  predicate MUST exempt blank-exchange / NULL-isin rows (the enrichment-stub
  class) or it would reject legitimate stub instruments. These textual guards
  pin those invariants so a future edit cannot silently break the ordering or
  widen/narrow the predicate.

  Same pattern as the L-4b lock-step test (``test_l4b_migration_lockstep.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _load_migration_source() -> str:
    here = Path(__file__).resolve()
    repo_root = here
    while repo_root.name != "market-data" and repo_root.parent != repo_root:
        repo_root = repo_root.parent
    mig = repo_root / "alembic" / "versions" / "039_unique_isin_exchange_instruments.py"
    return mig.read_text(encoding="utf-8")


def test_migration_039_revision_chain() -> None:
    """039 must follow 038 (the current head before this migration)."""
    src = _load_migration_source()
    assert 'revision = "039"' in src
    assert 'down_revision = "038"' in src


def test_partial_unique_index_predicate_exempts_blank_and_null() -> None:
    """The unique guard MUST be partial: only isin IS NOT NULL AND exchange <> ''.

    Without the predicate the index would reject the many legitimate
    blank-exchange / NULL-isin enrichment stubs that the dedup deliberately keeps.
    """
    src = _load_migration_source()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_instruments_isin_exchange" in src
    assert "ON instruments (isin, exchange)" in src
    assert "WHERE isin IS NOT NULL AND exchange <> ''" in src


def test_dedup_runs_before_constraint() -> None:
    """The loser DELETE must appear BEFORE the unique-index build (else the build
    aborts on the remaining duplicates)."""
    src = _load_migration_source()
    delete_pos = src.index("DELETE FROM instruments loser")
    index_pos = src.index("CREATE UNIQUE INDEX IF NOT EXISTS uq_instruments_isin_exchange")
    assert delete_pos < index_pos


def test_ohlcv_repointed_before_loser_delete() -> None:
    """OHLCV bars must be copied onto the survivor (ON CONFLICT DO NOTHING) BEFORE
    the loser instrument is deleted, so the survivor inherits the loser's unique
    bars instead of losing them to the CASCADE."""
    src = _load_migration_source()
    insert_pos = src.index("INSERT INTO ohlcv_bars")
    delete_pos = src.index("DELETE FROM instruments loser")
    assert insert_pos < delete_pos
    assert "ON CONFLICT (instrument_id, timeframe, bar_date) DO NOTHING" in src


def test_survivor_choice_prefers_nonblank_exchange_and_ohlcv() -> None:
    """The in-migration survivor pick must prefer a non-blank exchange and the
    OHLCV-bearing (live) row — matching the dedup script's live-ticker rule."""
    src = _load_migration_source()
    assert "(exchange <> '') DESC" in src
    assert "has_ohlcv DESC" in src


def test_downgrade_drops_index_only() -> None:
    """Downgrade drops the guard index; the merge itself is irreversible."""
    src = _load_migration_source()
    assert "DROP INDEX IF EXISTS uq_instruments_isin_exchange" in src
