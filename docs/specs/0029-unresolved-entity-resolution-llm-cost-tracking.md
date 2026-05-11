# PRD-0029 — Unresolved Entity Re-Resolution & Cross-Service LLM Cost Tracking

**Status**: Draft
**Created**: 2026-04-22
**Author**: Engineering (Claude)
**Services affected**: S6 (NLP Pipeline), S7 (Knowledge Graph), S8 (RAG Chat), S9 (API Gateway), `libs/ml-clients`, `intelligence-migrations`

---

## 1. Problem Statement

Two related observability and data-completeness gaps exist in the current system:

### 1A — Unresolved Entity Mentions

Block 9 of the NLP pipeline classifies entity mentions with confidence < 0.45 as `UNRESOLVED`. These mentions are stored in `nlp_db.entity_mentions` with `resolved_entity_id=NULL` but there is no mechanism to ever re-examine them. As the entity catalog grows (via market instrument ingestion or provisional entity creation), old UNRESOLVED mentions are never retried against the expanded catalog. Additionally, `resolution_outcome` is not persisted to the database, making it impossible to query UNRESOLVED mentions efficiently.

Two types of UNRESOLVED mentions exist:
1. **Catalog-gap entities**: Real organizations/instruments/persons not yet in the KG — should become new entities.
2. **Noise**: GLiNER false-positives (fragments, acronyms, common nouns incorrectly tagged) — should be permanently marked as noise, never re-processed.

Currently both types accumulate indefinitely. Entity signal counts, RAG retrieval, and knowledge graph confidence all degrade as a result.

### 1B — LLM Cost Blindness

`llm_usage_log` exists in `intelligence_db` and is populated only by S7 (Knowledge Graph) via `FallbackChainClient`. Two of the three external-LLM-calling services are entirely untracked:
- **S6 NLP Pipeline**: Qwen2.5:3b (Ollama, relevance scoring) and Qwen2.5:7b (Ollama, deep extraction) — untracked
- **S8 RAG Chat**: DeepInfra `deepseek-r1-distill-qwen-32b`, OpenRouter, and Ollama fallback — untracked

There is no cross-service cost dashboard and no tenant-level cost attribution path. The ops team cannot know how much is being spent per month on external AI providers without manual log inspection.

---

## 2. Target Users

| User | Need |
|------|------|
| **Operations / Admin** | Know monthly spend per provider; detect cost anomalies; budget planning |
| **Data Engineering** | Understand entity coverage gaps; see re-resolution throughput |
| **System (automated)** | Continuously improve entity catalog completeness without manual curation |

---

## 3. Functional Requirements

### Feature A — Unresolved Entity Re-Resolution

| ID | Requirement | Priority |
|----|-------------|---------|
| A-1 | Persist `resolution_outcome` in `nlp_db.entity_mentions` for all mentions | MUST |
| A-2 | Periodic background worker re-processes UNRESOLVED mentions in batches | MUST |
| A-3 | Phase 1: re-run Block 9 cascade (free) against current entity catalog | MUST |
| A-4 | Phase 2: LLM classification (Qwen2.5:3b, Ollama) for still-UNRESOLVED entity-creating mentions | MUST |
| A-5 | LLM-confirmed real entities → insert into `provisional_entity_queue` (Worker 13E creates them) | MUST |
| A-6 | LLM-classified noise → mark `resolution_outcome='noise'`; never re-process | MUST |
| A-7 | Noise mentions are **retained** (never deleted); they carry original mention text for audit | MUST |
| A-8 | Entity-creating mention classes eligible for LLM escalation: ORGANIZATION, FINANCIAL_INSTRUMENT, PERSON, FINANCIAL_INSTITUTION, GOVERNMENT_BODY, REGULATORY_BODY | MUST |
| A-9 | Non-escalatable classes (LOCATION, COMMODITY, INDEX, CURRENCY, MACROECONOMIC_INDICATOR): mark as `noise` directly without LLM call if cascade fails | MUST |
| A-10 | Worker operates on a configurable lookback window (default: 90 days) | MUST |
| A-11 | Transient `escalated` state prevents double-processing under concurrent workers | MUST |
| A-12 | Worker respects configurable batch size and run interval | SHOULD |
| A-13 | New worker logs throughput metrics (processed, resolved, escalated, noise) via structlog | SHOULD |

### Feature B — LLM Cost Tracking

| ID | Requirement | Priority |
|----|-------------|---------|
| B-1 | `libs/ml-clients` exposes `LlmUsageLogProtocol` that all LLM adapters accept as optional dependency | MUST |
| B-2 | All LLM adapters in `libs/ml-clients` log via the protocol when injected | MUST |
| B-3 | S7 Knowledge Graph refactored to inject its existing `LlmUsageLogRepository` via the new protocol | MUST |
| B-4 | S6 NLP Pipeline gets `llm_usage_log` table (migration 0008); logs Qwen calls | MUST |
| B-5 | S8 RAG Chat gets `llm_usage_log` table (new migration); logs DeepInfra/OpenRouter/Ollama streams | MUST |
| B-6 | Streaming adapters (S8) log cost **after** stream completes, not mid-stream | MUST |
| B-7 | Token counts extracted from final SSE chunk `usage` field (DeepInfra/OpenRouter) | MUST |
| B-8 | Ollama costs logged as $0.00 external with actual token estimates from word-count heuristic | MUST |
| B-9 | Every log row includes `tenant_id UUID` (NULL for system/admin calls) for future attribution | MUST |
| B-10 | Every log row includes `service_name VARCHAR(50)` | MUST |
| B-11 | `intelligence_db.llm_usage_log` extended with `service_name` and `tenant_id` columns | MUST |
| B-12 | S9 admin endpoint aggregates cost data from all three services | MUST |
| B-13 | Cost data exposed via Grafana-queryable API (not a frontend page) | MUST |
| B-14 | Admin endpoint secured by internal JWT with admin role claim | MUST |

---

## 4. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Re-resolution worker latency | Process 500 mentions/batch; complete within 5 minutes per batch including LLM calls |
| LLM classification timeout | Qwen2.5:3b per-mention: 10s timeout, 2 retries |
| Cost log write latency | < 50ms; fire-and-forget (non-blocking) |
| Cost aggregation API latency | < 2s (three internal service calls in parallel) |
| Re-resolution lookback backfill | First run processes up to 50K historical rows in time-ordered batches |
| Worker concurrency safety | `FOR UPDATE SKIP LOCKED` prevents double-processing |
| No external cost for re-resolution | Qwen2.5:3b is local Ollama; zero external provider cost |

---

## 5. Out of Scope

- Real-time per-query cost webhooks or billing integrations
- Tenant-level cost invoicing (tenant_id added for future use only)
- New frontend page for cost dashboard (Grafana dashboards only)
- Re-processing PROVISIONAL mentions (they already have the correct pipeline)
- Changing the Block 9 threshold values (0.45 / 0.72)
- Dedicated "entity curator" UI for reviewing NOISE decisions
- Cost tracking for embedding calls (nomic-embed-text, BGE-large) — future scope

---

## 6. Technical Design

### 6.1 Affected Services

| Service | Change Type | What Changes |
|---------|------------|-------------|
| S6 NLP Pipeline | NEW worker, NEW migration (0007 + 0008), config | `UnresolvedResolutionWorker`, `resolution_outcome` column, `llm_usage_log` table |
| S7 Knowledge Graph | REFACTOR | Inject `LlmUsageLogProtocol` into `FallbackChainClient` (rename `insert()→log()`); inject into `GeminiDescriptionAdapter` in `libs/ml-clients` |
| S8 RAG Chat | NEW migration, NEW cost logging | `llm_usage_log` table, wrap `LLMProviderChain.stream()` |
| S9 API Gateway | NEW endpoint | `GET /api/v1/admin/llm-costs` |
| `libs/ml-clients` | NEW protocol + cost utils | `LlmUsageLogProtocol`, `estimate_cost()`, adapter logging |
| `intelligence-migrations` | NEW migration (0005) | Add `service_name`, `tenant_id` to `llm_usage_log` |

---

### 6.2 API Changes

#### GET /api/v1/admin/llm-costs

- **Purpose**: Aggregate LLM usage and estimated costs across all three logging services for a given calendar period. Intended for Grafana/admin dashboards.
- **Auth**: Internal JWT required; role claim must include `admin`
- **Query parameters**:

| Parameter | Type | Required | Default | Validation | Description |
|-----------|------|----------|---------|------------|-------------|
| `period` | string | no | current month | `YYYY-MM` format | Calendar month to aggregate |
| `service` | string | no | `all` | `all \| nlp-pipeline \| rag-chat \| knowledge-graph` | Filter to single service |
| `provider` | string | no | `all` | `all \| deepinfra \| openrouter \| gemini \| ollama` | Filter to provider |
| `breakdown` | string | no | `provider` | `provider \| capability \| service \| day` | Grouping dimension |

- **Response** (200):

| Field | Type | Description |
|-------|------|-------------|
| `period` | string | Requested period (YYYY-MM) |
| `total_estimated_cost_usd` | float | Sum across all services/providers |
| `total_calls` | int | Total LLM API calls |
| `total_tokens_in` | int | Total input tokens |
| `total_tokens_out` | int | Total output tokens |
| `success_rate` | float | successful_calls / total_calls |
| `breakdown` | array | Rows grouped by requested dimension |
| `breakdown[].dimension` | string | Provider/capability/service/day name |
| `breakdown[].calls` | int | Call count |
| `breakdown[].tokens_in` | int | Input tokens |
| `breakdown[].tokens_out` | int | Output tokens |
| `breakdown[].estimated_cost_usd` | float | Estimated cost |
| `breakdown[].success_rate` | float | Success rate for dimension |
| `services_queried` | array of string | Which services were included |
| `services_failed` | array of string | Which services timed out / errored |

- **Error responses**: 401 (no JWT), 403 (non-admin role), 400 (invalid period format), 503 (all services unavailable)
- **Rate limit**: 60 req/min (admin-only, low volume)
- **Implementation note**: S9 calls three internal endpoints in parallel (`GET /internal/v1/llm-costs?period=:period`) and merges results. Service failures are degraded gracefully — partial results returned with `services_failed` populated.

#### GET /internal/v1/llm-costs (per-service internal endpoint)

Each of S6, S7, S8 exposes this internal endpoint for S9 to call:

- **Purpose**: Return aggregated cost data from this service's `llm_usage_log`
- **Auth**: Internal JWT (system role)
- **Query parameters**: `period` (YYYY-MM), `provider` (optional), `breakdown` (provider|capability|day)
- **Response**: Same breakdown structure as the public endpoint above
- **Exposed by**: S6 (`/internal/v1/llm-costs`), S7 (`/internal/v1/llm-costs`), S8 (`/internal/v1/llm-costs`)

---

### 6.3 Kafka Events

**No new Kafka events** for this PRD. The re-resolution worker uses periodic DB polling (established pattern). LLM cost logging is in-process to each service's own DB. Cross-service cost aggregation goes via S9 internal REST calls.

*Rationale*: UNRESOLVED mentions are already in `nlp_db`; emitting a Kafka event would duplicate DB-resident data with no consumer benefit. Periodic polling at 30-min intervals is sufficient given the slow-path nature of re-resolution.

---

### 6.4 Database Changes

#### Table: `entity_mentions` — Add resolution columns (nlp_db migration 0007)

| Column | Type | Nullable | Default | Server Default | Notes |
|--------|------|----------|---------|----------------|-------|
| `resolution_outcome` | VARCHAR(20) | yes | — | `'unresolved'` | New; backfilled below |
| `resolution_noise_reason` | VARCHAR(200) | yes | NULL | — | LLM-provided reason when classified as noise; `'non_entity_creating_class'` for non-escalatable classes |
| `resolution_processed_at` | TIMESTAMPTZ | yes | NULL | — | UTC timestamp of most recent worker processing |

**Backfill migration logic** (run in same migration after ALTER TABLE):
```sql
-- Rows with resolved_entity_id set → auto_resolved
UPDATE entity_mentions SET resolution_outcome = 'auto_resolved'
WHERE resolved_entity_id IS NOT NULL AND resolution_outcome = 'unresolved';

-- Rows without resolved_entity_id → unresolved (already set by server_default)
-- No additional update needed
```

**New index**:
```sql
CREATE INDEX idx_entity_mentions_unresolved
ON entity_mentions (created_at)
WHERE resolution_outcome = 'unresolved';
```

**Current migration head**: `0006` (add ner_model_id)
**New head**: `0007`

---

#### Table: `llm_usage_log` — Add columns (nlp_db migration 0008)

New table in `nlp_db`:

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| `log_id` | UUID | no | `gen_random_uuid()` | PK |
| `model_id` | VARCHAR(200) | no | — | e.g. `"Qwen2.5:3b"`, `"nomic-embed-text"` |
| `provider` | VARCHAR(50) | no | — | `"ollama"`, `"deepinfra"`, `"openrouter"`, `"gemini"` |
| `capability` | VARCHAR(50) | no | — | `"extraction"`, `"embedding"`, `"ner_classification"`, `"description"`, `"chat_completion"` |
| `service_name` | VARCHAR(50) | no | `'nlp-pipeline'` | Identifies origin service |
| `tenant_id` | UUID | yes | NULL | Reserved; NULL for all system calls currently |
| `tokens_in` | INT | no | 0 | Input tokens (word-count estimate for Ollama) |
| `tokens_out` | INT | no | 0 | Output tokens |
| `estimated_cost_usd` | FLOAT | no | 0.0 | $0 for Ollama |
| `latency_ms` | INT | no | 0 | Wall-clock duration of API call |
| `success` | BOOLEAN | no | true | False on error/timeout |
| `error_code` | VARCHAR(50) | yes | NULL | `"timeout"`, `"rate_limit"`, `"auth"`, `"model_error"` |
| `doc_id` | UUID | yes | NULL | Article/document being processed |
| `created_at` | TIMESTAMPTZ | no | `now()` | UTC |

**Indexes**:
```sql
CREATE INDEX idx_nlp_llm_usage_period ON llm_usage_log (created_at DESC);
CREATE INDEX idx_nlp_llm_usage_provider ON llm_usage_log (provider, created_at DESC);
```

**Current migration head**: `0007` (after adding resolution_outcome)
**New head**: `0008`

---

#### Table: `llm_usage_log` — New table in `rag_chat_db` (migration 0003)

Same schema as nlp_db version, with `service_name` defaulting to `'rag-chat'` and an additional column:

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `session_id` | UUID | yes | RAG chat session this call belonged to |
| `chat_thread_id` | UUID | yes | Thread identifier for grouping |

All other columns identical to nlp_db version.

**Current migration head**: `0002` (add_context_valkey_keys)
**New head**: `0003`

---

#### Table: `llm_usage_log` — Extend in `intelligence_db` (intelligence-migrations 0006)

Add missing columns to existing table:

```sql
ALTER TABLE llm_usage_log ADD COLUMN service_name VARCHAR(50) NOT NULL DEFAULT 'knowledge-graph';
ALTER TABLE llm_usage_log ADD COLUMN tenant_id UUID;
ALTER TABLE llm_usage_log ADD COLUMN error_code VARCHAR(50);
```

**Current migration head**: `0005` (`0005_add_extraction_model_id_to_claims` — PLAN-0031 B-2)
**New head**: `0006`

---

### 6.5 Domain Model Changes

#### Entity: `EntityMention` (S6 domain — `domain/models.py`)

**Change**: `resolution_outcome` field already exists in-memory (line 73). No domain change needed — DB model update captures it.

#### Enum: `ResolutionOutcome` (S6 domain — `domain/enums.py`)

**Add two new values**:

| Value | Meaning | When Set |
|-------|---------|----------|
| `auto_resolved` | Block 9 cascade succeeded (≥0.72) | Original Block 9 |
| `provisional` | 0.45–0.72; queued for Worker 13E | Original Block 9 |
| `unresolved` | <0.45; not yet re-processed | Original Block 9 |
| `escalated` | Being actively processed by `UnresolvedResolutionWorker` | Worker (transient) |
| `entity_created` | LLM confirmed real entity; inserted into provisional_entity_queue | Worker Phase 2 |
| `noise` | LLM classified as not a real entity; never re-process | Worker Phase 2 |

`escalated` is a transient state — rows in `escalated` for > 30 min (worker crash indicator) are reset to `unresolved` on next worker startup.

#### Entity: `UnresolvedResolutionBatch` (new S6 domain)

```python
@dataclass(frozen=True)
class UnresolvedResolutionBatch:
    """Results of a single re-resolution worker run."""
    batch_id: UUID          # UUIDv7, for logging correlation
    started_at: datetime    # UTC
    completed_at: datetime  # UTC
    total_processed: int    # mentions examined
    cascade_resolved: int   # resolved by re-running cascade
    escalated_to_llm: int   # sent to LLM for classification
    entity_created: int     # LLM → provisional_entity_queue insert
    noise_classified: int   # LLM → noise
    errors: int             # failed mentions (remain unresolved)
```

#### Protocol: `LlmUsageLogProtocol` (new, `libs/ml-clients`)

```python
@runtime_checkable
class LlmUsageLogProtocol(Protocol):
    """Minimal interface for logging a single LLM API call.

    Each service injects its own implementation (DB repository).
    Ollama (local) calls are logged with estimated_cost_usd=0.0.
    """
    async def log(
        self,
        *,
        model_id: str,
        provider: str,        # "deepinfra" | "openrouter" | "gemini" | "ollama"
        capability: str,      # "chat_completion" | "embedding" | "extraction" | "description" | "ner_classification"
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        estimated_cost_usd: float = 0.0,
        success: bool = True,
        error_code: str | None = None,
        **context: object,    # doc_id, entity_id, session_id — service-specific
    ) -> None: ...
```

#### Dataclass: `LlmCallUsage` (new, `libs/ml-clients`)

```python
@dataclass(frozen=True)
class LlmCallUsage:
    """Token usage extracted from a completed LLM call."""
    tokens_in: int
    tokens_out: int
    estimated_cost_usd: float
    provider: str
    model_id: str
    latency_ms: int
    success: bool
    error_code: str | None = None
```

#### Cost estimation utilities (new, `libs/ml-clients/cost.py`)

```python
# Pricing constants (per 1M tokens)
PRICING: dict[str, dict[str, float]] = {
    "deepinfra": {
        "deepseek-r1-distill-qwen-32b": {"input": 0.69, "output": 2.19},
    },
    "openrouter": {
        "deepseek/deepseek-r1-distill-qwen-32b": {"input": 0.69, "output": 2.19},
    },
    "gemini": {
        "gemini-3.1-flash-lite": {"input": 0.075, "output": 0.30},
    },
    "ollama": {
        "*": {"input": 0.0, "output": 0.0},  # local, always free
    },
}

def estimate_cost(provider: str, model_id: str, tokens_in: int, tokens_out: int) -> float:
    """Return estimated USD cost for a completed LLM call.

    Returns 0.0 for unknown provider/model combinations (conservative default).
    """
    ...

def estimate_tokens_from_text(text: str) -> int:
    """Approximate token count from text. Uses word-count heuristic (1 token ≈ 0.75 words).

    Used for Ollama calls that don't return token counts.
    """
    return max(1, int(len(text.split()) / 0.75))
```

---

### 6.6 Worker: `UnresolvedResolutionWorker` (S6)

**Location**: `services/nlp-pipeline/src/nlp_pipeline/application/workers/unresolved_resolution.py`

**Schedule**: Every 30 minutes (configurable via `unresolved_resolution_interval_s`, default 1800)

**Batch size**: 500 mentions per run (configurable via `unresolved_resolution_batch_size`, default 500)

**Lookback window**: 90 days (configurable via `unresolved_resolution_lookback_days`, default 90)

**Processing flow**:

```
Step 1: Claim batch (atomic, prevents double-processing)
   SELECT mention_id, mention_text, mention_class, resolution_confidence, doc_id
   FROM entity_mentions
   WHERE resolution_outcome = 'unresolved'
     AND created_at > now() - INTERVAL ':lookback_days days'
   ORDER BY created_at ASC
   LIMIT :batch_size
   FOR UPDATE SKIP LOCKED

   → UPDATE SET resolution_outcome = 'escalated' for claimed rows

Step 2: Phase 1 — Cascade re-run (free)
   For each mention:
   - Re-run Block 9 stages 1–4 against current entity catalog
   - If auto-resolved (≥0.72): UPDATE entity_mentions SET resolved_entity_id=:id,
     resolution_outcome='auto_resolved', resolution_confidence=:conf
   - If still unresolved: pass to Phase 2 (if eligible class) or Phase 3 (if non-eligible)

Step 3: Phase 2 — LLM classification (entity-creating classes only)
   Eligible classes: ORGANIZATION, FINANCIAL_INSTRUMENT, PERSON, FINANCIAL_INSTITUTION,
                     GOVERNMENT_BODY, REGULATORY_BODY

   Prompt (Qwen2.5:3b, Ollama, single-shot):
   """Is '{mention_text}' a specific real-world {mention_class}?
   A real entity has a distinct identity (e.g. a named company, person, or instrument).
   Generic terms, fragments, or common nouns are NOT real entities.
   Answer with exactly: YES or NO, then a one-sentence reason.
   Examples:
   - "Apple Inc" (organization) → YES: Apple Inc is a well-known technology company.
   - "the company" (organization) → NO: Generic reference, not a specific entity.
   - "Q3 results" (organization) → NO: Not an organization name."""

   If YES (LLM answer starts with "YES"):
   → INSERT INTO provisional_entity_queue (normalized_surface, mention_class, mention_text, ...)
     ON CONFLICT (normalized_surface, mention_class) DO NOTHING
   → UPDATE entity_mentions SET resolution_outcome='entity_created'

   If NO:
   → UPDATE entity_mentions SET resolution_outcome='noise',
     resolution_noise_reason=<llm_one_sentence_reason>

Step 4: Phase 3 — Non-eligible classes (no LLM)
   LOCATION, COMMODITY, INDEX, CURRENCY, MACROECONOMIC_INDICATOR:
   → UPDATE entity_mentions SET resolution_outcome='noise',
     resolution_noise_reason='non_entity_creating_class'

Step 5: Error handling
   On per-mention exception:
   - Log error with mention_id
   - UPDATE SET resolution_outcome='unresolved' (reset for next run)
   - Increment error counter
   - Continue to next mention

Step 6: Startup stale-lock recovery
   On worker startup:
   UPDATE entity_mentions SET resolution_outcome='unresolved'
   WHERE resolution_outcome = 'escalated'
     AND updated_at < now() - INTERVAL '30 minutes'
```

**New config fields** (add to `Settings` in `nlp_pipeline/config.py`, prefix `NLP_PIPELINE_`):
```
unresolved_resolution_enabled: bool = True
unresolved_resolution_interval_s: int = 1800
unresolved_resolution_batch_size: int = 500
unresolved_resolution_lookback_days: int = 90
unresolved_resolution_llm_timeout_s: float = 10.0
unresolved_resolution_llm_retries: int = 2
unresolved_resolution_stale_escalated_minutes: int = 30
unresolved_resolution_ollama_base_url: str = "http://ollama:11434"
unresolved_resolution_classification_model: str = "qwen2.5:3b"
unresolved_resolution_max_llm_batch: int = 20
```

**New `entity_mentions` columns** (migration 0007, in addition to `resolution_outcome`):
- `resolution_noise_reason VARCHAR(200)` — LLM reason or `'non_entity_creating_class'`
- `resolution_processed_at TIMESTAMPTZ` — timestamp of most recent worker processing

---

### 6.7 Data Flow — Re-Resolution Worker

```
┌─────────────────────────────────────────────────────────────────┐
│ UnresolvedResolutionWorker (runs every 30 min)                  │
│                                                                 │
│  nlp_db.entity_mentions                                        │
│  WHERE resolution_outcome='unresolved'                         │
│  LIMIT 500 FOR UPDATE SKIP LOCKED                              │
│       │                                                         │
│       ▼                                                         │
│  Mark batch → 'escalated'                                      │
│       │                                                         │
│       ├── Phase 1: Re-run Block 9 cascade (in-process)         │
│       │   ├── Resolved (≥0.72) → update 'auto_resolved'        │
│       │   └── Still UNRESOLVED → continue                      │
│       │                                                         │
│       ├── Phase 2: Eligible class?                              │
│       │   ├── YES → Qwen2.5:3b (Ollama) classify               │
│       │   │         ├── "YES" → provisional_entity_queue       │
│       │   │         │            → Worker 13E creates entity    │
│       │   │         │          mark 'entity_created'            │
│       │   │         └── "NO"  → mark 'noise' + reason          │
│       │   └── NO  → mark 'noise' (non_entity_creating_class)   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.8 Data Flow — LLM Cost Tracking (S8 Example)

```
User sends chat query
       │
       ▼
S8 RAG pipeline → LLMProviderChain.stream(prompt)
       │
       ├── Try DeepInfra: stream tokens → collect final SSE chunk
       │     {usage: {prompt_tokens: N, completion_tokens: M}}
       │     ← extract token counts
       │
       ▼ (after stream completes)
cost_logger.log(
    model_id="deepseek-r1-distill-qwen-32b",
    provider="deepinfra",
    capability="chat_completion",
    tokens_in=N,
    tokens_out=M,
    latency_ms=elapsed,
    estimated_cost_usd=estimate_cost("deepinfra", model, N, M),
    session_id=<session_id>,
)
       │
       ▼
rag_chat_db.llm_usage_log (INSERT, non-blocking, fire-and-forget)
```

---

## 7. Architecture Decisions

### ADR-0029-A: Periodic Polling vs Kafka for Re-Resolution Trigger

**Decision**: Periodic polling worker (no new Kafka topic).

**Rationale**: UNRESOLVED mentions are already persisted in `nlp_db`. A Kafka event would duplicate DB-resident data with no consumer benefit. The `FOR UPDATE SKIP LOCKED` pattern ensures correctness without Kafka's delivery semantics overhead. Periodic polling at 30-minute intervals is sufficient for a slow-path correction process. This matches the established pattern of Worker 13D-1..3 and Worker 13E.

**Alternative considered**: A `nlp.entity.unresolved.v1` Kafka topic batched per article. Rejected because: adds a new Avro schema, a new consumer group, and infrastructure for zero correctness benefit over polling.

### ADR-0029-B: Per-Service `llm_usage_log` vs Central Table

**Decision**: Per-service tables (nlp_db, rag_chat_db, intelligence_db), aggregated by S9 at query time.

**Rationale**: RULES.md R7 prohibits cross-service DB access. S6 and S8 cannot write to `intelligence_db`. A central Kafka→consumer approach would work but adds complexity for a monitoring feature. Per-service tables + S9 internal REST aggregation is simpler and follows the existing pattern (each service owns its own DB).

**Alternative considered**: Central `platform_db` owned by a new service. Rejected as over-engineering for current scale; revisit if more than 5 services need cost tracking.

### ADR-0029-C: Qwen2.5:3b for Noise Classification

**Decision**: Use local Qwen2.5:3b (Ollama) for binary entity classification.

**Rationale**: Zero external cost. The task is simple (binary yes/no classification) — a 3B parameter model is sufficient. Qwen2.5:3b is already present in the Ollama container for S6 relevance scoring. Using Gemini Flash Lite for this would cost ~$0.0003/call × potentially thousands of historical UNRESOLVED mentions = non-trivial cost for what is a maintenance task.

**Risk**: Qwen2.5:3b accuracy for entity classification is lower than GPT-4 class models. Mitigation: the prompt uses few-shot examples and the result is "soft" — a false positive creates a provisional queue entry which Worker 13E (LLM) validates before creating the entity (two-stage filter).

### ADR-0029-D: NOISE Retention Policy

**Decision**: Retain NOISE mentions permanently; never delete.

**Rationale**: (1) Mention text is needed for text search and RAG citation display. (2) Audit trail integrity — RULES.md R6: never discard data. (3) Future model upgrades may reclassify current NOISE as real entities. (4) Storage impact is negligible (one VARCHAR field per mention).

---

## 8. Security Analysis

### 8.1 Cost Admin Endpoint

- Admin role check on `GET /api/v1/admin/llm-costs` — must verify `role=admin` in internal JWT claims, not just presence of valid JWT
- No tenant data exposed — this endpoint returns aggregate system-level metrics only
- No PII in cost logs (doc_id, entity_id are UUIDs; no content stored in llm_usage_log)

### 8.2 LLM Classification (Re-Resolution Worker)

- Prompt includes user-generated `mention_text` — potential for prompt injection if an adversarial article was ingested. Mitigation: mention_text is truncated to 100 characters before inclusion in the LLM prompt; the model is local (no external data exfiltration risk)
- Prompt is structured as a classification task with few-shot examples that anchor expected output format

### 8.3 Multi-Tenant Isolation

- `tenant_id` column on `llm_usage_log` is NULL for all system calls currently. No tenant data is exposed via the cost endpoint (admin-only).
- Future multi-tenant cost attribution: when `tenant_id` is populated, the `/api/v1/admin/llm-costs` endpoint must support filtering by tenant and enforce that non-admin users can only see their own tenant's costs.

---

## 9. Failure Modes

| Component | Failure | Impact | Recovery |
|-----------|---------|--------|----------|
| Qwen2.5:3b (Ollama) unavailable | Worker Phase 2 fails | Mentions remain `escalated` → reset to `unresolved` on restart | Startup stale-lock recovery; worker retries on next cycle |
| Worker crashes mid-batch | Mentions stuck in `escalated` | No new re-resolution until recovery | Startup recovery resets `escalated` > 30 min old to `unresolved` |
| `provisional_entity_queue` INSERT conflict | Entity already queued by different article | `ON CONFLICT DO NOTHING` — silent; mention marked `entity_created` anyway | Acceptable — Worker 13E processes the existing queue row |
| Cost log write fails (DB down) | LLM call proceeds; cost not logged | Gap in cost data | Fire-and-forget; log error via structlog; no retry (don't block LLM path) |
| S6 internal cost endpoint down | S9 aggregation partial | `services_failed: ["nlp-pipeline"]` in response | S9 returns partial results with degraded flag; Grafana shows gap |
| DeepInfra final SSE chunk missing `usage` | Token counts unavailable | Fall back to word-count estimate from prompt length | `estimate_tokens_from_text(prompt)` → log with `source="estimated"` |

---

## 10. Scalability

### Re-Resolution Worker

| Dimension | Value | Notes |
|-----------|-------|-------|
| Historical UNRESOLVED mentions (first run) | Up to ~500K rows | Processed in 500-row batches; ~16 hours to exhaust backlog at 30-min intervals |
| Steady-state new UNRESOLVED per day | ~5K–20K | Depends on article volume; one batch run handles this comfortably |
| Qwen2.5:3b latency per mention | ~2–3s | 500 mentions × 3s = 25 min per batch (within 30-min interval) |
| DB SELECT impact | Low | Indexed on `(created_at) WHERE resolution_outcome='unresolved'` |

**Backfill note**: On first deployment, the worker should be configured with `unresolved_resolution_batch_size=2000` and `unresolved_resolution_interval_s=300` (5 min) for 48 hours to drain the historical backlog, then return to defaults.

### Cost Tracking

- S8 logging is fire-and-forget (async `asyncio.create_task`); no blocking of streaming responses
- `llm_usage_log` tables are append-only with no UPDATE/DELETE; partitioning by month is optional future work
- Estimated rows: ~500/day (S8) + ~200/day (S6) + ~100/day (S7) = ~800/day total; 30K/month; manageable without partitioning for 2 years

---

## 11. Test Strategy

### Unit Tests

| Test | What It Verifies | Service | Priority |
|------|-----------------|---------|---------|
| `test_resolution_outcome_persisted` | Block 9 sets resolution_outcome on EntityMention after cascade | S6 | HIGH |
| `test_unresolved_worker_cascade_resolves` | Phase 1 cascade: UNRESOLVED mention matches existing entity → auto_resolved | S6 | HIGH |
| `test_unresolved_worker_llm_yes_creates_queue_entry` | Phase 2: LLM returns YES → insert into provisional_entity_queue | S6 | HIGH |
| `test_unresolved_worker_llm_no_marks_noise` | Phase 2: LLM returns NO → resolution_outcome='noise', reason stored | S6 | HIGH |
| `test_unresolved_worker_non_eligible_class_is_noise` | Phase 3: LOCATION class → noise without LLM call | S6 | HIGH |
| `test_unresolved_worker_stale_lock_recovery` | On startup: escalated > 30 min → reset to unresolved | S6 | HIGH |
| `test_llm_usage_log_protocol_compliant` | LlmUsageLogProtocol structural check for all service implementations | libs | HIGH |
| `test_estimate_cost_deepinfra` | estimate_cost("deepinfra", "deepseek-r1-distill-qwen-32b", 1000, 500) returns correct value | libs | HIGH |
| `test_estimate_cost_gemini` | estimate_cost("gemini", "gemini-3.1-flash-lite", 1000, 500) returns correct value | libs | HIGH |
| `test_estimate_cost_ollama_zero` | estimate_cost("ollama", any, any, any) == 0.0 | libs | HIGH |
| `test_estimate_tokens_from_text` | 100-word text → ~133 tokens estimate | libs | MEDIUM |
| `test_deepinfra_adapter_extracts_usage_from_sse` | Final SSE chunk with usage field → LlmCallUsage populated | S8 | HIGH |
| `test_provider_chain_logs_cost_after_stream` | cost_logger.log called once after full stream, not per-chunk | S8 | HIGH |
| `test_provider_chain_logs_failure` | On DeepInfra exception → success=False, error_code set | S8 | HIGH |
| `test_resolution_outcome_enum_values` | ResolutionOutcome has 6 values: auto_resolved, provisional, unresolved, escalated, entity_created, noise | S6 | HIGH |
| `test_admin_cost_endpoint_requires_admin_role` | Non-admin JWT → 403 | S9 | HIGH |
| `test_admin_cost_endpoint_aggregates_parallel` | All 3 services respond → merged breakdown | S9 | MEDIUM |
| `test_admin_cost_endpoint_partial_failure` | One service times out → partial result + services_failed | S9 | MEDIUM |

### Integration Tests

| Test | Infrastructure | What It Verifies |
|------|---------------|-----------------|
| `test_migration_0007_backfill` | nlp_db Postgres | ALTER TABLE + UPDATE backfill: existing rows with resolved_entity_id get auto_resolved, NULL rows get unresolved |
| `test_migration_0008_llm_usage_log_created` | nlp_db Postgres | llm_usage_log table created with all columns and indexes |
| `test_worker_full_cycle_resolve` | nlp_db + Ollama stub | UNRESOLVED mention → cascade → auto_resolved |
| `test_worker_full_cycle_entity_created` | nlp_db + intelligence_db + Ollama stub | UNRESOLVED mention → LLM YES → provisional_entity_queue row created |
| `test_worker_full_cycle_noise` | nlp_db + Ollama stub | UNRESOLVED mention → LLM NO → noise |
| `test_cost_log_inserted_after_stream` | rag_chat_db + DeepInfra mock | Stream completes → llm_usage_log row present |
| `test_admin_cost_endpoint_e2e` | S6+S7+S8+S9 running | S9 calls all 3 internal endpoints, returns merged data |

### Edge Case Tests

| Test | What It Verifies |
|------|-----------------|
| `test_worker_batch_size_respected` | 600 UNRESOLVED mentions → only 500 claimed per run |
| `test_worker_lookback_window_respected` | 100-day-old mentions not included when lookback=90 |
| `test_conflict_provisional_queue_existing` | INSERT into provisional_entity_queue ON CONFLICT → mention still marked entity_created |
| `test_noise_reason_truncated` | LLM reason > 200 chars → truncated in DB |
| `test_duplicate_cost_log_idempotency` | Cost log INSERT with same log_id → no duplicate (PK constraint) |
| `test_ollama_unavailable_worker_continues` | Ollama down → Phase 2 errors → mentions reset to unresolved; Phase 1 still runs |

---

## 12. Migration Strategy

### Migration Execution Order

1. `intelligence-migrations` 0005 (intelligence_db: add service_name, tenant_id, error_code to llm_usage_log)
2. `nlp-pipeline` 0007 (nlp_db: add resolution_outcome, resolution_noise_reason, resolution_processed_at to entity_mentions + index)
3. `nlp-pipeline` 0008 (nlp_db: create llm_usage_log table)
4. `rag-chat` 0003 (rag_chat_db: create llm_usage_log table)

### Break-Surface Analysis

| Change | What Currently Exists | What Breaks | Fix |
|--------|----------------------|------------|-----|
| Add `resolution_outcome` to entity_mentions | Table has no such column | Existing INSERT tests may fail if `resolution_outcome` not passed | Add `server_default='unresolved'`; no INSERT changes needed |
| Add `resolution_outcome` values to ResolutionOutcome enum | 3 values: auto_resolved, provisional, unresolved | Pattern matches on ResolutionOutcome may warn on unhandled enum values | Add `escalated`, `entity_created`, `noise` cases to all match/if-elif chains |
| Add `LlmUsageLogProtocol` to FallbackChainClient constructor | Constructor has no `usage_logger` param | No breakage — optional param with `None` default | Add `usage_logger: LlmUsageLogProtocol | None = None` |
| Refactor S7 FallbackChainClient to use protocol | Currently uses `LlmUsageLogRepository` directly | Repository still satisfies protocol; tests need to verify structural match | Add `isinstance(repo, LlmUsageLogProtocol)` check in test |
| Add `service_name`, `tenant_id` to intelligence_db.llm_usage_log | 12 columns | S7 INSERT must include new columns or use server_default | migration uses `NOT NULL DEFAULT 'knowledge-graph'`; existing INSERTs work |

### Backward Compatibility

- `resolution_outcome='unresolved'` server_default ensures all existing UNRESOLVED rows are correctly classified without a full table scan backfill
- The backfill UPDATE in migration 0007 sets `auto_resolved` for rows with `resolved_entity_id IS NOT NULL` — this is a one-time migration; current row count in production is expected to be < 500K
- All new columns on `llm_usage_log` have server defaults; existing S7 INSERT statements continue to work without modification (server defaults handle the new columns)

---

## 13. Observability

### Structured Log Events (structlog)

| Event | Service | Fields | When |
|-------|---------|--------|------|
| `unresolved_resolution_batch_complete` | S6 | batch_id, total, cascade_resolved, entity_created, noise_classified, errors, duration_ms | End of each worker run |
| `unresolved_resolution_stale_lock_recovery` | S6 | rows_reset, oldest_escalated_at | On worker startup if stale rows found |
| `llm_cost_logged` | S6/S7/S8 | model_id, provider, capability, tokens_in, tokens_out, cost_usd, latency_ms | After each LLM call |
| `llm_cost_log_failed` | S6/S7/S8 | error | When DB write for cost log fails |

### Metrics (Prometheus counters via structlog)

| Metric | Type | Labels |
|--------|------|--------|
| `unresolved_mentions_processed_total` | Counter | `outcome` (cascade_resolved\|entity_created\|noise\|error) |
| `llm_usage_cost_usd_total` | Counter | `provider`, `capability`, `service_name` |
| `llm_usage_tokens_total` | Counter | `provider`, `token_type` (in\|out) |
| `llm_call_latency_ms` | Histogram | `provider`, `capability` |

### Grafana Dashboard Queries

The `GET /api/v1/admin/llm-costs` endpoint is designed to be called by Grafana JSON data source. Recommended dashboard panels:
- Monthly spend by provider (bar chart, breakdown=provider)
- Daily spend trend (line chart, breakdown=day)
- Cost per service (pie chart, breakdown=service)
- Success rate by provider (stat panel)

---

## 14. Open Questions

| ID | Question | Classification | Resolution |
|----|----------|---------------|-----------|
| OQ-001 | Should the `UnresolvedResolutionWorker` run in the same process as the main article consumer, or as a separate Docker entrypoint? | DEFERRED | Assumption: same process, registered as a background worker (matching Worker 13D-1..3 pattern). Can be separated if memory pressure is observed. |
| OQ-002 | Should the S9 admin cost endpoint also accept date ranges (start_date/end_date) in addition to period (YYYY-MM)? | DEFERRED | v1: period only. Date range support can be added without schema changes. |
| OQ-003 | For Ollama token count estimation: is word_count/0.75 sufficient, or should we add character-based fallback? | DEFERRED | Assumption: word_count/0.75 is sufficient for approximate tracking. Exact counts not needed for $0 provider. |
| OQ-004 | `entity_created` outcome: should the worker also emit a metric event that the entity was created, for real-time pipeline monitoring? | DEFERRED | Assumption: structlog event is sufficient. Can add `platform.entity.discovered.v1` Kafka event in a future iteration if monitoring shows value. |

---

## 15. Estimation

| Area | Waves | Effort |
|------|-------|--------|
| Feature A: S6 worker + migrations | 2 waves | Medium |
| Feature B: libs/ml-clients protocol + cost utils | 1 wave | Small |
| Feature B: S6 cost logging | 1 wave (combined with A wave 2) | Small |
| Feature B: S7 refactor | 1 wave | Small |
| Feature B: S8 cost logging | 1 wave | Small |
| Feature B: S9 admin endpoint | 1 wave | Small |
| Feature B: intelligence-migrations 0005 | Part of libs wave | Trivial |
| Total | ~5–6 waves | ~6–9 hours |

**Critical path**: Feature A Wave 1 (migrations) → Feature A Wave 2 (worker) → Worker 13E integration test

**Dependency note**: Feature B waves are independent of each other and can be parallelized. Feature A waves must be sequential (migration before worker).
