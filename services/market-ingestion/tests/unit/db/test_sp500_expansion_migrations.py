"""Unit tests for migrations 0014-0017 (PLAN-0106 waves A-1, C-0, E-1).

These are pure-Python tests (no Postgres required).  They verify:

1. Migration 0014: revision chain is correct; generated IDs are globally unique
   within the migration's insertions; no overlap with existing symbols.
2. Migration 0015: revision chain; correct SQL semantics.
3. Migration 0016: revision chain; correct SQL semantics.
4. Migration 0017: revision chain; generated IDs are unique; top-100 list has
   exactly 100 symbols.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_VERSIONS_DIR = Path(__file__).parent.parent.parent.parent / "alembic" / "versions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_migration(filename: str):
    """Load a migration file as a Python module without invoking alembic.op."""
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"_migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Stub alembic so the import succeeds without an actual Alembic env.
    sys.modules.setdefault("alembic", type(sys)("alembic"))
    sys.modules.setdefault("alembic.op", type(sys)("alembic.op"))
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Migration 0014 — S&P 500 universe expansion
# ---------------------------------------------------------------------------


class TestMigration0014:
    """Revision metadata + ID uniqueness for the S&P 500 expansion."""

    def test_revision_is_0014(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        assert mod.revision == "0014"

    def test_down_revision_is_0013(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        assert mod.down_revision == "0013"

    def test_new_sp500_symbols_has_no_duplicates(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        symbols = mod._NEW_SP500_SYMBOLS
        assert len(symbols) == len(
            set(symbols)
        ), f"Duplicate symbols found: {[s for s in symbols if symbols.count(s) > 1]}"

    def test_new_sp500_symbols_do_not_overlap_with_existing(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        overlap = mod._EXISTING_US_SYMBOLS & set(mod._NEW_SP500_SYMBOLS)
        assert not overlap, f"Overlap with existing symbols: {overlap}"

    def test_global_indices_has_no_duplicates(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        indices = mod._GLOBAL_INDICES
        pairs = list(indices)
        assert len(pairs) == len(set(pairs)), "Duplicate global index entries"

    def test_sp500_policy_ids_are_unique(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        ids = mod._sp500_policy_ids()
        assert len(ids) == len(set(ids)), "Duplicate policy IDs in S&P 500 expansion"

    def test_index_policy_ids_are_unique(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        ids = mod._index_policy_ids()
        assert len(ids) == len(set(ids)), "Duplicate policy IDs in global indices"

    def test_no_id_overlap_between_sp500_and_indices(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        sp500_ids = set(mod._sp500_policy_ids())
        index_ids = set(mod._index_policy_ids())
        assert not sp500_ids & index_ids, "ID collision between S&P 500 and global index policies"

    def test_policy_count_per_symbol(self) -> None:
        """Each S&P 500 symbol gets exactly 4 policies: 1 fundamentals + 3 OHLCV."""
        mod = _load_migration("0014_sp500_universe_expansion.py")
        ids = mod._sp500_policy_ids()
        # 4 policies per symbol
        assert len(ids) == len(mod._NEW_SP500_SYMBOLS) * 4

    def test_global_indices_get_3_ohlcv_policies_each(self) -> None:
        """Each global index gets exactly 3 OHLCV policies (1d / 1w / 1mo)."""
        mod = _load_migration("0014_sp500_universe_expansion.py")
        ids = mod._index_policy_ids()
        assert len(ids) == len(mod._GLOBAL_INDICES) * 3

    def test_ulid_from_seed_is_deterministic(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        seed = "eodhd:fundamentals:AAPL:US::General"
        assert mod._ulid_from_seed(seed) == mod._ulid_from_seed(seed)

    def test_ulid_has_correct_length(self) -> None:
        mod = _load_migration("0014_sp500_universe_expansion.py")
        uid = mod._ulid_from_seed("eodhd:test:SYM:US:1d:")
        assert len(uid) == 26
        assert uid.startswith("01HX")


# ---------------------------------------------------------------------------
# Migration 0015 — disable EODHD quotes for US/CC
# ---------------------------------------------------------------------------


class TestMigration0015:
    """Revision chain for the EODHD quote-disable migration."""

    def test_revision_is_0015(self) -> None:
        mod = _load_migration("0015_disable_eodhd_quotes_us_cc.py")
        assert mod.revision == "0015"

    def test_down_revision_is_0014(self) -> None:
        mod = _load_migration("0015_disable_eodhd_quotes_us_cc.py")
        assert mod.down_revision == "0014"

    def test_upgrade_and_downgrade_are_callable(self) -> None:
        """Upgrade and downgrade must be importable callables (not None)."""
        mod = _load_migration("0015_disable_eodhd_quotes_us_cc.py")
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)


# ---------------------------------------------------------------------------
# Migration 0016 — disable S2 news_sentiment
# ---------------------------------------------------------------------------


class TestMigration0016:
    """Revision chain for the news_sentiment disable migration."""

    def test_revision_is_0016(self) -> None:
        mod = _load_migration("0016_disable_s2_news_sentiment.py")
        assert mod.revision == "0016"

    def test_down_revision_is_0015(self) -> None:
        mod = _load_migration("0016_disable_s2_news_sentiment.py")
        assert mod.down_revision == "0015"

    def test_upgrade_and_downgrade_are_callable(self) -> None:
        mod = _load_migration("0016_disable_s2_news_sentiment.py")
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)


# ---------------------------------------------------------------------------
# Migration 0017 — top-100 insider_transactions + market_cap
# ---------------------------------------------------------------------------


class TestMigration0017:
    """Revision chain + ID uniqueness for the top-100 insider/market-cap migration."""

    def test_revision_is_0017(self) -> None:
        mod = _load_migration("0017_top100_insider_market_cap.py")
        assert mod.revision == "0017"

    def test_down_revision_is_0016(self) -> None:
        mod = _load_migration("0017_top100_insider_market_cap.py")
        assert mod.down_revision == "0016"

    def test_top100_symbols_has_exactly_100_entries(self) -> None:
        mod = _load_migration("0017_top100_insider_market_cap.py")
        assert len(mod._TOP100_SYMBOLS) == 100

    def test_top100_symbols_has_no_duplicates(self) -> None:
        mod = _load_migration("0017_top100_insider_market_cap.py")
        symbols = mod._TOP100_SYMBOLS
        assert len(symbols) == len(set(symbols)), f"Duplicate symbols: {[s for s in symbols if symbols.count(s) > 1]}"

    def test_insider_ids_are_unique(self) -> None:
        mod = _load_migration("0017_top100_insider_market_cap.py")
        ids = mod._all_insider_ids()
        assert len(ids) == len(set(ids)), "Duplicate insider_transaction policy IDs"

    def test_market_cap_ids_are_unique(self) -> None:
        mod = _load_migration("0017_top100_insider_market_cap.py")
        ids = mod._all_market_cap_ids()
        assert len(ids) == len(set(ids)), "Duplicate market_cap policy IDs"

    def test_no_id_overlap_between_insider_and_market_cap(self) -> None:
        mod = _load_migration("0017_top100_insider_market_cap.py")
        insider_ids = set(mod._all_insider_ids())
        market_cap_ids = set(mod._all_market_cap_ids())
        assert not insider_ids & market_cap_ids, "ID collision between insider_transactions and market_cap policies"

    def test_total_policy_count(self) -> None:
        """Each of the 100 symbols gets exactly 2 policies (insider + market_cap)."""
        mod = _load_migration("0017_top100_insider_market_cap.py")
        all_ids = mod._all_insider_ids() + mod._all_market_cap_ids()
        assert len(all_ids) == 200

    def test_seed_strings_differ_between_datasets(self) -> None:
        """Insider and market_cap seeds for the same symbol must produce different IDs."""
        mod = _load_migration("0017_top100_insider_market_cap.py")
        sym = "AAPL"
        insider_id = mod._ulid_from_seed(f"eodhd:insider_transactions:{sym}:US:::")
        market_cap_id = mod._ulid_from_seed(f"eodhd:market_cap:{sym}:US:::")
        assert insider_id != market_cap_id


# ---------------------------------------------------------------------------
# Migration 0020 — disable weekly/monthly OHLCV polling (now DERIVED)
# ---------------------------------------------------------------------------


class _CapturingBind:
    """Mock SQLAlchemy bind that records the SQL text passed to execute()."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, clause: object) -> None:
        # ``clause`` is a sqlalchemy.text() construct; str() yields the SQL.
        self.statements.append(str(clause))


class TestMigration0020:
    """Revision chain + SQL semantics for the weekly/monthly polling-disable migration."""

    _FILE = "0020_disable_weekly_monthly_ohlcv_polling.py"

    def test_revision_is_0020(self) -> None:
        mod = _load_migration(self._FILE)
        assert mod.revision == "0020"

    def test_down_revision_is_0019(self) -> None:
        mod = _load_migration(self._FILE)
        assert mod.down_revision == "0019"

    def test_upgrade_and_downgrade_are_callable(self) -> None:
        mod = _load_migration(self._FILE)
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)

    def _run(self, fn_name: str) -> list[str]:
        """Execute upgrade/downgrade against a capturing bind, return SQL statements."""
        mod = _load_migration(self._FILE)
        bind = _CapturingBind()
        mod.op.get_bind = lambda: bind  # type: ignore[attr-defined]
        getattr(mod, fn_name)()
        return bind.statements

    def test_upgrade_disables_only_weekly_and_monthly_ohlcv(self) -> None:
        stmts = self._run("upgrade")
        assert len(stmts) == 1
        sql = stmts[0]
        # Disables (enabled = false) the right rows …
        assert "enabled = false" in sql
        assert "dataset_type = 'ohlcv'" in sql
        assert "'1w'" in sql and "'1mo'" in sql
        # … and ONLY targets currently-enabled rows (idempotent re-run = no-op).
        assert "enabled = true" in sql
        # Must NOT touch daily or intraday ingestion.
        assert "'1d'" not in sql
        assert "'1m'" not in sql

    def test_downgrade_re_enables_weekly_and_monthly_ohlcv(self) -> None:
        stmts = self._run("downgrade")
        assert len(stmts) == 1
        sql = stmts[0]
        assert "enabled = true" in sql
        assert "dataset_type = 'ohlcv'" in sql
        assert "'1w'" in sql and "'1mo'" in sql
        assert "enabled = false" in sql  # only re-enable rows we disabled

    def test_idempotent_guard_in_where_clause(self) -> None:
        """Upgrade WHERE includes ``enabled = true`` so a re-run matches nothing."""
        sql = self._run("upgrade")[0].lower()
        assert "where" in sql and "enabled = true" in sql


# ---------------------------------------------------------------------------
# Migration 0022 — seed Tier-1-US tickerless-company polling policies
# (derived-bar-aware: 1m + 1d + fundamentals only; NO 1w/1mo)
# ---------------------------------------------------------------------------


class _RecordingBind:
    """Mock SQLAlchemy bind that records (statement, params) and answers EXISTS.

    ``execute`` returns a result whose ``.first()`` is ``None`` (no existing row)
    so every planned insert proceeds — modelling a clean DB.  All bound params are
    captured so the test can assert the exact set of rows the migration inserts.
    """

    class _Result:
        def __init__(self, first_value: object) -> None:
            self._first = first_value

        def first(self) -> object:
            return self._first

    def __init__(self, *, exists: bool = False) -> None:
        self._exists = exists
        self.inserts: list[dict] = []
        self.exists_calls: list[dict] = []
        self.deletes: list[dict] = []

    def execute(self, clause: object, params: dict | None = None) -> _RecordingBind._Result:
        sql = str(clause).strip().upper()
        if sql.startswith("SELECT"):
            self.exists_calls.append(params or {})
            # Return a row iff we are configured to claim everything exists.
            return self._Result(1 if self._exists else None)
        if sql.startswith("INSERT"):
            self.inserts.append(params or {})
            return self._Result(None)
        if sql.startswith("DELETE"):
            self.deletes.append(params or {})
            return self._Result(None)
        return self._Result(None)


class TestMigration0022:
    """Revision chain + policy-set semantics for the Tier-1-US seed migration."""

    _FILE = "0022_seed_tier1_us_polling_policies.py"

    def test_revision_is_0022(self) -> None:
        mod = _load_migration(self._FILE)
        assert mod.revision == "0022"

    def test_down_revision_is_0021(self) -> None:
        mod = _load_migration(self._FILE)
        assert mod.down_revision == "0021"

    def test_upgrade_and_downgrade_are_callable(self) -> None:
        mod = _load_migration(self._FILE)
        assert callable(mod.upgrade)
        assert callable(mod.downgrade)

    def test_exactly_three_policy_specs(self) -> None:
        """Each symbol gets exactly 3 policies: alpaca 1m + eodhd 1d + eodhd fundamentals."""
        mod = _load_migration(self._FILE)
        assert len(mod._POLICY_SPECS) == 3

    def test_policy_specs_are_the_expected_set(self) -> None:
        """The spec set is precisely {alpaca:ohlcv:1m, eodhd:ohlcv:1d, eodhd:fundamentals}."""
        mod = _load_migration(self._FILE)
        # (provider, dataset_type, variant, timeframe) identity of each spec.
        ids = {(p, dt, v, tf) for p, dt, v, tf, *_ in mod._POLICY_SPECS}
        assert ids == {
            ("alpaca", "ohlcv", None, "1m"),
            ("eodhd", "ohlcv", None, "1d"),
            ("eodhd", "fundamentals", "General", None),
        }

    def test_no_weekly_or_monthly_specs(self) -> None:
        """REGRESSION: derived bars — no 1w/1mo OHLCV rows may be seeded (cf. migration 0020)."""
        mod = _load_migration(self._FILE)
        timeframes = {tf for *_, tf, _b, _m, _j, _p in mod._POLICY_SPECS}  # type: ignore[misc]
        assert "1w" not in timeframes
        assert "1mo" not in timeframes

    def test_planned_rows_have_no_weekly_or_monthly(self) -> None:
        """The expanded row set must contain zero 1w/1mo rows for any symbol."""
        mod = _load_migration(self._FILE)
        rows = mod._planned_rows()
        assert all(r["timeframe"] not in ("1w", "1mo") for r in rows)

    def test_planned_row_count_is_symbols_times_three(self) -> None:
        mod = _load_migration(self._FILE)
        rows = mod._planned_rows()
        assert len(rows) == len(mod._TIER1_US_CANDIDATES) * 3

    def test_alpaca_tracks_candidate_tier_eodhd_is_tier_2(self) -> None:
        mod = _load_migration(self._FILE)
        rows = mod._planned_rows()
        for r in rows:
            if r["provider"] == "alpaca":
                assert r["tier"] == 1  # all candidates are tier-1
            else:
                assert r["tier"] == 2

    def _run(self, fn_name: str, *, exists: bool) -> _RecordingBind:
        mod = _load_migration(self._FILE)
        bind = _RecordingBind(exists=exists)
        mod.op.get_bind = lambda: bind  # type: ignore[attr-defined]
        getattr(mod, fn_name)()
        return bind

    def test_upgrade_seeds_all_rows_on_clean_db(self) -> None:
        """On an empty DB (no row exists), upgrade inserts exactly one row per planned row."""
        mod = _load_migration(self._FILE)
        expected = len(mod._planned_rows())
        bind = self._run("upgrade", exists=False)
        assert len(bind.inserts) == expected
        # Every insert carries a fresh 26-char ULID id.
        ids = [ins["id"] for ins in bind.inserts]
        assert all(len(i) == 26 for i in ids)
        assert len(ids) == len(set(ids)), "duplicate policy IDs generated"

    def test_upgrade_is_noop_when_all_rows_exist(self) -> None:
        """Idempotent re-run: when every 6-tuple already exists, upgrade inserts nothing."""
        bind = self._run("upgrade", exists=True)
        assert len(bind.inserts) == 0

    def test_upgrade_inserts_no_weekly_or_monthly_rows(self) -> None:
        """REGRESSION: not a single inserted row may carry a 1w/1mo timeframe."""
        bind = self._run("upgrade", exists=False)
        assert all(ins["timeframe"] not in ("1w", "1mo") for ins in bind.inserts)

    def test_downgrade_deletes_one_per_planned_row(self) -> None:
        mod = _load_migration(self._FILE)
        bind = self._run("downgrade", exists=False)
        assert len(bind.deletes) == len(mod._planned_rows())
