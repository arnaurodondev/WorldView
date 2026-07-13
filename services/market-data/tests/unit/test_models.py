"""Unit tests for SQLAlchemy ORM models (MD-014).

Tests verify column definitions, constraints, and metadata completeness
without requiring a live database connection.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from market_data.infrastructure.db.base import Base
from market_data.infrastructure.db.models import (
    AnalystConsensusModel,
    BalanceSheetModel,
    CashFlowStatementModel,
    CompanyProfileModel,
    DividendHistoryModel,
    EarningsAnnualTrendModel,
    EarningsHistoryModel,
    EarningsTrendModel,
    FailedTaskModel,
    FundHoldersModel,
    HighlightsModel,
    IncomeStatementModel,
    IngestionEventModel,
    InsiderTransactionsSnapshotModel,
    InstitutionalHoldersModel,
    InstrumentModel,
    OHLCVBarModel,
    OutboxEventModel,
    OutstandingSharesModel,
    PredictionEventModel,
    PredictionMarketModel,
    PredictionMarketOIModel,
    PredictionMarketPriceModel,
    PredictionMarketSnapshotModel,
    PredictionMarketTradeModel,
    QuoteModel,
    SecurityModel,
    ShareStatisticsModel,
    SplitsDividendsModel,
    TechnicalsSnapshotModel,
    ValuationRatiosModel,
)
from sqlalchemy import inspect

pytestmark = pytest.mark.unit


def _columns(model_class) -> set[str]:
    """Return set of column names for the given mapped class."""
    mapper = inspect(model_class)
    return {col.key for col in mapper.column_attrs}


def _table(model_class):
    """Return the SQLAlchemy Table object for the mapped class."""
    return model_class.__table__


class TestSecurityModel:
    def test_security_model_columns(self):
        cols = _columns(SecurityModel)
        assert "id" in cols
        assert "figi" in cols
        assert "isin" in cols
        assert "name" in cols
        assert "sector" in cols
        assert "industry" in cols
        assert "country" in cols
        assert "currency" in cols
        assert "created_at" in cols
        assert "updated_at" in cols

    def test_security_figi_unique(self):
        table = _table(SecurityModel)
        # figi has unique=True on the column itself
        figi_col = table.c["figi"]
        assert figi_col.unique is True

    def test_security_tablename(self):
        assert SecurityModel.__tablename__ == "securities"


class TestInstrumentModel:
    def test_instrument_model_unique_constraint(self):
        """``(symbol, exchange)`` must have a named UNIQUE constraint."""
        table = _table(InstrumentModel)
        constraint_names = {c.name for c in table.constraints}
        assert "uq_instruments_symbol_exchange" in constraint_names

    def test_instrument_has_flags_columns(self):
        cols = _columns(InstrumentModel)
        assert "has_ohlcv" in cols
        assert "has_quotes" in cols
        assert "has_fundamentals" in cols

    def test_instrument_fk_to_securities(self):
        table = _table(InstrumentModel)
        fk_targets = {fk.target_fullname for col in table.c for fk in col.foreign_keys}
        assert "securities.id" in fk_targets


class TestOHLCVBarModel:
    def test_ohlcv_model_composite_pk(self):
        """Primary key must be (instrument_id, timeframe, bar_date)."""
        table = _table(OHLCVBarModel)
        pk_cols = {col.name for col in table.primary_key}
        assert pk_cols == {"instrument_id", "timeframe", "bar_date"}

    def test_ohlcv_has_provider_priority(self):
        cols = _columns(OHLCVBarModel)
        assert "provider_priority" in cols

    def test_ohlcv_price_columns_present(self):
        cols = _columns(OHLCVBarModel)
        for price_col in ("open", "high", "low", "close", "adjusted_close", "volume"):
            assert price_col in cols, f"missing column: {price_col}"

    def test_ohlcv_has_is_partial(self):
        """PLAN-0040 B-1: ohlcv_bars must have an is_partial boolean column."""
        cols = _columns(OHLCVBarModel)
        assert "is_partial" in cols

    def test_ohlcv_has_is_derived(self):
        """PLAN-0036: ohlcv_bars must have an is_derived boolean column."""
        cols = _columns(OHLCVBarModel)
        assert "is_derived" in cols

    def test_ohlcv_complete_column_set(self):
        """DDL alignment: all expected ohlcv_bars columns must exist.

        If a migration adds or removes a column, update this set to keep
        the test in sync with the ORM model.
        """
        expected = {
            "instrument_id",
            "timeframe",
            "bar_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "adjusted_close",
            "source",
            "provider_priority",
            "is_derived",
            "is_partial",
        }
        actual = _columns(OHLCVBarModel)
        missing = expected - actual
        extra = actual - expected
        assert not missing, f"Missing columns: {missing}"
        assert not extra, f"Unexpected columns: {extra}"


class TestQuoteModel:
    def test_quote_model_pk(self):
        """Primary key must be ``instrument_id`` (latest quote per instrument)."""
        table = _table(QuoteModel)
        pk_cols = {col.name for col in table.primary_key}
        assert pk_cols == {"instrument_id"}

    def test_quote_has_bid_ask_last(self):
        cols = _columns(QuoteModel)
        assert "bid" in cols
        assert "ask" in cols
        assert "last" in cols
        assert "volume" in cols
        assert "timestamp" in cols


class TestFundamentalsModels:
    # Period-based models (quarterly/yearly/snapshot with period_type + period_end_date + data)
    PERIOD_MODELS: ClassVar[list] = [
        IncomeStatementModel,
        BalanceSheetModel,
        CashFlowStatementModel,
        HighlightsModel,
        ValuationRatiosModel,
        TechnicalsSnapshotModel,
        ShareStatisticsModel,
        SplitsDividendsModel,
        AnalystConsensusModel,
        EarningsHistoryModel,
        EarningsTrendModel,
        EarningsAnnualTrendModel,
        DividendHistoryModel,
        OutstandingSharesModel,
    ]

    # Non-period models (dedicated column schemas, no period_type/period_end_date)
    NON_PERIOD_MODELS: ClassVar[list] = [
        CompanyProfileModel,
        InstitutionalHoldersModel,
        FundHoldersModel,
        InsiderTransactionsSnapshotModel,
    ]

    @property
    def all_models(self) -> list:
        return self.PERIOD_MODELS + self.NON_PERIOD_MODELS

    def test_fundamentals_model_fk_constraints(self):
        """All fundamentals models must have instrument_id FK to instruments."""
        for model in self.all_models:
            table = _table(model)
            fk_targets = {fk.target_fullname for col in table.c for fk in col.foreign_keys}
            assert "instruments.id" in fk_targets, f"{model.__tablename__} missing FK to instruments.id"

    def test_period_models_have_period_columns(self):
        for model in self.PERIOD_MODELS:
            cols = _columns(model)
            assert "period_type" in cols, f"{model.__tablename__} missing period_type"
            assert "period_end_date" in cols, f"{model.__tablename__} missing period_end_date"

    def test_period_models_have_data_column(self):
        for model in self.PERIOD_MODELS:
            cols = _columns(model)
            assert "data" in cols, f"{model.__tablename__} missing data column"

    def test_non_period_models_have_data_column(self):
        for model in self.NON_PERIOD_MODELS:
            cols = _columns(model)
            assert "data" in cols, f"{model.__tablename__} missing data column"

    def test_eighteen_fundamentals_models(self):
        assert len(self.all_models) == 18


class TestInfrastructureModels:
    def test_infrastructure_models(self):
        """ingestion_events, failed_tasks, outbox_events must all be defined."""
        assert IngestionEventModel.__tablename__ == "ingestion_events"
        assert FailedTaskModel.__tablename__ == "failed_tasks"
        assert OutboxEventModel.__tablename__ == "outbox_events"

    def test_ingestion_event_unique_event_id(self):
        """event_id must have UNIQUE constraint (not PK)."""
        table = _table(IngestionEventModel)
        constraint_names = {c.name for c in table.constraints}
        assert "uq_ingestion_events_event_id" in constraint_names
        # event_id must NOT be the primary key
        pk_cols = {col.name for col in table.primary_key}
        assert "event_id" not in pk_cols
        assert "id" in pk_cols

    def test_failed_task_has_new_columns(self):
        """failed_tasks must use new column structure (fixed from legacy)."""
        cols = _columns(FailedTaskModel)
        assert "task_type" in cols
        assert "payload" in cols
        assert "attempts" in cols
        assert "max_attempts" in cols
        assert "next_attempt_at" in cols
        assert "last_error" in cols
        assert "status" in cols
        # Legacy columns must NOT exist
        assert "event_id" not in cols
        assert "attempt_count" not in cols
        assert "next_retry_at" not in cols

    def test_outbox_event_has_new_columns(self):
        """outbox_events must use new column structure (fixed from legacy)."""
        cols = _columns(OutboxEventModel)
        assert "event_type" in cols
        assert "topic" in cols
        assert "payload" in cols
        assert "status" in cols
        assert "claimed_by" in cols
        assert "claimed_at" in cols
        assert "lease_expires_at" in cols
        assert "attempts" in cols
        assert "dispatched_at" in cols
        # Legacy column name must NOT exist
        assert "leased_until" not in cols

    def test_outbox_event_has_partition_key(self):
        """PLAN-0057-followup Wave B (F-DATA-06): outbox_events must expose
        a nullable ``partition_key`` column so the dispatcher can forward
        the optional Kafka partition key to ``producer.produce(key=...)``.

        The column is nullable so events with no ordering invariant (legacy
        rows) continue to dispatch via Kafka's round-robin partitioner.
        """
        table = _table(OutboxEventModel)
        cols = _columns(OutboxEventModel)
        assert "partition_key" in cols
        # Must be nullable — NULL = round-robin (legacy behaviour).
        partition_col = table.c["partition_key"]
        assert partition_col.nullable is True


class TestPredictionMarketModels:
    """DDL alignment tests for prediction market tables (PRD-0019, BP-019)."""

    def test_prediction_market_tablename(self) -> None:
        assert PredictionMarketModel.__tablename__ == "prediction_markets"

    def test_prediction_market_columns(self) -> None:
        cols = _columns(PredictionMarketModel)
        assert "id" in cols
        assert "market_id" in cols
        assert "source" in cols
        assert "question" in cols
        assert "description" in cols
        assert "outcomes" in cols
        assert "close_time" in cols
        assert "resolution_status" in cols
        assert "resolved_answer" in cols
        assert "created_at" in cols
        assert "updated_at" in cols

    def test_prediction_market_unique_market_id(self) -> None:
        table = _table(PredictionMarketModel)
        constraint_names = {c.name for c in table.constraints}
        assert "uq_prediction_markets_market_id" in constraint_names

    def test_prediction_market_snapshot_tablename(self) -> None:
        assert PredictionMarketSnapshotModel.__tablename__ == "prediction_market_snapshots"

    def test_prediction_market_snapshot_columns(self) -> None:
        cols = _columns(PredictionMarketSnapshotModel)
        assert "id" in cols
        assert "market_id" in cols
        assert "snapshot_at" in cols
        assert "outcomes_prices" in cols
        assert "volume_24h" in cols
        assert "liquidity" in cols
        assert "source_event_id" in cols

    def test_prediction_market_snapshot_unique_market_snapshot(self) -> None:
        table = _table(PredictionMarketSnapshotModel)
        constraint_names = {c.name for c in table.constraints}
        assert "uq_pms_market_snapshot" in constraint_names

    def test_prediction_market_has_event_id(self) -> None:
        """PLAN-0056 A1 / migration 043: prediction_markets gains event_id."""
        cols = _columns(PredictionMarketModel)
        assert "event_id" in cols


class TestPredictionDeeperStreamModels:
    """DDL alignment tests for PLAN-0056 A1 deeper-stream tables (PRD-0033 §6.1)."""

    def test_prices_tablename_and_columns(self) -> None:
        assert PredictionMarketPriceModel.__tablename__ == "prediction_market_prices"
        cols = _columns(PredictionMarketPriceModel)
        assert cols == {
            "id",
            "market_id",
            "token_id",
            "outcome_name",
            "interval",
            "window_start_ts",
            "price",
            "source",
            "is_backfill",
        }

    def test_prices_composite_pk_includes_partition_column(self) -> None:
        """TimescaleDB requires the time column in the PK — PK is (id, window_start_ts)."""
        table = _table(PredictionMarketPriceModel)
        pk_cols = {col.name for col in table.primary_key}
        assert pk_cols == {"id", "window_start_ts"}

    def test_prices_unique_constraint(self) -> None:
        table = _table(PredictionMarketPriceModel)
        constraint_names = {c.name for c in table.constraints}
        assert "uq_pmp_market_token_interval_window" in constraint_names

    def test_trades_tablename_and_columns(self) -> None:
        assert PredictionMarketTradeModel.__tablename__ == "prediction_market_trades"
        cols = _columns(PredictionMarketTradeModel)
        assert cols == {"id", "market_id", "trade_id", "token_id", "price", "size_usd", "side", "ts"}

    def test_trades_composite_pk_includes_partition_column(self) -> None:
        table = _table(PredictionMarketTradeModel)
        pk_cols = {col.name for col in table.primary_key}
        assert pk_cols == {"id", "ts"}

    def test_trades_unique_market_trade(self) -> None:
        table = _table(PredictionMarketTradeModel)
        constraint_names = {c.name for c in table.constraints}
        assert "uq_pmt_market_trade" in constraint_names

    def test_oi_tablename_and_pk(self) -> None:
        assert PredictionMarketOIModel.__tablename__ == "prediction_market_oi"
        table = _table(PredictionMarketOIModel)
        pk_cols = {col.name for col in table.primary_key}
        assert pk_cols == {"market_id", "snapshot_date"}
        cols = _columns(PredictionMarketOIModel)
        assert {"total_oi_usd", "total_volume_24h_usd", "created_at", "updated_at"} <= cols

    def test_events_tablename_and_unique_event_id(self) -> None:
        assert PredictionEventModel.__tablename__ == "prediction_events"
        table = _table(PredictionEventModel)
        constraint_names = {c.name for c in table.constraints}
        assert "uq_prediction_events_event_id" in constraint_names
        cols = _columns(PredictionEventModel)
        assert {"id", "event_id", "name", "category", "start_date", "end_date", "market_count"} <= cols


class TestBaseMetadataCompleteness:
    EXPECTED_TABLES: ClassVar[set[str]] = {
        "securities",
        "instruments",
        "ohlcv_bars",
        "quotes",
        "income_statements",
        "balance_sheets",
        "cash_flow_statements",
        "highlights",
        "valuation_ratios",
        "technicals_snapshots",
        "share_statistics",
        "splits_dividends",
        "analyst_consensus",
        "earnings_history",
        "earnings_trends",
        "earnings_annual_trends",
        "dividend_history",
        "outstanding_shares",
        "company_profiles",
        "institutional_holders",
        "fund_holders",
        "insider_transactions_snapshot",
        "ingestion_events",
        "failed_tasks",
        "outbox_events",
        # PRD-0019: prediction markets
        "prediction_markets",
        "prediction_market_snapshots",
        # PLAN-0056 A1 (PRD-0033): prediction deeper streams
        "prediction_market_prices",
        "prediction_market_trades",
        "prediction_market_oi",
        "prediction_events",
    }

    def test_all_tables_in_metadata(self):
        """All model tables must be registered in Base.metadata."""
        registered = set(Base.metadata.tables.keys())
        missing = self.EXPECTED_TABLES - registered
        assert not missing, f"Tables missing from Base.metadata: {missing}"
