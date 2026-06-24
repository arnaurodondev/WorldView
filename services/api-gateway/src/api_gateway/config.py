"""Service configuration via environment variables."""

from __future__ import annotations

from pydantic import SecretStr  # — pydantic evaluates field types at runtime
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for the api-gateway service (stateless BFF)."""

    model_config = SettingsConfigDict(
        env_prefix="API_GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Valkey (caching + rate limiting)
    valkey_url: str = "redis://localhost:6379/0"

    # OIDC (Zitadel Cloud) — all required; service refuses to start without them (R13)
    oidc_issuer_url: str  # e.g. https://<instance>.zitadel.cloud
    oidc_client_id: str
    oidc_client_secret: SecretStr
    oidc_audience: str  # usually same as client_id
    # Set to true in test/dev environments where Zitadel is not running.
    # OIDC discovery failure becomes a warning instead of a fatal error;
    # the gateway starts with internal-JWT-only auth (no external OIDC token validation).
    oidc_discovery_optional: bool = False

    # Internal JWT (RS256) — PEM-encoded RSA-2048 key pair
    internal_jwt_private_key: SecretStr  # never logged — SecretStr
    internal_jwt_public_key: str

    # W1-05 (BUG-005): kid-based JWKS rotation. ``jwt_key_version`` is the
    # ``kid`` stamped into every issued internal JWT header. When operators
    # rotate the RSA key pair, they bump this value (e.g. "v1" → "v2") and
    # push the new private key + previous public key (for the grace window)
    # in the same deploy. Backends discover new kids via JWKS refresh-on-miss.
    # ``jwks_grace_hours`` is advisory metadata for operators — the actual
    # rotation hook is ``app.state.previous_jwks`` (operators append outgoing
    # keys there for the grace window).
    jwt_key_version: str = "v1"
    jwks_grace_hours: int = 24

    # Frontend
    frontend_url: str = "http://localhost:5173"
    cookie_secure: bool = True  # False only in local dev (override via API_GATEWAY_COOKIE_SECURE=false)

    # Downstream service URLs
    portfolio_url: str = "http://localhost:8001"
    market_ingestion_url: str = "http://localhost:8002"
    market_data_url: str = "http://localhost:8003"
    content_ingestion_url: str = "http://localhost:8004"
    content_store_url: str = "http://localhost:8005"
    nlp_pipeline_url: str = "http://localhost:8006"
    knowledge_graph_url: str = "http://localhost:8007"
    rag_chat_url: str = "http://localhost:8008"
    alert_url: str = "http://localhost:8010"
    alert_ws_url: str = "ws://localhost:8010"  # env: API_GATEWAY_ALERT_WS_URL

    # Rate limiting
    # WHY 300: authenticated users on the instrument detail page fire 4+ simultaneous
    # OHLCV timeseries calls (one per workspace panel) plus screener + KG graph + news.
    # 100 req/60s was too tight for multi-panel workspace usage → 429s on timeseries.
    # Unauthenticated tier stays at 20 req/60s (enforced in RateLimitMiddleware).
    rate_limit_requests: int = 2000
    rate_limit_window_seconds: int = 60
    # PLAN-0094 W1: per-tier limits read by RateLimitMiddleware.
    # Defaults match production env values in worldview-gitops.
    rate_limit_financial_mutation_requests: int = 30
    rate_limit_unauthenticated_requests: int = 20
    rate_limit_public_feedback_requests: int = 10

    # CORS
    # SEC-008: Port 3001 is the worldview-web frontend.  Port 3000 is unused and
    # could be attacker-controlled; it must not appear in the default allowlist.
    cors_origins: str = "http://localhost:5173,http://localhost:3001"

    # Environment guard — SEC-003: dev-login is blocked when app_env="production"
    # regardless of OIDC configuration, preventing accidental exposure in prod.
    # Valid values: "development", "staging", "production"
    app_env: str = "development"

    # F-Q1-02: dev-only admin allow-list. When ``app_env != "production"``,
    # any dev-login email matching one of these (comma-separated) values
    # gets ``role=admin`` in the issued internal JWT so admin endpoints
    # are reachable from the demo frontend without a real Zitadel role
    # provider. In production, role MUST come from the OIDC payload.
    dev_admin_emails: str = ""

    # PLAN-0057 Wave A-1 / BP-303 — Service-account secret used by
    # ``POST /internal/v1/service-token``. Background workers (e.g. the
    # nlp-pipeline price-impact worker) authenticate with this shared secret
    # to mint an RS256 internal JWT. Empty default keeps local dev workflows
    # using ``POST /v1/auth/dev-login``; production deployments MUST set this
    # via sealed secret. Compared with ``secrets.compare_digest`` to avoid
    # leaking timing information.
    service_account_token: SecretStr = SecretStr("")

    # NL screener — DeepInfra key for direct chat/completions call.
    # Falls back to empty (feature disabled) when not set.
    # env var: API_GATEWAY_DEEPINFRA_API_KEY (env_prefix + field name)
    deepinfra_api_key: SecretStr = SecretStr("")

    # ── Bundle pre-warmer (PLAN-0099 R3) ────────────────────────────────────
    # Background worker that periodically re-fetches the Intelligence-tab
    # composite bundle for a configured set of hot entity IDs (typically the
    # S&P 500). Keeps the downstream caches (S7 intel/paths) warm so the first
    # real user request hits a populated cache (~88 ms vs 4-10 s cold).
    #
    # Default is OFF so the worker is opt-in only and never fires in unit
    # tests, dev, or CI unless explicitly enabled via env var. Runtime
    # container is wired in infra/compose/docker-compose.yml.
    prewarm_enabled: bool = False
    # Comma-separated list of entity UUIDs; pydantic-settings parses CSV→list[str]
    # automatically for ``list[str]`` fields.
    prewarm_entity_ids: list[str] = []
    # Slightly below the bundle's underlying cache TTL (300 s) so we always
    # repopulate before expiry, never serving a cold miss to real users.
    prewarm_interval_seconds: int = 240
    # Base URL the worker hits — defaults to localhost so the container can
    # call its sibling api-gateway via the service network.
    prewarm_api_base_url: str = "http://localhost:8000"
    # Cap on concurrent in-flight prewarm requests (per cycle) — prevents the
    # worker from saturating the api-gateway it depends on.
    prewarm_concurrency: int = 3
    # Per-request timeout. Bundle fan-out can take several seconds when the
    # downstream caches are cold; allow generous headroom.
    prewarm_request_timeout_seconds: float = 30.0

    # Observability (STANDARDS.md §5 — mandatory in every service)
    service_name: str = "api-gateway"
    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str = ""
