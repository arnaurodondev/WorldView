# PRD-0030: Daily AI Briefings & Centralized Prompt Library

> **Status**: Draft
> **Author**: Arnau Rodon + Claude
> **Created**: 2026-04-24
> **Services affected**: S8 (rag-chat), S6 (nlp-pipeline), S7 (knowledge-graph), libs/ml-clients, libs/prompts (new), worldview-web frontend

---

## §1 Problem Statement

The worldview platform has two daily AI briefing endpoints already scaffolded in S8 (`GET /api/v1/briefings/morning` and `GET /api/v1/briefings/instrument/{entity_id}`) with Valkey 24h caching, rate limiting, and S9 proxy routes. However, these endpoints **generate briefings from empty context** — the `GenerateBriefingUseCase` receives `portfolio_context={}` and `market_snapshots=[{"type": "morning_overview"}]`, meaning the LLM produces hallucinated narratives with no grounding in actual platform data.

Additionally, LLM prompts are scattered as inline strings across 5+ files in 4 different services, making them impossible to audit, version, or maintain consistently. There is no shared prompt library — each service constructs its own prompt strings with ad-hoc f-string formatting.

**This PRD addresses two tightly coupled problems:**

1. **Briefings produce no value** — the data pipeline that feeds real context (news, signals, alerts, portfolio, market data) into the briefing LLM call does not exist.
2. **Prompt management is fragmented** — ~15 prompt strings across S6, S7, S8, and libs/ml-clients are inline, unversioned, and unreviewable in aggregate.

---

## §2 Target Users

| Segment | How They Use Briefings |
|---------|----------------------|
| **Retail Investors** | Morning dashboard brief: "What happened overnight? Are any of my holdings affected?" |
| **Research Analysts** | Instrument brief on entity detail page: "Quick synthesis of this company's recent developments" |
| **Thesis Evaluators** | Demonstrates end-to-end AI pipeline: data gathering → prompt construction → LLM generation → cached delivery |

---

## §3 Functional Requirements

### FR-01: Morning Market Briefing (Dashboard)

The morning briefing is a **user-specific** AI-generated markdown summary displayed on the dashboard via `MorningBriefCard`. It synthesizes:

| Data Source | Service | Endpoint | What It Provides |
|------------|---------|----------|-----------------|
| Portfolio holdings + watchlist | S1 | `GET /internal/v1/users/{user_id}/portfolio/context` | User's positions, tickers, weights, watchlist entities |
| High-impact news (last 24h) | S6 | `GET /api/v1/news/top?hours=24&limit=10&min_display_score=0.3` | Top-ranked articles with impact scores |
| Active alerts | S5 | `GET /api/v1/alerts/pending?min_severity=medium&limit=20` | Unacknowledged alerts for user |
| Batch quotes for portfolio | S3 | `POST /api/v1/quotes/batch` | Latest bid/ask/last/volume for all held instruments |
| Market overview (sector heatmap) | S3 | `POST /api/v1/fundamentals/screen` | Sector-level aggregates for market context |
| Recent events for portfolio entities | S7 | `POST /api/v1/events/search` | Structured events (earnings, filings, insider trades) for held entities |

**Behavior:**
- Cache key: `briefing:morning:{user_id}` (user-specific — includes portfolio data)
- Cache TTL: 24 hours (86,400s)
- Output format: Markdown
- Target length: 500–1,000 words
- Entity mentions extracted from input context (not LLM output)
- Rate limit: 100 briefings/day per user (existing, unchanged)

### FR-02: Instrument Briefing (Entity Detail Page)

The instrument briefing is an **entity-specific** (not user-specific) AI-generated markdown summary shown in the Intelligence tab of the entity detail page. It synthesizes:

| Data Source | Service | Endpoint | What It Provides |
|------------|---------|----------|-----------------|
| Entity details + relationships | S7 | `GET /api/v1/entities/{entity_id}/graph` | Canonical name, ticker, entity type, relationship graph |
| Latest quote | S3 | `GET /api/v1/quotes/{instrument_id}` | Bid/ask/last/volume/timestamp |
| Key fundamentals | S3 | `GET /api/v1/fundamentals/{instrument_id}/highlights` | TTM metrics (P/E, margins, revenue, etc.) |
| Recent articles | S6 | `GET /api/v1/entities/{entity_id}/articles?limit=10` | Top-ranked articles mentioning this entity |
| Recent events | S7 | `POST /api/v1/events/search` | Structured events for this entity |

**Behavior:**
- Cache key: `briefing:instrument:{entity_id}` (**no user_id** — same brief for all users)
- Cache TTL: 24 hours (86,400s)
- Output format: Markdown
- Target length: 300–600 words
- Requires entity_id → ticker → instrument_id resolution via S7 graph + S3 symbol lookup
- No rate limit per user (entity-scoped caching is sufficient)

### FR-03: Centralized Prompt Library (`libs/prompts/`)

A new shared Python library containing all LLM prompt templates used across the platform:

- **Typed `PromptTemplate` dataclass** with `name`, `version`, `description`, `template`, `parameters`, and `render(**kwargs)` method
- **Organized by domain**: `chat/`, `briefing/`, `extraction/`, `knowledge/`, `classification/`, `description/`
- **Shared safety footer** reused across all prompts
- **All existing inline prompts migrated** from S6, S7, S8, and libs/ml-clients
- **Two new briefing prompts** added: `MORNING_BRIEFING` and `INSTRUMENT_BRIEFING` (markdown output)

### FR-04: Frontend Briefing Rendering

- Update `MorningBriefCard.tsx` to render markdown (via react-markdown or similar)
- Replace the static placeholder in `IntelligenceTab.tsx` (lines 189-199) with a live `InstrumentBriefSection` that calls `getInstrumentBrief(entityId)` from the gateway
- Fix the `MorningBrief` TypeScript type to match the actual S8 response schema

---

## §4 Non-Functional Requirements

| Attribute | Target | Rationale |
|-----------|--------|-----------|
| Briefing generation latency | < 15s p95 (uncached) | LLM streaming + parallel context fetching |
| Cached briefing latency | < 200ms p95 | Valkey GET + JSON deserialize |
| Context gathering timeout | 10s per upstream call | Match existing `upstream_timeout_seconds` config |
| Graceful degradation | Partial context OK | If one upstream fails, generate brief from available data |
| Test coverage | ≥90% line coverage for new code | Thesis-grade quality |
| Prompt library test coverage | Every template renders without error | Catch missing parameters at test time |

---

## §5 Out of Scope

| Item | Why Excluded |
|------|-------------|
| Database-stored prompts with hot-reload | Overkill for thesis scope; code-defined templates with version strings are sufficient |
| A/B testing of prompts | No analytics infrastructure to measure prompt quality |
| Scheduled briefing generation (cron) | Briefings are generated on-demand with cache-aside; a cron pre-warmer can be added later |
| Email delivery of briefings | Already handled by S10 via the existing internal `POST /internal/v1/briefings` endpoint |
| Multilingual briefings | English only |
| Briefing history / archive | Current design overwrites cache; historical briefings could be persisted later |
| Push notifications for new briefings | Out of scope — briefings are pull-based |

---

## §6 Technical Design

### §6.1 Affected Services

| Service | Change Type | Summary |
|---------|------------|---------|
| **S8 (rag-chat)** | Major | New `BriefingContextGatherer`, new `S5Client`, fix `S1Client` path, rewrite `GenerateBriefingUseCase`, update `public_briefings.py`, update response schema, import prompts from `libs/prompts` |
| **S6 (nlp-pipeline)** | Minor | Replace inline extraction/relevance prompts with imports from `libs/prompts` |
| **S7 (knowledge-graph)** | Minor | Replace inline summary/profile/alias prompts with imports from `libs/prompts` |
| **libs/ml-clients** | Minor | Replace inline description prompt with import from `libs/prompts` |
| **libs/prompts (NEW)** | New library | PromptTemplate base, 15 migrated prompts + 2 new briefing prompts, shared safety footer |
| **worldview-web** | Moderate | Fix `MorningBrief` type, update `MorningBriefCard` for markdown, implement `InstrumentBriefSection` in `IntelligenceTab` |
| **worldview-gitops** | Config | Add `RAG_CHAT_S5_BASE_URL` env var |

### §6.2 API Changes

No new endpoints are created — this PRD wires data into existing endpoints.

#### GET /api/v1/briefings/morning (S8 — existing, behavior change)

- **Purpose**: Generate or retrieve a cached morning market briefing
- **Auth**: Required — InternalJWTMiddleware extracts `user_id` and `tenant_id` from `X-Internal-JWT`
- **Request**: No body (GET)
- **Response** (200) — `PublicBriefingResponse` (updated schema):

  | Field | Type | Required | Description |
  |-------|------|----------|-------------|
  | content | string | yes | Markdown-formatted briefing narrative |
  | risk_summary | object \| null | no | `{concentration_score: float, top_risk_signals: list, sector_breakdown: dict}` — present for morning briefings |
  | entity_mentions | list[BriefingEntityMention] | yes | Entities referenced in the brief, extracted from input context |
  | citations | list[BriefingCitation] | yes | Sources that informed the briefing, extracted from gathered context (not LLM output) |
  | generated_at | string | yes | ISO-8601 UTC timestamp of generation |
  | cached | boolean | yes | True if served from Valkey cache |
  | entity_id | string \| null | yes | Always null for morning briefings |

  `BriefingEntityMention`:

  | Field | Type | Description |
  |-------|------|-------------|
  | entity_id | string (UUID) | Entity identifier |
  | name | string | Canonical entity name |
  | ticker | string \| null | Ticker symbol if financial instrument |

  `BriefingCitation`:

  | Field | Type | Description |
  |-------|------|-------------|
  | source_type | string | `"article"`, `"event"`, or `"alert"` |
  | source_id | string (UUID) | Identifier of the source (article_id, event_id, or alert_id) |
  | title | string | Display title (article title, event text, or alert type) |
  | url | string \| null | Source URL (articles only) |

- **Error responses**: 401 (missing/invalid JWT), 429 (rate limit exceeded — 100/day), 503 (LLM provider unavailable or all context gathering failed)
- **Rate limit**: 100 briefing generations/day per user (Valkey counter, existing)
- **Cache**: Valkey key `briefing:morning:{user_id}`, TTL 86,400s (24h)

**Breaking change**: Response field renamed from `narrative` to `content`; new `entity_mentions` field added. S9 proxy passes through unchanged. Frontend already expects `content` and `entity_mentions` — this **fixes** the existing mismatch.

#### GET /api/v1/briefings/instrument/{entity_id} (S8 — existing, behavior change)

- **Purpose**: Generate or retrieve a cached instrument-specific briefing
- **Auth**: Required — InternalJWTMiddleware
- **Path param**: `entity_id` (UUID string)
- **Request**: No body (GET)
- **Response** (200) — same `PublicBriefingResponse` schema as above, with:
  - `risk_summary`: always `null` (no portfolio context)
  - `entity_id`: set to the path param value

- **Error responses**: 401 (missing/invalid JWT), 404 (entity not found in S7 — new), 503 (LLM unavailable)
- **Rate limit**: None per user — entity-scoped caching is sufficient
- **Cache**: Valkey key `briefing:instrument:{entity_id}` (**changed**: `user_id` removed from key)

**Breaking change**: Cache key loses `user_id` suffix. Old per-user cached entries expire naturally (24h TTL).

#### POST /internal/v1/briefings (S8 — existing, unchanged)

The internal endpoint used by S10 email scheduler remains unchanged. It continues to accept pre-built context in the request body (`portfolio_context`, `market_snapshots`, `active_signals`). The new `BriefingContextGatherer` is only used by the public GET endpoints.

### §6.3 Event Changes

**No new Kafka events or topics.** This PRD is entirely synchronous REST — briefing generation is a request/response flow with Valkey caching. No outbox, no dual writes.

### §6.4 Database Changes

**No database changes.** Briefings are cached in Valkey (not persisted to Postgres). The prompt library is code-defined (not DB-stored). No Alembic migrations required.

### §6.5 Domain Model Changes

#### Entity: BriefingContext (S8 — new, application layer)

- **Purpose**: Typed container for gathered briefing context, passed to prompt builder
- **Frozen**: yes (immutable after gathering)
- **Location**: `services/rag-chat/src/rag_chat/application/models/briefing_context.py`
- **Attributes**:

  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | briefing_type | BriefingType | yes | Enum: `MORNING` or `INSTRUMENT` |
  | user_id | UUID \| None | no | Set for morning briefings (user-specific) |
  | tenant_id | UUID \| None | no | Set for morning briefings |
  | entity_id | str \| None | no | Set for instrument briefings |
  | portfolio | PortfolioSnapshot \| None | no | Holdings + watchlist from S1 |
  | news_articles | list[NewsArticleSummary] | yes | Top articles from S6 (default: []) |
  | active_alerts | list[AlertSummary] | yes | Pending alerts from S5 (default: []) |
  | quotes | dict[str, QuoteSummary] | yes | Instrument_id → quote from S3 (default: {}) |
  | market_overview | MarketOverview \| None | no | Sector aggregates from S3 screener |
  | recent_events | list[EventSummary] | yes | Structured events from S7 (default: []) |
  | entity_graph | EntityGraphSnapshot \| None | no | Entity details + relationships from S7 |
  | fundamentals | FundamentalsSummary \| None | no | Key metrics from S3 (instrument briefings) |
  | gathered_at | datetime | yes | UTC timestamp when context was assembled |

- **Invariants**:
  - If `briefing_type == MORNING`: `user_id` must be set
  - If `briefing_type == INSTRUMENT`: `entity_id` must be set
- **Factory**: `BriefingContext.for_morning(user_id, tenant_id, ...)` and `BriefingContext.for_instrument(entity_id, ...)`

#### Value Object: PortfolioSnapshot (S8 — new)

- **Purpose**: Typed snapshot of user's portfolio context from S1
- **Frozen**: yes
- **Attributes**:

  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | user_id | UUID | yes | Portfolio owner |
  | holdings | list[HoldingItem] | yes | Current positions |
  | watchlist | list[WatchlistItem] | yes | Watched entities |
  | total_positions | int | yes | Count of held instruments |

  `HoldingItem`: `{ticker: str | None, entity_id: UUID | None, canonical_name: str | None, quantity: Decimal, current_weight: float}`

  `WatchlistItem`: `{ticker: str | None, entity_id: UUID | None, canonical_name: str | None}`

#### Value Object: NewsArticleSummary (S8 — new)

- **Purpose**: Lightweight article summary for briefing context
- **Frozen**: yes
- **Attributes**:

  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | article_id | UUID | yes | Article identifier |
  | title | str | yes | Article title |
  | url | str \| None | no | Source URL |
  | published_at | datetime \| None | no | Publication timestamp (UTC) |
  | source_type | str \| None | no | Provider name |
  | display_relevance_score | float | yes | Computed relevance score |
  | market_impact_score | float \| None | no | Estimated market impact |
  | primary_entity_id | UUID \| None | no | Main entity mentioned |
  | primary_entity_name | str \| None | no | Canonical name of primary entity (from S6 response) |

#### Value Object: AlertSummary (S8 — new)

- **Purpose**: Lightweight alert summary for briefing context
- **Frozen**: yes
- **Attributes**:

  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | alert_id | UUID | yes | Alert identifier |
  | entity_id | UUID | yes | Affected entity |
  | alert_type | str | yes | Alert classification |
  | severity | str | yes | low / medium / high / critical |
  | payload | dict | yes | Alert details |
  | created_at | datetime | yes | When the alert was created |

#### Value Object: QuoteSummary (S8 — new)

- **Purpose**: Lightweight quote snapshot for briefing context
- **Frozen**: yes
- **Attributes**:

  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | instrument_id | str | yes | S3 instrument identifier |
  | last | str \| None | no | Last trade price (decimal string) |
  | bid | str \| None | no | Bid price |
  | ask | str \| None | no | Ask price |
  | volume | int \| None | no | Volume |
  | timestamp | datetime | yes | Quote timestamp |

#### Value Object: MarketOverview (S8 — new)

- **Purpose**: Market-wide context from S3 screener for morning briefing
- **Frozen**: yes
- **Attributes**:

  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | sector_performance | dict[str, float] | yes | Sector name → avg % change |
  | top_gainers | list[dict] | yes | Top 5 gainers `{ticker, name, change_pct}` |
  | top_losers | list[dict] | yes | Top 5 losers `{ticker, name, change_pct}` |

#### Value Object: EventSummary (S8 — new)

- **Purpose**: Lightweight structured event for briefing context
- **Frozen**: yes
- **Attributes**:

  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | event_id | UUID | yes | Event identifier |
  | event_type | str | yes | Event classification |
  | event_subtype | str \| None | no | Sub-classification |
  | subject_entity_id | UUID | yes | Entity this event is about |
  | event_date | datetime \| None | no | When the event occurred |
  | event_text | str | yes | Human-readable event description |
  | extraction_confidence | float | yes | NLP extraction confidence |

#### Value Object: EntityGraphSnapshot (S8 — new)

- **Purpose**: Entity details and relationships from S7 for instrument briefing
- **Frozen**: yes
- **Attributes**:

  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | entity_id | str | yes | Entity identifier |
  | canonical_name | str | yes | Display name |
  | entity_type | str | yes | e.g. "financial_instrument", "person", "organization" |
  | ticker | str \| None | no | Ticker symbol (for S3 lookups) |
  | relationships | list[dict] | yes | `{relation_type, target_name, target_id, confidence}` |

#### Value Object: FundamentalsSummary (S8 — new)

- **Purpose**: Key financial metrics from S3 highlights for instrument briefing
- **Frozen**: yes
- **Attributes**:

  | Attribute | Type | Required | Description |
  |-----------|------|----------|-------------|
  | instrument_id | str | yes | S3 instrument identifier |
  | data | dict | yes | Raw highlights dict from S3 (P/E, margins, revenue, etc.) |

#### Enum: BriefingType (S8 — new)

- **Values**: `MORNING`, `INSTRUMENT`
- **Location**: `services/rag-chat/src/rag_chat/domain/enums.py` (extend existing file)

#### Entity: PromptTemplate (libs/prompts — new)

- **Purpose**: Typed, named, versioned prompt template with parameter validation
- **Frozen**: yes
- **Location**: `libs/prompts/src/prompts/_base.py`
- **Attributes**:

  | Attribute | Type | Required | Validation | Description |
  |-----------|------|----------|------------|-------------|
  | name | str | yes | 1-100 chars, no whitespace | Unique prompt identifier |
  | version | str | yes | semver-like (e.g. "1.0") | Bumped when prompt text changes |
  | description | str | yes | 1-500 chars | What this prompt does |
  | template | str | yes | len > 0 | Prompt text with `{param}` placeholders |
  | parameters | frozenset[str] | yes | — | Required parameter names |

- **Methods**:
  - `render(**kwargs) -> str` — substitute parameters into template; raises `ValueError` if required parameters are missing
- **Invariants**: `parameters` is a frozenset (immutable); `render()` validates all required params are present before substitution

### §6.6 Frontend Changes

#### Update TypeScript type: `MorningBrief` → `BriefingResponse`

**File**: `apps/worldview-web/types/api.ts`

Replace the existing `MorningBrief` interface:

```typescript
// BEFORE (mismatched with S8 response):
export interface MorningBrief {
  brief_id: string;
  content: string;
  generated_at: string;
  entity_mentions: Array<{ entity_id: string; name: string; ticker: string | null }>;
}

// AFTER (matches S8 PublicBriefingResponse):
export interface BriefingEntityMention {
  entity_id: string;
  name: string;
  ticker: string | null;
}

export interface BriefingCitation {
  source_type: "article" | "event" | "alert";
  source_id: string;
  title: string;
  url: string | null;
}

export interface BriefingResponse {
  content: string;          // markdown narrative
  risk_summary: {
    concentration_score: number;
    top_risk_signals: Array<{ signal_id: string; description: string }>;
    sector_breakdown: Record<string, number>;
  } | null;
  entity_mentions: BriefingEntityMention[];
  citations: BriefingCitation[];  // sources that informed the briefing
  generated_at: string;     // ISO-8601 UTC
  cached: boolean;
  entity_id: string | null;
}
```

#### Update `MorningBriefCard.tsx`

- Use `react-markdown` (already installed: `react-markdown@9.0.3`, `remark-gfm@4.0.0`)
- Render `brief.content` as markdown instead of plain text
- Keep entity-mention-to-link replacement (still works — entity names in markdown text)
- Remove `brief_id` reference (field doesn't exist)
- Handle `brief.risk_summary` — optionally display concentration score and sector breakdown

#### Implement `InstrumentBriefSection` in `IntelligenceTab.tsx`

Replace the static placeholder (lines 189-199) with a live component that:

1. Calls `createGateway(accessToken).getInstrumentBrief(entityId)` via `useQuery`
2. Shows a skeleton loader during fetch (3-line skeleton)
3. Renders markdown content via `react-markdown`
4. Handles 503 gracefully ("Brief generating..." soft error, same pattern as `MorningBriefCard`)
5. Shows `generated_at` timestamp
6. Shows a "Refresh" button if brief is >12h old (same stale indicator pattern)

**Query config**: `staleTime: 30min`, `retry: 2`, `retryDelay: 10_000`

#### Update gateway types

**File**: `apps/worldview-web/lib/gateway.ts`

Update return type of `getMorningBrief()` and `getInstrumentBrief()` from any/implicit to `BriefingResponse`.

### §6.7 Data Flow

#### Morning Briefing — Full Request Path

```
1. User opens dashboard → MorningBriefCard mounts
2. useQuery fires → GET /api/v1/briefings/morning
3. Next.js rewrite → GET http://api-gateway:8000/v1/briefings/morning
4. S9 proxy → GET http://rag-chat:8008/api/v1/briefings/morning
   (S9 adds X-Internal-JWT with user_id, tenant_id)
5. S8 public_briefings.py:
   a. Extract user_id from JWT
   b. Check Valkey: GET briefing:morning:{user_id}
      → HIT: return cached JSON with cached=true (< 200ms)
      → MISS: continue to step 6
6. S8 BriefingContextGatherer.gather_morning_context():
   Parallel (asyncio.gather, 10s timeout each):
   ├── S1 GET /internal/v1/users/{user_id}/portfolio/context → PortfolioSnapshot
   ├── S6 GET /api/v1/news/top?hours=24&limit=10&min_display_score=0.3 → list[NewsArticleSummary]
   ├── S5 GET /api/v1/alerts/pending?min_severity=medium&limit=20 → list[AlertSummary]
   ├── S3 POST /api/v1/quotes/batch (instrument_ids from portfolio) → dict[str, QuoteSummary]
   ├── S3 POST /api/v1/fundamentals/screen (sector overview) → MarketOverview
   └── S7 POST /api/v1/events/search (entity_ids from portfolio, last 7 days) → list[EventSummary]

   Note: S3 quotes/batch requires instrument_ids which come from portfolio holdings.
   Resolution: gather_morning_context() awaits S1 first, then fires S3/S5/S6/S7 in parallel.
   Optimization: S1 call is fast (< 100ms cached in S1's own Valkey at 300s TTL).

   On partial failure: log warning, continue with available data. If ALL fail → 503.

7. S8 GenerateBriefingUseCase:
   a. Check daily rate limit (Valkey INCR)
   b. Build BriefingContext from gathered data
   c. Extract entity_mentions from context (portfolio entities + news primary entities + alert entities)
   d. Render MORNING_BRIEFING prompt (from libs/prompts) with XML-wrapped context
   e. Stream LLM completion (DeepInfra → OpenRouter → Ollama fallback)
   f. Collect streamed tokens → markdown string
   g. Build risk_summary (HHI concentration, top signals, sector breakdown)
   h. Assemble PublicBriefingResponse
8. Write to Valkey: SET briefing:morning:{user_id} (TTL 86400s)
9. Return 200 with JSON response
```

#### Instrument Briefing — Full Request Path

```
1. User opens instrument detail → Intelligence tab → InstrumentBriefSection mounts
2. useQuery fires → GET /api/v1/briefings/instrument/{entity_id}
3. Next.js rewrite → S9 proxy → S8
4. S8 public_briefings.py:
   a. Check Valkey: GET briefing:instrument:{entity_id}
      → HIT: return cached (< 200ms)
      → MISS: continue
5. S8 BriefingContextGatherer.gather_instrument_context():
   Step A (sequential — need ticker for S3):
   └── S7 GET /api/v1/entities/{entity_id}/graph → EntityGraphSnapshot (includes ticker)

   Step B (parallel, if ticker found):
   ├── S3 GET /api/v1/instruments/symbol/{ticker} → instrument_id
   │   then:
   │   ├── S3 GET /api/v1/quotes/{instrument_id} → QuoteSummary
   │   └── S3 GET /api/v1/fundamentals/{instrument_id}/highlights → FundamentalsSummary
   ├── S6 GET /api/v1/entities/{entity_id}/articles?limit=10 → list[NewsArticleSummary]
   └── S7 POST /api/v1/events/search (entity_ids=[entity_id], last 30 days) → list[EventSummary]

   If ticker not found (non-financial entity): skip S3 calls, brief without price/fundamentals.
   If entity_id not found in S7: return 404.

6. GenerateBriefingUseCase:
   a. Build BriefingContext.for_instrument(...)
   b. Extract entity_mentions (target entity + relationship entities)
   c. Render INSTRUMENT_BRIEFING prompt with context
   d. Stream LLM → markdown
   e. risk_summary = None (no portfolio context)
   f. Assemble response
7. Write to Valkey: SET briefing:instrument:{entity_id} (TTL 86400s)
8. Return 200
```

#### Prompt Library — Import Flow

```
Service code (S6/S7/S8/libs/ml-clients)
  └── from prompts.<domain>.<module> import <PROMPT_TEMPLATE>
      └── PROMPT_TEMPLATE.render(context=..., safety=..., ...)
          └── returns formatted prompt string
              └── passed to LLM adapter (Ollama, DeepInfra, Gemini, etc.)
```

All prompt imports are compile-time (Python import), not runtime/DB. `libs/prompts` is installed as an editable dependency in each service's venv (same pattern as `libs/common`, `libs/contracts`, etc.).

---

## §7 Architecture Decisions

### ADR-B-01: S8 Gathers Its Own Briefing Context (vs. Caller-Provides)

**Decision**: S8's `BriefingContextGatherer` makes direct HTTP calls to S1, S3, S5, S6, S7 to assemble briefing context.

**Alternatives considered**:
- **Option B (Caller provides context)**: S9 or S10 gathers data and passes it in the request body. Rejected because: S9 is a thin proxy (R25-compatible), and having the API gateway orchestrate multi-service data gathering violates its architectural role. S10 already uses the internal endpoint with pre-built context — that path is preserved for email delivery.

**Rationale**: S8 already has clients for S1, S3, S6, S7 (used by the chat pipeline). Adding S5 is incremental. The `BriefingContextGatherer` follows the same pattern as `ParallelRetrievalOrchestrator` in the chat pipeline — parallel HTTP calls with per-call timeouts and graceful degradation.

### ADR-B-02: Prompt Library as Shared Code (vs. DB-Stored)

**Decision**: All prompts are code-defined `PromptTemplate` instances in `libs/prompts/`, installed as an editable dependency.

**Alternatives considered**:
- **Option B (DB-stored)**: Prompts in a `prompt_templates` table with versioning, hot-reload, and A/B testing. Rejected because: adds DB dependency to all services, requires migration infrastructure for prompts, and adds complexity without measurable benefit for thesis scope.
- **Option C (Config files)**: YAML/JSON prompt files loaded at startup. Rejected because: loses Python type safety, no parameter validation at import time, harder to test.

**Rationale**: Code-defined prompts are testable, type-safe, version-controlled via git, and require zero infrastructure. The `version` field on `PromptTemplate` enables tracking which prompt version generated a given output for debugging.

### ADR-B-03: Entity Mentions from Input Context (vs. LLM Output Parsing)

**Decision**: `entity_mentions` in the briefing response are extracted from the gathered input data (portfolio holdings, news article entities, graph entities), not by parsing entity names from the LLM-generated narrative.

**Rationale**: LLM output is non-deterministic — entity names might appear in different forms, be abbreviated, or be missing. Input data has structured entity_ids and canonical names with 100% recall. This approach is deterministic and requires no additional NLP processing.

---

## §8 Security Analysis

### Threat Model

| Threat | Risk | Mitigation |
|--------|------|------------|
| Prompt injection via cached briefing | LOW | Briefing prompts use XML-wrapped context (same pattern as chat pipeline); safety footer appended to all prompts |
| XSS via markdown rendering | MEDIUM | Frontend uses `react-markdown` which sanitizes HTML by default; no `dangerouslySetInnerHTML` |
| Data leakage across tenants | LOW | Morning briefing cache key includes `user_id`; S1 internal endpoint returns only that user's portfolio; S5 returns only that user's alerts |
| Instrument briefing information disclosure | LOW | Instrument briefs are entity-scoped (public market data, public news, public events); no user-specific data included |
| Rate limit bypass via cache | LOW | Rate limit checked before cache write; cached responses don't increment the counter |
| LLM hallucination | MEDIUM | Context-grounded prompt design; safety footer "never speculate beyond evidence"; entity_mentions from input data (not LLM output) |

### Multi-Tenant Isolation

- Morning briefing: `user_id` in cache key ensures no cross-user leakage
- S1 call uses `X-Internal-JWT` which carries the user's `sub` claim — S1 returns only that user's portfolio
- S5 call extracts `user_id` from JWT state — S5 returns only that user's alerts
- Instrument briefing: entity-scoped, no user data → no tenant isolation concern

---

## §9 Failure Modes

| Failure | Impact | Recovery |
|---------|--------|----------|
| S1 (portfolio) down | Morning brief loses portfolio context | Generate brief from news + alerts + market data only; log `briefing_partial_context` warning |
| S3 (market-data) down | No quotes or fundamentals | Brief generated from news + events only; less useful but functional |
| S5 (alert) down | No active alerts in brief | Generate without alerts; user still sees alerts in the alerts panel |
| S6 (nlp-pipeline) down | No news articles | Brief generated from portfolio + events + market data |
| S7 (knowledge-graph) down | No events, no entity graph | Morning: brief from portfolio + news + alerts. Instrument: return 503 (entity graph is critical for instrument brief) |
| ALL upstream services down | No context at all | Return 503 "Briefing generation unavailable" |
| LLM provider chain exhausted | DeepInfra → OpenRouter → Ollama all fail | Return 503; existing circuit breaker pattern handles this |
| Valkey down | Cache read/write fails | Bypass cache; generate fresh on every request (higher latency, more LLM costs); existing pattern in `public_briefings.py` already handles this |
| Stale cache served | Brief > 24h old | TTL-based expiry; frontend shows "may be outdated" indicator for briefs > 12h |

### Graceful Degradation Strategy

The `BriefingContextGatherer` uses `asyncio.gather(return_exceptions=True)` — each upstream call is independent. The resulting `BriefingContext` marks which data sources succeeded. The Python code that builds the prompt context passes empty strings for failed sections:

```python
# In GenerateBriefingUseCase._build_context_string():
portfolio_context = _format_portfolio(ctx.portfolio) if ctx.portfolio else ""
news_context = _format_news(ctx.news_articles) if ctx.news_articles else ""
alerts_context = _format_alerts(ctx.active_alerts) if ctx.active_alerts else ""
# ... etc.

# The prompt template always includes all section placeholders:
MORNING_BRIEFING.render(
    portfolio_context=portfolio_context,  # "" if S1 failed
    news_context=news_context,            # "" if S6 failed
    alerts_context=alerts_context,        # "" if S5 failed
    ...
)
```

The LLM naturally skips empty sections, generating from whatever data is available rather than failing entirely.

**Exception**: For instrument briefings, if S7 returns 404 for the entity_id, the endpoint returns 404 (not a degraded brief). The entity must exist in the knowledge graph.

---

## §10 Scalability & Performance

### Bottleneck Analysis

| Component | Throughput | Bottleneck | Mitigation |
|-----------|-----------|------------|------------|
| Context gathering | 6 upstream calls per uncached morning brief | S1 + S3 + S5 + S6 + S7 network I/O | Parallel execution (asyncio.gather); 10s per-call timeout |
| LLM generation | 1 streaming call per uncached brief | Token generation speed (DeepInfra: ~50 tok/s) | 24h cache means each user generates at most 1 brief/day |
| Valkey cache | ~1 key per user/day + ~1 key per entity/day | Memory | Bounded: max users × 1 key + max entities × 1 key; ~1KB per cached brief |
| Instrument brief cache efficiency | 1 brief per entity (shared across all users) | First request for an entity is slow | Acceptable — entity pages are accessed infrequently enough that 24h cache is sufficient |

### Estimated Cache Footprint

- Morning briefs: ~5 users × 1KB = 5KB (thesis scale)
- Instrument briefs: ~500 entities × 1KB = 500KB (thesis scale)
- Total Valkey overhead: < 1MB — negligible

---

## §11 Test Strategy

### Unit Tests — libs/prompts

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_prompt_template_render_valid` | `render()` substitutes all parameters correctly | HIGH |
| `test_prompt_template_render_missing_param` | `render()` raises `ValueError` on missing required param | HIGH |
| `test_prompt_template_render_extra_params_ignored` | Extra kwargs don't cause errors | MEDIUM |
| `test_all_prompts_render_with_sample_data` | Every exported prompt template renders without error | HIGH |
| `test_prompt_template_frozen` | PromptTemplate instances are immutable | MEDIUM |
| `test_safety_footer_appended` | All chat/briefing prompts contain the safety footer text | HIGH |
| `test_prompt_versions_are_semver` | Version strings match `\d+\.\d+` pattern | LOW |
| `test_morning_briefing_prompt_contains_sections` | Morning prompt includes expected section headers | MEDIUM |
| `test_instrument_briefing_prompt_contains_sections` | Instrument prompt includes expected section headers | MEDIUM |

### Unit Tests — S8 BriefingContextGatherer

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_gather_morning_context_all_sources_succeed` | All 6 upstream calls return data; BriefingContext fully populated | HIGH |
| `test_gather_morning_context_s1_fails` | S1 down → portfolio=None, rest populated | HIGH |
| `test_gather_morning_context_s5_fails` | S5 down → active_alerts=[], rest populated | HIGH |
| `test_gather_morning_context_all_fail` | All sources fail → raises ContextGatheringError | HIGH |
| `test_gather_morning_context_partial_portfolio_no_tickers` | Holdings without tickers → quotes dict empty | MEDIUM |
| `test_gather_morning_context_timeout_handling` | One source times out (>10s) → continues with others | HIGH |
| `test_gather_instrument_context_full` | S7 returns entity with ticker → S3 quotes + fundamentals populated | HIGH |
| `test_gather_instrument_context_no_ticker` | Non-financial entity (no ticker) → S3 calls skipped, fundamentals=None | HIGH |
| `test_gather_instrument_context_entity_not_found` | S7 returns empty graph → raises EntityNotFoundError | HIGH |
| `test_gather_instrument_context_s3_instrument_not_found` | Ticker exists but S3 has no matching instrument → quotes/fundamentals=None | MEDIUM |

### Unit Tests — S8 GenerateBriefingUseCase (updated)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_morning_briefing_generates_markdown` | Output content is valid markdown (no HTML tags) | HIGH |
| `test_instrument_briefing_generates_markdown` | Output content is valid markdown | HIGH |
| `test_morning_briefing_entity_mentions_from_context` | entity_mentions extracted from portfolio + news, not LLM output | HIGH |
| `test_instrument_briefing_entity_mentions_from_graph` | entity_mentions extracted from S7 graph entities | HIGH |
| `test_morning_briefing_risk_summary_calculated` | risk_summary includes concentration_score and sector_breakdown | MEDIUM |
| `test_instrument_briefing_risk_summary_none` | risk_summary is None for instrument briefings | MEDIUM |
| `test_briefing_rate_limit_enforced` | 101st briefing in a day raises RateLimitExceededError | HIGH |
| `test_briefing_prompt_uses_libs_prompts` | Prompt rendered via PromptTemplate.render(), not inline string | MEDIUM |
| `test_morning_briefing_citations_from_context` | citations populated from news articles + events + alerts (not LLM output) | HIGH |
| `test_instrument_briefing_citations_from_context` | citations populated from articles + events + graph | HIGH |

### Unit Tests — S8 S5Client

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_s5_client_get_pending_alerts` | Successful call returns list[AlertSummary] | HIGH |
| `test_s5_client_server_error` | S5 returns 500 → empty list (graceful degradation) | HIGH |
| `test_s5_client_timeout` | S5 times out → empty list | HIGH |
| `test_s5_client_auth_headers` | Request includes X-Internal-JWT header | MEDIUM |

### Unit Tests — S8 public_briefings.py (updated routes)

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_morning_briefing_cache_hit` | Cached response returned with cached=True | HIGH |
| `test_morning_briefing_cache_miss_generates` | Cache miss → context gathered → LLM called → response cached | HIGH |
| `test_instrument_briefing_cache_key_no_user_id` | Cache key is `briefing:instrument:{entity_id}` (no user_id) | HIGH |
| `test_instrument_briefing_entity_not_found_404` | Unknown entity_id → 404 | HIGH |
| `test_morning_briefing_response_schema` | Response matches PublicBriefingResponse with content, entity_mentions | HIGH |

### Integration Tests — S8

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_briefing_context_gathering_integration` | Mock HTTP servers for S1/S3/S5/S6/S7 | Full context gathering pipeline with realistic response shapes |
| `test_briefing_valkey_cache_roundtrip` | Valkey | Write briefing to cache → read back → fields match |
| `test_briefing_rate_limit_valkey` | Valkey | Rate limit counter increments and expires correctly |

### Prompt Migration Tests — S6, S7, libs/ml-clients

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_s6_extraction_prompt_from_libs_prompts` | S6 deep_extraction uses `prompts.extraction.deep.DEEP_EXTRACTION` | MEDIUM |
| `test_s7_summary_prompt_from_libs_prompts` | S7 summary worker uses `prompts.knowledge.summary.RELATION_SUMMARY` | MEDIUM |
| `test_s7_alias_prompt_from_libs_prompts` | S7 alias generation uses `prompts.knowledge.alias.ALIAS_GENERATION` | MEDIUM |
| `test_ml_clients_description_prompt_from_libs_prompts` | Gemini adapter uses `prompts.description.entity.ENTITY_DESCRIPTION` | MEDIUM |

### Frontend Tests — worldview-web

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_morning_brief_card_renders_markdown` | MorningBriefCard renders markdown content correctly | HIGH |
| `test_morning_brief_card_entity_links` | Entity mentions in markdown are linked to /instruments/{id} | HIGH |
| `test_morning_brief_card_loading_skeleton` | Shows skeleton during loading | MEDIUM |
| `test_morning_brief_card_503_soft_error` | Shows "generating" message on 503 | HIGH |
| `test_instrument_brief_section_renders` | InstrumentBriefSection shows markdown when data available | HIGH |
| `test_instrument_brief_section_placeholder_replaced` | Static placeholder is gone; live component renders | MEDIUM |
| `test_instrument_brief_section_error_handling` | Shows soft error on 503 | HIGH |
| `test_briefing_response_type_matches_backend` | BriefingResponse type has content, risk_summary, entity_mentions, cached | MEDIUM |

### Gitops Verification

| Test | What It Verifies | Priority |
|------|-----------------|----------|
| `test_rag_chat_env_has_s5_base_url` | `worldview-gitops/env/dev/rag-chat.env` contains `RAG_CHAT_S5_BASE_URL` | HIGH |

---

## §12 Break-Surface Analysis & Migration

| Change | What Currently Exists | What Will Break | Migration Strategy |
|--------|----------------------|-----------------|-------------------|
| `PublicBriefingResponse.narrative` → `content` | S8 `schemas.py` field named `narrative` | S9 proxy passes through (transparent); S10 internal endpoint uses separate schema (unchanged); frontend already expects `content` | Rename field in S8 schema; S9 pass-through needs no change; this **fixes** the existing frontend mismatch |
| Add `entity_mentions` to S8 response | Field absent in current response | Frontend `MorningBriefCard` references `brief.entity_mentions` which returns `undefined` | Add field to response schema; existing frontend code now works correctly |
| Add `risk_summary` to S8 response | Field absent in public response (only in internal) | No breakage — new optional field | Add as `dict | None`, null for instrument briefings |
| Repurpose `citations` in S8 response | Currently `citations: list[dict] = []` (always empty for briefings) | No breakage — field already exists, type stays `list[dict]` | Populate from gathered context sources (articles, events, alerts) instead of RAG retrieval chunks; add `BriefingCitation` Pydantic model for structured typing |
| Instrument cache key drops `user_id` | Key: `briefing:instrument:{entity_id}:{user_id}` | Old per-user entries remain until TTL expiry | Let 24h TTL expire naturally; new key takes over immediately |
| S1Client path: `/api/v1/` → `/internal/v1/` | S8 chat pipeline PORTFOLIO intent uses S1Client | Chat pipeline S1 calls now hit `/internal/v1/` path | Path change is single-line; S1 internal endpoint already exists and accepts same JWT auth |
| `GenerateBriefingUseCase` gains `BriefingContextGatherer` dependency | Currently accepts pre-built context dicts | Constructor signature changes | Internal endpoint (S10) continues passing context via request body; public endpoints use gatherer; use case accepts both paths via optional `context` param |
| Delete `intent_prompts.py` inline strings | 9 prompt strings + `get_system_prompt()` function in S8 | All S8 imports from this module break | Replace with imports from `prompts.chat.intent`; keep `get_system_prompt()` as a thin wrapper that delegates to the prompt library |
| Delete S6 inline extraction prompt | `_build_prompt()` in `deep_extraction.py` | S6 extraction block breaks | Import from `prompts.extraction.deep`; same render() interface |
| Delete S7 inline prompts (3 files) | `summary.py`, `provisional_enrichment.py`, `instrument_consumer.py` | S7 workers/consumers break | Import from `prompts.knowledge.*`; same string output |
| Delete `libs/ml-clients` description prompt | `_build_prompt()` in `gemini_description.py` | Gemini adapter breaks | Import from `prompts.description.entity`; `render(name=..., type=..., hints=...)` |
| S8 config: add `s5_base_url` | Not in current `Settings` class | New required field (needs default) | Add with default `http://alert:8010`; add to gitops env file |

---

## §13 Observability

### Metrics (Prometheus)

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `briefing_generation_total` | Counter | `type` (morning/instrument), `status` (success/error/partial) | Total briefing generations |
| `briefing_generation_duration_seconds` | Histogram | `type` | End-to-end generation time (context + LLM) |
| `briefing_context_gather_duration_seconds` | Histogram | `type`, `source` (s1/s3/s5/s6/s7) | Per-source context gathering time |
| `briefing_context_source_failures_total` | Counter | `type`, `source`, `error_type` (timeout/http_error/connection) | Context source failures |
| `briefing_cache_hit_total` | Counter | `type` | Cache hits |
| `briefing_cache_miss_total` | Counter | `type` | Cache misses |
| `briefing_llm_tokens_total` | Counter | `type` | Approximate token count per generation |

### Structured Logging

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `briefing_context_gathered` | INFO | `type`, `user_id`, `sources_succeeded`, `sources_failed`, `duration_ms` | After context gathering completes |
| `briefing_context_source_failed` | WARNING | `type`, `source`, `error`, `timeout` | Individual upstream call fails |
| `briefing_generated` | INFO | `type`, `user_id`, `entity_id`, `content_chars`, `entity_mention_count`, `citation_count`, `cached`, `duration_ms` | After briefing successfully generated |
| `briefing_generation_failed` | ERROR | `type`, `user_id`, `entity_id`, `error` | LLM or context gathering catastrophic failure |
| `briefing_cache_hit` | DEBUG | `type`, `cache_key` | Valkey cache hit |
| `prompt_rendered` | DEBUG | `prompt_name`, `prompt_version`, `param_count` | PromptTemplate.render() called |

---

## §14 Open Questions

| # | Question | Classification | Resolution |
|---|----------|---------------|------------|
| ~~OQ-1~~ | ~~Instrument briefing component status~~ | ~~RESOLVED~~ | Placeholder exists in `IntelligenceTab.tsx` (lines 189-199); gateway method `getInstrumentBrief()` is wired; static placeholder needs replacement with live component |
| ~~OQ-2~~ | ~~Morning briefing market overview data source~~ | ~~RESOLVED~~ | Include both LLM synthesis from news/signals AND structured S3 data (sector heatmap via screener, top movers via batch quotes) |

All open questions resolved. No BLOCKING items remain.

---

## §15 Estimation

### Implementation Waves (suggested breakdown for `/plan`)

| Wave | Scope | Effort | Dependencies |
|------|-------|--------|-------------|
| **W-1: libs/prompts scaffold** | New library: `pyproject.toml`, `_base.py` (PromptTemplate), `_safety.py`, tests | Small | None |
| **W-2: Migrate existing prompts** | Move 13 inline prompts from S8/S6/S7/ml-clients → `libs/prompts`; update all imports; verify existing tests pass | Medium | W-1 |
| **W-3: New briefing prompts** | Write `MORNING_BRIEFING` and `INSTRUMENT_BRIEFING` prompt templates in `libs/prompts`; add render tests | Small | W-1 |
| **W-4: S8 context gathering** | `BriefingContextGatherer`, `S5Client`, S1Client path fix, value objects, config update, gitops env | Large | W-3 |
| **W-5: S8 briefing pipeline** | Rewrite `GenerateBriefingUseCase` + `public_briefings.py`; update response schema; wire context gatherer; update all S8 tests | Large | W-4 |
| **W-6: Frontend rendering** | Update `MorningBriefCard` for markdown, implement `InstrumentBriefSection`, fix types (react-markdown already installed) | Medium | W-5 |

### Total estimated new files: ~20
### Total estimated modified files: ~25
### Total estimated new test cases: ~59

---

## §16 Prompt Inventory — Full Migration Map

This section documents every prompt being migrated and the new location in `libs/prompts/`.

| # | Current Location | Prompt Name | New Location | Parameters |
|---|-----------------|-------------|-------------|------------|
| 1 | `S8 intent_prompts.py` | `_FACTUAL_LOOKUP_PROMPT` | `prompts.chat.intent.FACTUAL_LOOKUP` | `{safety}` |
| 2 | `S8 intent_prompts.py` | `_RELATIONSHIP_PROMPT` | `prompts.chat.intent.RELATIONSHIP` | `{safety}` |
| 3 | `S8 intent_prompts.py` | `_SIGNAL_INTEL_PROMPT` | `prompts.chat.intent.SIGNAL_INTEL` | `{safety}` |
| 4 | `S8 intent_prompts.py` | `_FINANCIAL_DATA_PROMPT` | `prompts.chat.intent.FINANCIAL_DATA` | `{safety}` |
| 5 | `S8 intent_prompts.py` | `_COMPARISON_PROMPT` | `prompts.chat.intent.COMPARISON` | `{safety}` |
| 6 | `S8 intent_prompts.py` | `_REASONING_PROMPT` | `prompts.chat.intent.REASONING` | `{safety}` |
| 7 | `S8 intent_prompts.py` | `_PORTFOLIO_PROMPT` | `prompts.chat.intent.PORTFOLIO` | `{safety}` |
| 8 | `S8 intent_prompts.py` | `_GENERAL_PROMPT` | `prompts.chat.intent.GENERAL` | `{safety}` |
| 9 | `S8 intent_classifier.py` | `_CLASSIFICATION_PROMPT` | `prompts.classification.intent.INTENT_CLASSIFICATION` | `{message}`, `{history}`, `{entities}` |
| 10 | `S8 intent_prompts.py` | `EMAIL_DEEP_BRIEF_PROMPT` | **DELETED** — replaced by #14 and #15 | — |
| 11 | `S6 deep_extraction.py` | `_build_prompt()` inline | `prompts.extraction.deep.DEEP_EXTRACTION` | `{entities}`, `{text}` |
| 12 | `S7 summary.py` | `_generate_summary()` inline | `prompts.knowledge.summary.RELATION_SUMMARY` | `{evidence_statements}` |
| 13 | `S7 provisional_enrichment.py` | entity profile inline | `prompts.knowledge.entity_profile.ENTITY_PROFILE` | `{name}`, `{entity_class}` |
| 14 | `S7 instrument_consumer.py` | alias generation inline | `prompts.knowledge.alias.ALIAS_GENERATION` | `{name}`, `{ticker}` |
| 15 | `libs/ml-clients gemini_description.py` | `_build_prompt()` inline | `prompts.description.entity.ENTITY_DESCRIPTION` | `{name}`, `{type}`, `{hints}` |
| 16 | **NEW** | — | `prompts.briefing.morning.MORNING_BRIEFING` | `{portfolio_context}`, `{news_context}`, `{alerts_context}`, `{market_overview}`, `{events_context}`, `{safety}` |
| 17 | **NEW** | — | `prompts.briefing.instrument.INSTRUMENT_BRIEFING` | `{entity_context}`, `{fundamentals_context}`, `{news_context}`, `{events_context}`, `{relationships_context}`, `{safety}` |
