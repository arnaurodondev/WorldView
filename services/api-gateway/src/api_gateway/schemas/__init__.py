"""S9 Pydantic response schemas — source of OpenAPI component schemas.

WHY: Adding response_model= to proxy routes generates typed OpenAPI spec
components, enabling pnpm generate-types to produce correct TypeScript
definitions in types/generated/api.ts.

All schemas use ConfigDict(extra="allow") so future upstream fields don't
cause validation errors in production.
"""

from api_gateway.schemas.alerts import AlertResponse
from api_gateway.schemas.common import Meta
from api_gateway.schemas.dashboard import DashboardSnapshotResponse
from api_gateway.schemas.fundamentals import (
    EarningsCalendarResponse,
    EarningsEvent,
    FundamentalsRecord,
    FundamentalsResponse,
)
from api_gateway.schemas.instruments import (
    InstrumentSearchResult,
    OHLCVBar,
    OHLCVResponse,
    QuoteResponse,
)
from api_gateway.schemas.news import NewsArticle, NewsTopResponse
from api_gateway.schemas.portfolios import PortfolioBundleResponse, PortfolioResponse
from api_gateway.schemas.prediction_markets import (
    PredictionMarket,
    PredictionMarketsListResponse,
)
from api_gateway.schemas.screener import ScreenerResponse, ScreenerResultItem
from api_gateway.schemas.watchlists import WatchlistResponse

__all__ = [
    "AlertResponse",
    "DashboardSnapshotResponse",
    "EarningsCalendarResponse",
    "EarningsEvent",
    "FundamentalsRecord",
    "FundamentalsResponse",
    "InstrumentSearchResult",
    "Meta",
    "NewsArticle",
    "NewsTopResponse",
    "OHLCVBar",
    "OHLCVResponse",
    "PortfolioBundleResponse",
    "PortfolioResponse",
    "PredictionMarket",
    "PredictionMarketsListResponse",
    "QuoteResponse",
    "ScreenerResponse",
    "ScreenerResultItem",
    "WatchlistResponse",
]
