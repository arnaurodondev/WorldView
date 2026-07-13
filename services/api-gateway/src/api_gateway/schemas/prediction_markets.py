"""Prediction markets response schemas.

WHY: These Pydantic models mirror the S3 PredictionMarket schemas in
services/market-data/src/market_data/api/schemas/prediction_markets.py.

WHY separate from the TypeScript PredictionMarket interface shape:
The TS interface uses field names like `title`, `yes_probability`, `volume_usd`
that map to the *legacy* S3 field names. S3's actual API returns
`question`, `outcomes`, `volume_24h`. The gateway's proxy routes return
the S3 response verbatim (no field transformation), so these schemas
match what the wire actually carries.

The TypeScript types/api.ts comment acknowledges S9 proxy routes use generic
`Response` objects — these schemas add typed OpenAPI component schemas for
routes that the frontend does consume, improving type-generator output.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PredictionMarketOutcome(BaseModel):
    """Outcome price for a single market outcome (YES/NO or multi-choice).

    Mirrors S3 OutcomePriceResponse.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    token_id: str | None = None
    price: float | None = None  # Implied probability in [0, 1]


class PredictionMarket(BaseModel):
    """A single prediction market summary row.

    Mirrors S3 PredictionMarketSummaryResponse (used in the list endpoint).

    WHY outcomes list (not yes_probability/no_probability): S3 stores
    multi-choice market outcomes as a list of {name, token_id, price} entries.
    YES/NO markets have two outcomes; multi-choice can have more.
    Frontend code extracts yes_probability from outcomes[0].price for binary
    markets.

    WHY extra=allow: The detail endpoint (PredictionMarketDetailResponse) is a
    superset of this schema — adding description + created_at. With extra=allow,
    the same Python model covers both list and detail responses without a
    validation error.
    """

    model_config = ConfigDict(extra="allow")

    market_id: str
    question: str | None = None
    outcomes: list[PredictionMarketOutcome] = []
    volume_24h: float | None = None
    close_time: str | None = None  # ISO 8601 datetime
    resolution_status: str | None = None  # "open" | "closed" | "resolved"
    resolved_answer: str | None = None
    updated_at: str | None = None  # ISO 8601 datetime
    market_slug: str | None = None  # Polymarket slug for canonical URL
    category: str | None = None  # e.g. "politics", "crypto"
    # PLAN-0056 Wave E1: S3 now carries CLOB liquidity + open interest on the
    # detail/history snapshots. extra="allow" already lets these flow through
    # verbatim; declaring them explicitly makes the OpenAPI schema advertise them
    # to frontend type-generators (the source of truth for what the wire carries).
    liquidity: float | None = None  # CLOB order-book depth (USD)
    open_interest: float | None = None  # Total outstanding notional (USD)


class PredictionMarketTrade(BaseModel):
    """One executed fill on a market token (PLAN-0056 Wave E1).

    Passthrough mirror of S3 ``PredictionMarketTradeResponse``. ``size_usd`` may
    be null (some feeds omit notional). extra="allow" keeps forward-compat.
    """

    model_config = ConfigDict(extra="allow")

    ts: str | None = None  # ISO 8601 datetime
    price: float | None = None
    size_usd: float | None = None
    side: str | None = None  # free-form: "buy" | "sell"
    token_id: str | None = None


class PredictionEvent(BaseModel):
    """A Polymarket "event" group — a set of related markets (PLAN-0056 Wave E1).

    Passthrough mirror of S3 ``PredictionEventResponse``. extra="allow" so any
    additional S3 field flows through without a gateway schema change.
    """

    model_config = ConfigDict(extra="allow")

    event_id: str
    name: str | None = None
    category: str | None = None
    start_date: str | None = None  # ISO 8601 datetime
    end_date: str | None = None  # ISO 8601 datetime
    market_count: int = 0


class PredictionMarketsListResponse(BaseModel):
    """Paginated list of prediction markets.

    Mirrors S3 PredictionMarketsListResponse (note: S3 uses `items` not `markets`).
    WHY items (not markets): S3's schema uses `items`; the TypeScript
    PredictionMarketsResponse uses `markets`. Until S9 adds a transformation
    layer, the wire carries `items`. Frontend code should read `items`.
    """

    model_config = ConfigDict(extra="allow")

    items: list[PredictionMarket] = []
    total: int = 0
    limit: int = 20
    offset: int = 0
