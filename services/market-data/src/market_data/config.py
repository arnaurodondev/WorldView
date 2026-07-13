"""Service configuration via environment variables."""

from __future__ import annotations

import os

import structlog
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the market-data service."""

    model_config = SettingsConfigDict(
        env_prefix="MARKET_DATA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8003
    debug: bool = False

    # Database
    database_url: SecretStr = SecretStr("postgresql+asyncpg://postgres:postgres@localhost:5432/market_data_db")
    # Optional read replica URL. When set, read-only API queries are routed to this
    # DB instance (e.g. a streaming replica). When unset, reads use database_url.
    read_replica_url: SecretStr | None = None

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    schema_registry_url: str = "http://localhost:8081"

    # PLAN-0113 FIX-2: static-membership instance ids (opt-in). Empty default =
    # dynamic membership (no-op). Setting a stable, per-replica value enables Kafka
    # static membership so a rolling restart does not trigger a full group rebalance.
    kafka_ohlcv_consumer_instance_id: str = ""
    kafka_quotes_consumer_instance_id: str = ""
    kafka_fundamentals_consumer_instance_id: str = ""
    kafka_insider_transactions_consumer_instance_id: str = ""
    kafka_intraday_resampling_consumer_instance_id: str = ""
    kafka_prediction_market_consumer_instance_id: str = ""
    # PLAN-0056 Wave A3: static-membership ids for the four deeper-stream
    # prediction consumers (history / event / trade / oi). Empty = dynamic.
    kafka_prediction_history_consumer_instance_id: str = ""
    kafka_prediction_event_consumer_instance_id: str = ""
    kafka_prediction_trade_consumer_instance_id: str = ""
    kafka_prediction_oi_consumer_instance_id: str = ""

    # ── PLAN-0056 Wave D1: PredictionMoveDetector worker ───────────────────────
    # Periodic worker that scans ``prediction_market_snapshots`` per open market
    # and emits ``market.prediction.move.v1`` when an outcome's implied
    # probability moves materially over a lookback window.  Every threshold is
    # env-driven (NO hardcoded gates) so the noise floor can be re-tuned without
    # a redeploy.  All env vars carry the ``MARKET_DATA_`` prefix.
    #
    # Run cadence (seconds between cycles). 900 s = 15 min: frequent enough to
    # catch fresh moves, sparse enough that the read-replica scan is cheap.
    prediction_move_detector_interval_seconds: int = 900
    # Lookback window (hours) over which Δ implied-probability is measured. The
    # window-start snapshot is the oldest snapshot within this span; the latest
    # snapshot is the window end. Default 24 h pairs with the ``1d`` label.
    prediction_move_window_hours: int = 24
    # Free-form window granularity label written to the event ``interval`` field
    # (Avro allows 1h | 1d | 1w). Kept in lock-step with ``window_hours`` by
    # convention — no PG enum (BP-007).
    prediction_move_interval_label: str = "1d"
    # Δ gate: only emit when ``abs(new_price - prev_price) >= τ``. Prices are
    # implied probabilities in [0,1], so 0.15 = a 15-percentage-point swing.
    prediction_move_delta_threshold: float = 0.15
    # Liquidity floor (USD) on the latest snapshot — thin markets are noise.
    prediction_move_min_liquidity_usd: float = 5_000.0
    # 24h-volume floor (USD) on the latest snapshot — untraded markets are noise.
    prediction_move_min_volume_usd: float = 1_000.0
    # Safety cap on markets scanned per page and snapshots pulled per market so a
    # runaway market count / snapshot fan-out can never blow up a single cycle.
    prediction_move_market_page_size: int = 200
    prediction_move_snapshot_limit: int = 500

    # ── Prediction-market LIST endpoint latest-volume window (PLAN-0056 QA) ─────
    # The ``GET /api/v1/prediction-markets`` list endpoint LEFT JOIN LATERALs the
    # newest snapshot per market to surface ``volume_24h`` (which drives the
    # "recently traded first" ordering). ``prediction_market_snapshots`` is a
    # TimescaleDB hypertable partitioned by ``snapshot_at`` into weekly chunks
    # (~1.8M rows / 64 days). WITHOUT a time bound the LATERAL's
    # ``ORDER BY snapshot_at DESC LIMIT 1`` cannot stop early for a market whose
    # newest snapshot lives in an OLD chunk (or that has stopped being polled):
    # ChunkAppend descends EVERY chunk per market x 527 open markets, reading
    # cold pages off disk (~1.8 s cold). Under concurrent load these slow queries
    # pile up and exhaust the async DB pool -> the endpoint 500s ("upstream
    # service error") and the frontend prediction rows stay stuck as skeletons.
    #
    # Bounding the lookup to a recent window lets Postgres/TimescaleDB prune to
    # the few in-window chunks (chunk exclusion), so the query stays bounded
    # (~60-370 ms) regardless of history depth. Markets with NO snapshot inside
    # the window fall to ``volume_24h = NULL`` -> sort to the bottom, which is
    # the DESIRED behaviour: a "24-hour volume" older than this window is stale
    # and must not float a dead market to the top of the dashboard (this is the
    # documented intent of the ORDER BY — surface recently-traded markets first).
    # 0 or negative disables the bound (unbounded LATERAL — legacy behaviour).
    prediction_market_list_volume_window_days: int = 30

    # ── Outbox dispatcher (BUG-4 / BP-612) ─────────────────────────────────────
    # These tune the ``DispatcherConfig`` built in ``dispatcher_main`` /
    # ``create_dispatcher``. Historically market-data built ``DispatcherConfig()``
    # with no override, so it inherited the lib default ``max_attempts=5``. A
    # transient broker blip on 2026-06-17 exhausted that 5-attempt budget in
    # minutes and permanently dead-lettered 44 ``market.instrument.*`` events
    # (lost downstream InstrumentRef / canonical-entity creation). market-ingestion
    # already raised this to 20 under BP-612; we now apply the same symmetric fix
    # here. 20 attempts x ~60 s backoff is ~20 min coverage, enough to ride out a
    # rolling restart or Kafka blip before dead-lettering.
    dispatcher_poll_interval_seconds: float = 5.0
    dispatcher_lease_seconds: int = 30
    dispatcher_batch_size: int = 100
    dispatcher_max_attempts: int = 20

    # Storage
    storage_endpoint: str = "http://localhost:7480"
    storage_access_key: SecretStr  # Required — set MARKET_DATA_STORAGE_ACCESS_KEY env var
    storage_secret_key: SecretStr  # Required — set MARKET_DATA_STORAGE_SECRET_KEY env var

    # Valkey
    valkey_url: str = "redis://localhost:6379/0"

    # Fundamentals read-cache (chat-enhancement-roadmap Area 1 #3).
    #
    # The chat hot-path hammers a handful of tickers (AAPL/AMZN/NVDA) with the
    # SAME fundamentals reads across many questions. Fundamentals only change
    # quarterly, so a short-TTL Valkey cache in front of the read use-cases
    # (/fundamentals/history, /fundamentals/query, /fundamentals/batch) cuts DB
    # round-trips + connection-pool pressure with safe bounded staleness.
    #
    # ``fundamentals_cache_enabled`` (env MARKET_DATA_FUNDAMENTALS_CACHE_ENABLED)
    # is a kill-switch: set False to route every read straight to the DB (the
    # pre-cache behaviour) without a redeploy.
    fundamentals_cache_enabled: bool = True
    # Default 6h — comfortably shorter than the quarterly refresh cadence, so a
    # freshly-ingested quarter is visible within at most one TTL window. Env:
    # MARKET_DATA_FUNDAMENTALS_CACHE_TTL_SECONDS.
    fundamentals_cache_ttl_seconds: int = 21_600

    # Internal auth (PRD-0025): S9 api-gateway base URL for JWKS endpoint.
    api_gateway_url: str = "http://api-gateway:8000"

    # F-001: When True, InternalJWTMiddleware decodes JWTs WITHOUT signature
    # verification if the JWKS public key is unavailable. NEVER enable in
    # production — only for E2E tests that run without a full S9 stack.
    internal_jwt_skip_verification: bool = False

    # F-012: When False, disables JTI replay detection in InternalJWTMiddleware.
    # Market-data is called multiple times per request (quotes + fundamentals)
    # with the same JWT from rag-chat's gather_instrument_context(). Set to
    # False in dev so parallel calls to market-data share a single JWT without
    # triggering replay rejection. Keep True in production with proper JWT rotation.
    internal_jwt_jti_check_enabled: bool = False

    # EODHD on-demand enrichment (PLAN-0073 Worker 13J)
    eodhd_api_key: SecretStr = SecretStr("")
    eodhd_base_url: str = "https://eodhd.com"

    # PLAN-0066 Wave G: maximum date range (in days) for GET /api/v1/ohlcv/bars.
    # Callers requesting more than this span receive HTTP 422.
    # Env var: MARKET_DATA_OHLCV_MAX_DAYS (or S3_OHLCV_MAX_DAYS is not supported —
    # this service uses the MARKET_DATA_ prefix from env_prefix).
    ohlcv_max_days: int = 365

    # Intraday resampling source timeframe (BP-254 — must be config-driven, not hardcoded).
    # Valid values: "1m", "5m", "15m", "1h". Changing this migrates the entire
    # ResampledOHLCVUseCase + IntradayResamplingConsumer pipeline to the new finest
    # granularity without any code change.
    intraday_source_tf: str = "1m"

    # PLAN-0089 Wave L-4b — hour of UTC day at which the insider-90d rollup
    # worker fires. Default 03:00 places it one hour after L-3's 02:00 so
    # the two big analytical writes do not pile up.
    insider_rollup_hour_utc: int = 3

    # PLAN-0089 Wave L-5b — hour of UTC day at which the intelligence rollup
    # sync worker fires. Default 04:00 places it one hour after L-4b's 03:00
    # and two hours after L-3's 02:00 so three large nightly writes are evenly
    # spread across the 02:00-04:00 UTC window. Configurable via env var
    # ``MARKET_DATA_INTELLIGENCE_ROLLUP_HOUR_UTC``.
    intelligence_rollup_hour_utc: int = 4

    # URLs for the 4 upstream intelligence services called by the L-5b worker.
    # Default to Docker-Compose service names so the out-of-box local dev stack
    # works without any extra configuration.
    # NOTE: the S6 news-rollup endpoint lives in nlp-pipeline (nlp_db owns
    # routing_decisions / document_source_metadata / article_impact_windows),
    # NOT in content-store. The previous default (``http://content-store:8006``)
    # was doubly wrong — wrong service AND wrong port — so every nightly call
    # silently 404'd, leaving news_count_7d/llm_relevance_7d_max/
    # display_relevance_7d_weighted NULL across all instruments.
    # ``content_store_url`` is kept as an alias for backward env-var compat.
    nlp_pipeline_url: str = "http://nlp-pipeline:8006"
    content_store_url: str = "http://nlp-pipeline:8006"
    knowledge_graph_url: str = "http://knowledge-graph:8007"
    alert_service_url: str = "http://alert:8010"
    rag_chat_url: str = "http://rag-chat:8008"

    # RS256 private key for signing internal JWTs sent to upstream services.
    # Mirrors the pattern used by ``FundamentalsRefreshWorker``. Empty string
    # triggers the dev HS256 fallback (acceptable when
    # ``internal_jwt_skip_verification=True`` on the upstream services).
    internal_jwt_private_key: str = ""

    # PLAN-0102 T-W6-02 / BP-617 — per-message processing timeout (seconds)
    # for the fundamentals consumer's `market.dataset.fetched` topic. The
    # default 90 s replaces the previous library-wide 45 s default after a
    # live observation that large-universe payloads (Russell 1000 sweeps
    # with 600+ sections in a single payload) blew the 45 s budget and
    # were dead-lettered. Set via env var
    # ``MARKET_DATA_FUNDAMENTALS_TIMEOUT_S`` if a different ceiling is
    # required. Surface via the ``fundamentals_consumer_processing_ms``
    # histogram (see infrastructure/metrics/prometheus.py) before bumping
    # again — the tail is the actionable signal, not the timeout itself.
    fundamentals_timeout_s: int = 90

    # NEW-6 (2026-07-06) — screener statement-timeout ceiling (milliseconds).
    # ``query_screen`` issues ``SET LOCAL statement_timeout`` for the duration of
    # the read transaction so a pathological plan is cancelled cleanly at the DB
    # (asyncpg ``QueryCanceledError`` → HTTP 504) instead of hanging the request
    # and holding a pooled connection. This ceiling was previously HARDCODED to
    # 8000 ms; it is now a tunable so ops can raise it during sustained host
    # CPU/IO contention (the load-driven multiplier that turned a ~1 s screen
    # into an ~18 s timeout in the R1 audit) without a redeploy, or lower it to
    # shed load faster. The DISTINCT ON query rewrite that shipped with this
    # setting keeps the screen well under 8 s even under contention, so the
    # default is unchanged. Env var: ``MARKET_DATA_SCREEN_STATEMENT_TIMEOUT_MS``.
    screen_statement_timeout_ms: int = 8000

    # Observability (STANDARDS.md §5 — mandatory in every service)
    service_name: str = "market-data"
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
                "Set APP_ENV != 'production' or remove the flag."
            )
        if "postgres:postgres" in self.database_url.get_secret_value():
            structlog.get_logger(__name__).warning(  # type: ignore[no-untyped-call]
                "default_db_credentials_detected",
                message=(
                    "MARKET_DATA_DATABASE_URL still uses the default 'postgres:postgres' credentials. "
                    "Set this env var to a secure database URL before deploying to production."
                ),
            )
        return self
