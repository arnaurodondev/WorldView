"""Fundamentals ORM models — one table per FundamentalsSection."""

from market_data.infrastructure.db.models.fundamentals.analyst_consensus import AnalystConsensusModel
from market_data.infrastructure.db.models.fundamentals.balance_sheets import BalanceSheetModel
from market_data.infrastructure.db.models.fundamentals.cash_flow_statements import CashFlowStatementModel
from market_data.infrastructure.db.models.fundamentals.company_profiles import CompanyProfileModel
from market_data.infrastructure.db.models.fundamentals.dividend_history import DividendHistoryModel
from market_data.infrastructure.db.models.fundamentals.earnings_annual_trends import EarningsAnnualTrendModel
from market_data.infrastructure.db.models.fundamentals.earnings_history import EarningsHistoryModel
from market_data.infrastructure.db.models.fundamentals.earnings_trends import EarningsTrendModel
from market_data.infrastructure.db.models.fundamentals.fund_holders import FundHoldersModel
from market_data.infrastructure.db.models.fundamentals.highlights import HighlightsModel
from market_data.infrastructure.db.models.fundamentals.income_statements import IncomeStatementModel
from market_data.infrastructure.db.models.fundamentals.insider_transactions_snapshot import (
    InsiderTransactionsSnapshotModel,
)
from market_data.infrastructure.db.models.fundamentals.institutional_holders import InstitutionalHoldersModel
from market_data.infrastructure.db.models.fundamentals.outstanding_shares import OutstandingSharesModel
from market_data.infrastructure.db.models.fundamentals.share_statistics import ShareStatisticsModel
from market_data.infrastructure.db.models.fundamentals.splits_dividends import SplitsDividendsModel
from market_data.infrastructure.db.models.fundamentals.technicals_snapshots import TechnicalsSnapshotModel
from market_data.infrastructure.db.models.fundamentals.valuation_ratios import ValuationRatiosModel

__all__ = [
    "AnalystConsensusModel",
    "BalanceSheetModel",
    "CashFlowStatementModel",
    "CompanyProfileModel",
    "DividendHistoryModel",
    "EarningsAnnualTrendModel",
    "EarningsHistoryModel",
    "EarningsTrendModel",
    "FundHoldersModel",
    "HighlightsModel",
    "IncomeStatementModel",
    "InsiderTransactionsSnapshotModel",
    "InstitutionalHoldersModel",
    "OutstandingSharesModel",
    "ShareStatisticsModel",
    "SplitsDividendsModel",
    "TechnicalsSnapshotModel",
    "ValuationRatiosModel",
]
