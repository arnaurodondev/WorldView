"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EODHDProviderSettings(BaseModel):
    """Operational parameters for the EODHD news provider."""

    base_url: str = "https://eodhd.com/api/news"
    page_size: int = 100
    # OPT-3: Cap pages fetched per fetch_all_pages() call to avoid runaway credit
    # consumption on busy news days. Each page costs 5 EODHD API credits; default 3
    # yields at most 3 x page_size articles per cycle, which covers all normal cases.
    # ge=1 prevents a zero/negative value from silently truncating all ingestion.
    max_pages_per_cycle: int = Field(default=3, ge=1, le=50)
    rate_limit_per_second: float = 10.0
    # OPT-5 (2026-06-15): per-ticker news polling is the dominant EODHD consumer.
    # The TickerNewsSymbolSyncWorker auto-creates one `eodhd_ticker_news` Source
    # per US equity (~600 enabled). EODHD charges /api/news at 5 credits/request,
    # so polling ~600 tickers at the global 5-minute tick cadence burned ~94k of
    # the 100k daily quota (≈94%) and starved fundamentals/OHLCV. Override the
    # poll interval for EODHD_TICKER_NEWS to 1 hour: at ~600 tickers x ~24
    # polls/day x 5 credits the consumption drops ~24x to a few thousand
    # credits/day, leaving ample headroom for fundamentals and new policies.
    # ge=60 prevents a misconfig from re-creating the 5-minute thrash.
    # Configurable via CONTENT_INGESTION_EODHD__TICKER_NEWS_POLL_INTERVAL_SECONDS.
    ticker_news_poll_interval_seconds: int = Field(default=3600, ge=60)
    # ── News batch sweep (QUOTA-OPT, 2026-06-16) ────────────────────────────
    # EODHD's /api/news bills a FLAT 5 credits + 5 credits/ticker PER REQUEST,
    # irrespective of how many articles the request returns (1 or 1000). So the
    # cheapest correct strategy is to pull the ENTIRE batch published since our
    # last watermark in a single request at the maximum page size. We only
    # paginate (a second request) when a sweep returns a FULL page — i.e. more
    # than ``news_page_limit`` articles accrued since the last run, which is
    # rare for an hourly incremental cadence. ``max=1000`` is the EODHD ceiling.
    news_page_limit: int = Field(default=1000, ge=1, le=1000)
    # Safety overlap subtracted from the watermark when building ``from`` so a
    # boundary article published in the same minute as the previous sweep is
    # not missed. EODHD's ``from`` is date-granular, so 1 day of overlap is the
    # smallest unit that guarantees no gap; downstream url_hash dedup
    # (FetchAndWriteUseCase) absorbs the resulting re-fetch at zero extra cost.
    news_watermark_overlap_days: int = Field(default=1, ge=0, le=7)
    # Hard cap on pages fetched per news sweep. The sweep normally exits when a
    # page comes back partial (< news_page_limit) — one request for an hourly
    # incremental run. This cap is a defensive backstop: if EODHD ever ignores
    # ``offset`` and keeps returning full pages, the ``while`` loop would spin
    # forever, burning 5 credits/iteration and hanging the worker (QA H1). At
    # 1000 articles/page, 10 pages = 10k articles, far beyond any real
    # since-watermark batch; hitting the cap is logged as a WARNING (never a
    # silent truncation) so a genuinely huge backlog is visible, not swallowed.
    news_max_pages: int = Field(default=10, ge=1, le=50)


class FinnhubProviderSettings(BaseModel):
    """Operational parameters for the Finnhub provider."""

    base_url: str = "https://finnhub.io/api/v1"
    rate_limit_per_minute: int = 55


class NewsAPIProviderSettings(BaseModel):
    """Operational parameters for the NewsAPI.org provider."""

    base_url: str = "https://newsapi.org/v2/everything"
    page_size: int = 100
    quota_ttl_seconds: int = 86400
    # BP-460: NewsAPI free tier allows only 100 requests/day.
    # With 2 enabled sources polling every 60 s (the global scheduler_interval_seconds),
    # the daily quota is exhausted within minutes.  Override polling to 4 hours
    # (14 400 s): 2 sources x 6 polls/day = 12 requests, well under the 100-request cap.
    # Configurable via CONTENT_INGESTION_NEWSAPI__POLL_INTERVAL_SECONDS.
    poll_interval_seconds: int = 14400


class SECEdgarProviderSettings(BaseModel):
    """Operational parameters for the SEC EDGAR provider."""

    efts_url: str = "https://efts.sec.gov/LATEST/search-index"
    filing_base_url: str = "https://www.sec.gov/Archives/edgar/data"
    default_forms: str = "10-K,10-Q,8-K,DEF14A"
    max_concurrent: int = 8
    market_hours_interval_seconds: int = 60
    off_hours_interval_seconds: int = 1800


class PolymarketProviderSettings(BaseModel):
    """Operational parameters for the Polymarket Gamma API provider."""

    base_url: str = "https://gamma-api.polymarket.com/markets"
    page_size: int = Field(default=500, ge=1, le=1000)
    max_pages_per_cycle: int = Field(default=20, ge=1, le=100)


class HTTPClientSettings(BaseModel):
    """Shared httpx client tuning parameters."""

    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0
    max_retries: int = 3


class Settings(BaseSettings):
    """Configuration for the Content Ingestion service (S4).

    All fields are read from environment variables prefixed with
    ``CONTENT_INGESTION_`` (set by ``env_prefix``).

    Exception: source API keys use their own conventional unprefixed names
    (EODHD_API_KEY, FINNHUB_API_KEY, etc.) and are overridden via
    ``validation_alias`` to bypass the prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="CONTENT_INGESTION_",
        env_file=".env",
        extra="ignore",
        env_nested_delimiter="__",
    )

    # ── External API keys (no CONTENT_INGESTION_ prefix — shared variables) ──
    eodhd_api_key: str = ""
    sec_edgar_user_agent: str = "worldview/1.0 contact@worldview.example"
    finnhub_api_key: str = ""
    newsapi_key: str = ""

    # ── Database ──────────────────────────────────────────────────────────────
    db_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/content_ingestion_db")
    db_url_read: SecretStr = SecretStr("")  # Falls back to db_url if empty (R23)

    # ── Kafka ─────────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_schema_registry_url: str = "http://localhost:8081"
    kafka_schema_registry_basic_auth: str = ""
    kafka_outbox_topic: str = "content.article.raw.v1"
    # PLAN-0113 FIX-2: opt-in static-membership instance id (KIP-345/BP-703).
    # Empty default = dynamic membership (no-op); set per-replica to pin identity.
    kafka_document_ready_consumer_instance_id: str = ""

    # ── MinIO (object storage) ────────────────────────────────────────────────
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "worldview-bronze"
    minio_secure: bool = False

    # ── Security ──────────────────────────────────────────────────────────────
    admin_token: str = ""  # CONTENT_INGESTION_ADMIN_TOKEN — admin/DevOps only
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # ── Scheduler (process — R22) ────────────────────────────────────────────
    scheduler_interval_seconds: int = 300
    scheduler_tick_interval_seconds: float = 60.0
    scheduler_max_tasks_per_tick: int = 100

    # ── Watchdog (3-pass stale-task recovery) ────────────────────────────────
    # Pass 2: PENDING/RETRY orphans (no lease) stuck longer than this are
    #   re-armed as PENDING so the scheduler can pick them up again.
    # Pass 3: anything still stuck past dlq_max_age is moved to FAILED.
    watchdog_pending_max_age_seconds: int = 3600  # 1 h
    watchdog_dlq_max_age_seconds: int = 21600  # 6 h

    # ── Worker (process — R22) ─────────────────────────────────────────────
    worker_batch_size: int = 5
    worker_lease_seconds: int = 300
    worker_idle_sleep_seconds: float = 5.0
    worker_concurrency: int = 2
    worker_task_timeout_seconds: float = 120.0
    # D-04: Polymarket tasks paginate the full market catalogue via the Gamma API
    # (up to 20 pages x 500 markets = 10 000 results + MinIO writes per result).
    # The default 120 s timeout is too short; use a dedicated timeout of 900 s.
    worker_polymarket_task_timeout_seconds: float = 900.0

    # ── Outbox / dispatcher ────────────────────────────────────────────────
    outbox_batch_size: int = 100
    outbox_poll_interval_seconds: float = 5.0
    outbox_lease_seconds: int = 30
    # Raised from 5->20: 5 attempts with 60 s max backoff exhausts in ~5 min,
    # far shorter than a typical rolling restart or Kafka blip (30-90 min).
    # 20 attempts gives ~20 min coverage before dead-lettering.
    outbox_max_attempts: int = 20
    outbox_metrics_poll_seconds: int = 30

    # ── Rate limiting ─────────────────────────────────────────────────────────
    newsapi_daily_limit: int = 100

    # ── Valkey ────────────────────────────────────────────────────────────────
    valkey_url: str = "redis://localhost:6379"

    # ── Backfill ─────────────────────────────────────────────────────────────
    backfill_enabled: bool = False
    backfill_from_date: str = ""
    backfill_to_date: str = ""
    backfill_sources: str = ""
    backfill_batch_delay_seconds: float = 0.5

    # PLAN-0055 Sub-Plan A — auto-backfill on startup. Independent of
    # ``backfill_enabled`` (which gates per-source behavior). ``backfill_on_startup``
    # seeds NULL watermarks to (now - INITIAL_DAYS) so the scheduler tick can
    # fetch backwards. OFF by default in code; gitops env flips it ON.
    backfill_on_startup: bool = False
    # Plain int defaults — pre-commit's older pydantic-settings doesn't surface
    # ``Field(default=N, ge=1)``-annotated attrs to mypy. Runtime clamping in
    # ``seed_source_watermarks.py`` covers the validation that ``ge=1`` provided.
    backfill_initial_days: int = 14
    # Hard cap on horizon — runtime clamps INITIAL_DAYS to YEARS * 365.
    backfill_years: int = 3

    # ── Provider settings (operational params — overridable via ConfigMap) ───
    eodhd: EODHDProviderSettings = EODHDProviderSettings()
    finnhub: FinnhubProviderSettings = FinnhubProviderSettings()
    newsapi: NewsAPIProviderSettings = NewsAPIProviderSettings()
    sec_edgar: SECEdgarProviderSettings = SECEdgarProviderSettings()
    polymarket: PolymarketProviderSettings = PolymarketProviderSettings()
    http_client: HTTPClientSettings = HTTPClientSettings()

    # ── Ticker-news sync worker (PLAN-0106 Wave C-2) ─────────────────────────
    # TickerNewsSymbolSyncWorker creates one ``eodhd_ticker_news`` Source row per
    # instrument returned by market-data every ``ticker_news_sync_interval_hours``
    # hours. The kill-switch is ON by default so fresh deploys immediately
    # bootstrap per-ticker source rows from the instrument universe.
    ticker_news_sync_enabled: bool = True
    ticker_news_sync_interval_hours: float = 6.0

    # ── Internal JWT (for worker → market-data cross-service calls) ───────────
    # Must match the RS256 private key used by S9 (api-gateway).  When empty
    # (dev/CI), the worker falls back to an HS256 dev token accepted by
    # market-data's ``internal_jwt_skip_verification=true`` dev mode.
    internal_jwt_private_key: SecretStr = SecretStr("")

    # ── Market-data service URL (for worker cross-service calls) ─────────────
    market_data_url: str = "http://market-data:8003"

    # ── Observability (STANDARDS.md §5 — mandatory in every service) ─────────
    service_name: str = "content-ingestion"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""

    @model_validator(mode="after")
    def _warn_default_db_credentials(self) -> Settings:
        """Warn at startup if db_url still contains default superuser credentials (D-7).

        Uses structlog so the warning is captured by the structured log pipeline
        in production log aggregators (F-SEC-001).
        """
        # F-007: Production guard — reject skip_verification in production.
        if self.internal_jwt_skip_verification and os.getenv("APP_ENV", "").lower() == "production":
            raise ValueError(
                "internal_jwt_skip_verification MUST NOT be enabled in production. "
                "Set APP_ENV != 'production' or remove the flag.",
            )
        if "postgres:postgres" in self.db_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "CONTENT_INGESTION_DB_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
