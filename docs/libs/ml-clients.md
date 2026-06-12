# ML Clients Library

> **Package**: `ml-clients` · **Path**: `libs/ml-clients/` · **Version**: 0.2.0
> **Purpose**: Protocol interfaces and concrete adapters for embedding, NER, structured
> extraction, entity description generation, cross-encoder reranking, and LLM cost
> tracking. The **only** path through which S6 (NLP Pipeline) and S7 (Knowledge
> Graph) call ML models.

---

## Purpose

Without a shared ML client library, each service that needs embeddings or NER would
implement its own HTTP client against Ollama, DeepInfra, or GLiNER — with
duplicated error handling, semaphore management, and metric tracking. `ml-clients`
provides:

- **Protocol interfaces** (structural typing, not ABC) so service code can be tested
  with any compliant mock without importing concrete adapters.
- **Concrete adapters** for every supported backend (Ollama, DeepInfra, Jina,
  GLiNER local/HTTP/adaptive, Anthropic, Gemini, OpenAI/ChatGPT, DeepSeek, Cohere).
- **Uniform error mapping** — every adapter converts backend errors to `RetryableError`
  or `FatalError` so the Kafka consumer's retry/dead-letter logic works consistently.
- **Semaphore injection** — all adapters require a semaphore to cap concurrent ML
  calls. Unbounded concurrency OOMs GPU/CPU backends under load.
- **Cost tracking** — `estimate_cost()`, `LlmCallUsage`, and `LlmUsageLogProtocol`
  enable per-call cost attribution without coupling adapter code to service DB schemas.

---

## Installation

```toml
[project]
dependencies = ["ml-clients"]

# With optional ML backends:
dependencies = [
    "ml-clients[gliner]",     # local GLiNER model
    "ml-clients[anthropic]",  # Anthropic Claude
    "ml-clients[gemini]",     # Google Gemini
    "ml-clients[openai]",     # OpenAI-compatible (ChatGPT, DeepSeek, DeepInfra)
]
```

```bash
pip install -e "libs/ml-clients"
pip install -e "libs/ml-clients[gliner,openai]"
```

Core dependencies: `pydantic-settings>=2.0`, `structlog>=25.0`, `httpx>=0.27`,
`messaging`. Optional: `gliner>=0.2`, `anthropic>=0.30`, `google-genai>=0.7`,
`openai>=1.40`. Python 3.11–3.12.

---

## Protocols

All service code should depend on these interfaces — never on concrete adapter classes.

| Protocol | Import | Method(s) | Used by |
|----------|--------|-----------|---------|
| `EmbeddingClient` | `from ml_clients import EmbeddingClient` | `embed(inputs: list[EmbeddingInput]) → list[EmbeddingOutput]` | S6 NLP Pipeline |
| `NERClient` | `from ml_clients import NERClient` | `extract_entities(inp: NERInput) → NEROutput`; `batch_extract_entities(inputs) → list[NEROutput]` | S6 NLP Pipeline |
| `ExtractionClient` | `from ml_clients import ExtractionClient` | `extract(inp: ExtractionInput) → ExtractionOutput` | S6, S7 |
| `EntityDescriptionClient` | `from ml_clients.description_client import EntityDescriptionClient` | `generate_description(entity_id, canonical_name, entity_type, context_hints) → str | None` | S7 `DefinitionRefreshWorker` |

All protocols are `@runtime_checkable`: `isinstance(adapter, EmbeddingClient)` works.

> **Note**: `runtime_checkable` only verifies method *presence*, not async vs sync.
> Type errors from sync implementations are caught by mypy, not at runtime.

---

## Dataclasses

All are `@dataclass(frozen=True)` — immutable.

| Dataclass | Fields |
|-----------|--------|
| `EmbeddingInput` | `text: str`, `model_id: str`, `instruction_prefix: str | None = None` |
| `EmbeddingOutput` | `embedding: list[float]`, `model_id: str`, `dimension: int` |
| `NERInput` | `text: str`, `entity_classes: list[str]`, `threshold: float = 0.5` |
| `EntityMention` | `text: str`, `label: str`, `start: int`, `end: int`, `score: float` |
| `NEROutput` | `mentions: list[EntityMention]` |
| `ExtractionInput` | `prompt: str`, `context: str`, `output_schema: dict`, `model_id: str`, `template_id: str | None = None` |
| `ExtractionOutput` | `result: dict`, `raw_response: str`, `model_id: str`, `extraction_confidence: float | None = None` |

---

## Adapters

| Adapter | Protocol | Backend | Default model | Optional install |
|---------|----------|---------|---------------|-----------------|
| `OllamaEmbeddingAdapter` | `EmbeddingClient` | Ollama REST `/api/embeddings` | `bge-large-en-v1.5` (1024-dim) | — |
| `DeepInfraEmbeddingAdapter` | `EmbeddingClient` | DeepInfra OpenAI-compat `/embeddings` | `BAAI/bge-large-en-v1.5` (1024-dim) | — |
| `JinaEmbeddingAdapter` | `EmbeddingClient` | Jina AI REST `/v1/embeddings` | `jina-embeddings-v3` (1024-dim) | — |
| `GLiNERLocalAdapter` | `NERClient` | GLiNER in-process (same container) | `urchade/gliner_large-v2.1` | `[gliner]` |
| `GLiNERHTTPAdapter` | `NERClient` | GLiNER server REST `/ner/batch` (fixed concurrency) | — | — |
| `AdaptiveGLiNERHTTPAdapter` | `NERClient` | GLiNER server REST `/ner/batch` (AIMD adaptive) | — | — |
| `OllamaExtractionAdapter` | `ExtractionClient` | Ollama REST `/api/chat` | `qwen2.5:7b-instruct` | — |
| `AnthropicExtractionAdapter` | `ExtractionClient` | Anthropic Messages API | `claude-sonnet-4-6` | `[anthropic]` |
| `GeminiExtractionAdapter` | `ExtractionClient` | Google GenAI API | `gemini-2.5-pro` | `[gemini]` |
| `ChatGPTExtractionAdapter` | `ExtractionClient` | OpenAI Chat Completions | `gpt-5-mini` | `[openai]` |
| `DeepSeekExtractionAdapter` | `ExtractionClient` | DeepSeek (OpenAI-compat) | DeepSeek R1 Distill 32B | `[openai]` |
| `GeminiDescriptionAdapter` | `EntityDescriptionClient` | Google GenAI API | `gemini-3.1-flash-lite` | `[gemini]` |
| `DeepInfraDescriptionAdapter` | `EntityDescriptionClient` | DeepInfra (OpenAI-compat) | `Qwen/Qwen3-235B-A22B-Instruct-2507` (primary), `Qwen/Qwen3-32B` (fallback) | `[openai]` |
| `CohereRerankAdapter` | (custom) | Cohere Rerank API v2 | `rerank-english-v3.0` | — |
| `EmbeddingGemmaRouterAdapter` | (custom — *not* `EmbeddingClient`) | DeepInfra OpenAI-compat `/embeddings` | `google/embeddinggemma-300m` (768-dim, MRL→512/256/128) | — |
| `NullDescriptionAdapter` | `EntityDescriptionClient` | No-op (always returns None) | — | — |

**Error mapping contract** (all adapters):

| Condition | Raised as |
|-----------|-----------|
| Timeout / network error / 5xx / 429 | `RetryableError` |
| 4xx / malformed JSON / bad input / wrong dimension | `FatalError` |
| Missing optional package | `FatalError` |

---

## Primary → Fallback Wrappers (LIB-004 / TASK-W4-02)

`ml_clients.fallback` provides drop-in wrappers that compose two adapters into a
single client implementing the same Protocol. On `RetryableError` (timeout, 5xx,
or `RateLimitError` 429 after the primary's own retries are exhausted), the
wrapper transparently calls the secondary adapter. `FatalError` always
propagates without invoking the fallback — a malformed request will fail the
same way against either backend.

| Wrapper | Protocol | Methods proxied |
|---|---|---|
| `FallbackEmbeddingClient` | `EmbeddingClient` | `embed` |
| `FallbackNERClient` | `NERClient` | `extract_entities`, `batch_extract_entities` |
| `FallbackExtractionClient` | `ExtractionClient` | `extract` |

```python
from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter
from ml_clients.fallback import FallbackEmbeddingClient

client = FallbackEmbeddingClient(
    primary=DeepInfraEmbeddingAdapter(api_key=..., ...),
    fallback=OllamaEmbeddingAdapter(base_url=..., semaphore=..., ...),
)
# Same interface as EmbeddingClient — no other call-site changes needed.
outputs = await client.embed(inputs)
```

A single structured log line `ml_client_falling_back_to_secondary` is emitted
whenever the fallback fires (fields: `primary`, `fallback`, `operation`,
`error`, `error_type`) — convenient for Grafana alerting.

---

## Adaptive GLiNER Concurrency

`AdaptiveGLiNERHTTPAdapter` uses **AIMD (Additive-Increase / Multiplicative-Decrease)**
— the same algorithm as TCP congestion control — to automatically discover and
maintain the right concurrency level for the GLiNER server cluster.

**How it works:**

1. Fans out one HTTP request per input text (not a single batch request), allowing
   individual texts to be served by different GLiNER replicas.
2. A `ResizableSemaphore` (custom asyncio semaphore with runtime-adjustable limit)
   caps concurrent in-flight requests.
3. An `AIMDController` monitors rolling average latency and adjusts the semaphore:

   | Condition | Action |
   |-----------|--------|
   | Rolling avg latency < `target_latency_ms` | `limit += 1` (additive increase) |
   | Rolling avg latency > `target_latency_ms * 1.5` | `limit -= 1` (soft decrease) |
   | HTTP 5xx | `limit -= 1` (error signal) |
   | Timeout | `limit //= 2` (multiplicative decrease) |

4. Waits for `min_samples` observations (default 3) before adjusting, avoiding
   over-reaction to cold-start variance.
5. On rebalance / shutdown: all paused partitions are resumed and tracking cleared.

**Steady-state:** 1 CPU GLiNER replica → limit ~1; N CPU replicas → limit ~N;
N GPU replicas → limit N–2N. No configuration changes needed when scaling.

```python
from ml_clients.adapters import AdaptiveGLiNERHTTPAdapter

adapter = AdaptiveGLiNERHTTPAdapter(
    base_url="http://gliner-server:8080",
    initial_concurrency=2,         # adjusted quickly by AIMD
    max_concurrency=30,            # hard upper bound
    target_latency_ms=2000.0,      # CPU inference target; ~200 for GPU
    timeout_seconds=60.0,
    window_size=10,
)
outputs = await adapter.batch_extract_entities(inputs)   # order preserved
```

**When to use which GLiNER adapter:**

| Adapter | Use when |
|---------|----------|
| `GLiNERLocalAdapter` | Model runs in-process (same container; no network hop) |
| `GLiNERHTTPAdapter` | Fixed concurrency; replica count known and stable |
| `AdaptiveGLiNERHTTPAdapter` | Replica count varies, GPU vs CPU unknown, or production |

---

## Cost Tracking (`ml_clients.cost`, `ml_clients.usage_log`)

### `estimate_cost(provider, model_id, tokens_in, tokens_out) → float`

Returns estimated USD cost for one LLM call. Lookup order: exact provider+model
match → wildcard `"*"` within provider (for Ollama, always `$0.00`) → `0.0`.

```python
from ml_clients.cost import estimate_cost, estimate_tokens_from_text, PRICING

cost = estimate_cost("deepinfra", "Qwen/Qwen3-235B-A22B-Instruct-2507", 500, 100)
# → 0.000071 * 0.5 + 0.000100 * 0.1 = ...

tokens = estimate_tokens_from_text(long_text)   # word-count heuristic, min 1
```

**Current `PRICING` table** (USD per 1M tokens):

| Provider | Model | Input | Output |
|----------|-------|-------|--------|
| `deepinfra` | `Qwen/Qwen3-235B-A22B-Instruct-2507` | $0.071 | $0.10 |
| `deepinfra` | `Qwen/Qwen3-32B` | $0.08 | $0.28 |
| `deepinfra` | `deepseek-ai/DeepSeek-V4-Flash` | $0.14 | $0.28 |
| `openrouter` | `deepseek/deepseek-r1-distill-qwen-32b` | $0.69 | $2.19 |
| `gemini` | `gemini-3.1-flash-lite` | $0.075 | $0.30 |
| `ollama` | `*` (all models) | $0.00 | $0.00 |

### `LlmUsageLogProtocol` (structural protocol)

Service-side cost-log repositories implement this protocol. Adapters accept it
as an optional `usage_logger` parameter and fire-and-forget log calls.

```python
from ml_clients.usage_log import LlmUsageLogProtocol

# Your service implements:
class LlmUsageLogRepository:
    async def log(self, *, model_id, provider, capability,
                  tokens_in, tokens_out, latency_ms,
                  estimated_cost_usd=0.0, success=True,
                  error_code=None, **context) -> None:
        # Persist to llm_usage_log table
        ...
```

### `LlmCallUsage` (value object)

Frozen dataclass returned by cost-aware adapters:
`model_id`, `provider`, `capability`, `tokens_in`, `tokens_out`,
`estimated_cost_usd`, `latency_ms`, `success`, `error_code`.

### `DeepInfraDescriptionAdapter` — Monthly Cost Cap

Uses an atomic Valkey `INCRBYFLOAT`-then-check pattern:
1. Reserve estimated cost before any API call.
2. If reservation exceeds `max_monthly_usd * 0.95`: return `None` without calling.
3. After the call: adjust reservation to actual token usage.
4. If both primary and fallback fail: undo reservation.

Strips Qwen3 `<think>...</think>` reasoning blocks before returning descriptions.
Sanitizes `canonical_name` (strips control chars + angle brackets) before prompt
insertion to prevent prompt injection (PRD-0073 §12).

---

## Configuration

All settings read from environment variables. Consumed via `MLClientsSettings`
(pydantic-settings).

| ENV var | Default | Description |
|---------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama server base URL |
| `EMBEDDING_MODEL_ID` | `bge-large-en-v1.5` | Embedding model in Ollama |
| `EXTRACTION_MODEL_ID` | `qwen2.5:7b-instruct` | Extraction model in Ollama |
| `NER_MODEL_PATH` | `urchade/gliner_large-v2.1` | HuggingFace path for local GLiNER |
| `MAX_OLLAMA_CONCURRENT` | `4` | Semaphore value for Ollama concurrency |

Cloud adapter API keys are not part of `MLClientsSettings` — they are passed as
constructor arguments from each service's own settings class.

---

## Usage Examples

### Embedding in a FastAPI Service

```python
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator
from fastapi import FastAPI, Depends
from ml_clients import EmbeddingClient, MLClientsSettings
from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter
from ml_clients.dataclasses import EmbeddingInput

settings = MLClientsSettings()
_embedding_client: EmbeddingClient | None = None

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _embedding_client
    _embedding_client = DeepInfraEmbeddingAdapter(
        api_key=settings.embedding_api_key,  # from your service settings
        model_id="BAAI/bge-large-en-v1.5",
    )
    yield
    _embedding_client = None

app = FastAPI(lifespan=lifespan)

def get_embedding_client() -> EmbeddingClient:
    assert _embedding_client is not None
    return _embedding_client

@app.post("/embed")
async def embed(text: str, client: EmbeddingClient = Depends(get_embedding_client)):
    outputs = await client.embed([EmbeddingInput(text=text, model_id="BAAI/bge-large-en-v1.5")])
    return {"dimension": outputs[0].dimension}
```

### NER with Valkey Dedup

```python
import asyncio
from ml_clients.adapters.gliner_adaptive import AdaptiveGLiNERHTTPAdapter
from ml_clients.dataclasses import NERInput

semaphore = asyncio.Semaphore(4)
adapter = AdaptiveGLiNERHTTPAdapter(
    base_url="http://gliner:8080",
    initial_concurrency=2,
    max_concurrency=16,
    target_latency_ms=3000.0,
)

inputs = [NERInput(text=section, entity_classes=["ORG", "PERSON", "GPE"])
          for section in article_sections]
outputs = await adapter.batch_extract_entities(inputs)  # order preserved
all_mentions = [m for out in outputs for m in out.mentions]
```

### Cost-Tracked Description Generation

```python
from ml_clients.adapters.deepinfra_description import DeepInfraDescriptionAdapter

adapter = DeepInfraDescriptionAdapter(
    api_key=settings.deepinfra_api_key,
    semaphore=asyncio.Semaphore(3),
    cost_tracker=valkey_client,      # Valkey for monthly cap
    max_monthly_usd=10.0,
    usage_logger=llm_log_repo,       # optional: persists to llm_usage_log table
)

description = await adapter.generate_description(
    entity_id=str(entity_id),
    canonical_name="Apple Inc.",
    entity_type="company",
    context_hints={"ticker": "AAPL", "exchange": "NASDAQ"},
)
# Returns None if monthly cost cap exceeded
```

### Cross-Encoder Reranking

```python
from ml_clients.adapters.cohere_rerank import CohereRerankAdapter

reranker = CohereRerankAdapter(api_key=settings.cohere_api_key)
results = await reranker.rerank(
    query="Apple quarterly earnings",
    documents=["doc1 text...", "doc2 text..."],
    top_n=12,
)
# [{"index": 0, "relevance_score": 0.92}, {"index": 1, "relevance_score": 0.74}, ...]
```

---

## Architecture Notes

### Why `Protocol` instead of `ABC`?

`Protocol` (structural subtyping) means service code can be tested with any mock
object that has the right methods — no subclassing required. `isinstance(mock,
EmbeddingClient)` returns `True` as long as the mock has an `embed` method. ABCs
require explicit subclassing, which couples test code to the library.

### Why semaphore injection instead of a configured semaphore inside the adapter?

An adapter-internal semaphore would be per-instance. If a service creates multiple
adapter instances (e.g., for different models), they would each have their own
semaphore — effectively multiplying the concurrency cap. Injecting a shared
`asyncio.Semaphore` at construction makes the total concurrency budget explicit and
shared across all adapters that call the same backend.

### `GLiNERLocalAdapter` and the event loop

`GLiNERLocalAdapter` wraps all synchronous GLiNER inference calls in
`loop.run_in_executor(None, ...)`. Without this, GLiNER's CPU inference would block
the event loop, stalling all concurrent requests in the service.

### `DeepInfraEmbeddingAdapter` — 1500-char truncation

BGE-large has a 512-token BERT context window. Texts exceeding ~512 tokens cause
the GGML runner to abort (BP-121). Both `DeepInfraEmbeddingAdapter` and
`OllamaEmbeddingAdapter` apply a 1500-character truncation limit so that ingestion
embeddings and query embeddings remain in the same semantic space.

### `EmbeddingGemmaRouterAdapter` — news-routing classifier (PLAN-0111 C-1)

`google/embeddinggemma-300m` (DeepInfra, 768-dim) produces the **classifier input
vector** for the news-routing cascade router: a short headline (`title + subtitle`)
is embedded once, then a small calibrated head decides the routing tier.

Key design points:

- **Separate vector space.** This embedding is **never** ANN-compared against the
  BGE retrieval vectors (`DeepInfraEmbeddingAdapter`, 1024-dim). To make that
  invariant structural, the adapter is deliberately **not** an `EmbeddingClient`
  and returns raw `list[list[float]]` rather than `EmbeddingOutput` — so it can't
  be accidentally wired into the retrieval path.
- **Task-specific prompts.** EmbeddingGemma is prompt-conditioned.
  `embed_for_classification(texts)` prepends `task: classification | query: ` (the
  router default, since the downstream use is a classifier). `embed_documents(
  (title, content))` uses the retrieval form `title: {title} | text: {content}`.
- **Matryoshka (MRL) truncation.** Native 768d; pass `dimensions=512|256|128` to
  truncate **client-side** then **L2-renormalize** to unit norm (per the model
  card). DeepInfra also accepts a server-side `dimensions` param, but we truncate
  client-side so the renormalization is explicit and deterministic.
- `encoding_format=float` (the model is float32/bfloat16, **not** float16); timeout
  is wrapped in `httpx.Timeout` (BP-235). Verified live 2026-06-12: 200 OK, 768d,
  ~0.32s; finance/finance cosine 0.76 > finance/sports 0.58.

Config lives on `MLClientsSettings` (`router_embedding_*`); the API key is read
from the environment (`*_DEEPINFRA_API_KEY`), never hardcoded.

---

## Extension Points

To add a new adapter:

1. Create `libs/ml-clients/src/ml_clients/adapters/<provider>_<capability>.py`.
2. Implement the appropriate protocol (`EmbeddingClient`, `NERClient`, `ExtractionClient`,
   or `EntityDescriptionClient`).
3. Map all backend errors to `RetryableError` or `FatalError`.
4. Add to `libs/ml-clients/src/ml_clients/adapters/__init__.py`.
5. Add tests in `libs/ml-clients/tests/` (mock all HTTP calls).
6. Add to the adapter table in this doc.
7. If the adapter uses a new provider, add pricing to `cost.py`'s `PRICING` table.

---

## Testing

```bash
cd libs/ml-clients

# Unit tests (no external services):
python -m pytest tests/ --ignore=tests/integration/ -v --tb=short

# Integration tests (requires Ollama with models pulled):
ollama pull bge-large-en-v1.5
ollama pull qwen2.5:7b-instruct
OLLAMA_BASE_URL=http://localhost:11434 \
  python -m pytest tests/integration/ -v -m integration

# Type checking and lint:
mypy --strict src/
ruff check src/ tests/
```

Unit tests cover the error-mapping matrix for each adapter:
timeout → `RetryableError`, 5xx → `RetryableError`, 4xx → `FatalError`,
malformed output → `FatalError`, valid response → correct output type.

---

## Common Pitfalls

1. **GLiNER synchronous call in async handler** — `gliner_model.predict_entities()`
   blocks the event loop. Always use `GLiNERLocalAdapter` which wraps in executor.
2. **Adapter without a semaphore (or effectively unbounded semaphore)** — Ollama,
   GLiNER, and Cohere all OOM or rate-limit under unbounded concurrency. Use a sane
   `asyncio.Semaphore` value from config.
3. **Swallowing adapter exceptions** — adapters already wrap all errors. Catch only
   `RetryableError` / `FatalError` at consumer boundaries — don't catch raw httpx
   exceptions or you bypass the consumer's retry/dead-letter logic.
4. **Importing concrete adapters in service business logic** — couple against the
   Protocol instead. `from ml_clients import EmbeddingClient`, not
   `from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter`.
5. **Missing `[openai]` extra for DeepInfra** — `DeepInfraDescriptionAdapter`
   requires `openai>=1.40` (uses `openai.AsyncOpenAI` against the DeepInfra base
   URL). Missing package raises `FatalError` at call time with a clear message.
