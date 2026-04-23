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
| `RAG_CHAT_OLLAMA_CLASSIFICATION_MODEL` | `qwen2.5:3b` | No | |
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
