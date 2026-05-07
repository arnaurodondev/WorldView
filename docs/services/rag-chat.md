# RAG / Chat Service

> **Owner**: Chat domain · **Database**: `rag_db` (owned) · **Port**: 8008
> **Status**: In-progress (PLAN-0015 Wave G-1 complete)

---

## Mission & Boundaries

**Owns**: Query rewriting, intent classification, hybrid retrieval orchestration
(vector + KG + SQL), result fusion, reranking, context assembly, prompt building,
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
| POST | `/api/v1/chat` | Sync chat completion | X-Tenant-Id + X-User-Id |
| POST | `/api/v1/chat/stream` | SSE streaming chat | X-Tenant-Id + X-User-Id |
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
    "sections": list[BriefSection] # PLAN-0049 T-A-1-04 — see below
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
| `status` | `{"step": "loading_context" \| "entity_resolution" \| "intent_classification" \| "query_expansion" \| "parallel_retrieval" \| "ranking_evidence"}` |
| `token` | `{"text": "..."}` — streamed LLM output chunk |
| `citations` | `[{ref, id, title, url, source, published_at}]` |
| `contradictions` | `[...]` |
| `metadata` | `{thread_id, message_id, intent, provider, latency_ms}` |
| `error` | `{code, message}` |

---

## RAG Pipeline (13 Steps)

```
Input → [0] Validate → [1] Cache check → [2] Rate limit → [3] Load history
      → [4] Entity resolution (S6) → [5] Intent + plan
      → [6] HyDE expansion + embedding → [7] Parallel retrieval (5A-5I)
      → [8] Graph enrichment + fusion → [9] BGE reranking
      → [10] Contradiction detection + context assembly
      → [11] Prompt build → [12] LLM streaming → [13] Output processing + citation injection + persist
```

### Parallel Retrieval Steps (5A-5I)

| Step | Source | Description |
|------|--------|-------------|
| 5A | S6 | Vector chunk search (top-20) |
| 5B | S7 | Relation search by embedding (top-15) |
| 5C | S7 | Egocentric graph per entity (up to 3 entities) |
| 5D | S7 | Claims search (date-filtered, top-15) |
| 5E | S7 | Event search (date-filtered, top-10) |
| 5F | S7 | Contradiction fetch per entity |
| 5G | S3 | Financial highlights + quotes per ticker |
| 5H | S1 | Portfolio context for PORTFOLIO intent |
| 5I | S7 | Cypher traversal (if cypher_enabled) |

All steps run concurrently via `asyncio.gather` with 5s per-task timeout. Failures return empty lists (safe degradation).

---

## LLM Provider Chain

| Order | Provider | Model | Notes |
|-------|----------|-------|-------|
| 1 | DeepInfra | `deepseek-r1-distill-qwen-32b` | Primary (requires `DEEPINFRA_API_KEY`) |
| 2 | OpenRouter | `deepseek/deepseek-r1-distill-qwen-32b` | Fallback (requires `OPENROUTER_API_KEY`) |
| 3 | Ollama (local) | `deepseek-r1:32b` | Emergency fallback (always available) |

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
│   │   ├── intent_classifier.py      # Ollama Qwen 2.5:3b 7-way intent
│   │   ├── hyde_expander.py          # HyDE hypothesis + embedding
│   │   ├── retrieval_plan_builder.py # Map intent → retrieval flags
│   │   ├── retrieval_orchestrator.py # asyncio.gather parallel retrieval
│   │   ├── fusion.py                 # GraphEnricher + FusionPipeline
│   │   ├── reranker.py               # BGE reranker via Ollama
│   │   ├── context_assembler.py      # Numbered context blocks
│   │   ├── prompt_builder.py         # Full prompt assembly
│   │   ├── output_processor.py       # Strip think/reasoning, citations
│   │   └── sse_emitter.py            # SSE event builders
│   ├── ports/
│   │   ├── upstream_clients.py       # S1Port, S3Port, S6Port, S7Port
│   │   └── embedding.py             # EmbeddingPort
│   ├── security/
│   │   └── input_validator.py        # PII + injection detection
│   └── use_cases/
│       ├── chat_orchestrator.py      # 13-step pipeline coordinator
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

| Env Var | Default | Required | Notes |
|---------|---------|----------|-------|
| `RAG_CHAT_RAG_DB_URL` | — | Yes | PostgreSQL write URL |
| `RAG_CHAT_RAG_DB_URL_READ` | (same) | No | Read replica URL |
| `RAG_CHAT_VALKEY_URL` | `redis://localhost:6379/0` | No | |
| `RAG_CHAT_DEEPINFRA_API_KEY` | — | Yes | Primary LLM |
| `RAG_CHAT_OPENROUTER_API_KEY` | — | No | Fallback LLM |
| `RAG_CHAT_OLLAMA_BASE_URL` | `http://localhost:11434` | No | Emergency + local models |
| `RAG_CHAT_OLLAMA_COMPLETION_MODEL` | `deepseek-r1:32b` | No | |
| `RAG_CHAT_OLLAMA_CLASSIFICATION_MODEL` | `qwen3:0.6b` | No | |
| `RAG_CHAT_OLLAMA_RERANKER_MODEL` | `bge-reranker-v2-m3` | No | |
| `RAG_CHAT_S1_INTERNAL_TOKEN` | — | Yes | Portfolio service auth |
| `RAG_CHAT_CYPHER_ENABLED` | `false` | No | Enable Cypher retrieval |
| `RAG_CHAT_RATE_LIMIT_PER_TENANT` | `10` | No | Requests/minute |
| `RAG_CHAT_UPSTREAM_TIMEOUT_SECONDS` | `5.0` | No | Per retrieval task |

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
| `rag_citation_accuracy` | gauge | — |
| `rag_citation_accuracy_call_failures_total` | counter | `reason` |
| `rag_circuit_breaker_open` | gauge | `source` |

#### Retrieval Quality Metrics (PLAN-0063 W5-5)

`rag_retrieval_score_distribution` — histogram of per-chunk fusion scores (buckets `[0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0]`), labelled by `source_type`. Emitted in `retrieval_orchestrator._fetch_chunks`.

`rag_source_contribution_total` — counter incremented once per query per source that contributed ≥1 chunk to fusion. Together with the histogram, reveals whether lexical / KG / SQL sources are pulling weight.

`rag_reranker_position_change` — rolling gauge (window=100 queries) of the fraction of queries where the reranker's top-1 differs from the fusion top-1. Updated via `record_reranker_position_change()` after step 8 in `ChatOrchestrator`. A gauge near 0 means the reranker is redundant; near 1 means fusion ordering is unreliable.

`rag_citation_accuracy` — gauge set by the weekly citation-accuracy cron (`ScoreCitationAccuracyUseCase`). Values: 0 = irrelevant snippets, 1 = direct verbatim support.

### Citation-Accuracy Cron

`infrastructure/jobs/citation_accuracy_cron.py` — `start_citation_accuracy_cron(use_case) → asyncio.Task` schedules a background asyncio task:
- **First run**: immediately on startup (gauge populated within minutes of first deployment)
- **Recurring**: weekly, Sunday 03:00 UTC

`application/use_cases/score_citation_accuracy.py` — `ScoreCitationAccuracyUseCase`:
1. Calls `MessageRepository.sample_recent_with_citations(n=50)` — random sample from last 7 days, assistant-role messages, non-empty `citations` JSONB
2. For each message, `iter_cited_claims(msg)` extracts `(sentence, "c{N}")` pairs from `[cN]` inline markers, or `(full_content, "c{ref}")` for plain-chat messages
3. For each pair, calls `LLMJudgePort.score_citation(claim=, snippet=)` where `snippet = cite.title or ""`
4. Normalises raw 0–3 scores to [0, 1] (÷3), drops invalid responses
5. Sets `rag_citation_accuracy` gauge; returns 0.0 if fewer than 10 samples

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

RAG retrieval (Steps 5A–5I) queries globally shared data (articles, entities,
relations, claims, events from S3/S5/S6/S7). This is by design — news and
market intelligence are not tenant-specific. Tenant isolation applies only to:

- **Chat thread context**: which thread the response is persisted to (tenant-scoped)
- **Portfolio context (Step 5H)**: scoped by S1's `user_id` check on portfolio data
- **Conversation history**: loaded from the tenant-scoped thread

### Security Notes

- **404 (not 403)** on cross-tenant access prevents thread ID enumeration attacks.
- `tenant_id` is extracted from the RS256 internal JWT set by `InternalJWTMiddleware`
  (PRD-0025). It is never read from raw request headers.
- Defense-in-depth: ownership is checked in the **use case layer** (not just the
  route), so any new routes that touch threads inherit the same protection.

---

## Local Run

```bash
cd services/rag-chat
cp configs/dev.local.env.example .env
# Edit .env: set RAG_CHAT_DEEPINFRA_API_KEY and RAG_CHAT_RAG_DB_URL
make run       # API on port 8008
make test      # unit tests
make lint
```
