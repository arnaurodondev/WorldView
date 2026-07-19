# API Gateway / BFF Service (S9)

> **Owner**: Gateway domain · **Database**: None (stateless) · **Port**: 8000
> **Status**: Production-ready · **Spec**: PRD-0025 (auth), PRD-0028 (frontend routes)

---

## Mission & Boundaries

**Owns**: Unified API entry point for the frontend, request routing, response
composition (BFF pattern), authentication/authorization (OIDC + RS256 internal JWT),
rate limiting, per-endpoint caching (Valkey), CORS enforcement, error standardization,
security headers.

**Never does**: Business logic, data persistence, direct database access, LLM
completions, NLP processing.

---

## Database state

api-gateway is **stateless**: the service holds no schema and writes no rows.

- The `gateway_db` PostgreSQL database is provisioned by `infra/postgres/init.sql`
  for legacy / forward-compatibility reasons (e.g. potential future rate-limit
  state, audit log, idempotency keys) but is intentionally **empty** and contains
  **no `alembic_version` table**.
- The `services/api-gateway/alembic/` directory exists as a scaffold (env.py and
  empty `versions/` folder) but has **zero migrations**. There are no SQLAlchemy
  models, sessions, or engines instantiated anywhere in `src/api_gateway/`.
- All caching state lives in Valkey (response cache, JWT/JWKS cache, rate-limit
  buckets, PKCE state). All persistent state is owned by the downstream services
  (S1 portfolio, S5 content-store, etc.) and accessed via REST.
- The QA finding "`gateway_db` missing `alembic_version`" is **expected** — it
  is not an oversight or a missing migration. If api-gateway ever needs durable
  state, add the first migration under `services/api-gateway/alembic/versions/`
  and `ALEMBIC_ENABLED=true` will be opt-in at that point.

---

## API Surface — Full Endpoint Reference

All routes are prefixed with `/v1` (main), `/v1/auth` (auth), or `/internal`.

### Authentication Endpoints (`/v1/auth`)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/auth/login` | PKCE login — redirect to Zitadel | No |
| GET | `/v1/auth/callback` | PKCE callback — exchange code, provision S1 user, set cookie | No |
| POST | `/v1/auth/refresh` | Rotate refresh_token cookie → new access_token | No |
| POST | `/v1/auth/logout` | Revoke token at Zitadel, clear httpOnly cookie | No |
| GET | `/v1/auth/me` | Return current user profile from access token | Bearer |
| GET | `/v1/auth/register` | Redirect to Zitadel self-registration | No |
| GET | `/v1/auth/ws-token` | Issue 30-second short-lived JWT for WebSocket auth | Yes |
| POST | `/v1/auth/dev-login` | Dev-only login — returns JWT for seed demo user | No |

**`POST /v1/auth/dev-login`**: Available only when `OIDC_DISCOVERY_OPTIONAL=true` and Zitadel is not configured. Returns the same response shape as `/v1/auth/callback` (access token + user profile). Returns `403 Forbidden` when OIDC is configured (production). Used by the frontend "Dev Login" button for local development without Zitadel.

**Refresh-token cookie (silent refresh)**: The `refresh_token` is stored in an `httpOnly; Secure; SameSite=strict` cookie set by `/v1/auth/callback` and re-issued (rotated) on every `/v1/auth/refresh`. The cookie `Path` is **`/api/v1/auth/refresh`** — it must match the browser-visible request path, since the frontend calls the same-origin Vercel proxy (`BASE=/api`, rewritten by `next.config.ts` to S9), not S9 directly. A mismatched path means the browser never attaches the cookie and every refresh 401s. Two preconditions for a refresh token to exist at all: (1) the authorize request must include the `offline_access` scope (both `GET /v1/auth/login` and the frontend `app/login/page.tsx` authorize URL request it — Zitadel returns no `refresh_token` otherwise), and (2) the Zitadel app must have the Refresh Token grant enabled and be a confidential Web app. See audit `docs/audits/2026-07-19-refresh-token-failure.md`.

### Health & Internal Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/healthz` | Liveness probe | No |
| GET | `/readyz` | Readiness probe (checks Valkey) | No |
| GET | `/metrics` | Prometheus metrics | No |
| GET | `/internal/jwks` | RS256 public key (JWKS format) for backend JWT verification | No |
| POST | `/internal/v1/service-token` | Mint a service-account RS256 internal JWT (PLAN-0057 Wave A-1 / BP-303) | Shared secret |

**`POST /internal/v1/service-token`** (PLAN-0057 Wave A-1 — closes BP-303):

Mints a 5-minute RS256 internal JWT for background workers. Solves the production "OHLCV auth blackhole" problem where workers minted their `X-Internal-JWT` via `POST /v1/auth/dev-login`, which is hard-blocked when `app_env == "production"`.

Authentication: shared `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` secret + service identity on the allow-list (`routes/internal.py::_ALLOWED_SERVICE_NAMES`). Comparison uses `secrets.compare_digest` (constant-time). The allow-list currently holds two callers: `nlp-pipeline-price-impact` and `rag-chat-brief-scheduler` (PLAN-0094 W2 — the morning-brief overnight scheduler; without it every scheduled brief 401'd on upstream calls).

Request body (`application/json`):

```json
{
  "service_name": "nlp-pipeline-price-impact",
  "secret": "<shared-secret>"
}
```

Response (200):

```json
{
  "access_token": "<rs256-jwt>",
  "expires_in": 300,
  "token_type": "Bearer"
}
```

Issued JWT claims: `sub="service:<service_name>"`, `tenant_id="system"`, `role="system"`, `service_name=<name>`, `iss="worldview-gateway"`, 5-minute expiry.

Status codes:
- **200**: secret valid AND `service_name` allow-listed → JWT issued.
- **401**: wrong secret OR unknown service_name (same error to avoid disclosing which check failed).
- **422**: missing/invalid request body (Pydantic validation).
- **503**: `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` unset (deployment misconfiguration) or RSA private key missing.

**This endpoint is NOT guarded by `app_env`** — the shared secret IS the auth boundary, and the endpoint must work in production (that is the whole reason it exists). Each successful mint logs `service_token_issued` with the `service_name` (never the secret nor the JWT).

To register a new service caller:
1. Add the canonical name to `_ALLOWED_SERVICE_NAMES` in `services/api-gateway/src/api_gateway/routes/internal.py`.
2. Distribute the shared `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` to the caller's deployment via sealed secret (matching env var on the caller side, e.g. `NLP_PIPELINE_SERVICE_ACCOUNT_TOKEN`).
3. Update the caller to pass `service_account_token=settings.service_account_token` and `service_name=<canonical-name>` to its HTTP client (see `MarketDataClient` in services/nlp-pipeline for the reference pattern).

### Composition Endpoints (multi-service aggregation)

| Method | Path | Sources | Auth |
|--------|------|---------|------|
| GET | `/v1/companies/{id}/overview` | S3 (fundamentals + OHLCV) + S5 (news) | Yes |
| GET | `/v1/companies/by-ticker/{ticker}/overview` | Ticker-direct variant of the overview composition (B-Q task 6, 2026-06-10) — resolves the ticker via `resolve_security_id` (S3 lookup + KG alias fallback, 1h TTL cache) then reuses `CompanyOverviewUseCase`. Replaces the chat entity cards' search→overview two-request dance. 404 on unknown ticker. | Yes |
| GET | `/v1/instruments/{id}/page-bundle` | Composes overview + fundamentals + technicals + insider + top-news in one round-trip (PLAN-0059 I-5) | Yes |
| GET | `/v1/market/heatmap` | S3 — single `GET /api/v1/market/sector-returns?period=…` call (the old 11-parallel-screener fan-out is dead code; see BP-465) | Yes |
| GET | `/v1/market/top-movers` | S3 (sorted by daily_return) | Yes |
| GET | `/v1/market/sparklines` | S3 OHLCV fan-out — batch 14-day close arrays for sparkline rendering. Query: `instrument_ids` (comma-separated UUIDs, max 50), `days` (int, default 14). Valkey TTL 900 s. Response: `{"data": {"<id>": [<close>, ...]}, "meta": {"days_requested": int, "fetched_at": ISO8601, "missing": [<id>]}}` | Yes |
| GET | `/v1/map/layers` | S3 (GeoJSON overlays) | No |

#### `/v1/instruments/{id}/page-bundle` — initial-load composite (PLAN-0059 I-5)

Collapses the instrument-detail page's overview-tab waterfall into a single
HTTP request. Behavior:

- **Composition** — two-phase `asyncio.gather`:
  - Phase 1: `get_company_overview` (which itself parallelises 5 calls and
    resolves the KG `entity_id`).
  - Phase 2 (uses Phase-1's resolved `entity_id`): full
    `/api/v1/fundamentals/{id}` + `/technicals-snapshot` +
    `/insider-transactions-snapshot` + S6 `/api/v1/news/entity/{entity_id}?limit=5`.
- **Per-call failures degrade gracefully** — failed sub-resources return
  `null` in the response. The bundle still returns 200 so the FE renders
  partial UIs rather than seeing a 5xx.
- **Overall timeout** — the whole composition is wrapped in
  `asyncio.wait_for(20s)`. On timeout the bundle returns 200 with all
  sub-fields `null`.
- **Auth required** — explicit `request.state.user is None → 401` guard
  at the route handler.
- **JWT-per-call** — each downstream gets a freshly-signed internal JWT
  via `make_headers` factory so InternalJWTMiddleware's JTI-replay
  detection accepts the parallel fan-out.

Response shape: `{instrument_id, entity_id, overview, fundamentals,
technicals, insider, top_news}`. Sub-resource shapes match the dedicated
endpoints' responses verbatim so clients can prime TanStack Query caches
with bundle.* values.

### News Endpoints (→ S5 Content Store)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/news/relevant` | Most relevant articles (all sources) | No |
| GET | `/v1/news/top` | Top-scored articles (PRD-0026); response includes `sentiment` (positive/negative/neutral/mixed/null) and `impact_score` (FLOAT 0-1/null) per article (PLAN-0050 Wave E) | No |
| GET | `/v1/news/entity/{entity_id}` | Articles for a specific entity; same `sentiment` + `impact_score` fields (PLAN-0050 Wave E) | Yes |
| GET | `/v1/articles/{document_id}` | Resolve a PIPELINE doc_id (e.g. relation-evidence `document_id`) to article metadata `{document_id, title, url, source, source_type, published_at, word_count}` via content-store `POST /api/v1/documents/batch` (single-element batch). 404 when unknown. Do NOT confuse with `/v1/documents/{id}` (S4 tenant uploads — 500s on pipeline ids). Backend-gaps wave 3, 2026-06-11 | Yes |

### Chat & Conversation Endpoints (→ S8 RAG/Chat)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/chat` | Synchronous chat (buffered) | Yes |
| POST | `/v1/chat/stream` | SSE streaming chat (unbuffered, chunked) | Yes |
| POST | `/v1/threads` | Create conversation thread | Yes |
| GET | `/v1/threads` | List threads | Yes |
| GET | `/v1/threads/{thread_id}` | Get thread by ID | Yes |
| PATCH | `/v1/threads/{thread_id}` | Patch mutable thread fields (currently only `title`). Body `{title?: string}`. PLAN-0051 T-E-5-06. Used by chat sidebar inline rename. | Yes |
| DELETE | `/v1/threads/{thread_id}` | Delete thread | Yes |

### Market Data Endpoints (→ S3 Market Data)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/ohlcv/{instrument_id}` | OHLCV price history | Yes |
| POST | `/v1/ohlcv/batch` | Batch OHLCV bars for up to 50 instruments (PLAN-0049 T-A-1-05) — fans out per-symbol calls in parallel; per-symbol failures populate `error` instead of failing the whole batch | Yes |
| GET | `/v1/quotes/{instrument_id}` | Latest quote (PriceSnapshot-enriched). Includes nullable `bid`/`ask` (2026-06-10) — populated only when the snapshot was quote-sourced (`fresh_quote`/`bulk_quote`, ≤15 min); bar-derived prices report null (no order-book context). Includes nullable `previous_close` (2026-06-11) — derived as `price - change`; null when the prior-session close is unknown. | Yes |
| POST | `/v1/quotes/batch` | Batch quotes for multiple instruments (same `bid`/`ask`/`previous_close` semantics) | Yes |
| GET | `/v1/instruments/{instrument_id}/peers` | Top-N market-cap peers in same GICS industry (sector fallback) → S3 `/instruments/{id}/peers`. Each peer: ticker, name, market_cap, pe_ratio, return_1y, change_pct, `last_price` (B-Q-1, 2026-06-10 — quotes.last with latest-1d-close fallback, null when neither exists). Default limit 8, max 20. Accepts ticker or UUID slug. | Yes |
| GET | `/v1/instruments/{instrument_id}/intraday-stats` | B-Q-2 (2026-06-10) → S3-computed session stats: `open`, `prev_close`, `day_high`, `day_low`, `vwap` (+`vwap_source` 1m/5m), `volume`, `volume_vs_30d_ratio`, `session_date`. All nullable — null = no data, never 0. Accepts ticker or UUID slug. | Yes |
| GET | `/v1/instruments/{instrument_id}/returns` | B-Q-3 (2026-06-10) → S3-computed close-on-close % returns: `{1D,1W,1M,3M,6M,YTD,1Y,3Y,5Y}` — calendar-anchored from daily closes; null per period when history is insufficient (never extrapolated). | Yes |
| GET | `/v1/instruments/{instrument_id}/price-levels` | B-Q-4 (2026-06-10) → S3-computed levels: 52w high/low + % distances (null below 190-session honesty threshold), MA50/MA200, prior-session H/L, and simple fractal swing-point support/resistance (method string in `sr_method`). | Yes |
| GET | `/v1/fundamentals/{instrument_id}/income-statement` | Income-statement records → S3 `/income-statement` (PLAN-0088 G-1). Forwards `?period_type=quarterly\|annual` (2026-06-11) | Yes |
| GET | `/v1/fundamentals/{instrument_id}/balance-sheet` | Balance-sheet records → S3 `/balance-sheet` (B-Q task 7, 2026-06-10; QUARTERLY default per BP-546). `?period_type=annual` selects the ANNUAL rows (2026-06-11) | Yes |
| GET | `/v1/fundamentals/{instrument_id}/cash-flow` | Cash-flow records → S3 `/cash-flow` (B-Q task 7, 2026-06-10; QUARTERLY default per BP-546). `?period_type=annual` selects the ANNUAL rows (2026-06-11) | Yes |
| GET | `/v1/fundamentals/{instrument_id}` | All fundamentals sections (composite) | Yes |
| GET | `/v1/fundamentals/{instrument_id}/technicals` | Technical indicators snapshot (beta, SMA50/200, short interest) → S3 `/technicals-snapshot` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/share-statistics` | Share statistics (float, short interest, insider/institutional %) → S3 `/share-statistics` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/insider-transactions` | Recent insider buys/sells → S3 `/insider-transactions-snapshot` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/earnings-trend` | Forward EPS/revenue analyst estimates → S3 `/earnings-trend` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/earnings-annual-trend` | Annual earnings projections → S3 `/earnings-annual-trend` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/splits-dividends` | Stock splits and dividend history → S3 `/splits-dividends` | Yes |
| GET | `/v1/fundamentals/{instrument_id}/snapshot` | Pre-computed derived metrics snapshot (eps_ttm, beta, avg_volume_30d, FCF, interest coverage, net_debt_to_ebitda, credit_rating) → S3 `instrument_fundamentals_snapshot` table. Always 200 — all fields null for un-backfilled instruments. PLAN-0050 Wave D. | Yes |
| POST | `/v1/fundamentals/screen` | Dynamic screener | No |
| POST | `/v1/screener/nl-translate` | NL→filter translation via a DIRECT DeepInfra call (bypasses S8). PLAN-0117 W4 (FR-6): now best-effort POSTs its `usage.estimated_cost` to S8 `/internal/v1/llm-usage` (`capability='screener_nl_translate'`, `cost_source='provider'`) so the previously-untracked spend lands in the S8 ledger — logging failure NEVER fails the screener request (NFR-1) | Yes |
| GET | `/v1/fundamentals/screen/fields` | Available screener fields | No |
| GET | `/v1/fundamentals/timeseries` | Fundamental timeseries | No |
| GET | `/v1/fundamentals/economic-calendar` | Economic events (→ S7 temporal_events, passes `event_type=economic`) | Yes |

**Request body** for `POST /v1/ohlcv/batch` (PLAN-0049 T-A-1-05):

```python
{
    "requests": [
        {
            "instrument_id": str,    # required, ≤64 chars
            "timeframe": str,        # 1m | 5m | 15m | 30m | 1h | 4h | 1d | 1w | 1M (default "1d")
            "start": str | None,     # ISO date; defaults to lookback (3d for ≤5m, 30d for 1h, 90d otherwise)
            "end": str | None,
            "limit": int | None      # 1–2000
        },
        ...
    ]                                # max 50 entries (BP-026 — bounds external blast radius)
}
```

**Response** — partial-success batch (one entry per request, same order):

```python
{
    "results": [
        {"instrument_id": str, "timeframe": str, "bars": [...], "error"?: str},
        ...
    ],
    "fetched_at": str  # ISO-8601 UTC
}
```

Per-symbol failures populate `error` (e.g. `"market-data returned 502"`,
`"HTTPError: timeout"`) instead of failing the whole batch — partial success is
preferable to all-or-nothing for dashboard widgets.

### Entity & Knowledge Graph Endpoints (→ S7)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/entities/{entity_id}` | Entity enrichment detail (description, metadata, data_completeness). PLAN-0099: now also returns `health_score`, `aliases` (alias_text + alias_type), `top_relations` (authority-ranked, with direction + counterpart name + LLM summary) and `relation_count`. Recent article/mention counts are NOT here — use `/v1/entities/{id}/articles` (data lives in nlp_db, R9) | Yes |
| GET | `/v1/entities/{entity_id}/graph` | Entity relationship graph. Query params: `limit`, `min_confidence`, `semantic_mode`, `confidence_breakdown`, `focus_node` (PLAN-0074 Wave G: `confidence_breakdown` + `focus_node` now forwarded). PLAN-0099: edges now forward ALL S7 relation fields (`confidence` raw nullable, `semantic_mode`, `evidence_count`, `summary_authority`, `first/latest_evidence_at`, `relation_period_type`, `strongest_contra_score`, `latest_contra_at`, `support/corroboration/contradiction`); nodes gain `isin` (+ `industry`/`market_cap` from S7 EntitySummary) | Yes |
| GET | `/v1/relations/{relation_id}` | Full relation (edge) detail + evidence list (PLAN-0099). Pass-through → S7 `GET /api/v1/relations/{relation_id}`. Returns relation metadata, temporal validity, contra stats, current LLM summary, subject/object entity summaries, and up to `evidence_limit` (default 25, max 100) evidence items with `evidence_text`, `document_id`, `source_name`, `source_type`, `polarity`. Article title/url/published_at NOT included (no article metadata in intelligence_db — resolve `document_id` via `GET /v1/articles/{document_id}`, added 2026-06-11; `/v1/documents/{id}` is the S4 tenant-upload route and does NOT resolve pipeline docs) | Yes |
| GET | `/v1/entities/{entity_id}/events` | Entity-scoped temporal events (PLAN-0099) → S7 `GET /api/v1/temporal-events?entity_id=…` (filters via `entity_event_exposures`). Query params: `active_only` (default true), `event_type`, `limit`, `offset`. `entity_id` is injected from the path and cannot be overridden. Response: `{events: [...], total}` with computed `lifecycle_phase` | Yes |
| GET | `/v1/entities/{entity_id}/contradictions` | Entity contradictions | Yes |
| POST | `/v1/entities/similar` | Find similar entities (vector search) | No |
| GET | `/v1/entities/{entity_id}/intelligence` | Full entity intelligence aggregate (health_score, narrative, confidence_breakdown, key_metrics). Valkey-cached 60 s. Query params: `confidence_breakdown`, `focus_node` (PLAN-0074 Wave G) | Yes |
| GET | `/v1/entities/{entity_id}/narratives` | Paginated narrative version history. Query params: `limit`, `cursor` (PLAN-0074 Wave G) | Yes |
| POST | `/v1/entities/{entity_id}/narratives/generate` | Manually trigger narrative generation. Proxy-layer rate limit: 1 req/hr/entity/user via `set_nx` (BP-200). Returns 202. (PLAN-0074 Wave G) | Yes |
| GET | `/v1/entities/{entity_id}/paths` | Pre-computed multi-hop opportunity paths. Valkey-cached 5 min. Query params: `limit`, `min_score`, `min_hops`, `max_hops` (PLAN-0074 Wave G) | Yes |
| GET | `/v1/paths/between` | On-demand pairwise pathfinding — "is A connected to B, and how?" (PLAN-0112 W4). Proxies S7 `GET /api/v1/paths/between`. Query params: `source`, `target`, `max_hops` (1–3, default 3), `limit` (1–20, default 5), `meaningful_only`. Valkey-cached 5 min, tenant-scoped key `pathbetween:{tenant}:{source}:{target}:{max_hops}:{limit}:{meaningful_only}`. Forwards S7 status codes (400/404/422/503). | Yes |
| GET | `/v1/connections/weird` | Global "weird connections" feed (PLAN-0112 W5, FR-7). Proxies S7 `GET /api/v1/connections/weird`. Query params: `limit` (1–100, default 20), `offset` (≥0, default 0), `min_weirdness` (0–1, default 0.0), `since_days` (1–365, optional), `entity_type` (optional — None params omitted so S7 applies defaults). Returns `{connections[WeirdConnectionPublic], total, freshness_ts}`. Valkey-cached 5 min, tenant-scoped key `weird:{tenant}:{limit}:{offset}:{min_weirdness}:{since_days}:{entity_type}`. Forwards S7 status codes (422). | Yes |

### Entity-Context Chat Endpoints (→ S8 RAG-Chat)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/chat/entity-context` | Synchronous entity-context chat. Pre-validates `entity_id` (UUID) and `question` (non-empty) before proxying to S8. Error pass-through: 429/400/404/422/503 forwarded. (PLAN-0074 Wave G) | Yes |
| POST | `/v1/chat/entity-context/stream` | SSE streaming entity-context chat. Same validation as synchronous endpoint; streams chunks with `text/event-stream`. (PLAN-0074 Wave G) | Yes |

### Portfolio Endpoints (→ S1 Portfolio)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/portfolios` | List portfolios. `response_model=list[PortfolioResponse]` | Yes |
| GET | `/v1/portfolios/{id}/value-history` | Equity-curve snapshots (PLAN-0046 / T-46-5-01) | Yes |
| GET | `/v1/portfolios/{id}/exposure` | Invested / cash / leverage breakdown (PLAN-0046 / T-46-5-02). Response now includes `buying_power` (v1 semantics: equals `cash`, margin not modelled — 2026-06-10 sprint gap #5) | Yes |
| GET | `/v1/portfolios/{id}/twr` | **Flow-adjusted time-weighted return** (2026-06-10 sprint gap #3) — proxy to S1. Daily TWR series: sub-period returns between external cash flows, geometrically linked. Query: `days` (1-3650, default 90). Response: `{portfolio_id, from_date, to_date, points: [{date, twr_cum_pct, nav}], flow_days}` | Yes |
| GET | `/v1/portfolios/{id}/realized-pnl` | Realised P&L (FIFO, PLAN-0051 / T-A-1-04). Forwards `from`/`to`. Adds `Cache-Control: max-age=300` on 200. | Yes |
| GET | `/v1/portfolios/{id}/sector-breakdown` | Optimised sector breakdown (PLAN-0099 W4). Segments now carry `instrument_ids: [uuid]` (2026-06-10 sprint gap #2) so the frontend joins sector filters to holdings rows by id instead of name aliasing. Valkey-cached 60s | Yes |
| GET | `/v1/holdings/{portfolio_id}` | Holdings for a portfolio. Items include `asset_class` (instruments LEFT JOIN, nullable — 2026-06-10 sprint gap #1) | Yes |
| GET | `/v1/transactions` | List transactions (API-004: `portfolio_id` forwarded as `X-Portfolio-ID` header, not query param) | Yes |
| POST | `/v1/transactions` | Create transaction | Yes |
| GET | `/v1/portfolio/{id}/bundle` | **BFF bundle (PLAN-0070 C-1)** — collapses portfolio + holdings + transactions + value_history into 1 round-trip. Each leg degrades independently (`null` on failure). `_meta.partial=True` when any leg fails. `asyncio.wait_for(25s)`. UUID validation on `id`. `response_model=PortfolioBundleResponse` | Yes |

### Watchlist Endpoints (→ S1 Portfolio)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/watchlists` | List watchlists | Yes |
| POST | `/v1/watchlists` | Create watchlist | Yes |
| GET | `/v1/watchlists/{id}` | Get watchlist | Yes |
| DELETE | `/v1/watchlists/{id}` | Delete watchlist | Yes |
| POST | `/v1/watchlists/{id}/members` | Add entity to watchlist | Yes |
| DELETE | `/v1/watchlists/{id}/members/{entity_id}` | Remove entity from watchlist | Yes |
| GET | `/v1/watchlists/{id}/insights` | Composite insights: `{members_count, movers[{ticker, price, change_pct, news_count, alert_active}], sectors, news, alerts}`. `movers` sorted by `|change_pct|` DESC. Prices sourced from `/internal/v1/price/{iid}` (PriceSnapshot — includes 1D change). Cache-Control max-age=60. PLAN-0050 Wave B / QA iter-1 F-Q1-02. | Yes |

### Brokerage Connection Endpoints (→ S1 Portfolio, PRD-0022)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/brokerage-connections` | Initiate SnapTrade connection | Yes |
| GET | `/v1/brokerage-connections` | List connections | Yes |
| DELETE | `/v1/brokerage-connections/{id}` | Disconnect and revoke | Yes |
| GET | `/v1/brokerage-connections/{id}/callback` | OAuth callback | Yes |
| GET | `/v1/brokerage-connections/{id}/sync-errors` | List sync errors | Yes |

### Alert Endpoints (→ S10 Alert)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/alerts/pending` | List pending alerts | Yes |
| DELETE | `/v1/alerts/{alert_id}/ack` | Acknowledge per-user delivery row | Yes |
| PATCH | `/v1/alerts/{alert_id}/acknowledge` | Tenant-level ack (sets `alerts.acknowledged_at`); idempotent. PLAN-0051 T-D-4-02. `Cache-Control: no-store`. | Yes |
| PATCH | `/v1/alerts/{alert_id}/snooze` | Set `alerts.snooze_until` (body `{until: datetime}`; max 30 days out). PLAN-0051 T-D-4-02. `Cache-Control: no-store`. | Yes |
| GET | `/v1/alerts/history` | Paginated tenant alert history; query: `severity`, `entity_id`, `from`, `to`, `status` (`active\|acknowledged\|snoozed\|all`), `limit` (≤200), `offset`. PLAN-0051 T-D-4-02. `Cache-Control: no-store`. | Yes |

### Admin Endpoints (PLAN-0033)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/admin/llm-costs` | Cross-service LLM cost aggregation (S6+S7+S8 fan-out). Router prefix is `/v1/admin` (canonical); the `/api/v1/...` form also resolves via the `strip_api_prefix` middleware. | Yes (admin role) |

**Query params** for `/v1/admin/llm-costs`:
- `period` (optional, `YYYY-MM`, default: current UTC month)
- `provider` (optional, default: `all`; choices: `all`, `deepinfra`, `openrouter`, `gemini`, `ollama`)
- `breakdown` (optional, default: `provider`; choices: `provider`, `capability`, `day`)

**Behaviour**: Fan-out to S6/S7/S8 via `asyncio.gather`. Returns 200 with partial results if 1–2 services fail (failed services return `error` field); returns 503 only when all three fail. Requires `role == "admin"` in the authenticated user context.

### Email Preference Endpoints (→ S10 Alert)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/email/preferences` | Get email preferences | Yes |
| PUT | `/v1/email/preferences` | Update email preferences | Yes |

### Prediction Market Endpoints (→ S3 Market Data, PRD-0019)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/signals/prediction-markets` | List prediction markets | Yes |
| GET | `/v1/signals/prediction-markets/categories` | Category counts for currently-open markets | Yes |
| GET | `/v1/signals/prediction-markets/events` | List Polymarket event groups (`limit`/`offset`) — PLAN-0056 Wave E1 | Yes |
| GET | `/v1/signals/prediction-markets/events/{event_id}` | Single event group (404 if unknown) — PLAN-0056 Wave E1 | Yes |
| GET | `/v1/signals/prediction-markets/{id}` | Get market detail (now surfaces `liquidity` / `open_interest`) | Yes |
| GET | `/v1/signals/prediction-markets/{id}/history` | Market price history — forwards `interval` (1h/1d/1w) + `token_id` for per-token bars; `liquidity` on snapshots — PLAN-0056 Wave A4/E1 | Yes |
| GET | `/v1/signals/prediction-markets/{id}/trades` | Recent executed fills (`since`, `limit`) — PLAN-0056 Wave E1 | Yes |
| GET | `/v1/entities/{entity_id}/predictions` | Prediction markets referencing an entity, with polarity (proxies S7 `/api/v1/entities/{id}/predictions`; verbatim, no odds hydration — frontend hydrates via the market-detail route by `condition_id`) — PLAN-0056 Wave E1 | Yes |

> **Route ordering** (PLAN-0056 Wave E1): the literal `/events` and `/events/{event_id}` routes are registered **before** `/{market_id}` in `routes/intelligence.py` so FastAPI's registration-order matching does not treat `events` as a `market_id`.

**Query params** for `GET /v1/signals/prediction-markets`:
- `status` (optional, default `open`; choices: `open`, `resolved`, `cancelled`, `all`)
- `query` (optional, max 200 chars) — case-insensitive `question ILIKE` filter
- `category` (optional, max 50 chars) — PLAN-0049 T-C-3-03.  Suggested values: `macro`, `politics`, `sports`, `crypto`, `general` (non-binding — backend does case-insensitive equality only and never validates the enum, so future Polymarket tags pass through without a code change).  Rows with `category IS NULL` never match a filter.
- `limit` (optional, 1–200, default 50)
- `offset` (optional, default 0)

### Briefing Endpoints (→ S8 RAG/Chat, stub)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/briefings/morning` | AI morning briefing — augmented with a best-effort `prediction_signals` leg (top open prediction markets from S3; `null` on failure, never breaks the brief) — PLAN-0056 Wave E1 | Yes |
| POST | `/v1/briefings/morning/generate` | Force-regenerate morning brief (proxies S8 `POST /api/v1/briefings/morning/generate`; 202 + queued; 503 on S8 timeout) | Yes |
| GET | `/v1/briefings/instrument/{entity_id}` | Instrument briefing (stub) | Yes |

### Dashboard Snapshot (PLAN-0070 C-2)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/dashboard/snapshot` | **BFF bundle** — collapses 6 dashboard page queries into 1 round-trip: news (top 8), heatmap (11 sectors), prediction_markets (top 5), earnings_calendar (7-day), alerts (top 10), morning_brief. Each leg degrades independently (`null` on failure). `_meta.partial=True` when any leg fails. `asyncio.wait_for(20s)`. `response_model=DashboardSnapshotResponse` | Yes |

### Search & Signals Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/search` | Full-text document search (proxies → S6 /api/v1/search/documents). Params forwarded verbatim: q, entity_id (multi), scope, source_type, date_from, date_to, date_preset, page, page_size. Authenticated only. PLAN-0064 W6. | Yes |
| GET | `/v1/search/instruments` | Search instruments by name/ticker. `response_model=list[InstrumentSearchResult]` | No |
| GET | `/v1/signals/ai` | Enriched AI-signals feed (2026-06-10 overhaul, `routes/signals.py`). Proxies S6 `/api/v1/signals` (outbox `nlp.signal.detected.v1`), then: drops nil-UUID entities, dedups per (entity_id, doc_id) keeping the most informative claim (non-neutral polarity > confidence), batch-enriches via S7 KG (`ticker` + `entity_name`; KG-unknown entities dropped, KG outage degrades gracefully) and S5 content-store (article title/url/source/published_at). `label` = Avro polarity when decisive, else signal_type heuristic. Each item: `signal_id, entity_id, ticker, entity_name, label, polarity, signal_type, signal_type_label, score` (LLM extraction confidence 0–1, NOT a price prediction), `market_impact_score` (observed day-0 abnormal move; 0 = unlabelled), `article_title, article_url, source_name, published_at, created_at`. `?limit=` 1–50 (default 8; over-fetches 4× from S6 for dedup headroom). NOTE: a dead legacy handler for the same path remains in `routes/market.py`; `signals_router` is registered first and wins (guarded by test). | Yes |

### Feedback Endpoints (→ S1 Portfolio, PLAN-0052 Wave D)

Thin proxy from `/v1/feedback/*` → portfolio service `/api/v1/feedback/*`. Anonymous routes accept unauthenticated requests; the gateway issues a system JWT for those.

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/feedback/submissions` | Create bug/feature/UX/design feedback | Optional (anon needs `email`) |
| GET | `/v1/feedback/submissions` | List submissions (admin) or own (`?mine=true`) | Yes |
| GET | `/v1/feedback/submissions/anonymous` | List submissions made by unauthenticated users (anon-tenant) | Admin |
| GET | `/v1/feedback/submissions/{id}` | Read one submission (admin or owner) | Yes |
| PATCH | `/v1/feedback/submissions/{id}` | Update status / tags / assigned_to | Admin |
| DELETE | `/v1/feedback/submissions/{id}` | Hard-delete submission (returns 204) | Admin |
| POST | `/v1/feedback/nps` | Submit NPS score (rate-limited to one per 30 days, application-layer) | Yes |
| GET | `/v1/feedback/nps/aggregate?days=30` | Promoter / passive / detractor counts + NPS score | Admin |
| GET | `/v1/feedback/features` | Public roadmap (vote-sorted) | Public |
| POST | `/v1/feedback/features` | Submit a new feature request | Yes |
| PATCH | `/v1/feedback/features/{id}` | Update status / category / is_public on a feature | Admin |
| POST | `/v1/feedback/features/{id}/vote` | Idempotent upvote | Yes |
| POST | `/v1/feedback/micro-survey` | Thumbs-up/down with `survey_key` (used by docs widget) | Optional (anon ok) |
| GET | `/v1/feedback/beta-program/enrollment` | Read user's beta-program state | Yes |
| PATCH | `/v1/feedback/beta-program/enrollment` | Toggle enrolled / programs list | Yes |

PII redaction: all user-supplied free-text fields (`description`, `comment`, `console_logs`) are scrubbed for Bearer/JWT/API-key/email/CC/SSN patterns before persist (see `services/portfolio/src/portfolio/security/pii_redaction.py`).

---

## Middleware Stack

Starlette runs middleware **outermost-first**, i.e. the reverse of the
`app.add_middleware()` registration order. The **request-time execution order**
(per `app.py` comment block) is:

| Run order | Middleware | Purpose |
|-----------|-----------|---------|
| 1 | `OIDCAuthMiddleware` | Validate Zitadel RS256 access token → `request.state.user` (runs first so user state exists for everything below) |
| 2 | `InternalJWTIssuerMiddleware` | Issue RS256 `X-Internal-JWT` for downstream services using the resolved user |
| 3 | `RateLimitMiddleware` | Sliding-window counter via Valkey; sub-tier buckets; fail-closed when Valkey unconfigured (D-001) |
| 4 | `CORSMiddleware` | Explicit origin allowlist (never `*`), credentials allowed |
| 5 | OTel middleware | Distributed tracing spans (when `OTLP_ENDPOINT` set) |
| 6 | Prometheus middleware | Request count/latency metrics (`add_prometheus_middleware`) |
| 7 | `SecurityHeadersMiddleware` | X-Frame-Options, X-Content-Type-Options, Referrer-Policy, HSTS |
| 8 | `RequestIdMiddleware` | Validate/generate `X-Request-ID`, bind to structlog (outermost — wraps every response) |

> The registration order in `app.py` is the inverse: `RequestId → SecurityHeaders
> → Prometheus → OTel → CORS → RateLimit → InternalJWTIssuer → OIDCAuth` (OIDCAuth
> added last → outermost → runs first).

A separate `strip_api_prefix` HTTP middleware rewrites inbound `/api/v1/...`
paths to `/v1/...` before routing, so both prefixes resolve to the same handler
(Cloudflare/Next.js rewrite compatibility — Dashboard Regression #5).

---

## Authentication Architecture (PRD-0025)

### External Auth — OIDC/PKCE (Zitadel)

1. **Login**: `GET /v1/auth/login` generates PKCE state + S256 challenge, stores in Valkey (`auth:pkce:{state}`, TTL 10min), redirects to Zitadel authorization endpoint.
2. **Callback**: `GET /v1/auth/callback` exchanges code for tokens, validates access token, provisions user in S1 via system JWT, sets httpOnly refresh_token cookie.
3. **Refresh**: `POST /v1/auth/refresh` reads httpOnly cookie, exchanges at Zitadel token endpoint.
4. **Logout**: `POST /v1/auth/logout` revokes refresh_token at Zitadel, clears cookie, invalidates Valkey cache.

PKCE state uses **atomic GETDEL** (not GET+DEL) to prevent state replay attacks (BP-146).

### Internal Auth — RS256 JWT

S9 signs every proxied request with an RS256 internal JWT:

| JWT Type | TTL | Use Case |
|----------|-----|----------|
| User JWT | 5 min | Standard authenticated request forwarding |
| System JWT | 60 sec | S9 → S1 user provisioning during OIDC callback |
| WebSocket JWT | 30 sec | Short-lived token for direct WS connection to S10 |

**Backend verification**: All services (S1–S8, S10) run `InternalJWTMiddleware` which fetches S9's public key from `GET /internal/jwks` at startup and validates every non-health request.

**JWT payload** (user type):
```json
{
  "iss": "worldview-gateway",
  "sub": "<user-uuid>",
  "tenant_id": "<tenant-uuid>",
  "oidc_sub": "<zitadel-sub>",
  "role": "user",
  "jti": "<uuid7>",
  "iat": 1700000000,
  "exp": 1700000300,
  "kid": "<sha256-thumbprint>"
}
```

### Service-to-Service Auth — gateway accepts its OWN internal JWT (2026-07-16, fix/gateway-s2s-auth)

Backend services proxy user requests **back through S9** (e.g. rag-chat's chat
tools calling `/v1/signals/prediction-markets`, screener, top-movers, economic/
earnings calendars, S7 intelligence, S10). They forward the gateway-issued
internal JWT in the `X-Internal-JWT` header. Those gateway routes gate on
`request.state.user`, but `OIDCAuthMiddleware` historically populated it **only**
from a real Zitadel `Authorization: Bearer` token — so every such S2S call
returned **401** and the chat data tools silently degraded to `[]` (the
`FIX-LIVE-S` Bearer shim was a documented prod no-op).

`OIDCAuthMiddleware` now runs a **second, lower-precedence** step: if no real
Zitadel user was established, it accepts the gateway's **own** internal JWT as a
trusted service principal.

**Verification (strict — reuses `jwt_utils.decode_internal_jwt`, the gateway's
own signer/verifier, so it cannot drift from what S9 mints):**

- **Signature**: RS256 against the gateway's own public key
  (`app.state.rsa_public_key`). The private half is the ONLY key that mints
  internal JWTs → a forged token cannot pass. `alg=none` / HS256-confusion are
  rejected (algorithm list is `["RS256"]` only).
- **`iss`** must equal `worldview-gateway`.
- **`aud`** must equal `worldview-internal` — **required and validated**. A token
  minted for a different audience, or one that **omits `aud` entirely** (the
  known DEF-002 minter gap), is **rejected**. Every gateway-minted token carries
  `aud`, so S2S callers forwarding gateway tokens are unaffected; any
  aud-omitting minter is correctly refused rather than silently trusted.
- **`exp`** (plus `iat` + `jti`) required and validated → expired tokens rejected.

**Safety properties:**

- **Precedence**: only runs when `request.state.user is None` after the Zitadel
  path → the real-user OIDC path is unchanged.
- **No fail-open**: on ANY verification failure `request.state.user` stays `None`
  and the route returns its normal 401.
- **No privilege escalation**: the principal carries exactly the `sub` /
  `tenant_id` / `role` the gateway itself signed. A forwarded user JWT
  re-authenticates that same user with that user's own role; a service JWT
  carries `role="system"` (never `admin`). The resulting `request.state.user`
  dict is flagged `service_principal: true` for observability.
- **Public paths** (`_AUTH_SKIP_PATHS`) short-circuit before this step, so they
  stay unauthenticated even when a valid `X-Internal-JWT` is present.
- **System principals are read-only** (least-privilege guard, security review
  2026-07-16): a `role="system"` service-account token (minted by
  `issue_service_jwt` for background/machine callers) is refused on **mutating
  methods** (`POST`/`PUT`/`PATCH`/`DELETE`) against the sensitive
  financial/account mutation prefixes in `_S2S_SYSTEM_MUTATION_PREFIXES`
  (`/v1/transactions`, `/v1/brokerage-connections`, `/v1/portfolios`,
  `/v1/watchlists`, `/v1/alerts`, `/v1/alert-rules`, `/v1/email/preferences`,
  `/v1/documents`) → `request.state.user` stays `None` (route 401s). A machine
  identity gets **read-only** access at the gateway. This does NOT affect POST
  *read* endpoints (screener/batch-quotes/search — different prefixes), GET
  reads on those prefixes, brief-generation workers (`/v1/briefings/*` is not
  listed), or a **forwarded user** token (`role="user"`/`"admin"`), which keeps
  the user's own authority (e.g. rag-chat's user-initiated create-alert). Real
  writes always arrive with a Zitadel Bearer (frontend → S9 only) which takes
  precedence and is never a service principal.

Coexists with any direct backend→backend paths (e.g. rag-chat's direct
market-data prediction call): this restores the **gateway-proxied** path
generally for all user-gated routes.

### Legacy Header Removal (2026-04-18)

The `_auth_headers()` helper in `routes/helpers.py` no longer forwards `X-Tenant-Id` or `X-User-Id` headers to downstream services. All backends now extract identity exclusively from the `X-Internal-JWT` token (verified via `InternalJWTMiddleware`). This eliminates the header-spoofing attack vector (see BP-161).

### Public Paths (skip OIDC validation)

`/v1/auth/*`, `/healthz`, `/readyz`, `/metrics`, `/internal/jwks`

---

## Rate Limiting

Tiered, sliding-window counters keyed in Valkey. All limits are wired from
`Settings` into `RateLimitMiddleware` in `app.py`:

- **Authenticated (read/general)**: `RATE_LIMIT_REQUESTS` — **default 2000 req/min**
  per `user_id` (raised again to absorb multi-panel workspace fan-out; the
  in-code middleware comments still reference the older 300 figure). Key: `user_id`.
- **Financial mutations**: `RATE_LIMIT_FINANCIAL_MUTATION_REQUESTS` — default 30
  req/min. Applies to authenticated `POST/PUT/DELETE/PATCH` on financial paths
  (creating/deleting transactions, etc.) in a **dedicated Valkey bucket** so a
  stolen token cannot fire the full read budget at mutating endpoints (PLAN-0094 W1).
- **Public feedback**: `RATE_LIMIT_PUBLIC_FEEDBACK_REQUESTS` — default 10 req/min
  for `/v1/feedback/*` (anonymous-friendly surface).
- **Export endpoints**: dedicated low-rate bucket for `GET /*/export` (SEC-103).
- **Unauthenticated**: `RATE_LIMIT_UNAUTHENTICATED_REQUESTS` — default 20 req/min
  per IP hash (`sha256(ip)[:16]`).
- **Fail-closed (D-001)**: when Valkey is **unconfigured / `None`** at request
  time the limiter rejects with 503 (it will not self-heal and must not run
  wide-open). Note: the OIDC user-cache read inside `OIDCAuthMiddleware` is
  independently **fail-open** (a transient Valkey read error rebuilds identity
  from token claims rather than locking users out).
- 429 responses include `Retry-After` header.

---

## Caching Architecture

### Valkey Cache

- **Request cache**: Per-endpoint response caching with configurable TTL per route
- **User identity cache**: `auth:user:{sub}` (TTL: 1 hour)
- **PKCE state**: `auth:pkce:{state}` (TTL: 10 min, atomic GETDEL)
- **Rate limit counters**: `rl:v1:{type}:{key}` (TTL: window seconds)

### In-Flight Deduplication

Concurrent identical requests share a single upstream call via `asyncio.Future` dedup:

```python
_inflight: dict[str, asyncio.Future] = {}

async def cached_fetch(key, ttl, fetcher):
    # Check Valkey → check in-flight → single upstream call → cache result
```

Negative caching (120s) prevents thundering herd on upstream failures.

---

## Configuration

All env vars are prefixed with `API_GATEWAY_`:

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `HOST` | `0.0.0.0` | No | Bind address |
| `PORT` | `8000` | No | Bind port |
| `DEBUG` | `false` | No | Debug mode |
| `VALKEY_URL` | `redis://localhost:6379/0` | No | Valkey connection |
| `OIDC_ISSUER_URL` | — | **Yes** | Zitadel issuer URL |
| `OIDC_CLIENT_ID` | — | **Yes** | Zitadel client ID |
| `OIDC_CLIENT_SECRET` | — | **Yes** | Zitadel client secret (SecretStr) |
| `OIDC_AUDIENCE` | — | **Yes** | Token audience |
| `OIDC_DISCOVERY_OPTIONAL` | `false` | No | Allow startup without Zitadel (dev/test) |
| `INTERNAL_JWT_PRIVATE_KEY` | — | **Yes** | PEM RSA-2048 private key (SecretStr) |
| `INTERNAL_JWT_PUBLIC_KEY` | — | **Yes** | PEM RSA-2048 public key |
| `JWT_KEY_VERSION` | `v1` | No | Key-rotation version tag embedded in signed JWTs |
| `JWKS_GRACE_HOURS` | `24` | No | Grace window during which a rotated-out public key still verifies |
| `FRONTEND_URL` | `http://localhost:5173` | No | CORS + redirect origin |
| `COOKIE_SECURE` | `true` | No | Defaults `true` (PLAN-0030 F-013); set `false` only in local dev |
| `PORTFOLIO_URL` | `http://localhost:8001` | No | S1 URL |
| `MARKET_INGESTION_URL` | `http://localhost:8002` | No | S2 URL |
| `MARKET_DATA_URL` | `http://localhost:8003` | No | S3 URL |
| `CONTENT_INGESTION_URL` | `http://localhost:8004` | No | S4 URL |
| `CONTENT_STORE_URL` | `http://localhost:8005` | No | S5 URL |
| `NLP_PIPELINE_URL` | `http://localhost:8006` | No | S6 URL |
| `KNOWLEDGE_GRAPH_URL` | `http://localhost:8007` | No | S7 URL |
| `RAG_CHAT_URL` | `http://localhost:8008` | No | S8 URL |
| `ALERT_URL` | `http://localhost:8010` | No | S10 HTTP URL |
| `ALERT_WS_URL` | `ws://localhost:8010` | No | S10 WebSocket base URL (separate from HTTP URL for WS routing) |
| `RATE_LIMIT_REQUESTS` | `2000` | No | Authenticated read/general rate limit per minute (raised again for multi-panel workspace fan-out) |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | No | Rate limit window |
| `RATE_LIMIT_FINANCIAL_MUTATION_REQUESTS` | `30` | No | Per-minute limit for authenticated financial mutations (POST/PUT/DELETE/PATCH) — separate bucket |
| `RATE_LIMIT_UNAUTHENTICATED_REQUESTS` | `20` | No | Per-minute limit per IP hash for unauthenticated requests |
| `RATE_LIMIT_PUBLIC_FEEDBACK_REQUESTS` | `10` | No | Per-minute limit for `/v1/feedback/*` |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3001` | No | Comma-separated allowed origins (SEC-008: port 3001 is worldview-web, not 3000) |
| `APP_ENV` | `development` | No | Environment guard: `development`, `staging`, or `production`. When `production`, `POST /v1/auth/dev-login` returns 403 regardless of OIDC config. |
| `DEV_ADMIN_EMAILS` | `""` | No | Comma-separated emails that receive `role=admin` in dev-login JWTs (dev/staging only; ignored when `APP_ENV=production`) |
| `SERVICE_ACCOUNT_TOKEN` | `""` | No | Shared secret for `POST /internal/v1/service-token`. Must be set in production for background workers to mint RS256 JWTs. |
| `DEEPINFRA_API_KEY` | `""` | No | DeepInfra key (SecretStr) — used by gateway-side LLM helpers (e.g. chat-safety pre-checks) |
| `PREWARM_ENABLED` | `false` | No | Opt-in switch for the bundle pre-warmer worker (see "Workers") |
| `PREWARM_ENTITY_IDS` | `[]` | No | Comma/JSON list of hot entity UUIDs to keep warm |
| `PREWARM_INTERVAL_SECONDS` | `240` | No | Pre-warm loop interval |
| `PREWARM_API_BASE_URL` | `http://localhost:8000` | No | Base URL the worker calls (its own gateway) |
| `PREWARM_CONCURRENCY` | `3` | No | Max parallel pre-warm fan-out |
| `PREWARM_REQUEST_TIMEOUT_SECONDS` | `30.0` | No | Per-request timeout for pre-warm calls |
| `SERVICE_NAME` | `api-gateway` | No | structlog service name |
| `LOG_LEVEL` | `INFO` | No | Logging level |
| `LOG_JSON` | `true` | No | JSON-formatted logs |
| `OTLP_ENDPOINT` | `""` | No | OpenTelemetry collector endpoint |

---

## S9 Reliability Guarantees (PLAN-0070)

**Timeouts** — every composition endpoint is wrapped in `asyncio.wait_for`:

| Endpoint | Budget |
|----------|--------|
| `GET /v1/instruments/{id}/page-bundle` | 20 s |
| `GET /v1/portfolio/{id}/bundle` | 25 s |
| `GET /v1/dashboard/snapshot` | 20 s |
| `GET /v1/market/heatmap` | 15 s |
| `GET /v1/watchlists/{id}/insights` | 15 s |
| `GET /v1/ohlcv/batch` | 30 s |

On timeout: HTTP 504 with `{"detail": "composition timeout"}`.

**Retry logic** — `_checked_get()` retries 3× with backoff (0.1 s, 0.5 s, 1.5 s) on 500/503 responses. `_checked_post()` does NOT retry (idempotency unsafe).

**JWT factory** — `make_headers=lambda: _auth_headers(request)` is passed to every `asyncio.gather` fan-out so each parallel downstream call gets a fresh JWT with a unique JTI, preventing JTI replay detection failures.

**Pydantic response_model** — 25+ S9 routes have `response_model=` annotations generating named OpenAPI component schemas. The committed spec is at `infra/contracts/s9-openapi.json`; TypeScript types at `apps/worldview-web/types/generated/api.ts`.

**Schemas package** — `services/api-gateway/src/api_gateway/schemas/` contains 18 modules:
`common`, `instruments`, `market`, `news`, `portfolios`, `alerts`, `watchlists`,
`screener`, `prediction_markets`, `fundamentals`, `dashboard`, `dashboard_bundle`,
`intelligence`, `intelligence_bundle`, `narratives`, `paths`, `entity_chat`,
`financials_bundle`. All schemas use `ConfigDict(extra="allow")`.

---

## Internal Modules

> **History**: `routes/proxy.py` (4319 lines) was split into focused domain
> routers (PLAN-0089 B-3). There is **no `proxy.py` anymore** — routes live in
> the per-domain modules below. The combined router is assembled in
> `routes/__init__.py` and imported by `app.py` as `main_router`.

```
services/api-gateway/src/api_gateway/
├── app.py                   # FastAPI app factory, lifespan (OIDC discovery, RSA keypair,
│                            #   httpx clients, Valkey), middleware wiring, /api/v1→/v1 strip
├── config.py                # Settings (all env vars below)
├── domain.py                # OIDCProviderConfig, InternalJWTClaims dataclasses
├── middleware.py            # RequestId, SecurityHeaders, OIDCAuth, InternalJWTIssuer, RateLimit
├── oidc.py                  # OIDC discovery, JWKS parse, RSA key utilities
├── jwt_utils.py             # RS256 JWT issuance (user/system/ws/service)
├── pkce.py                  # PKCE verifier/challenge/state + Valkey storage
├── resolution.py            # resolve_security_id: ticker | UUID → canonical instrument_id
│                            #   (UUID short-circuit → S3 lookup → S7 KG alias fallback, 1h TTL)
├── clients.py               # Legacy aggregate httpx client surface (re-exports clients/*)
├── clients/                 # Per-domain typed httpx clients
│   ├── base.py              # BaseClient: _checked_get (3× retry on 500/503), _checked_post (no retry)
│   ├── portfolio.py · market.py · news.py · instrument.py
│   ├── dashboard.py · dashboard_bundle.py · alert_rules.py
├── application/use_cases/   # BFF composition use cases (hexagonal)
│   ├── company_overview.py · instrument_page_bundle.py
│   ├── portfolio_bundle.py · dashboard_snapshot.py
├── workers/                 # Out-of-process background workers (opt-in)
│   └── bundle_prewarmer_main.py  # PLAN-0099 R3 cache pre-warmer (see "Workers" below)
├── schemas/                 # 18 Pydantic response-schema modules (all ConfigDict(extra="allow"))
│   ├── __init__.py · common.py · instruments.py · market.py · news.py
│   ├── portfolios.py · alerts.py · watchlists.py · screener.py · fundamentals.py
│   ├── prediction_markets.py · dashboard.py · dashboard_bundle.py
│   ├── intelligence.py · intelligence_bundle.py · narratives.py · paths.py
│   ├── entity_chat.py · financials_bundle.py
└── routes/
    ├── __init__.py          # Combines 10 domain routers into main_router (registration order matters)
    ├── auth.py              # 8 OIDC auth endpoints (login/callback/refresh/logout/me/register/ws-token/dev-login)
    ├── health.py            # /healthz, /readyz
    ├── internal.py          # GET /internal/jwks, POST /internal/v1/service-token
    ├── admin_costs.py       # GET /v1/admin/llm-costs (registered separately in app.py)
    ├── risk_metrics.py      # /v1/portfolios/{id}/risk-metrics (registered before main_router)
    ├── alerts.py · chat.py · chat_safety.py (chat helpers) · content.py
    ├── dashboard.py · instruments.py · intelligence.py · market.py
    ├── portfolio.py · signals.py · helpers.py (_auth_headers/_system_headers/proxy_json_response)
```

**Route registration order** (`app.py`): `health → internal → auth → admin_costs →
risk_metrics → main_router`. Within `main_router` (`routes/__init__.py`):
`alerts → chat → dashboard → content → instruments → intelligence → signals →
market → portfolio`. Order is load-bearing — `signals_router` is registered
before `market_router` so its enriched `GET /v1/signals/ai` wins over the dead
legacy handler in `market.py`; literal-segment routes (`/entities/similar`,
`/instruments/lookup`) are registered before parameterised ones.

**Total proxy/composition routes**: ~186 route decorators across the domain
routers (was "96 in proxy.py").

---

## Kafka Integration

**None.** S9 is stateless and does not produce or consume Kafka topics. There is
no Kafka consumer/producer infrastructure in `src/api_gateway/`. All messaging is
via synchronous HTTP to downstream services, with Valkey for caching/state.

> **Planned (not built)**: `resolution.py` notes a future `entity.dirtied.v1`
> consumer to invalidate the resolution cache on entity renames (tracked as
> PLAN-0089 F2 step 6). Until then the resolution cache is TTL-only.

## Workers

The gateway ships one **opt-in, out-of-process** background worker:

| Worker | Entry point | Purpose |
|--------|-------------|---------|
| Bundle pre-warmer | `python -m api_gateway.workers.bundle_prewarmer_main` | PLAN-0099 R3 — periodically re-fetches the Intelligence-tab composite bundle for a configured set of hot entity IDs so the underlying S7 intel (60 s) / paths (300 s) caches stay warm (first real request hits ~88 ms instead of a cold 4–10 s fan-out). |

The worker refuses to start unless `API_GATEWAY_PREWARM_ENABLED=true` **and**
`API_GATEWAY_PREWARM_ENTITY_IDS` has ≥1 UUID (default posture is OFF — dev/test/CI
never fire it). It mints its own short-lived RS256 service-account JWT using the
gateway's private key and sends it as both `X-Internal-JWT` and
`Authorization: Bearer`. Tuned by the `PREWARM_*` env vars (see Configuration).

---

## Security Headers

Every response includes (via `SecurityHeadersMiddleware`):

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-XSS-Protection: 0`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `Strict-Transport-Security: max-age=31536000` (production only, when `COOKIE_SECURE=true`)

### OIDC Callback Error Sanitization (SEC-003)

The `/v1/auth/callback` handler sanitizes `error` and `error_description` query params before JSON reflection:

- **`error`**: Only known RFC 6749 error codes pass through (e.g. `access_denied`, `invalid_scope`). Unknown values become `"unknown_error"`.
- **`error_description`**: Non-alphanumeric special characters are stripped by regex `[^a-zA-Z0-9 _.,!?()\-]`. Truncated to 200 chars.

---

## Error Standardization

```json
{
    "error": {
        "code": "NOT_FOUND",
        "message": "Instrument with ID abc123 not found",
        "status": 404,
        "details": {}
    }
}
```

- **4xx**: Descriptive message from downstream
- **5xx**: Generic "Internal server error" (never leak internals)
- **429**: Includes `Retry-After` header

---

### Portfolio Risk Metrics (Composition — PLAN-0046)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/portfolios/{id}/risk-metrics` | Drawdown, volatility, Sharpe, Sortino, beta vs SPY. Pure S9 composition over S1 value-history + S3 SPY OHLCV. Query param: `lookback_days` (5-3650, default 90 — floor lowered 10→5 on 2026-06-10, sprint gap #4: short windows return 200 with nulled return-based metrics + `data_quality.status="insufficient_data"` instead of 422; `period_return`/`cagr` still compute from 2+ points). All metrics independently nullable. | Yes |

**Response fields**: `drawdown_max`, `drawdown_current`, `volatility_annualized`, `sharpe`,
`sortino`, `beta_vs_spy`, `n_returns`, `as_of`, `lookback_window`, `data_quality`.

**`data_quality.status` values**:
- `ok` — sufficient data and SPY available
- `insufficient_data` — fewer than 10 daily returns
- `benchmark_unavailable` — SPY OHLCV missing
- `data_anomaly_detected` — contaminated-zero in value series (all metrics suppressed)

### Additional Portfolio Endpoints (S9 → S1)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/portfolios` | Create portfolio | Yes |
| DELETE | `/v1/portfolios/{id}` | Archive portfolio | Yes |
| GET | `/v1/portfolios/{id}/holding-lots` | FIFO lot breakdown per instrument | Yes |
| GET | `/v1/portfolios/{id}/concentration` | Sector/asset class concentration | Yes |
| GET | `/v1/portfolios/{id}/performance` | Performance metrics (Calmar, win-rate) | Yes |
| GET | `/v1/portfolios/{id}/transactions` | Transactions nested under portfolio | Yes |

**Transaction note**: `GET /v1/transactions` forwards `portfolio_id` as `X-Portfolio-ID`
header (not query param) to S1 — this is by design (API-004).

### Additional Brokerage Endpoints (S9 → S1)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/brokerage-connections/{id}/balance` | Cash/buying-power (best-effort) | Yes |
| POST | `/v1/brokerage-connections/{id}/sync` | Trigger immediate background sync (202 Accepted) | Yes |

### Prediction Market Categories

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/v1/signals/prediction-markets/categories` | Category counts for currently-open markets | Yes |

### Additional Watchlist Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| PATCH | `/v1/watchlists/{id}` | Rename watchlist | Yes |
| GET | `/v1/watchlists/{id}/members` | List watchlist members | Yes |

### Additional Intelligence/Knowledge Graph Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/search/relations` | ANN search over relation summaries (proxy → S7) | Yes |
| POST | `/v1/claims/search` | Search analyst claims by entity + filters (proxy → S7) | Yes |

### Proposal Confirmation (PLAN-0082)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/chat/proposals/{proposal_id}/confirm` | Confirm a pending LLM-proposed action (proxied to S8) | Yes |

---

## Known Stubs & TODOs

| Endpoint | Status | Reason |
|----------|--------|--------|
| `GET /v1/briefings/morning` | Stub | S8 briefing feature not yet implemented |
| `GET /v1/briefings/instrument/{id}` | Stub | S8 briefing feature not yet implemented |
| `GET /v1/signals/ai` (legacy copy in `routes/market.py`) | Dead code | Superseded by `routes/signals.py` (registered first); remove the market.py handler in a follow-up owned by the market routes workstream |
| `GET /v1/quotes/stream` | Stub | Returns 503 `not_implemented` (+`Retry-After`) — streaming quotes land in PLAN-0059 Wave D; poll `/v1/quotes/{id}` until then |
| WebSocket proxy | N/A | S9 cannot transparently proxy WS; clients connect to S10 directly with 30s token from `GET /v1/auth/ws-token` |

---

## Observability

- **Metrics**: Request count/latency by route, cache hit/miss ratio, rate limit triggers, upstream service latency
- **Log fields**: `service=gateway`, `route`, `upstream_service`, `cache_status`, `tenant_id`
- **Tracing**: OpenTelemetry spans for every upstream call

---

## Testing

| Type | What | Command |
|------|------|---------|
| Unit | Route logic, middleware, JWT utils, PKCE, config | `make test` |
| Integration | Cross-cutting security (headers, CORS, rate limit, JWKS) | `make test-integration` |
| Lint | Ruff + mypy | `make lint` |

**Test suite**: ~74 test files (unit + integration + contract + e2e), ~700 tests passing.

---

## How to Run Locally

### Option A — Full Docker Compose (Recommended)

```bash
make dev       # launches full platform with MailHog, pgweb, kafka-ui
make seed      # load sample data (seeds a demo user)
make fetch-secrets   # pull API keys and OIDC credentials from worldview-config
```

### Option B — Dev Mode (No Zitadel)

When `OIDC_DISCOVERY_OPTIONAL=true` and no Zitadel is configured, the gateway
starts in **dev mode**:

- `POST /v1/auth/dev-login` is enabled (returns JWT for the seed demo user)
- The frontend's login page automatically shows a "Dev Login" button
- `OIDCAuthMiddleware` passes through requests (no Zitadel validation)

```bash
cd services/api-gateway

# Generate RSA keypair for internal JWT signing
./scripts/generate-internal-keypair.sh
# → writes INTERNAL_JWT_PRIVATE_KEY and INTERNAL_JWT_PUBLIC_KEY to stdout

# Configure
cat > configs/.env << 'EOF'
API_GATEWAY_OIDC_DISCOVERY_OPTIONAL=true
API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY="<generate with: openssl genrsa 2048>"
API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY="<extract with: openssl rsa -pubout>"
API_GATEWAY_VALKEY_URL=redis://localhost:6379/0
API_GATEWAY_PORTFOLIO_URL=http://localhost:8001
API_GATEWAY_COOKIE_SECURE=false
EOF

make run    # uvicorn on port 8000

# Test dev-login:
curl -X POST http://localhost:8000/v1/auth/dev-login
# → {"access_token": "...", "user": {...}}
```

### Option C — Full Zitadel Integration

1. Create a Zitadel Cloud project at https://zitadel.cloud
2. Create a "Web App" application with PKCE (not client secret)
3. Add redirect URI: `http://localhost:8000/v1/auth/callback`
4. Set env vars:

```bash
API_GATEWAY_OIDC_ISSUER_URL=https://<your-domain>.zitadel.cloud
API_GATEWAY_OIDC_CLIENT_ID=<your-client-id>
API_GATEWAY_OIDC_CLIENT_SECRET=<your-client-secret>
API_GATEWAY_OIDC_AUDIENCE=<your-audience>
API_GATEWAY_OIDC_DISCOVERY_OPTIONAL=false
```

---

## Runbook

### JWKS Endpoint

All backend services fetch S9's public key at startup:
```
GET /internal/jwks
→ {"keys": [{"kty":"RSA","use":"sig","kid":"...","n":"...","e":"AQAB"}]}
```

If a backend cannot reach this endpoint at startup, it retries 3× with 3 s sleep.
After 3 failures, `InternalJWTMiddleware._public_key` is `None` and the service
**passes all requests through** (test-safe, not production-safe).

### Service Token for Background Workers

Workers that need to make authenticated calls to backend services use the service
account token endpoint:

```bash
curl -X POST http://localhost:8000/internal/v1/service-token \
  -H "Content-Type: application/json" \
  -d '{"service_name": "my-worker", "secret": "<API_GATEWAY_SERVICE_ACCOUNT_TOKEN>"}'
# → {"access_token": "...", "expires_in": 300}
```

To add a new worker:
1. Add its name to `_ALLOWED_SERVICE_NAMES` in `routes/internal.py`
2. Set `API_GATEWAY_SERVICE_ACCOUNT_TOKEN` on S9
3. Set the same token value on the worker service

### Registering New Backend Services

Add the service URL to S9's config (e.g. `API_GATEWAY_NEW_SERVICE_URL=http://...`)
and add a typed httpx client in `clients.py`.

---

## Testing

| Type | What | Command |
|------|------|---------|
| Unit | Route logic, middleware, JWT utils, PKCE, config | `make test` |
| Integration | Cross-cutting security (headers, CORS, rate limit, JWKS) | `make test-integration` |
| Lint | Ruff + mypy | `make lint` |

**Test suite**: ~74 test files (unit + integration + contract + e2e), ~700 tests passing.

Integration tests validate:
- Security headers on all responses
- JWKS endpoint accessible without auth
- Rate limit 429 after threshold
- CORS preflight returns explicit methods (never `*`)

---

## Docker

```yaml
# docker-compose.yml
svc-api-gateway:
  build: { context: ., dockerfile: services/api-gateway/Dockerfile }
  profiles: [runtime]
  ports: ["8000:8000"]
  env_file: services/api-gateway/configs/.env
  depends_on:
    svc-portfolio: { condition: service_started }
    svc-market-data: { condition: service_started }
    valkey: { condition: service_healthy }
```

---

## Common Pitfalls

- **CORS port**: default `CORS_ORIGINS` uses port 3001 (worldview-web), not 3000. Frontend
  on a non-standard port will get CORS errors. Set `API_GATEWAY_CORS_ORIGINS` accordingly.

- **`X-Tenant-Id` / `X-User-Id` headers are dead** — removed after PRD-0025. All backends
  extract identity from `X-Internal-JWT` only. Never forward raw header identity.

- **Rate limiting is fail-closed**: if Valkey is unavailable, all requests are rejected
  with 503 (D-001 security decision). Ensure Valkey is healthy before deploying S9.

- **JTI replay detection**: each parallel fan-out call (e.g. dashboard snapshot) must
  use `make_headers=lambda: _auth_headers(request)` to generate a fresh JWT with a unique
  JTI per downstream call. Reusing the same JWT across parallel calls triggers replay detection.

- **`dev-login` returns 403 in production**: the endpoint is gated behind
  `oidc_config is None`. It is never available when `OIDC_DISCOVERY_OPTIONAL=false`.

- **`COOKIE_SECURE=true` by default**: local dev without HTTPS requires
  `API_GATEWAY_COOKIE_SECURE=false`; otherwise the refresh_token cookie is not sent by the browser.

## LLM Cost Metering & Guardrails (PLAN-0117)

S9 owns **no** `llm_usage_log` table of its own. The only direct LLM call it makes — the
natural-language screener translation at `POST /v1/screener/nl-translate` (a direct
DeepInfra call) — is cost-tracked by reporting usage to the S8 internal endpoint
`POST /internal/v1/llm-usage` (`RecordLlmUsageUseCase`), which persists to `rag_db` and
emits `llm_usage_silent_zero_cost_total`. This keeps all cost accounting centralized.

- **Boot-time priceability warning**: app lifespan calls `warn_unpriceable_models(...)`,
  logging a structured WARNING if `_NL_SCREENER_MODEL` has no pricing path.
  See `docs/BUG_PATTERNS.md` BP-715.
