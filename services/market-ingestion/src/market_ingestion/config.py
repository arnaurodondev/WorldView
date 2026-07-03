"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the market-ingestion service."""

    model_config = SettingsConfigDict(
        env_prefix="MARKET_INGESTION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8002
    debug: bool = False

    # Database
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/ingestion_db")
    database_url_read: str = ""  # Optional read-replica; falls back to database_url if empty

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"

    # Storage
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: SecretStr  # Required — set MARKET_INGESTION_STORAGE_ACCESS_KEY env var
    storage_secret_key: SecretStr  # Required — set MARKET_INGESTION_STORAGE_SECRET_KEY env var
    storage_bucket: str = "market-ingestion"
    bronze_bucket: str = "market-bronze"
    canonical_bucket: str = "market-canonical"

    # Provider base URLs (operational — overridable without image rebuild)
    eodhd_base_url: str = "https://eodhd.com/api"

    # Provider API keys — SecretStr prevents accidental serialisation via
    # repr(), model_dump(), or error tracebacks (F-002 QA finding).
    # N-003: Default "demo" is intentional for local dev and CI testing.
    # The demo key supports EODHD's original 3 endpoints at low concurrency.
    # Tests use the demo key explicitly; set MARKET_INGESTION_EODHD_API_KEY to
    # a real key in production. Startup validator below emits a WARNING if unset.
    eodhd_api_key: SecretStr = SecretStr("demo")
    finnhub_api_key: SecretStr = SecretStr("")
    polygon_api_key: SecretStr = SecretStr("")  # — empty = Polygon disabled
    polygon_base_url: str = "https://api.polygon.io"
    alpha_vantage_api_key: SecretStr = SecretStr("")
    alpaca_api_key: SecretStr = SecretStr("")  # — empty = Alpaca disabled
    alpaca_secret_key: SecretStr = SecretStr("")
    alpaca_base_url: str = "https://data.alpaca.markets"
    alpaca_feed: str = "iex"  # "iex" (free, ~15min delayed) | "sip" (paid, real-time)

    # Routing weights (PRD-0032, ADR-032-02): comma-separated provider:weight pairs.
    # These env vars define priority ordering for each dataset+timeframe slot.
    # No DB table — config-backed only. Force-reload via POST /internal/v1/routing/reload.
    routing_ohlcv_intraday: str = "alpaca:100,polygon:80"  # timeframes: 1m,5m,15m,30m,1h,4h
    # EOD/daily OHLCV: Alpaca is now the primary deep-daily source (free, IEX,
    # ~6y of split-adjusted daily bars), EODHD is failover-only. Yahoo Finance is
    # DROPPED from OHLCV routing (PLAN-0036 final topology) — Alpaca 1Day replaces
    # it as the free deep-daily provider, so every timeframe family has exactly
    # ONE source and there is no cross-source seam. (1w/1mo are derived-on-read
    # in market-data from the polled daily series, never routed here.)
    routing_ohlcv_eod: str = "alpaca:100,eodhd:80"  # timeframes: 1d,1w,1M
    routing_quotes: str = "eodhd:100"
    routing_fundamentals: str = "eodhd:100"
    # Finnhub provides these for free — set to "finnhub:100,eodhd:80" to prefer Finnhub.
    routing_news_sentiment: str = "eodhd:100"
    routing_earnings_calendar: str = "eodhd:100"
    routing_insider_transactions: str = "eodhd:100"

    # Valkey / Redis
    valkey_url: str = "redis://localhost:6379/0"

    # ── EODHD shared quota ────────────────────────────────────────────────────
    # These are FORMAL fields (not just read via getattr) so the env overrides
    # MARKET_INGESTION_EODHD_MONTHLY_QUOTA / _DAILY_QUOTA actually take effect —
    # previously they were silently dropped by ``extra="ignore"``.
    #
    # eodhd_monthly_quota: monthly credit counter cap — REPORTING ONLY (no block).
    # eodhd_daily_quota:   EODHD's REAL per-UTC-day cap — the value that BLOCKS.
    # Verified via GET /api/user (dailyRateLimit=100000). INCIDENT 2026-07-03:
    # the old monthly-only guard tripped a false hard block a few days into every
    # month because normal daily usage blew past a 100k MONTHLY cap. Both values
    # must match content-ingestion's (shared EODHD account key + Valkey counters).
    eodhd_monthly_quota: int = 100_000
    eodhd_daily_quota: int = 100_000

    # Scheduler
    scheduler_tick_interval_seconds: float = 60.0
    scheduler_max_tasks_per_tick: int = 1000

    # Auto-backfill on startup (PLAN-0055 Sub-Plan A).
    # The scheduler process spawns a non-blocking task on startup that enqueues a
    # backfill (now - INITIAL_DAYS, now) for every enabled polling policy whose
    # ``backfill_start_date`` cursor doesn't already cover that horizon.
    # OFF by default in code; gitops env flips it ON in dev + prod.
    auto_backfill_on_startup: bool = False
    # Initial validation horizon. Operators ratchet up gradually (14 → 365 → 3650)
    # without redeploying via MARKET_INGESTION_AUTO_BACKFILL_INITIAL_DAYS.
    # NOTE: plain default rather than ``Field(default=14, ge=1)`` — the older
    # pydantic-settings version that pre-commit pins (~2.1) doesn't surface
    # Field-annotated class attributes to mypy. The runtime guard against
    # zero/negative values lives in ``run_startup_backfill.py``.
    auto_backfill_initial_days: int = 14
    # Hard cap on horizon — runtime clamps INITIAL_DAYS to YEARS * 365.
    auto_backfill_years: int = 10

    # Fundamentals refresh worker (PLAN-0099 W2-T02; default flipped ON 2026-05-28
    # per PLAN-0100 W4-T03). When enabled the worker re-enqueues fundamentals
    # fetches for the configured symbol universe every N hours so freshly-reported
    # quarters (e.g. AMD FY2026 Q1) land in ``intelligence_db`` without waiting
    # for the slow polling policy to come round. See
    # ``infrastructure/workers/fundamentals_refresh_worker.py`` for the loop.
    #
    # WHY DEFAULT ON (2026-05-28): the AMD-Q1-FY2026 freshness diagnostics
    # (``docs/audits/2026-05-28-plan-0100-amd-freshness-diagnostics.md``)
    # confirmed H1 — the worker shipping OFF by default in PLAN-0099 W2-T02
    # caused 4/6 Q4 chat-eval variants to fail because no automated path was
    # keeping AMD's fundamentals on a refresh cadence. Flipping the default to
    # ``True`` aligns the deployed behaviour with the only correct production
    # posture; operators retain a per-deploy opt-out by setting the env var
    # ``FUNDAMENTALS_REFRESH_ENABLED=false`` explicitly. BP-608 documents the
    # general anti-pattern of shipping a scheduled worker disabled by default.
    fundamentals_refresh_enabled: bool = True
    fundamentals_refresh_interval_hours: float = 6.0

    # InstrumentPolicySyncWorker (PLAN-0106 Wave D-1): periodically queries
    # market-data for all US/CC instruments and creates Alpaca 1m polling
    # policies for any symbol not already covered.  Runs every 6 hours by
    # default so newly-listed symbols gain intraday coverage within a day.
    # Set INSTRUMENT_POLICY_SYNC_ENABLED=false to disable without redeploying.
    instrument_policy_sync_enabled: bool = True
    instrument_policy_sync_interval_hours: float = 6.0

    # InsiderUniverseRefreshWorker (PRD-0089 L-4b): weekly re-runs the
    # InsiderUniverseLoader, which expands the insider-transactions polling
    # universe to the OHLCV-covered set via market-data's internal endpoint.
    #
    # GATED OFF BY DEFAULT (deliberately): enabling this starts spending EODHD
    # credits — ~2,830 credits/month at weekly cadence for this environment's
    # ~654 OHLCV-covered universe (1 credit/call). The "~13k/month for 3000
    # instruments" figure in older docs is stale. The spend decision stays the
    # operator's: set MARKET_INGESTION_INSIDER_UNIVERSE_REFRESH_ENABLED=true to
    # opt in once budget is confirmed. BP-608: never ship a credit-spending
    # scheduled worker enabled by default.
    insider_universe_refresh_enabled: bool = False
    # Weekly slot, in UTC. day_of_week follows datetime.weekday()
    # (Monday=0 .. Sunday=6); default Sunday 05:00 UTC (quiet window, after the
    # 03:00 UTC 90d insider rollup).
    insider_universe_refresh_day_of_week: int = 6
    insider_universe_refresh_hour_utc: int = 5
    fundamentals_refresh_top_n: int = 500
    fundamentals_refresh_provider: str = "eodhd"
    fundamentals_refresh_variant: str = "quarterly"
    # CSV override; empty = use the worker's built-in mega-cap default list.
    # Operators set this to pin a specific universe during incidents. Wins
    # over the live top-N endpoint (PLAN-0100 W5) when non-empty so ops
    # always have a kill-switch.
    fundamentals_refresh_symbols: str = ""

    # PLAN-0100 T-W5-02: when True (default) the worker calls market-data's
    # ``GET /internal/v1/instruments/top-by-market-cap`` to refresh its
    # symbol universe each tick. Flip to False to keep the worker on the
    # static ``_DEFAULT_SYMBOL_UNIVERSE`` only — useful as a one-shot
    # operator kill-switch if the endpoint regresses.
    fundamentals_refresh_use_internal_endpoint: bool = True
    # Base URL of market-data — same host the EODHD adapters do NOT call;
    # this is for the internal top-N endpoint specifically.
    market_data_url: str = "http://market-data:8003"
    # RS256 private key used to sign internal JWTs (PEM). Empty in dev →
    # worker signs an HS256 dev token instead; production market-data
    # rejects HS256 unless ``MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true``.
    internal_jwt_private_key: SecretStr = SecretStr("")

    # Worker
    worker_batch_size: int = 10
    worker_lease_seconds: int = 300
    worker_concurrency: int = 4
    # Idle-poll cadence: how long the worker sleeps when ClaimTasksUseCase
    # returns 0 rows. Defaults to 5 s for production back-pressure. CI/E2E
    # overrides this to 1 s so manually-triggered tasks are picked up within
    # the test's 30 s deadline even after the queue has accumulated prior
    # work from earlier tests (R12 — E2E task-progression fix).
    worker_idle_sleep_seconds: float = 5.0
    provider_http_timeout_seconds: float = 30.0

    # Dispatcher
    dispatcher_batch_size: int = 50
    dispatcher_poll_interval_seconds: float = 1.0
    # Lease >=30 s — typical Kafka publish <5 s; 6x safety margin prevents
    # concurrent dispatchers from re-claiming a stalled record.
    dispatcher_lease_seconds: int = 60
    # Raised from 5->20: 5 attempts with 60 s max backoff exhausts in ~5 min,
    # far shorter than a typical rolling restart or Kafka blip (30-90 min).
    # 20 attempts gives ~20 min coverage before dead-lettering.
    dispatcher_max_attempts: int = 20

    # Auth (PRD-0025 Wave D) — S9 api-gateway base URL for JWKS fetch
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # Observability (STANDARDS.md §5 — mandatory in every service)
    service_name: str = "market-ingestion"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if database_url still contains default superuser credentials (D-7)."""
        # F-007: Production guard — reject skip_verification in production.
        if self.internal_jwt_skip_verification and os.getenv("APP_ENV", "").lower() == "production":
            raise ValueError(
                "internal_jwt_skip_verification MUST NOT be enabled in production. "
                "Set APP_ENV != 'production' or remove the flag.",
            )
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "MARKET_INGESTION_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self

    @model_validator(mode="after")
    def _warn_demo_eodhd_key(self) -> Settings:
        if self.eodhd_api_key.get_secret_value() == "demo":
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "demo_eodhd_api_key",
                message=(
                    "EODHD API key is 'demo' — limited to demo endpoints only. "
                    "Set MARKET_INGESTION_EODHD_API_KEY for production use."
                ),
            )
        return self
