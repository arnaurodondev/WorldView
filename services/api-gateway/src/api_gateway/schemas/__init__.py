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
from api_gateway.schemas.dashboard_bundle import DashboardBundleResponse
from api_gateway.schemas.entity_chat import EntityContextChatRequest
from api_gateway.schemas.financials_bundle import FinancialsBundleResponse
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
from api_gateway.schemas.intelligence import (
    ConfidenceBreakdownPublic,
    ConfidenceTrendPoint,
    EntityIntelligencePublic,
    EntitySentimentTimeseriesResponse,
    NarrativeVersionPublic,
    SentimentDataPoint,
    SourceSharePublic,
)
from api_gateway.schemas.intelligence_bundle import EntityIntelligenceBundleResponse
from api_gateway.schemas.market import YieldCurveResponse, YieldPoint
from api_gateway.schemas.narratives import NarrativeListResponse, NarrativeTriggerResponse
from api_gateway.schemas.news import ArticleImpactHistoryResponse, ImpactWindow, NewsArticle, NewsTopResponse
from api_gateway.schemas.paths import EntityPathsResponse, PathEdgePublic, PathInsightPublic, PathNodePublic
from api_gateway.schemas.portfolios import (
    PortfolioBundleResponse,
    PortfolioResponse,
    PortfolioSectorAttributionResponse,
    SectorBucket,
)
from api_gateway.schemas.prediction_markets import (
    PredictionMarket,
    PredictionMarketsListResponse,
)
from api_gateway.schemas.screener import NLScreenerRequest, NLScreenerResponse, ScreenerResponse, ScreenerResultItem
from api_gateway.schemas.watchlists import WatchlistResponse

__all__ = [
    "AlertResponse",
    "ArticleImpactHistoryResponse",
    "ConfidenceBreakdownPublic",
    "ConfidenceTrendPoint",
    "DashboardBundleResponse",
    "DashboardSnapshotResponse",
    "EarningsCalendarResponse",
    "EarningsEvent",
    "EntityContextChatRequest",
    "EntityIntelligenceBundleResponse",
    "EntityIntelligencePublic",
    "EntityPathsResponse",
    "EntitySentimentTimeseriesResponse",
    "FinancialsBundleResponse",
    "FundamentalsRecord",
    "FundamentalsResponse",
    "ImpactWindow",
    "InstrumentSearchResult",
    "Meta",
    "NLScreenerRequest",
    "NLScreenerResponse",
    "NarrativeListResponse",
    "NarrativeTriggerResponse",
    "NarrativeVersionPublic",
    "NewsArticle",
    "NewsTopResponse",
    "OHLCVBar",
    "OHLCVResponse",
    "PathEdgePublic",
    "PathInsightPublic",
    "PathNodePublic",
    "PortfolioBundleResponse",
    "PortfolioResponse",
    "PortfolioSectorAttributionResponse",
    "PredictionMarket",
    "PredictionMarketsListResponse",
    "QuoteResponse",
    "ScreenerResponse",
    "ScreenerResultItem",
    "SectorBucket",
    "SentimentDataPoint",
    "SourceSharePublic",
    "WatchlistResponse",
    "YieldCurveResponse",
    "YieldPoint",
]
