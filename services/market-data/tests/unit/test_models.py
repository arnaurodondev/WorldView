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
    }

    def test_all_tables_in_metadata(self):
        """All model tables must be registered in Base.metadata."""
        registered = set(Base.metadata.tables.keys())
        missing = self.EXPECTED_TABLES - registered
        assert not missing, f"Tables missing from Base.metadata: {missing}"
