"""ORM models package — imports all models to populate ``Base.metadata``.

Importing this module ensures every table is registered with the SQLAlchemy
declarative base, making ``Base.metadata.create_all()`` and Alembic
autogenerate work correctly.
"""

from market_data.infrastructure.db.models.earnings_calendar import EarningsCalendarModel
from market_data.infrastructure.db.models.fundamentals import (
    AnalystConsensusModel,
    BalanceSheetModel,
    CashFlowStatementModel,
    CompanyProfileModel,
    DividendHistoryModel,
    EarningsAnnualTrendModel,
    EarningsHistoryModel,
    EarningsTrendModel,
    FundHoldersModel,
    HighlightsModel,
    IncomeStatementModel,
    InsiderTransactionsSnapshotModel,
    InstitutionalHoldersModel,
    OutstandingSharesModel,
    ShareStatisticsModel,
    SplitsDividendsModel,
    TechnicalsSnapshotModel,
    ValuationRatiosModel,
)
from market_data.infrastructure.db.models.fundamentals_snapshot import InstrumentFundamentalsSnapshotModel
from market_data.infrastructure.db.models.infrastructure import (
    FailedTaskModel,
    IngestionEventModel,
    OutboxEventModel,
)
from market_data.infrastructure.db.models.insider_transactions import InsiderTransactionModel
from market_data.infrastructure.db.models.instruments import InstrumentModel
from market_data.infrastructure.db.models.ohlcv import OHLCVBarModel
from market_data.infrastructure.db.models.prediction_markets import (
    PredictionMarketModel,
    PredictionMarketSnapshotModel,
)
from market_data.infrastructure.db.models.quotes import QuoteModel
from market_data.infrastructure.db.models.securities import SecurityModel

__all__ = [
    "AnalystConsensusModel",
    "BalanceSheetModel",
    "CashFlowStatementModel",
    "CompanyProfileModel",
    "DividendHistoryModel",
    "EarningsAnnualTrendModel",
    "EarningsCalendarModel",
    "EarningsHistoryModel",
    "EarningsTrendModel",
    "FailedTaskModel",
    "FundHoldersModel",
    "HighlightsModel",
    "IncomeStatementModel",
    "IngestionEventModel",
    "InsiderTransactionModel",
    "InsiderTransactionsSnapshotModel",
    "InstitutionalHoldersModel",
    "InstrumentFundamentalsSnapshotModel",
    "InstrumentModel",
    "OHLCVBarModel",
    "OutboxEventModel",
    "OutstandingSharesModel",
    "PredictionMarketModel",
    "PredictionMarketSnapshotModel",
    "QuoteModel",
    "SecurityModel",
    "ShareStatisticsModel",
    "SplitsDividendsModel",
    "TechnicalsSnapshotModel",
    "ValuationRatiosModel",
]
