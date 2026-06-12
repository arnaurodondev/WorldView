# RAG / Chat Service

> **Owner**: Chat domain · **Database**: `rag_db` (owned) · **Port**: 8008
> **Status**: PLAN-0080 Wave A (Intelligence-Layer LLM Tools) COMPLETE — 14 tools total (v2 manifest)

---

## Mission & Boundaries

**Owns**: Query rewriting, tool-use chat pipeline, 20-tool catalog, SSE streaming
(vector + KG + SQL tools), result injection, context assembly, prompt building,
LLM provider fallback, streaming response delivery, citation injection, response caching.

**Never does**: Store data persistently (stateless orchestrator for knowledge), generate embeddings
(Intelligence / S6), serve financial data (Market Data / S3), manage articles (Content).

---

## API Surface

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/healthz` | Liveness | — |
| GET | `/readyz` | Readiness (rag_db + Valkey) | — |
| GET | `/metrics` | Prometheus | — |
| POST | `/api/v1/chat` | Sync chat completion | X-Internal-JWT |
| POST | `/api/v1/chat/stream` | SSE streaming chat | X-Internal-JWT |
| POST | `/api/v1/chat/entity-context` | Entity-scoped sync chat (PLAN-0074 Wave F) — loads S7 intelligence context, prefixes system prompt with entity narrative/metrics/graph, delegates to chat pipeline | X-Internal-JWT |
| POST | `/api/v1/chat/entity-context/stream` | Entity-scoped SSE streaming chat (PLAN-0074 Wave F) — same as above but yields SSE events | X-Internal-JWT |
| POST | `/api/v1/threads` | Create conversation thread | X-Tenant-Id + X-User-Id |
| GET | `/api/v1/threads` | List threads (paginated) | X-Tenant-Id + X-User-Id |
| GET | `/api/v1/threads/{thread_id}` | Get thread with messages | X-Tenant-Id + X-User-Id |
| PATCH | `/api/v1/threads/{thread_id}` | Patch mutable thread fields (currently only `title`). Body `{title?: string}` returns full ThreadDetailResponse. Ownership enforced atomically inside `update_title` UPDATE. **Empty body (`{}`) or `title=null` is a no-op** — the use case short-circuits and returns the thread unchanged (QA-iter1 MAJ-3). PLAN-0051 T-E-5-06. | X-Tenant-Id + X-User-Id |
| DELETE | `/api/v1/threads/{thread_id}` | Soft-delete thread | X-Tenant-Id + X-User-Id |
| GET | `/internal/v1/llm-costs` | LLM cost aggregates for rag-chat (PLAN-0033); queries `rag_chat_db.llm_usage_log` (no service_name filter — S8-exclusive DB); params: `period` (YYYY-MM), `provider`, `breakdown` | X-Internal-JWT (system) |

### Request/Response Models

```python
# ChatRequestSchema (POST /api/v1/chat and /api/v1/chat/stream)
{
    "message": str,              # User query (max 2000 chars)
    "thread_id": UUID | None,    # Continue existing conversation thread
    "entity_ids": list[UUID]     # Pre-selected entity filter (optional)
}

# ChatResponse (POST /api/v1/chat — synchronous)
{
    "answer": str,
    "citations": [
        {
            "ref": int,          # [1], [2] marker in answer text
            "id": str,           # chunk / relation / financial item ID
            "title": str | None,
            "url": str | None,
            "source": str | None,
            "published_at": str | None
        }
    ],
    "contradictions": list,      # detected contradictions across sources
    "thread_id": UUID | None,
    "message_id": UUID | None,
    "intent": str,               # FACTUAL_LOOKUP | GENERAL | COMPARISON | FINANCIAL_DATA | PORTFOLIO | REASONING | RELATIONSHIP | SIGNAL_INTEL
    "provider": str,             # deepinfra | openrouter | ollama
    "latency_ms": int
}
```

### EntityContextChatRequest / EntityContextChatResponse (PLAN-0074 Wave F)

```python
# EntityContextChatRequest (POST /api/v1/chat/entity-context{,/stream})
{
    "entity_id": UUID,              # S7 entity to load intelligence context for
    "question": str,                # User question (1–2000 chars; HTML tags stripped)
    "conversation_id": UUID | None, # Continue existing conversation thread
    "include_graph_context": bool   # Default True — load egocentric graph for relations
}

# EntityContextChatResponse (POST /api/v1/chat/entity-context — synchronous)
# Same shape as ChatResponse; the entity context is injected into the system prompt,
# not surfaced in the response body.
{
    "answer": str,
    "citations": list,
    "contradictions": list,
    "thread_id": UUID | None,
    "message_id": UUID | None,
    "intent": str,
    "provider": str,
    "latency_ms": int
}
```

**Entity context pipeline (PLAN-0074 Wave F)**:
1. `EntityContextClient` makes parallel HTTP calls to S7 `/internal/v1/entities/{id}/intelligence` + `/api/v1/entities/{id}/graph?depth=1&limit=5` (BP-235: `httpx.Timeout(5.0)`, retry 5xx once).
2. On S7 failure: `EntityChatContext(is_empty=True)` — question passed through unchanged to the regular pipeline.
3. On S7 success: `_build_system_prompt_prefix(ctx)` injects entity name, type, narrative, health score, data completeness, and top-5 relations before the user question (max 2000 chars prefix).
4. `entity_id` is added to `ChatRequest.context.entity_ids` so `search_documents` scopes retrieval to chunks referencing that entity (PLAN-0078 entity filter).

### BriefingResponse / PublicBriefingResponse (PLAN-0049 T-A-1-04)

`POST /internal/v1/briefings` (consumed by S10 email scheduler) and
`GET /api/v1/briefings/{morning,instrument/{entity_id}}` (proxied via S9)
return a structured AI brief.  The schema is **forward-compatible across rollouts**:
older callers only read `narrative` while newer surfaces render the
`headline` + `sections` shape.

```python
# BriefingResponse (POST /internal/v1/briefings)
{
    "narrative": str,              # Full markdown — always present
    "risk_summary": dict,          # Per-position risk telemetry
    "citations": list[dict],       # [{ref, id, title, url, ...}]
    "generated_at": str,           # ISO-8601 UTC
    "summary": str | None,         # PLAN-0048 — 1–2 sentence headline (collapsed view)
    "headline": str | None,        # PLAN-0049 T-A-1-04 — top-card title (≤240 chars)
    "sections": list[dict]         # PLAN-0049 T-A-1-04 — see BriefSection shape below.
                                   # PLAN-0083 (2026-05-08): the API model declares
                                   # this as list[dict[str, Any]] so JSON round-trip
                                   # via Valkey cache is symmetric. Domain code
                                   # constructs `BriefSection` frozen dataclasses;
                                   # a Pydantic field_validator converts them via
                                   # .to_dict() at response-construction time.
}

# PublicBriefingResponse (GET /api/v1/briefings/...)
# Adds two fields on top of BriefingResponse:
{
    ...,
    "cached": bool,                # Cache-hit indicator
    "entity_id": str | None        # Set on instrument briefings only
}

# BriefSection — one heading + bullet list
{
    "title": str,                  # ≤120 chars (heading)
    "bullets": list[str]           # 1–8 entries
}
```

**Render contract (frontend):** the three brief surfaces consume different
fields of `BriefingResponse`:

| Surface | Reads | Renders via |
|---------|-------|-------------|
| `<MorningBriefCard>` (dashboard, expanded) | `summary` + `sections[]` + `citations[]` if `sections.length > 0`; otherwise `narrative` | structured 3-row layout *or* `<MarkdownContent>` fallback |
| `<InstrumentAISubheader>` (instrument page header) | `narrative` only | `<MarkdownContent size="compact">` |
| `<IntelligenceTab>` brief block (instrument page) | `narrative` only | `<MarkdownContent size="comfortable">` |

The two instrument surfaces deliberately ignore `sections`/`headline` —
in tight column layouts the structured-cards form is too tall.  Backend
keeps emitting the structured fields so a future deepening of those
surfaces (phase 2) is purely a frontend swap.  When the backend emits
`sections == []` (or only `narrative`), every surface still works
unchanged — R11: never break wire format.

### SSE Streaming Events (POST /api/v1/chat/stream)

| Event | Payload |
|-------|---------|
| `thinking` | `{"stage": str}` — emitted before first LLM call; shows pulsing indicator in UI |
| `status` | `{"step": "loading_context" \| "entity_resolution" \| "query_expansion"}` |
| `tool_call` | `{"type": "tool_call", "tool": str, "label": str, "input": dict, "status": "running"}` — emitted before each tool executes |
| `tool_result` | `{"type": "tool_result", "tool": str, "status": "ok" \| "error" \| "empty" \| "transport_error", "item_count": int, "duration_ms"?: int, "result_preview"?: [{"id", "title"}], "grounding_sample"?: {"fields": {...}, "sampled_rows": int, "total_rows": int, "truncated": bool}}` — emitted after each tool completes. `duration_ms` is server-measured; `result_preview` is bounded to 3 entries (80-char titles). `grounding_sample` (PLAN-0110 W2 / PRD-0091 FR-5) is an **optional, opt-in** bounded/redacted sample of allow-listed numeric/identifier tool-result VALUES — attached **only when** `CHAT_EVAL_GROUNDING_SAMPLES=true` AND `status=="ok"` AND a sample survives the allow-list; omit-when-empty so the legacy 4-key payload stays byte-identical when off. Hard caps: ≤3 rows, ≤8 fields/row, ≤32 chars/value, ≤1024 bytes (`truncated=true` when cut). Allow-list is numeric/identifier fields only (`revenue, eps, gross_profit, pe_ratio, ticker, period, confidence, …`); document bodies, narrative text, and any portfolio/account identifiers are never sampled (FR-8). Unknown tools → no sample. Used by the chat-eval judge to verify (not presume) numeric grounding |
| `suggestions` | JSON array of exactly 3 follow-up question strings — emitted after `contradictions`. Derived deterministically from resolved entities + executed tools (no extra LLM call); toggled by `RAG_CHAT_SUGGESTIONS_ENABLED` (default true) |
| `token` | `{"text": "..."}` — streamed LLM output chunk |
| `citations` | `[{ref, id, title, url, source, published_at}]` |
| `contradictions` | `[...]` |
| `metadata` | `{thread_id, message_id, intent, provider, latency_ms}` |
| `error` | `{code, message}` |
| `pending_action` | `{proposal_id, tool_name, description, params: {entity_id, condition, threshold, severity}}` — emitted when a write-action tool proposes an action awaiting user confirmation (PLAN-0082) |
| `action_executed` | `{proposal_id, tool_name, result: {alert_id, entity_id, condition, severity, created_at}}` — emitted when a confirmed action is executed successfully (PLAN-0082) |
| `action_rejected` | `{proposal_id, tool_name, reason}` — emitted when a user rejects an action proposal or execution fails (PLAN-0082) |

---

## Chat Pipeline (Tool-Use Architecture)

**PLAN-0067 replaced the classical 13-step pipeline with a tool-use loop. Tool-use is the ONLY path — there is no feature flag and no fallback to the classical pipeline.**

```
Input → Validate → Cache check → Rate limit → Load history → Release UoW
      → emit_thinking(stage)
      → LLM first turn (chat_with_tools, tool catalog injected as schema)
      → for each tool_call in response:
            emit_tool_call(tool_name, input_summary, status="running")
            execute tool → inject result into context
            emit_tool_result(tool_name, status="ok"|"error"|"empty", item_count)
      → [all-tools-failed guard — prevents second LLM turn with zero context]
      → LLM second turn (stream_chat) → emit token events
      → Output processing + citation injection
      → Re-acquire UoW → persist thread + message
```

### Tool Catalog (20 tools — `libs/tools/src/tools/capability_manifest.yaml` v3)

| Tool | Target | Description | Since |
|------|--------|-------------|-------|
| `get_price_history` | S3 | OHLCV price data for a ticker | v1 |
| `get_fundamentals_history` | S3 | Quarterly financial metrics | v1 |
| `search_documents` | S6 | Hybrid BM25+ANN full-text search (primary text retrieval) | v1 |
| `get_entity_graph` | S7 | Egocentric graph for an entity | v1 |
| `traverse_graph` | S7 | Multi-hop path finding (Cypher injection guard active) | v1 |
| `search_entity_relations` | S7 | Relation triplets between entities | v1 |
| `search_claims` | S7 | Analyst claims, date-filtered | v1 |
| `search_events` | S7 | Corporate events, date-filtered | v1 |
| `get_contradictions` | S7 | Cross-source contradiction pairs | v1 |
| `get_portfolio_context` | S1 | User portfolio holdings | v1 |
| `get_entity_narrative` | S9→S7 | LLM-generated entity narrative (markdown); high-authority (trust_weight=0.88). Endpoint: `GET /api/v1/entities/{id}/narratives` | v2 |
| `get_entity_paths` | S9→S7 | Top-N pre-computed multi-hop relationship paths, composite_score-ranked. Endpoint: `GET /api/v1/entities/{id}/paths` | v2 |
| `get_entity_health` | S9→S7 | Entity health score, key metrics, source distribution (extracted from intelligence bundle). Endpoint: `GET /api/v1/entities/{id}/intelligence` | v2 |
| `get_entity_intelligence` | S9→S7 | Full intelligence bundle: narrative + paths + health + relations summary. Single call for "tell me everything about X". Endpoint: `GET /api/v1/entities/{id}/intelligence` | v2 |
| `get_morning_brief` | DB | User's latest morning brief from `user_briefs` table via `BriefArchivePort`. Read-only (R27). trust_weight=0.92 | v3 |
| `compare_entities` | S3 | Side-by-side comparison of 2-4 tickers: fundamentals highlights + latest quote in parallel | v3 |
| `screen_universe` | S9→S3 | Quantitative screener via S9 `POST /v1/fundamentals/screen`. Filter by market_cap, P/E, sector, region | v3 |
| `get_market_movers` | S9→S3 | Top gainers/losers/most-active via S9 `GET /v1/market/top-movers`. Default: gainers/1d | v3 |
| `get_economic_calendar` | S9→S3 | Macro events (CPI, FOMC, GDP) via S9 `GET /v1/fundamentals/economic-calendar` | v3 |
| `get_earnings_calendar` | S9→S3 | Earnings release dates + EPS via S9 `GET /v1/fundamentals/earnings-calendar` | v3 |

**v2 intelligence tools (PLAN-0080 Wave A)**: all 4 call S9-proxied endpoints (R14/R7 compliance — never S7 directly). All respect `EntityContext` scope: when the executor is bound to an entity via `ToolExecutorFactory.for_request(entity_context=...)`, the `entity_id` is auto-injected and LLM-supplied values are silently overridden (M-1 enforcement).

**v3 catalog tools (PLAN-0081 Wave A)**: 6 tools backed by `S3BriefPort` (new Protocol — screener/movers/calendars via S9 proxy) and `BriefArchivePort` (existing). `S3BriefClient` adapter wired in `app.py` lifespan. `BriefArchiveReadAdapter` creates per-call read sessions (R27). All tools are read-only — no UnitOfWork acquired.

All tool executions are independent; failures return empty results (safe degradation). The all-tools-failed guard prevents the second LLM turn from being called with zero context — the orchestrator short-circuits to a fallback answer in that case.

---

### Action Tools and User Authorization (PLAN-0082)

Two tools differ from the rest: they interact with user-owned state rather than read-only market data.

| Tool | Type | Target | Description |
|------|------|--------|-------------|
| `get_alerts` | Read-only | S10 | List active alert rules for the authenticated user |
| `create_alert` | Write (requires confirmation) | S10 | Propose a new price/volume alert rule |

#### Confirmation Flow

`create_alert` follows the "propose before execute" pattern — the LLM never creates alerts directly:

```
1. LLM emits create_alert tool call.
2. ToolExecutor._handle_create_alert():
   a. Validates condition against _VALID_CONDITIONS allowlist
      {"price_below", "price_above", "volume_spike", "percent_change"}.
   b. Validates severity against _VALID_SEVERITIES allowlist
      {"low", "medium", "high", "critical"}.
   c. On invalid condition or severity → returns [] (safe refusal, no modal shown).
   d. On valid inputs → generates proposal_id (UUIDv7) and returns an
      action_pending RetrievedItem.
3. ChatOrchestratorUseCase detects item_type == action_pending and emits
   pending_action SSE event (proposal_id, tool_name, description, params).
4. Frontend shows ActionConfirmModal to the user.
5. User confirms → frontend calls POST /api/v1/chat/proposals/{proposal_id}/confirm
   with the params from the SSE event.
6. Proposal endpoint calls S10 POST /v1/alerts and emits action_executed SSE.
7. User declines → frontend emits action_rejected locally (no server call needed).
```

#### Security Properties

- **No silent writes**: `create_alert` NEVER calls S10 without explicit user confirmation.
- **Condition allowlist** (`_VALID_CONDITIONS` in `tool_executor.py`): prompt-injected strings like `"__SYSTEM_PROMPT__"` or `"admin_override"` are rejected before reaching the SSE stream.
- **Severity allowlist** (`_VALID_SEVERITIES` in `tool_executor.py`): strings like `"CRITICAL; DROP TABLE alerts;"` are rejected at the same stage.
- **Auth from JWT only**: `user_id` and `tenant_id` come exclusively from the `InternalJWT` parsed by middleware — never from tool call arguments. The `**_` in the handler signature silently discards injected `tenant_id`/`user_id` args.
- **Rate limit**: max 5 `create_alert` proposals per `ToolExecutor` instance (per chat request). A 6th call returns `None` without presenting a confirmation modal.
- **Idempotency guard** (`proposal.py`): `_CONFIRMED_PROPOSALS` in-memory set prevents duplicate alert creation if the frontend retries a confirmation. Returns HTTP 409 on replay. Single-instance only — move to Valkey for multi-replica deployments.
- **All-tools-failed guard exemption**: when `create_alert` is the only tool and its result is `action_pending`, the orchestrator does NOT emit `all_tools_failed`. The guard only fires when ALL tool results are empty AND no pending action proposals were generated.

---

## LLM Provider Chain

| Order | Provider | Model (env var to override) | Notes |
|-------|----------|------------------------------|-------|
| 1 | DeepInfra | `Qwen/Qwen3-235B-A22B-Instruct-2507` (`RAG_CHAT_COMPLETION_MODEL`) | Primary (requires `RAG_CHAT_DEEPINFRA_API_KEY`) |
| 2 | OpenRouter | `deepseek/deepseek-r1-distill-qwen-32b` (`RAG_CHAT_OPENROUTER_COMPLETION_MODEL`) | Fallback (requires `RAG_CHAT_OPENROUTER_API_KEY`) |
| 3 | Ollama (local) | `deepseek-r1:32b` (`RAG_CHAT_OLLAMA_COMPLETION_MODEL`) | Emergency fallback |

**Intent classification**: `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` via DeepInfra (`RAG_CHAT_DEEPINFRA_CLASSIFICATION_MODEL`); Ollama `qwen3:0.6b` fallback.

**Reranker**: Cohere Rerank v2 (requires `RAG_CHAT_COHERE_API_KEY`); falls back to fusion_score ordering when absent. Ollama `bge-reranker-v2-m3` is a legacy option but no longer in the Ollama registry.

**Embeddings**: Jina AI embeddings-v3 (1024-dim, requires `RAG_CHAT_JINA_API_KEY`) when available; falls back to S6/Ollama bge-large (7-13s on CPU).

60-second negative cache per provider in Valkey on failure. `ProviderUnavailableError` raised if all fail.

---

## Safety Controls

- **Input validation**: max 2000 chars, PII regex scan (email/phone/SSN/CC), prompt injection detection
- **Output sanitization**: strip `<think>`, `<reasoning>`, `<scratchpad>` tags; PII redaction
- **Rate limit**: `RATE_LIMIT_PER_TENANT` requests/min per tenant (Valkey sliding window)
- **Completion cache**: Valkey 24h TTL, keyed by `rag:v1:completion:{message_hash}:{thread_id}`

---

## Caching Strategy

| Key | TTL | Purpose |
|-----|-----|---------|
| `rag:v1:completion:{hash}` | 24h | Full completion response |
| `rag:v1:neg:{provider}` | 60s | Provider negative cache |
| `rag:v1:rate:{tenant_id}` | 60s | Rate limit counter |

---

## Database Schema

### `threads` table

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID (PK) | UUIDv7 |
| `tenant_id` | UUID | Multi-tenant isolation |
| `user_id` | UUID | Owner |
| `title` | text | Auto-generated or user-set |
| `created_at` | timestamptz | |
| `updated_at` | timestamptz | |
| `last_message_at` | timestamptz | |
| `is_deleted` | bool | Soft delete |

### `messages` table

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID (PK) | UUIDv7 |
| `thread_id` | UUID (FK) | |
| `role` | text | `user` \| `assistant` |
| `content` | text | |
| `intent` | text | Assistant messages only |
| `provider` | text | LLM provider used |
| `model` | text | |
| `token_count_in` | int | |
| `token_count_out` | int | |
| `latency_ms` | int | |
| `citations` | jsonb | |
| `contradiction_refs` | jsonb | |
| `created_at` | timestamptz | |

---

## Internal Architecture

```
services/rag-chat/src/rag_chat/
├── api/
│   ├── dependencies.py          # AuthContextDep, UoWDep, ReadUoWDep
│   ├── schemas.py               # ChatRequestSchema, ChatResponse
│   └── routes/
│       ├── chat.py              # POST /api/v1/chat, POST /api/v1/chat/stream
│       └── threads.py           # CRUD for conversation threads
├── application/
│   ├── caching/
│   │   ├── completion_cache.py  # Valkey 24h response cache
│   │   └── rate_limiter.py      # Sliding-window rate limiter
│   ├── pipeline/
│   │   ├── tool_executor.py          # ToolExecutorFactory, EntityContext, ToolCallProvenance; 8 handlers; Cypher injection guard (_ALLOWED_CYPHER_REL_TYPES)
│   │   ├── hyde_expander.py          # HyDE hypothesis + embedding
│   │   ├── fusion.py                 # GraphEnricher + FusionPipeline
│   │   ├── reranker.py               # BGE reranker via Ollama
│   │   ├── context_assembler.py      # Numbered context blocks
│   │   ├── prompt_builder.py         # Full prompt assembly
│   │   ├── output_processor.py       # Strip think/reasoning, citations
│   │   └── sse_emitter.py            # SSE event builders (emit_thinking, emit_tool_call, emit_tool_result)
│   ├── ports/
│   │   ├── upstream_clients.py       # S1Port, S3Port, S6Port, S7Port
│   │   ├── llm_provider.py           # LlmChatProvider Protocol (chat_with_tools + stream_chat) alongside LlmStreamProvider
│   │   └── embedding.py             # EmbeddingPort
│   ├── security/
│   │   └── input_validator.py        # PII + injection detection
│   └── use_cases/
│       ├── chat_orchestrator.py      # Tool-use loop coordinator (max 2 LLM turns; all-tools-failed guard)
│       ├── get_thread.py
│       ├── list_threads.py
│       ├── delete_thread.py
│       └── persist_chat.py
├── domain/
│   ├── entities/chat.py         # ChatRequest, ChatContext, RetrievedItem, ConversationThread, Message
│   ├── enums.py                 # Intent, ItemType, MessageRole
│   ├── errors.py                # RateLimitExceededError, PIIDetectedError, etc.
│   └── value_objects.py         # DateRange, Citation
└── infrastructure/
    ├── clients/
    │   ├── s1_client.py         # Portfolio context
    │   ├── s3_client.py         # Market data fundamentals/quotes
    │   ├── s6_client.py         # Chunk search + entity resolution
    │   └── s7_client.py         # Relations, graph, claims, events
    ├── config/settings.py
    ├── db/
    │   ├── models.py            # Thread, Message ORM
    │   ├── repositories.py      # ThreadRepository, MessageRepository
    │   ├── session.py           # Dual-URL session factory (R23)
    │   └── unit_of_work.py      # RagUnitOfWork, ReadOnlyRagUnitOfWork
    ├── llm/
    │   ├── deepinfra_adapter.py
    │   ├── openrouter_adapter.py
    │   ├── ollama_adapter.py
    │   └── provider_chain.py
    └── metrics/
        └── prometheus.py        # 10 Prometheus metrics
```

---

## Configuration

All env vars use prefix `RAG_CHAT_`.

| Env Var | Default | Required | Notes |
|---------|---------|----------|-------|
| `RAG_CHAT_DATABASE_URL` | — | Yes | PostgreSQL write URL (`postgresql+asyncpg://...`) |
| `RAG_CHAT_DATABASE_URL_READ` | (same as write) | No | Read replica URL (R27) |
| `RAG_CHAT_DB_POOL_SIZE` | `10` | No | Write pool size |
| `RAG_CHAT_DB_MAX_OVERFLOW` | `20` | No | Write pool max overflow |
| `RAG_CHAT_DB_POOL_SIZE_READ` | `20` | No | Read pool size |
| `RAG_CHAT_DB_MAX_OVERFLOW_READ` | `30` | No | Read pool max overflow |
| `RAG_CHAT_VALKEY_URL` | `redis://localhost:6379/0` | No | Valkey for caching, rate limiting, circuit breakers |
| `RAG_CHAT_DEEPINFRA_API_KEY` | — | No | Primary LLM provider (strongly recommended) |
| `RAG_CHAT_OPENROUTER_API_KEY` | — | No | Fallback LLM provider |
| `RAG_CHAT_COHERE_API_KEY` | — | No | Reranker (Cohere Rerank v2); falls back to fusion_score when absent |
| `RAG_CHAT_JINA_API_KEY` | — | No | Query embeddings (Jina v3 1024-dim, ~100-300ms); falls back to S6/Ollama bge-large when absent |
| `RAG_CHAT_OLLAMA_BASE_URL` | `http://localhost:11434` | No | Ollama for GLiNER NER + emergency completion fallback |
| `RAG_CHAT_OLLAMA_COMPLETION_MODEL` | `deepseek-r1:32b` | No | Ollama completion model (emergency fallback only) |
| `RAG_CHAT_OLLAMA_CLASSIFICATION_MODEL` | `qwen3:0.6b` | No | Ollama intent classification model |
| `RAG_CHAT_OLLAMA_RERANKER_MODEL` | `bge-reranker-v2-m3` | No | Ollama reranker (legacy — no longer in Ollama registry) |
| `RAG_CHAT_COMPLETION_PROVIDER` | `deepinfra` | No | Primary provider: `deepinfra` |
| `RAG_CHAT_COMPLETION_MODEL` | `Qwen/Qwen3-235B-A22B-Instruct-2507` | No | DeepInfra completion model ID |
| `RAG_CHAT_OPENROUTER_COMPLETION_MODEL` | `deepseek/deepseek-r1-distill-qwen-32b` | No | OpenRouter fallback model ID |
| `RAG_CHAT_DEEPINFRA_CLASSIFICATION_MODEL` | `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` | No | DeepInfra intent classification model |
| `RAG_CHAT_API_GATEWAY_URL` | `http://api-gateway:8000` | No | S9 URL for JWKS fetch at startup |
| `RAG_CHAT_INTERNAL_JWT_SKIP_VERIFICATION` | `false` | No | **Dev/test only** — skip RS256 JWT verification |
| `RAG_CHAT_S1_BASE_URL` | `http://portfolio:8001` | No | S1 portfolio service URL |
| `RAG_CHAT_S3_BASE_URL` | `http://market-data:8003` | No | S3 market data service URL |
| `RAG_CHAT_S6_BASE_URL` | `http://nlp-pipeline:8006` | No | S6 NLP pipeline service URL |
| `RAG_CHAT_S7_BASE_URL` | `http://knowledge-graph:8007` | No | S7 knowledge graph service URL |
| `RAG_CHAT_KG_INTERNAL_BASE_URL` | `http://knowledge-graph:8007` | No | S7 URL for entity context calls (may route differently in production VPC) |
| `RAG_CHAT_S1_INTERNAL_TOKEN` | `""` | No | Deprecated — no longer used (PRD-0025 RS256 JWT now propagated via middleware) |
| `RAG_CHAT_RATE_LIMIT_PER_TENANT` | `10` | No | Requests per minute per `(tenant_id, user_id)` |
| `RAG_CHAT_UPSTREAM_TIMEOUT_SECONDS` | `5.0` | No | Per retrieval task timeout |
| `RAG_CHAT_CB_ENABLED` | `true` | No | Enable circuit breakers for retrieval sources |
| `RAG_CHAT_CB_FAILURE_THRESHOLD` | `3` | No | Failures before circuit opens |
| `RAG_CHAT_CB_FAILURE_WINDOW_SECONDS` | `120` | No | Failure counting window |
| `RAG_CHAT_CB_COOL_DOWN_SECONDS` | `120` | No | Cooldown after circuit opens (10-3600s) |
| `RAG_CHAT_CB_PROBE_TTL_SECONDS` | `5` | No | SETNX probe lock TTL for stampede prevention (1-30s) |
| `RAG_CHAT_TRUST_W_SOURCE` | `0.4` | No | Trust formula weight for source authority |
| `RAG_CHAT_TRUST_W_CORROBORATION` | `0.1` | No | Trust formula weight for corroboration factor |
| `RAG_CHAT_TRUST_W_EXTRACTION` | `0.1` | No | Trust formula weight for extraction confidence |
| `RAG_CHAT_CITATION_CRON_ENABLED` | `false` | No | Enable citation accuracy cron (costs LLM tokens). Cadence is **DAILY 03:00 UTC** over the **last 24h** of messages (PLAN-0107; was weekly Sunday + 7d window) |
| `RAG_CHAT_CITATION_JUDGE_PROVIDER` | `deepinfra` | No | `deepinfra` or `ollama` |
| `RAG_CHAT_CITATION_JUDGE_MODEL` | `meta-llama/Meta-Llama-3.1-8B-Instruct` | No | Model for citation accuracy scoring |
| `RAG_CHAT_CITATION_MIN_SAMPLES` | `10` | No | Min messages required to emit gauge (1-500) |
| `RAG_CHAT_CITATION_CALL_TIMEOUT_S` | `15.0` | No | Per-judge-call timeout (>0, ≤120s) |
| `RAG_CHAT_CITATION_RUN_BUDGET_S` | `600.0` | No | Total wall-clock budget per cron run |
| `RAG_CHAT_LOG_LEVEL` | `INFO` | No | structlog log level |
| `RAG_CHAT_LOG_JSON` | `true` | No | JSON-structured logs |
| `RAG_CHAT_OTLP_ENDPOINT` | `""` | No | OpenTelemetry collector endpoint |
| `CHAT_EVAL_GROUNDING_SAMPLES` | `false` | No | **Un-prefixed** (NOT `RAG_CHAT_`) eval-harness toggle (PLAN-0110 W2 / PRD-0091 FR-5). When `true`, the `tool_result` SSE frame carries the optional bounded/redacted `grounding_sample` (see SSE table above). Read per-call from `os.environ` in `SSEEmitter.emit_tool_result` (hot-toggle, no restart). Default OFF (NFR-2) keeps eval-only data out of normal traffic |

---

## Observability

### Prometheus Metrics

| Metric | Type | Labels |
|--------|------|--------|
| `rag_queries_total` | counter | `intent`, `provider`, `status` |
| `rag_latency_seconds` | histogram | `intent`, `provider` |
| `rag_first_token_latency_seconds` | histogram | `provider` |
| `rag_retrieval_items_total` | histogram | `source_type` |
| `rag_cache_hits_total` | counter | — |
| `rag_provider_fallback_total` | counter | `from_provider` |
| `rag_provider_unavailable_total` | counter | `provider` |
| `rag_thread_count` | gauge | `tenant_id` |
| `rag_contradiction_surfaced_total` | counter | — |
| `rag_injection_blocked_total` | counter | — |
| `rag_retrieval_score_distribution` | histogram | `source` |
| `rag_source_contribution_total` | counter | `source` |
| `rag_reranker_position_change` | gauge | — |
| `rag_citation_accuracy_24h` | gauge | — |
| `rag_citation_accuracy_call_failures_total` | counter | `reason` |
| `rag_circuit_breaker_open` | gauge | `source` |
| `rag_tool_call_total` | counter | `tool_name`, `status` |
| `rag_tool_call_latency_seconds` | histogram | `tool_name` |
| `rag_tool_use_first_turn_latency_seconds` | histogram | — |

#### Retrieval Quality Metrics (PLAN-0063 W5-5)

`rag_retrieval_score_distribution` — histogram of per-chunk fusion scores (buckets `[0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0]`), labelled by `source_type`. Emitted in `retrieval_orchestrator._fetch_chunks`.

`rag_source_contribution_total` — counter incremented once per query per source that contributed ≥1 chunk to fusion. Together with the histogram, reveals whether lexical / KG / SQL sources are pulling weight.

`rag_reranker_position_change` — rolling gauge (window=100 queries) of the fraction of queries where the reranker's top-1 differs from the fusion top-1. Updated via `record_reranker_position_change()` after step 8 in `ChatOrchestrator`. A gauge near 0 means the reranker is redundant; near 1 means fusion ordering is unreliable.

`rag_citation_accuracy_24h` — **canonical** gauge (PLAN-0107) set by the **daily** citation-accuracy cron (`ScoreCitationAccuracyUseCase`). Values: 0 = irrelevant snippets, 1 = direct verbatim support. Sample window: last 24h of assistant messages. Surfaced as the "Citation Accuracy (24h)" stat panel in `infra/grafana/dashboards/rag-chat.json` (PLAN-0107 follow-up). The legacy `rag_citation_accuracy` alias was removed in the same revision — it was dual-emitted during the PLAN-0099 W4 transition window but no Grafana panel or external consumer ever scraped it.

### Citation-Accuracy Cron

`infrastructure/jobs/citation_accuracy_cron.py` — `start_citation_accuracy_cron(use_case) → asyncio.Task` schedules a background asyncio task:
- **First run**: immediately on startup (gauge populated within minutes of first deployment) — only if no `last_run_at` is recorded in Valkey
- **Recurring (PLAN-0107)**: **DAILY at 03:00 UTC** (was weekly Sunday 03:00 UTC). Cadence + sample window were paired in PLAN-0107 so a daily run scores the last 24h of messages.
- **Crashloop guard (PLAN-0107)**: a Valkey-backed `last_run_at` key with a 1h grace window prevents repeated runs if the service is restart-looping (each run burns DeepInfra tokens).

`application/use_cases/score_citation_accuracy.py` — `ScoreCitationAccuracyUseCase`:
1. Calls `MessageRepository.sample_recent_with_citations(n=50, since=now-24h)` — random sample from the **last 24 hours** (PLAN-0107; was 7 days), assistant-role messages, non-empty `citations` JSONB.
2. For each message, `iter_cited_claims(msg)` extracts `(sentence, "c{N}")` pairs from `[cN]` inline markers, or `(full_content, "c{ref}")` for plain-chat messages.
3. **Dedup (PLAN-0107)**: `(message_id, citation.id)` is the dedup key — the same chunk cited under different `[cN]` refs within one message scores ONCE; the same chunk reused across two messages still scores twice (by design).
4. For each pair, calls `LLMJudgePort.score_citation(claim=, snippet=, judge_prompt_id=...)`. **Snippet upgrade (PLAN-0107)**: `snippet = cite.text` (chunk text persisted in the `citations` JSONB up to ~2500 chars), falling back to `cite.title` for legacy records where `text` is `None`. `judge_prompt_id = "citation_judge@<version>#<hash>"` is persisted on each artefact (`q_<id>.json`) so saved outputs are unambiguously linked to the rubric text that produced them.
5. Normalises raw 0–3 scores to [0, 1] (÷3), drops invalid responses.
6. Sets the `rag_citation_accuracy_24h` gauge; returns 0.0 if fewer than `RAG_CHAT_CITATION_MIN_SAMPLES` samples. (The legacy `rag_citation_accuracy` alias was removed in the PLAN-0107 follow-up cleanup — see metrics list above.)

**Schema note (PLAN-0107)**: `Citation` domain entity now carries a `text: str | None` field that is persisted to the `citations` JSONB column for the judge but **NEVER sent to the frontend** — the SSE projection layer strips it before emitting the `citations` event (regression-pinned by `test_sse_citations_event_never_emits_text_field`).

**Migration `0008_*` (PLAN-0107)**: adds the partial index `ix_messages_role_created_partial ON messages (role, created_at DESC) WHERE citations IS NOT NULL` to support the new `since`-filtered query in the cron.

**PLAN-0084 A-1 hardening (wire-up + prompt fence + error isolation):**

- **Wire-up** (`app.py`): Controlled by `RAG_CHAT_CITATION_CRON_ENABLED` (default `false`). When enabled, `_wire_citation_cron()` builds a `CitationJudgeAdapter` → `ScoreCitationAccuracyUseCase` and calls `start_citation_accuracy_cron()`. The returned `asyncio.Task` is stored on `app.state.citation_cron_task` and cancelled on shutdown. A done-callback (BP-268 pattern) logs `CRITICAL` if the cron task crashes unexpectedly.
- **Prompt injection fence** (F-S01): `_sanitise(text, max_chars)` truncates claim and snippet to 1024 chars and replaces known delimiter tokens (`<<<CLAIM `, `<<<SNIPPET `, `>>>`, `Respond with ONLY`) with `[REDACTED]`. The rubric uses explicit `<<<CLAIM START/END>>>` and `<<<SNIPPET START/END>>>` delimiters.
- **Per-call timeout**: `CitationJudgeAdapter` wraps the provider call in `asyncio.wait_for(timeout=citation_call_timeout_s)`. On timeout it raises `LLMJudgeTimeoutError` (domain error, never swallowed).
- **Error isolation**: `execute()` catches `LLMJudgeTimeoutError` and generic provider exceptions per-pair; both increment `rag_citation_accuracy_call_failures_total` (`reason=timeout|provider_error|invalid_response`). The outer loop continues for remaining pairs.
- **Wall-clock budget**: `asyncio.timeout(run_budget_s)` (default 600s) wraps the entire scoring loop. If the budget is exceeded the partial results are committed and the gauge is emitted.

**Environment variables (citation cron):**

| Variable | Default | Description |
|---|---|---|
| `RAG_CHAT_CITATION_CRON_ENABLED` | `false` | Set `true` to enable the cron (off by default to avoid LLM cost on first deploy) |
| `RAG_CHAT_CITATION_JUDGE_PROVIDER` | `deepinfra` | `deepinfra` or `ollama` |
| `RAG_CHAT_CITATION_MIN_SAMPLES` | `10` | Minimum messages required to emit a gauge |
| `RAG_CHAT_CITATION_CALL_TIMEOUT_S` | `15.0` | Per-judge-call timeout in seconds |
| `RAG_CHAT_CITATION_RUN_BUDGET_S` | `600.0` | Total wall-clock budget per cron run |

**New metrics (PLAN-0084 A-1):**

| Metric | Type | Labels | Description |
|---|---|---|---|
| `rag_citation_accuracy_call_failures_total` | counter | `reason` | Count of skipped judge calls; reason = `timeout`, `provider_error`, `invalid_response` |

### Circuit Breaker (PLAN-0084 A-2)

`application/pipeline/circuit_breaker.py` — `SourceCircuitBreaker` guards each retrieval source (chunk, relations, graph, claims, events, contradictions, financial, portfolio) with a sliding-window failure counter backed by Valkey.

**Key design decisions (PLAN-0084 A-2):**

- **SETNX probe gating (F-X01)**: When the cooldown TTL expires (state key absent), only one caller wins the SETNX probe key. That caller receives `is_open() = False` and is allowed through. All other concurrent callers receive `True` (backed off) until the probe TTL expires. Prevents stampede on recovery.
- **Symmetric ZSET cleanup (F-X05 Option A)**: `record_success()` deletes only the state key and probe key. The failures ZSET is intentionally NOT deleted — it expires via its own TTL. This avoids a race where a concurrent `record_failure()` writer that ZADD'd just before `record_success()` ran would have its entry deleted, silently losing failure history.
- **Default cooldown lowered to 120s** (was 3600s): more appropriate for transient ML-provider outages where recovery is typically under 2 minutes.
- **Probe TTL default 5s**: controls how long the "back off" window lasts after one probe is admitted.
- **Prometheus gauge**: `rag_circuit_breaker_open` (label: `source`) set to 1 when breaker trips, 0 when recovered.

**Environment variables (circuit breaker):**

| Variable | Default | Description |
|---|---|---|
| `RAG_CHAT_CB_COOL_DOWN_SECONDS` | `120` | Cooldown after open (10–3600s) |
| `RAG_CHAT_CB_PROBE_TTL_SECONDS` | `5` | How long the "only one probe" lock lasts (1–30s) |
| `RAG_CHAT_CB_ENABLED` | `true` | Set `false` to disable all circuit breakers |

**New metrics (PLAN-0084 A-2):**

| Metric | Type | Labels | Description |
|---|---|---|---|
| `rag_circuit_breaker_open` | gauge | `source` | 1 = breaker open, 0 = closed/recovered |

---

## Trust Model (PLAN-0079)

Every `RetrievedItem` carries a `trust_weight ∈ [0, 1]` computed by `TrustScorer`
(`application/pipeline/trust_scorer.py`). The weight feeds the existing fusion
pipeline invariant `fusion_score = retrieval_score × recency_score × trust_weight`.

### Formula

```
trust = w_source × source_authority(source_type)
      + w_corroboration × corroboration_factor(evidence_count)
      + w_extraction × extraction_confidence_factor
```

The formula is **additive** (not multiplicative) to prevent numerical collapse.
With default weights, a `sec_10k` item yields `0.4×1.0 + 0.1×0.5 + 0.1×0.5 = 0.50`.

### SOURCE_AUTHORITY Table

Canonical per-source authority scores live in
`libs/contracts/src/contracts/trust/__init__.py`. Representative values:

| Source type | Authority |
|---|---|
| `sec_10k`, `sec_10q` | 1.00 |
| `sec_8k` | 0.95 |
| `sec_10k_a`, `sec_10q_a` | 0.92 |
| `earnings_data`, `earnings_transcript` | 0.92 |
| `corporate_action` | 0.88 |
| `press_release`, `financial` | 0.85 |
| `research`, `relation` | 0.80 |
| `claim` | 0.75 |
| `eodhd_news`, `finnhub_news`, `newsapi` | 0.65 |
| `default` | 0.50 |
| `social` | 0.30 |
| `user_generated` | 0.20 |

### Recency

Recency is **not** included in the trust formula — it is handled separately by
`item.recency_score` (computed by `compute_recency_score`, PLAN-0063 W5-4) and
multiplied into the final `fusion_score` downstream.

### Tunable Weights (env vars)

| Variable | Default | Description |
|---|---|---|
| `RAG_CHAT_TRUST_W_SOURCE` | `0.4` | Weight for source authority factor |
| `RAG_CHAT_TRUST_W_CORROBORATION` | `0.1` | Weight for corroboration factor (MVP: 0.5 when evidence_count=0) |
| `RAG_CHAT_TRUST_W_EXTRACTION` | `0.1` | Weight for extraction confidence (defaults to 0.5 when unavailable) |

Weights can be tuned without redeploying code. Note: the weights do not need to sum to 1.0. Recency is handled separately as a multiplicative factor via `item.recency_score` (PLAN-0063 W5-4), independent of these additive trust components.

### Eval Gate

Production weight changes MUST be validated against the 120-query golden set
(PLAN-0063 §3) with a ≥0.03 NDCG@10 regression threshold before being promoted.
Use `python scripts/eval_retrieval.py --mode trust_sweep --trust-w-source <W>
--trust-w-corroboration <W> --trust-w-extraction <W>` to run the eval harness
(live sweep gated on PLAN-0063 §3 golden set completion).

---

## Tenant Isolation

S8 enforces tenant isolation at the **application layer** via `tenant_id` scoping
on all thread and message operations. The boundary is documented here as a formal
contract; regression tests exist in `tests/unit/api/test_tenant_isolation.py`.

### Thread Ownership

Every `ConversationThread` carries a `tenant_id` (UUID, NOT NULL). All read and
write operations pass `tenant_id` from the JWT auth context to the repository,
which filters `WHERE tenant_id = :tid`:

- **`GetThreadUseCase`**: `threads.get(thread_id, user_id, tenant_id=tenant_id)` —
  returns `None` when tenant_id does not match → `ThreadNotFoundError` → HTTP 404.
- **`DeleteThreadUseCase`**: `threads.soft_delete(thread_id, user_id, tenant_id)` —
  same ownership check (single UPDATE with tenant_id filter, no TOCTOU window).
- **`ListThreadsUseCase`**: `threads.list_active(user_id, tenant_id, ...)` —
  returns only threads owned by the requesting tenant.
- **`CreateThreadUseCase`**: Thread is created with the requesting tenant's
  `tenant_id` — no cross-tenant creation is possible.

### Message Ownership

Messages inherit tenant isolation from their parent thread: `messages.thread_id`
FK → `threads.thread_id`. Since thread reads are tenant-scoped, messages are
transitively isolated.

### RAG Retrieval Scoping

RAG tool calls query globally shared data (articles, entities,
relations, claims, events from S1/S3/S6/S7). This is by design — news and
market intelligence are not tenant-specific. Tenant isolation applies only to:

- **Chat thread context**: which thread the response is persisted to (tenant-scoped)
- **Portfolio context (`get_portfolio_context` tool)**: scoped by S1's `user_id` check on portfolio data
- **Conversation history**: loaded from the tenant-scoped thread

### Security Notes

- **404 (not 403)** on cross-tenant access prevents thread ID enumeration attacks.
- `tenant_id` is extracted from the RS256 internal JWT set by `InternalJWTMiddleware`
  (PRD-0025). It is never read from raw request headers.
- Defense-in-depth: ownership is checked in the **use case layer** (not just the
  route), so any new routes that touch threads inherit the same protection.

---

## Proposal Confirmation Endpoint (PLAN-0082)

After the LLM emits a `create_alert` tool call, the pipeline emits a `pending_action` SSE
event instead of executing immediately. The frontend shows a confirmation modal. On "Confirm"
the frontend calls:

```
POST /api/v1/chat/proposals/{proposal_id}/confirm
X-Internal-JWT: <user jwt>
Content-Type: application/json

{
  "tool_name": "create_alert",
  "entity_id": "<UUID>",
  "condition": "price_below | price_above | volume_spike | percent_change",
  "threshold": {"value": 200.0},
  "severity": "low | medium | high | critical"
}
```

Response: SSE stream with `action_executed` or `action_rejected` event.

**Idempotency**: `_CONFIRMED_PROPOSALS` in-memory set prevents duplicate alert creation
on retry. Returns 409 on replay. Single-instance only — move to Valkey for multi-replica.

---

## Briefing Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/internal/v1/briefings` | X-Internal-Token | Generate portfolio risk narrative for email digest |
| GET | `/api/v1/briefings/morning` | X-Internal-JWT | Morning briefing (proxied via S9) |
| POST | `/api/v1/briefings/morning/generate` | X-Internal-JWT | Force-regenerate the morning brief — bypasses the cache/staleness check (dashboard Regenerate button). 202 + `{"status": "queued", "generated_at"}`; shares the 60/hr `brief_gen_rate` bucket with instrument generate; writes both fresh + lastgood cache keys (proxied via S9 `POST /v1/briefings/morning/generate`) |
| GET | `/api/v1/briefings/instrument/{entity_id}` | X-Internal-JWT | Instrument briefing |

**`POST /internal/v1/briefings`**: consumed by S10 email scheduler. Rate-limited to
100/day per user. Uses `EMAIL_DEEP_BRIEF_PROMPT` system prompt. Returns `BriefingResponse`
(see API Surface section).

---

## Internal Retrieval Endpoint (PLAN-0063)

```
POST /v1/internal/retrieve
X-Internal-JWT: <system jwt>

{"query_text": "...", "top_k": 20, "query_embedding": [...]}
```

Read-only retrieval for the eval harness. Runs steps 0/3/4/5 (no fusion, no rerank, no LLM).
When `query_embedding` is set, HyDE+embedder are bypassed (deterministic for CI).
Returns: `{intent, candidates: [{chunk_id, doc_id, rank, score, item_type, source_type, snippet}]}`.

---

## How to Run Locally

### Option A — Full Docker Compose (Recommended)

```bash
make dev    # starts all services including rag-chat on port 8008
```

### Option B — Standalone (Requires DeepInfra Key)

```bash
cd services/rag-chat

cat > .env << 'EOF'
RAG_CHAT_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rag_db
RAG_CHAT_VALKEY_URL=redis://localhost:6379/0
RAG_CHAT_DEEPINFRA_API_KEY=<your-deepinfra-key>
RAG_CHAT_INTERNAL_JWT_SKIP_VERIFICATION=true   # no Zitadel required
RAG_CHAT_S1_BASE_URL=http://localhost:8001
RAG_CHAT_S3_BASE_URL=http://localhost:8003
RAG_CHAT_S6_BASE_URL=http://localhost:8006
RAG_CHAT_S7_BASE_URL=http://localhost:8007
EOF

# Migrate
alembic upgrade head

# Run
make run    # uvicorn on port 8008
```

### Minimal Dev Without External Services

Without DeepInfra, the service falls back to local Ollama for completions. The
pipeline degrades gracefully — all tool calls still execute but LLM responses come
from the local model:

```bash
# Ensure Ollama is running with deepseek-r1:32b model
ollama pull deepseek-r1:32b

# Set RAG_CHAT_DEEPINFRA_API_KEY to empty (falls back to Ollama)
```

---

## How to Run Tests

```bash
cd services/rag-chat

# Unit tests (fast, no external deps)
python -m pytest tests/unit/ -m unit -v

# Integration tests (require rag_db + Valkey)
python -m pytest tests/integration/ -m integration -v

# Full suite
python -m pytest tests/ -v

# Lint + types
make lint
```

**After editing code**: always rebuild the container before declaring done, since
the production container has old code until rebuilt:

```bash
docker compose build rag-chat && docker compose up -d rag-chat
```

---

## Common Pitfalls

- **`ToolExecutorFactory` must be wired in `app.py` lifespan** — not auto-instantiated.
  Forgetting this causes `AttributeError` at first chat request.

- **`ToolUseBlock.id` (not `.tool_use_id`)** — use `.id` when building `ToolCallProvenance`.

- **UoW must be released before the tool loop** — holding it open across tool I/O causes
  connection pool exhaustion under load. Re-acquire for the final persist step.

- **All-tools-failed guard**: if all tools return `error`/`empty`, the orchestrator MUST
  NOT invoke the second LLM turn — it short-circuits to a fallback answer.

- **`RAG_CHAT_CYPHER_ENABLED` is REMOVED** — `traverse_graph` is always available but
  always guarded by `_ALLOWED_CYPHER_REL_TYPES` allowlist.

- **`bleach` required** as a dependency for HTML stripping in `InputValidator`.

- **Rate limit is per `(tenant_id, user_id)`** — not per `tenant_id` alone.

- **SSE stream cleanup**: on client disconnect, `asyncio.CancelledError` is raised —
  clean up any open `httpx` connections.

- **Thread ownership check in use case layer** (not just route) — never bypass this.

- **`fusion_score = score × recency_score × trust_weight`** — deviation > 1e-9 is a
  programming error. Construct `RetrievedItem` via `create()` factory.

---

## Runbook

### Check Provider Health

```bash
curl http://localhost:8008/api/v1/providers/status
```

### Check LLM Cost Usage

```bash
curl http://localhost:8008/internal/v1/llm-costs?period=2026-05 \
  -H "X-Internal-JWT: <system-jwt>"
```

### Circuit Breaker State

The `rag_circuit_breaker_open` gauge (label: `source`) shows 1 when a retrieval
source is tripped. To reset manually, delete the Valkey key `rag:cb:state:{source}`.

### Disable Citation Cron

Set `RAG_CHAT_CITATION_CRON_ENABLED=false` (default). Enable only when you want
daily citation accuracy scoring (consumes LLM tokens). PLAN-0107 switched the
cadence from weekly Sunday → DAILY 03:00 UTC and the sample window from 7 days → 24 hours.
