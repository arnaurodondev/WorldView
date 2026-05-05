# PLAN-0067 — W11 Full Tool Catalog: Embedding Search + Graph Traversal as LLM Tools

> **Status**: draft
> **Created**: 2026-05-03
> **Owner agent**: Staff engineer / TPM
> **Estimated effort**: ~4.5 dev-days (5 waves, 20 tasks + security/safety additions from revision 2026-05-03)
> **Critical path**: Wave 1 → Wave 2 → Wave 3 → Wave 4 ∥ Wave 5 (frontend)
> **Hard dependency**: PLAN-0066 Wave H must ship first — Wave H creates `ToolRegistry`, `ToolExecutor` (S3 only), `capability_manifest.yaml` (2 tools), and the 2-turn tool loop in `ChatOrchestratorUseCase`.

---

## 1. Scope

PLAN-0066 Wave H establishes the tool-use infrastructure with two temporal tools (`get_price_history`, `get_fundamentals_history`). Those tools cover structured time-series data. The platform's **key differentiators** — **embedding-based document search** and **knowledge graph traversal** — are NOT yet in the tool catalog. This plan adds them.

Specifically, PLAN-0066 Wave H does NOT include:
- LLM adapter function calling support — `deepinfra_adapter.py` has NO `tools` parameter today; the whole tool-use loop depends on the LLM actually being able to call tools
- `search_documents` → wraps `S6Port.search_chunks()` — the BM25+ANN hybrid embedding search (THE core differentiator)
- `get_entity_graph` → wraps `S7Port.get_egocentric_graph()` — entity-centric subgraph extraction
- `traverse_graph` → wraps `S7Port.cypher_traverse()` — free-form Cypher graph traversal (THE graph differentiator)
- `search_entity_relations` → wraps `S7Port.search_relations()` — relation triplets
- `search_claims` → wraps `S7Port.search_claims()` — analyst claim extraction
- `search_events` → wraps `S7Port.search_events()` — structured corporate event search
- `get_contradictions` → wraps `S7Port.get_contradictions()` — cross-source contradiction pairs
- `get_portfolio_context` → wraps `S1Port.get_portfolio_context()` — user portfolio + watchlist
- Full orchestrator migration — currently the 13-step classical pipeline (IntentClassifier → RetrievalPlanBuilder → ParallelOrchestrator) runs for ALL queries; with this plan, ALL queries go through the tool-use loop (feature-flag gated)
- Frontend tool-call progress UI — the spinner showing "Traversing knowledge graph..." during tool execution

**What this plan does NOT change**:
- The S6, S7, S3, S1 port implementations — all retrieval logic is untouched
- The `ToolSpec`, `ToolRegistry`, `ToolExecutor` base classes from PLAN-0066
- The `capability_manifest.yaml` format (only adds entries, per R29)
- The existing 13-step classical pipeline — it becomes the feature-flag-off fallback path

**Out of scope**:
- NL→SQL (NL-SQL-style) tool — future ADR
- `IntentClassifier` / `RetrievalPlanBuilder` hard deletion — they stay as dead code until PLAN-0067 is validated in staging
- PLAN-0067 does not retire the golden eval CI gate (PLAN-0063) — it adds a parallel tool-use eval path

---

## 2. Gap Analysis: What PLAN-0066 Wave H Left Incomplete

### 2.1 The LLM adapter has no function calling support

`deepinfra_adapter.py` sends this payload to DeepInfra OpenAI-compat endpoint:
```python
payload = {
    "model": self._model,
    "messages": [{"role": "user", "content": prompt}],
    "stream": True,
    "max_tokens": max_tokens,
    "temperature": temperature,
}
```

No `tools` key. No `tool_choice` key. The LLM cannot emit `tool_use` blocks.

PLAN-0066 Wave H T-W10-H-03 assumed the LLM adapter would receive tools — but the adapter was never updated. This is the **most critical gap**: without it, the entire tool-use loop is a dead code path.

### 2.2 `ToolExecutor` only handles S3

PLAN-0066 Wave H builds `ToolExecutor` with only `_handle_get_price_history` and `_handle_get_fundamentals_history`. The 8 retrieval sources (S6, S7×6, S1) have no handlers.

### 2.3 The orchestrator still runs the classical pipeline for all queries

PLAN-0066 Wave H adds the tool loop as an *additional* path that runs AFTER the classical pipeline. The classical pipeline (IntentClassifier → RetrievalPlanBuilder → ParallelOrchestrator) still fires for every query. PLAN-0067 inverts this: the tool-use path becomes the default for all queries.

### 2.4 The current `LlmStreamProvider` port is too narrow

```python
class LlmStreamProvider(Protocol):
    def stream(self, prompt: str, *, max_tokens: int, temperature: float) -> AsyncIterator[str]: ...
```

This takes a `prompt: str` — a single flat string. Tool-calling requires structured `messages: list[dict]` format (system + user + assistant turns) and a `tools` parameter. The port must be extended.

---

## 3. Codebase State Verification

Read 2026-05-03.

| Component | Type | Service | Current state (from code) | Expected state after PLAN-0067 | Delta |
|-----------|------|---------|--------------------------|-------------------------------|-------|
| `LlmStreamProvider` port | interface | S8 | `stream(prompt: str)` only — no messages format, no tools | `chat_with_tools(messages, tools)` + keep `stream()` for back-compat | extend port |
| `DeepInfraCompletionAdapter` | class | S8 | no `tools` key in payload, no `delta.tool_calls` parsing | add `tools` parameter, parse tool_use blocks, signal `ToolCallBatch` | modify |
| `OpenRouterAdapter` | class | S8 | no tool support | same as DeepInfra | modify |
| `OllamaAdapter` | class | S8 | no tool support | add stub (log warning — not all Ollama models support tools) | modify |
| `ToolCallBatch` | domain type | libs | does not exist after PLAN-0066 (Wave H assumed it) | `@dataclass class ToolCallBatch: tool_calls: list[ToolUseBlock]` | new in `libs/tools/types.py` |
| `LLMToolResponse` | domain type | libs | does not exist | `@dataclass: text: str | None, tool_calls: list[ToolUseBlock], finish_reason: str` | new |
| `capability_manifest.yaml` | config | libs | 2 tools (PLAN-0066 Wave H) | 10 tools (+ 8 new) | extend (R29) |
| `ToolExecutor` S6 handler | method | S8 | does not exist | `_handle_search_documents` → `S6Port.search_chunks()` | new |
| `ToolExecutor` S7 graph handlers | methods | S8 | does not exist | `_handle_get_entity_graph` + `_handle_traverse_graph` | new |
| `ToolExecutor` S7 signals handlers | methods | S8 | does not exist | `_handle_search_entity_relations` + `_handle_search_claims` + `_handle_search_events` + `_handle_get_contradictions` | new |
| `ToolExecutor` S1 handler | method | S8 | does not exist | `_handle_get_portfolio_context` | new |
| `ToolExecutor.__init__` | constructor | S8 | `(registry, s3)` after PLAN-0066 | `(registry, s3, s6, s7, s1)` | modify |
| `SSEEmitter.emit_tool_call` | method | S8 | does not exist | `emit_tool_call(tool_name, input_dict, status)` | new |
| `SSEEmitter.emit_tool_result` | method | S8 | does not exist | `emit_tool_result(tool_name, status)` | new |
| `ChatOrchestratorUseCase` | use case | S8 | PLAN-0066 Wave H adds tool loop after classical pipeline | tool-use path becomes default (feature flag); classical path becomes fallback | modify |
| `config.tool_use_enabled` | env var | S8 | does not exist | `TOOL_USE_ENABLED=true` in dev env; `false` as safe default | new env var |
| `IntentClassifier` | class | S8 | 3-tier, active for all queries | gated: runs only when `tool_use_enabled=False` | gate |
| `RetrievalPlanBuilder` | class | S8 | active for all queries | gated: runs only when `tool_use_enabled=False` | gate |
| `ParallelRetrievalOrchestrator` | class | S8 | active for all queries | gated: runs only when `tool_use_enabled=False` | gate |
| `ToolCallIndicator` | component | worldview-web | does not exist | spinner + tool label, consumed from SSE `tool_call` events | new |
| `useChatStream` | hook | worldview-web | no `tool_call`/`tool_result` event handling | consume new SSE events, expose `activeTools: string[]` state | modify |

**No DB migrations, Kafka topics, or Avro schema changes** — this plan is pure application-layer + frontend.

---

## 4. Wave Decomposition

### Wave W11-1: LLM Chat Interface + Function Calling

**Goal**: Add function-calling support to all LLM adapters so the tool-use loop can actually dispatch tool calls.
**Depends on**: PLAN-0066 Wave H complete
**Estimated effort**: 45 min
**Architecture layer**: libs (domain types) + S8 infrastructure (LLM adapters)

#### Pre-read
- `services/rag-chat/src/rag_chat/application/ports/llm_provider.py` — current `LlmStreamProvider` port
- `services/rag-chat/src/rag_chat/infrastructure/llm/deepinfra_adapter.py` — current streaming adapter (no tool support)
- `services/rag-chat/src/rag_chat/infrastructure/llm/openrouter_adapter.py` — same
- `libs/tools/tool_spec.py` — `ToolSpec`, `ToolUseBlock` from PLAN-0066 Wave H

#### Tasks

##### T-W11-1-01: `ToolCallBatch` + `LLMToolResponse` domain types
**Type**: impl
**depends_on**: none
**blocks**: T-W11-1-02, T-W11-1-03
**Target files**:
- `libs/tools/types.py` (new — add alongside PLAN-0066's `tool_spec.py`)

**What to build**:
Two dataclasses that represent the possible outcomes of a tool-capable LLM call:

```python
@dataclass
class ToolUseBlock:
    """Single tool call emitted by the LLM. Defined here if not already in tool_spec.py."""
    id: str                   # LLM-assigned call ID (e.g. "call_abc123")
    name: str                 # tool name (matches registry)
    input: dict               # parsed JSON arguments

@dataclass
class ToolCallBatch:
    """Yielded from the LLM stream when the model emits function calls instead of text.

    WHY SEPARATE: streaming responses mix text tokens and tool_call deltas in the same
    stream. When finish_reason=="tool_calls" arrives, the caller needs a clean signal
    to stop accumulating text and start executing tools.
    """
    tool_calls: list[ToolUseBlock]
    finish_reason: str = "tool_calls"

@dataclass
class LLMToolResponse:
    """Non-streaming response from chat_with_tools() — either text or tool calls."""
    text: str | None                          # set when finish_reason=="stop"
    tool_calls: list[ToolUseBlock]            # set when finish_reason=="tool_calls"
    finish_reason: str                        # "stop" | "tool_calls" | "length"
    usage: dict | None = None                 # token counts for cost tracking

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
```

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_tool_call_batch_has_tool_calls_true` | `ToolCallBatch` with items → `has_tool_calls=True` | unit |
| `test_llm_tool_response_stop_no_tool_calls` | `finish_reason="stop"` + text → `has_tool_calls=False` | unit |

Minimum: 2 unit tests.

**Acceptance criteria**:
- [ ] `ToolUseBlock` fields align with OpenAI `tool_calls[].function` structure (name, arguments as parsed dict)
- [ ] `LLMToolResponse.usage` can be passed to existing cost-tracking infrastructure

---

##### T-W11-1-02: `LlmChatProvider` port extension
**Type**: impl
**depends_on**: T-W11-1-01
**blocks**: T-W11-1-03
**Target files**:
- `services/rag-chat/src/rag_chat/application/ports/llm_provider.py` (modify — extend port)

**What to build**:
Add a new protocol alongside the existing `LlmStreamProvider` (do NOT remove or modify the existing protocol — it is used by HyDE expander):

```python
@runtime_checkable
class LlmChatProvider(Protocol):
    """Structured chat interface with optional function calling.

    Used by ChatOrchestratorUseCase tool-use loop.
    Separate from LlmStreamProvider to avoid breaking HyDE and other callers.
    """

    async def chat_with_tools(
        self,
        messages: list[dict],         # OpenAI-format: [{"role": ..., "content": ...}]
        tools: list[dict] | None = None,   # OpenAI tool definitions; None = no tools
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMToolResponse:
        """Non-streaming call. Returns either text or tool_calls. Used for the first
        LLM turn in the tool-use loop where we need to see tool calls before streaming."""
        ...

    def stream_chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        """Streaming chat for the final LLM turn after tools have been executed.
        No tools on this call — the model just generates the final answer."""
        ...
```

**Rationale for non-streaming first turn**: function calls arrive as `delta.tool_calls` in the stream, but the tool call's `arguments` JSON is chunked across many SSE events and must be reassembled. Non-streaming first turn (until `finish_reason`) simplifies argument accumulation and is standard practice in production function-calling pipelines.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_llm_chat_provider_is_runtime_checkable` | Protocol `isinstance` check works | unit |

Minimum: 1 unit test.

---

##### T-W11-1-03: `DeepInfraCompletionAdapter` + `OpenRouterAdapter` function calling
**Type**: impl
**depends_on**: T-W11-1-01, T-W11-1-02
**blocks**: T-W11-3-02
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/llm/deepinfra_adapter.py` (modify)
- `services/rag-chat/src/rag_chat/infrastructure/llm/openrouter_adapter.py` (modify)
- `services/rag-chat/src/rag_chat/infrastructure/llm/ollama_adapter.py` (modify — stub)

**What to build**:

`DeepInfraCompletionAdapter.chat_with_tools()`:
```python
async def chat_with_tools(
    self,
    messages: list[dict],
    tools: list[dict] | None = None,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> LLMToolResponse:
    payload = {
        "model": self._model,
        "messages": messages,
        "stream": False,           # non-streaming for clean tool_calls accumulation
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"   # LLM decides whether to call tools

    # POST to DeepInfra OpenAI-compat endpoint (non-streaming)
    # Parse response.choices[0].message.tool_calls OR .content
    # Map to LLMToolResponse
```

Tool call parsing:
```python
def _parse_tool_calls(self, raw_calls: list[dict]) -> list[ToolUseBlock]:
    """Parse OpenAI-format tool_calls into ToolUseBlock objects."""
    result = []
    for call in raw_calls or []:
        fn = call.get("function", {})
        result.append(ToolUseBlock(
            id=call.get("id", ""),
            name=fn.get("name", ""),
            input=json.loads(fn.get("arguments", "{}")),
        ))
    return result
```

`stream_chat()` — streaming call without tools (final answer turn):
```python
def stream_chat(self, messages: list[dict], *, max_tokens=1024, temperature=0.2) -> AsyncIterator[str]:
    # Uses existing streaming infrastructure but sends messages list instead of prompt
    # payload["messages"] = messages (not [{"role": "user", "content": prompt}])
```

`OllamaAdapter`: add stub implementations that log a warning and raise `NotImplementedError` with message "Ollama function calling not supported — use DeepInfra or OpenRouter for tool-use path".

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_deepinfra_chat_with_tools_sends_tools_in_payload` | `tools` present in HTTP payload when provided | unit (mock HTTP) |
| `test_deepinfra_chat_with_tools_returns_tool_calls` | response with `tool_calls` → `LLMToolResponse.has_tool_calls=True` | unit |
| `test_deepinfra_chat_with_tools_returns_text_on_stop` | response with `content` → `LLMToolResponse.text` set | unit |
| `test_deepinfra_chat_with_no_tools_omits_tools_from_payload` | `tools=None` → no `tools` key in payload | unit |
| `test_openrouter_chat_with_tools_identical_contract` | OpenRouter adapter same behavior as DeepInfra for tool calls | unit (mock HTTP) |
| `test_deepinfra_parse_tool_calls_handles_bad_json_arguments` | malformed `arguments` JSON → empty dict, no exception | unit |

Minimum: 6 unit tests.

**Acceptance criteria**:
- [ ] `tools=None` → no `tools` key in payload (clean backwards compat)
- [ ] Malformed `arguments` JSON → `input={}` with warning log, not exception
- [ ] `OllamaAdapter` raises `NotImplementedError` for `chat_with_tools` (clear error for developers)

---

##### T-W11-1-04: `provider_chain.py` threading + cost tracking
**Type**: impl
**depends_on**: T-W11-1-03
**blocks**: T-W11-3-02
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/llm/provider_chain.py` (modify)

**What to build**:
The `ProviderChain` class currently manages failover between DeepInfra → OpenRouter → Ollama for streaming. It must expose `chat_with_tools()` and `stream_chat()` with the same fallback logic:

```python
async def chat_with_tools(
    self,
    messages: list[dict],
    tools: list[dict] | None = None,
    **kwargs,
) -> LLMToolResponse:
    for provider in self._providers:
        try:
            resp = await provider.chat_with_tools(messages, tools, **kwargs)
            await self._usage_logger.log(resp.usage, provider=provider.name)
            return resp
        except NotImplementedError:
            continue          # skip Ollama if it can't do tool calling
        except Exception as e:
            logger.warning("provider %s failed chat_with_tools: %s", provider.name, e)
            continue
    raise RuntimeError("All LLM providers failed for chat_with_tools")
```

Cost tracking: `resp.usage` from `LLMToolResponse` logged to the existing `UsageLogger` (same as current stream path).

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_provider_chain_skips_ollama_for_tool_calls` | Ollama `NotImplementedError` → chain continues to OpenRouter | unit (mocks) |
| `test_provider_chain_chat_with_tools_logs_usage` | successful call → usage logger called | unit |

Minimum: 2 unit tests.

**Acceptance criteria**:
- [ ] Ollama `NotImplementedError` is caught and causes graceful fallback (not a hard failure)
- [ ] Usage logged for every `chat_with_tools` call that succeeds

---

#### Validation Gate — Wave W11-1
- [ ] `ruff` + `mypy` pass on `libs/tools/` and `services/rag-chat/`
- [ ] 11 new tests pass
- [ ] Existing `LlmStreamProvider` callers unaffected (HyDE expander, etc.)
- [ ] `DeepInfraCompletionAdapter` still passes existing streaming tests
- [ ] **BP-324 prevention test**: `test_deepinfra_adapter_is_instance_of_llm_chat_provider` — asserts `isinstance(DeepInfraCompletionAdapter(...), LlmChatProvider)` is `True`. This test must be added in T-W11-1-03. Its purpose is to make BP-324 impossible to repeat: any future adapter that adds an application-layer feature without updating the adapter will fail this isinstance check at CI time.

#### Break Impact — Wave W11-1
| Broken file | Why | Fix |
|---|---|---|
| Any test that mocks `LlmStreamProvider` | New `LlmChatProvider` protocol added; mocks may fail `isinstance` checks | Ensure mocks that need both implement both; existing stream-only mocks unaffected |
| `services/rag-chat/src/rag_chat/infrastructure/llm/provider_chain.py` | Must implement `LlmChatProvider` | Done by T-W11-1-04 |

#### Regression Guardrails — Wave W11-1
- BP-025 (external I/O timeout): `chat_with_tools()` is a non-streaming HTTP call to DeepInfra. Add `asyncio.wait_for(timeout=self._timeout)` identical to the streaming path.
- Keep `stream()` unchanged — the HyDE expander (`hyde_expander.py`) and existing callers must not break.

---

### Wave W11-2: Expand Tool Catalog (Embedding + Graph + Signals + Portfolio)

**Goal**: Register 8 new tools in `capability_manifest.yaml` and implement their `ToolExecutor` handlers — embedding search, graph traversal, claims, events, contradictions, portfolio context.
**Depends on**: Wave W11-1 (for `ToolUseBlock` types, though `ToolExecutor` handlers are independent)
**Estimated effort**: 75 min
**Architecture layer**: libs (manifest) + S8 application (ToolExecutor handlers)

#### Pre-read
- `libs/tools/capability_manifest.yaml` — current 2-tool manifest (from PLAN-0066 Wave H)
- `libs/tools/tool_registry.py` — `ToolRegistry.register()` API (from PLAN-0066 Wave H)
- `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py` — current S3-only `ToolExecutor` (from PLAN-0066 Wave H)
- `services/rag-chat/src/rag_chat/application/ports/upstream_clients.py` — `S6Port`, `S7Port`, `S1Port` interfaces
- `services/rag-chat/src/rag_chat/application/pipeline/retrieval_orchestrator.py` — how existing fetch methods format `RetrievedItem` objects (copy those formatting patterns)

#### Tasks

##### T-W11-2-01: `capability_manifest.yaml` — 8 new tool entries (R29)
**Type**: config
**depends_on**: none
**blocks**: T-W11-2-02, T-W11-2-03, T-W11-2-04, T-W11-2-05
**Target files**:
- `libs/tools/capability_manifest.yaml` (modify — append 8 entries)

**What to add** (append under existing temporal tools):

```yaml
  - name: search_documents
    description: >
      Searches the platform's document corpus using hybrid BM25 + ANN embedding search.
      Returns text excerpts from news articles, SEC filings (10-K, 10-Q, 8-K), earnings
      call transcripts, and analyst reports. Use for factual questions, news, company
      announcements, and any question requiring text evidence. This is the primary
      retrieval tool for unstructured information.
    parameters:
      - name: query
        type: string
        description: Natural language search query
        required: true
      - name: entity_tickers
        type: array
        description: List of stock tickers to constrain results (e.g. ["AAPL", "MSFT"])
        required: false
      - name: date_from
        type: date
        description: Earliest document date (YYYY-MM-DD). Optional.
        required: false
      - name: date_to
        type: date
        description: Latest document date (YYYY-MM-DD). Optional.
        required: false
      - name: source_types
        type: array
        description: "Filter by source: ['sec_filing', 'earnings', 'news', 'analyst_report']"
        required: false
    trust_weight: 0.80
    example_queries:
      - "What risks does AAPL mention in their latest 10-K?"
      - "What did analysts say about NVDA's data centre revenue?"
      - "What happened to MSFT's stock last week?"

  - name: get_entity_graph
    description: >
      Retrieves the egocentric knowledge graph for a named entity — the entity's
      immediate neighbours, relationships, and their summaries. Use when the question
      asks about connections, subsidiaries, partnerships, board members, or the
      entity's place in a larger structure. Returns nodes and edges with confidence scores.
    parameters:
      - name: entity_name
        type: string
        description: Name of the entity (company, person, fund) to build the graph around
        required: true
      - name: depth
        type: integer
        description: Graph hop depth (1 or 2). Default 1. Use 2 for broader connectivity.
        required: false
      - name: relation_types
        type: array
        description: "Filter by relation type: ['subsidiary_of', 'board_member_of', 'partnership', 'competitor_of']"
        required: false
    trust_weight: 0.85
    example_queries:
      - "What companies is Elon Musk connected to?"
      - "Who are AAPL's main subsidiaries?"
      - "What are TSLA's key partnerships?"

  - name: traverse_graph
    description: >
      Executes a targeted knowledge graph traversal to find multi-hop paths between
      entities. More powerful than get_entity_graph for finding indirect connections,
      competitive relationships, or shared investors. Use when the question requires
      tracing a path or finding how two entities are linked.
    parameters:
      - name: start_entity
        type: string
        description: Starting entity name
        required: true
      - name: target_entity
        type: string
        description: Target entity name to find paths to. Optional — if omitted, explores from start.
        required: false
      - name: depth
        type: integer
        description: Maximum path depth (2-4). Default 3.
        required: false
      - name: cypher_pattern
        type: string
        description: Optional Cypher relationship filter (e.g. "[:INVESTS_IN|:BOARD_MEMBER_OF]")
        required: false
    trust_weight: 0.85
    example_queries:
      - "How is Sam Altman connected to Microsoft?"
      - "What is the investment chain between SoftBank and ARM?"
      - "Are AAPL and MSFT connected through any shared board members?"

  - name: search_entity_relations
    description: >
      Searches for relation triplets involving an entity in the knowledge graph.
      Returns structured (subject, relation_type, object) triples with confidence scores.
      Use for listing what is known about an entity's relationships in structured form.
    parameters:
      - name: entity_name
        type: string
        description: Entity to find relations for
        required: true
      - name: relation_type
        type: string
        description: "Specific relation type to filter: 'invests_in', 'competes_with', 'acquired', etc."
        required: false
      - name: min_confidence
        type: number
        description: Minimum confidence threshold (0.0–1.0). Default 0.6.
        required: false
      - name: limit
        type: integer
        description: Maximum number of relations to return. Default 15.
        required: false
    trust_weight: 0.82
    example_queries:
      - "List all companies that Microsoft has acquired"
      - "Who competes with NVDA in the GPU market?"

  - name: search_claims
    description: >
      Searches for analyst claims and extracted assertions about an entity. Claims are
      LLM-extracted structured statements from financial documents (e.g., "AAPL will
      expand into India"). Use for opinion-type questions, target price questions, or
      when you need to contrast what analysts are saying.
    parameters:
      - name: entity_name
        type: string
        description: Entity the claims are about
        required: true
      - name: claim_type
        type: string
        description: "Type of claim: 'price_target', 'revenue_forecast', 'risk_factor', 'strategic_move'"
        required: false
      - name: date_from
        type: date
        description: Earliest claim extraction date (YYYY-MM-DD)
        required: false
      - name: date_to
        type: date
        description: Latest claim extraction date (YYYY-MM-DD)
        required: false
    trust_weight: 0.78
    example_queries:
      - "What are analysts saying about AAPL's AI strategy?"
      - "What price targets exist for NVDA?"

  - name: search_events
    description: >
      Retrieves structured corporate events involving an entity — earnings releases,
      M&A activity, leadership changes, product launches, regulatory filings. Use for
      timeline or event-based questions.
    parameters:
      - name: entity_name
        type: string
        description: Entity involved in the events
        required: true
      - name: event_type
        type: string
        description: "Event type: 'earnings', 'merger', 'acquisition', 'ipo', 'leadership_change', 'product_launch'"
        required: false
      - name: date_from
        type: date
        description: Earliest event date
        required: false
      - name: date_to
        type: date
        description: Latest event date
        required: false
    trust_weight: 0.82
    example_queries:
      - "When did AAPL last announce a major acquisition?"
      - "What leadership changes happened at Google in 2025?"

  - name: get_contradictions
    description: >
      Retrieves cross-source contradictions detected in analyst claims about an entity.
      Returns pairs of conflicting statements with their strength and sources.
      Use when the question is about disagreement, uncertainty, or conflicting signals.
    parameters:
      - name: entity_name
        type: string
        description: Entity to find contradictions for
        required: true
      - name: confidence_threshold
        type: number
        description: Minimum contradiction strength (0.0–1.0). Default 0.5.
        required: false
    trust_weight: 0.75
    example_queries:
      - "Are there conflicting analyst views on TSLA's profitability?"
      - "What do different sources disagree about regarding AAPL's China exposure?"

  - name: get_portfolio_context
    description: >
      Retrieves the current user's portfolio holdings and watchlist. Use when the
      question references the user's own positions, portfolio P&L, or watchlisted stocks.
      Do NOT call this tool unless the question explicitly references "my portfolio",
      "my holdings", "my watchlist", or similar personal context.
    parameters: []
    trust_weight: 0.92
    example_queries:
      - "How is my portfolio performing today?"
      - "Which of my holdings have the highest exposure to AI?"
```

**Downstream test impact** (R29 enforcement):
- `tests/architecture/test_tool_manifest_sync.py` — after this task, the manifest has 10 entries but only 2 registered handlers (S3 from PLAN-0066). The architecture test will FAIL until T-W11-2-02 through T-W11-2-05 complete. This is expected and must be fixed before Wave W11-2's validation gate.

**Acceptance criteria**:
- [ ] All 8 new entries have `name`, `description`, `parameters`, `trust_weight`, `example_queries`
- [ ] `get_portfolio_context` description explicitly says "Do NOT call unless..." — prevents LLM over-calling

---

##### T-W11-2-02: `ToolExecutor` extended constructor + S6 handler (`search_documents`)
**Type**: impl
**depends_on**: T-W11-2-01
**blocks**: none (parallel-safe with T-W11-2-03, T-W11-2-04, T-W11-2-05)
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py` (modify)

**What to build**:

First, update `ToolExecutor.__init__` to accept all four port clients:
```python
class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        s3: S3Port,
        s6: S6Port,          # NEW
        s7: S7Port,          # NEW
        s1: S1Port,          # NEW
        user_id: UUID | None = None,    # NEW — for portfolio context
        tenant_id: UUID | None = None,  # NEW
        x_internal_token: str | None = None,  # NEW
    ) -> None: ...
```

`_handle_search_documents(query, entity_tickers=None, date_from=None, date_to=None, source_types=None)`:
1. Build `ChunkSearchRequest(query_text=query, top_k=20, date_from=date_from, date_to=date_to)`.
2. If `entity_tickers`: resolve each via `_s3.find_instrument_by_ticker()` → get `instrument_id` list. **Partial resolution**: if some tickers resolve and some don't (unknown tickers return `None`), proceed with the resolved subset — do NOT abort the whole call. Log `log.warning("ticker_not_found", ticker=t)` for each unresolved ticker. Add only the resolved `instrument_id`s to the request filter.
3. Call `_s6.search_chunks(request)` → list of `EnrichedChunkResult`.
4. Format each as `RetrievedItem(content=result.text[:_TOOL_RESULT_MAX_CHARS], item_type=ItemType.chunk, score=result.score, trust_weight=spec.trust_weight, source=result.source_type, title=result.metadata.get("title"), url=result.metadata.get("url"), published_at=result.metadata.get("published_at"))`.
5. Return up to 20 items.

`_TOOL_RESULT_MAX_CHARS = 4000` — class-level constant shared by all handlers. Each `RetrievedItem.content` is truncated to this limit before returning. Prevents context window overflow when multiple tools return large payloads (10 tools × 4000 chars = 40,000 chars max, well within typical LLM context limits).

**Error handling**: if `search_chunks` raises or returns empty, return `[]` (never raise). Log `log.warning("tool_failed", tool="search_documents", error=str(e))`.

**Structured logging** (required on every handler):
```python
t0 = time.monotonic()
# ... handler logic ...
log.info("tool_executed", tool="search_documents", latency_ms=round((time.monotonic()-t0)*1000), items_returned=len(items))
```

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_executor_search_documents_calls_search_chunks` | correct `ChunkSearchRequest` sent to S6 | unit (mock S6) |
| `test_executor_search_documents_maps_to_retrieved_items` | `EnrichedChunkResult` → `RetrievedItem` fields correct | unit |
| `test_executor_search_documents_returns_empty_on_s6_error` | S6 raises → `[]` returned, `tool_failed` warning logged | unit |
| `test_executor_search_documents_with_tickers_resolves_instrument_ids` | ticker provided → `find_instrument_by_ticker` called | unit |
| `test_executor_search_documents_partial_ticker_resolution` | `["AAPL", "UNKNOWN"]` → proceeds with AAPL only, warning logged for UNKNOWN | unit |
| `test_executor_search_documents_content_truncated_at_max_chars` | result.text > 4000 chars → content ≤ 4000 chars in RetrievedItem | unit |

Minimum: 6 unit tests.

---

##### T-W11-2-03: `ToolExecutor` S7 graph traversal handlers (`get_entity_graph`, `traverse_graph`)
**Type**: impl
**depends_on**: T-W11-2-01
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py` (modify)

**What to build**:

`_handle_get_entity_graph(entity_name, depth=1, relation_types=None)`:
1. Resolve entity_name → entity_id via `_s7.search_relations(entity_name, top_k=1)` → get first result's entity_id. If not found: return `[]`.
2. Call `_s7.get_egocentric_graph(entity_id, depth=depth)` → `EgocentricGraph`.
3. Format as a text summary:
   ```
   Knowledge Graph for {entity_name} (depth {depth}):
   Nodes: {node_count} entities
   Edges:
   - {subject} --[{relation_type} (conf: {confidence:.2f})]→ {object}: {summary}
   ...
   ```
4. Return 1 `RetrievedItem(content=summary_text, item_type=ItemType.relation, trust_weight=spec.trust_weight)`.

`_handle_traverse_graph(start_entity, target_entity=None, depth=3, cypher_pattern=None)`:
1. Resolve `start_entity` → entity_id.
2. **Cypher injection guard** (CRITICAL — R-001): the `cypher_pattern` parameter is set by the LLM. An unconstrained pattern like `[:DETACH DELETE n]` or arbitrary Cypher could corrupt the graph. Validate against an allowlist:
   ```python
   _ALLOWED_CYPHER_REL_TYPES: frozenset[str] = frozenset({
       "INVESTS_IN", "BOARD_MEMBER_OF", "SUBSIDIARY_OF",
       "COMPETES_WITH", "PARTNERSHIP", "ACQUIRED", "FOUNDER_OF",
       "SUPPLIES_TO", "REGULATES", "LISTED_ON",
   })

   def _sanitize_cypher_pattern(self, pattern: str | None) -> str | None:
       """Strip any relationship type not in the allowlist. If no valid types remain, return None."""
       if pattern is None:
           return None
       # Extract rel type tokens from pattern like "[:INVESTS_IN|:BOARD_MEMBER_OF]"
       tokens = re.findall(r':([A-Z_]+)', pattern)
       allowed = [t for t in tokens if t in _ALLOWED_CYPHER_REL_TYPES]
       if not allowed:
           log.warning("cypher_pattern_rejected", pattern=pattern, reason="no_allowlisted_rel_types")
           return None
       return "[:" + "|:".join(allowed) + "]"
   ```
3. Build Cypher query using sanitized pattern only: if `target_entity` provided → path query; else → exploration from start.
4. Call `_s7.cypher_traverse(entity_id, depth, sanitized_pattern)`.
5. Format paths as numbered list. Truncate to `_TOOL_RESULT_MAX_CHARS`.
6. Return 1 `RetrievedItem(content=result_text[:_TOOL_RESULT_MAX_CHARS], item_type=ItemType.cypher_path)`.

**Structured logging**:
```python
log.info("tool_executed", tool="traverse_graph", latency_ms=..., paths_found=N, depth=depth)
```

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_executor_get_entity_graph_formats_nodes_and_edges` | graph result → RetrievedItem with relation counts in text | unit |
| `test_executor_get_entity_graph_returns_empty_on_unknown_entity` | entity not found → `[]` | unit |
| `test_executor_traverse_graph_calls_cypher` | `cypher_traverse` called with correct args | unit (mock S7) |
| `test_executor_traverse_graph_returns_empty_on_s7_error` | S7 raises → `[]` | unit |
| `test_executor_traverse_graph_rejects_disallowed_cypher_pattern` | `cypher_pattern="[:DELETE n]"` → pattern sanitized to `None`, `cypher_pattern_rejected` warning logged | unit |
| `test_executor_traverse_graph_allows_known_rel_types` | `cypher_pattern="[:INVESTS_IN|:BOARD_MEMBER_OF]"` → pattern passes allowlist unchanged | unit |
| `test_executor_traverse_graph_partial_allowlist` | `cypher_pattern="[:INVESTS_IN|:UNKNOWN_REL]"` → only `INVESTS_IN` retained | unit |
| `test_executor_get_entity_graph_content_truncated` | large graph → content ≤ 4000 chars | unit |

Minimum: 8 unit tests.

---

##### T-W11-2-04: `ToolExecutor` S7 signals handlers (`search_entity_relations`, `search_claims`, `search_events`, `get_contradictions`)
**Type**: impl
**depends_on**: T-W11-2-01
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py` (modify)

**What to build**:

Each handler follows the same pattern: call the corresponding S7 port method, format results as a text list, return `list[RetrievedItem]`. Every handler **must** emit structured logs and truncate content to `_TOOL_RESULT_MAX_CHARS`.

`_handle_search_entity_relations(entity_name, relation_type=None, min_confidence=0.6, limit=15)`:
- Call `_s7.search_relations(entity_name, relation_type, min_confidence, top_k=limit)`.
- Format: `"{subject} --[{relation_type}]→ {object} (confidence: {conf:.2f})\n  {summary}"`.
- Truncate each item's content to `_TOOL_RESULT_MAX_CHARS`.
- Return 1 `RetrievedItem(item_type=ItemType.relation)` per result, up to `limit`.
- Log: `log.info("tool_executed", tool="search_entity_relations", latency_ms=..., items_returned=N)` or `log.warning("tool_failed", ...)` on exception.

`_handle_search_claims(entity_name, claim_type=None, date_from=None, date_to=None)`:
- Call `_s7.search_claims(entity_name, claim_type, date_from, date_to)`.
- Format: `"[{polarity}] {claim_type}: {text} (confidence: {conf:.2f}, date: {date})"`.
- Return 1 `RetrievedItem(item_type=ItemType.claim)` per result, content truncated.
- Log `tool_executed` / `tool_failed`.

`_handle_search_events(entity_name, event_type=None, date_from=None, date_to=None)`:
- Call `_s7.search_events(entity_name, event_type, date_from, date_to)`.
- Format: `"{event_date}: [{event_type}] {event_text}"`.
- Return 1 `RetrievedItem(item_type=ItemType.event)` per result, content truncated.
- Log `tool_executed` / `tool_failed`.

`_handle_get_contradictions(entity_name, confidence_threshold=0.5)`:
- Call `_s7.get_contradictions(entity_name, confidence_threshold)`.
- Format each contradiction as a paired statement block.
- Return 1 `RetrievedItem` per contradiction pair, content truncated.
- Log `tool_executed` / `tool_failed`.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_executor_search_relations_formats_triplets` | relation result → RetrievedItem with subject/object in text | unit |
| `test_executor_search_claims_returns_empty_on_s7_error` | S7 raises → `[]`, no exception, `tool_failed` logged | unit |
| `test_executor_search_events_date_filter_passed` | `date_from`/`date_to` forwarded to S7Port call | unit |
| `test_executor_get_contradictions_formats_sides` | contradiction → RetrievedItem with both sides' text | unit |
| `test_executor_signals_handlers_log_tool_executed` | successful handler → `tool_executed` log emitted with `items_returned` | unit |

Minimum: 5 unit tests.

---

##### T-W11-2-05: `ToolExecutor` S1 handler (`get_portfolio_context`)
**Type**: impl
**depends_on**: T-W11-2-01
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/tool_executor.py` (modify)

**What to build**:

`_handle_get_portfolio_context()`:
1. If `self._user_id` is None (no auth context): return `[]` (anonymous sessions have no portfolio).
2. Call `_s1.get_portfolio_context(self._user_id, self._tenant_id, self._x_internal_token)`.
3. Format: list holdings (ticker, market_value, unrealized_pnl) + watchlist tickers as a compact text block. Truncate to `_TOOL_RESULT_MAX_CHARS`.
4. Return 1 `RetrievedItem(item_type=ItemType.financial, trust_weight=0.92, content=text[:_TOOL_RESULT_MAX_CHARS])`.

**Privacy / R14 compliance**: portfolio holdings are PII (specific monetary positions of a real user). The structured log for this handler MUST NOT include tickers, market values, or P&L figures:
```python
# CORRECT — safe to log:
log.info("tool_executed", tool="get_portfolio_context", latency_ms=..., holding_count=N, watchlist_count=M)

# PROHIBITED — never log these:
# log.info(..., tickers=[h.ticker for h in holdings], total_value=portfolio.total_value)
```
The formatted `RetrievedItem.content` (which contains holdings) flows to the LLM — this is intentional and necessary. But it must never appear in log output.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_executor_portfolio_returns_empty_when_no_user` | `user_id=None` → `[]` without calling S1 | unit |
| `test_executor_portfolio_formats_holdings_and_watchlist` | holdings + watchlist → RetrievedItem with both sections | unit |
| `test_executor_portfolio_returns_empty_on_s1_error` | S1 raises → `[]`, `tool_failed` warning logged | unit |
| `test_executor_portfolio_log_does_not_contain_tickers` | log record for `get_portfolio_context` → no ticker names, no market values | unit (log capture) |

Minimum: 4 unit tests.

---

#### Validation Gate — Wave W11-2
- [ ] `ruff` + `mypy` pass
- [ ] 23 new tests pass (6 from T-W11-2-02 + 8 from T-W11-2-03 + 5 from T-W11-2-04 + 4 from T-W11-2-05)
- [ ] Architecture test `test_tool_manifest_sync.py` passes — all 10 manifest entries have registered handlers
- [ ] Existing S6/S7/S1 port tests unaffected (handlers only wrap, do not modify ports)
- [ ] `test_executor_traverse_graph_rejects_disallowed_cypher_pattern` passes — injection guard in place
- [ ] `test_executor_portfolio_log_does_not_contain_tickers` passes — R14 privacy compliance verified

#### Break Impact — Wave W11-2
| Broken file | Why | Fix |
|---|---|---|
| `services/rag-chat/src/rag_chat/infrastructure/wiring/dependencies.py` | `ToolExecutor` constructor gains `s6`, `s7`, `s1`, user-auth args | update dependency injection to pass all four ports |
| `tests/architecture/test_tool_manifest_sync.py` | manifest has 10 entries but only 2 were registered (PLAN-0066); now 10 handlers registered | passes after T-W11-2-02..T-W11-2-05 are complete |

#### Regression Guardrails — Wave W11-2
- BP-025 (external I/O timeout): all new handler methods wrap S6/S7/S1 calls in `asyncio.wait_for(timeout=self._timeout)` — same pattern as existing `_handle_get_price_history`.
- R29: `capability_manifest.yaml` updated in T-W11-2-01 before handlers written in T-W11-2-02..05 — manifest is always the spec, not the code.
- **Circuit breakers**: the existing `ParallelRetrievalOrchestrator` uses `self._cbs` (per-source circuit breaker dict) to prevent hammering a degraded upstream. `ToolExecutor` calls the same ports (S6, S7, S1) but does NOT yet integrate circuit breakers. For this plan, `asyncio.wait_for(timeout=5.0)` + `except Exception → return []` provides sufficient protection. **Post-PLAN-0067 work item**: integrate `ToolExecutor` with the same `CircuitBreaker` infrastructure as `ParallelRetrievalOrchestrator` to prevent repeated tool calls to a known-degraded source from adding latency per query. Track in TRACKING.md as a tech-debt item.
- **Cypher injection** (T-W11-2-03): the `_ALLOWED_CYPHER_REL_TYPES` allowlist in `_sanitize_cypher_pattern` must be updated whenever new relationship types are added to the Neo4j schema. Treat it as a security-critical constant — changes require code review.

---

### Wave W11-3: ChatOrchestrator Full Tool-Use Migration

**Goal**: Migrate `ChatOrchestratorUseCase` to use the tool-use path for ALL queries, behind `TOOL_USE_ENABLED` feature flag. Add SSE tool-call events. Gate the classical pipeline as the fallback path.
**Depends on**: Wave W11-1 (`LlmChatProvider` port), Wave W11-2 (`ToolExecutor` with all handlers)
**Estimated effort**: 75 min
**Architecture layer**: S8 application / config

#### Pre-read
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` — full orchestrator (453 lines)
- `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py` — current 7 event types
- `services/rag-chat/src/rag_chat/infrastructure/config/settings.py` — how feature flags / env vars are added

#### Tasks

##### T-W11-3-01: `SSEEmitter` — `tool_call` + `tool_result` event types
**Type**: impl
**depends_on**: none
**blocks**: T-W11-3-02
**Target files**:
- `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py` (modify)

**What to build**:
```python
def emit_tool_call(
    self,
    tool_name: str,
    input_summary: dict,    # safe subset of input — no PII
    status: str = "running",
) -> dict[str, str]:
    """Emitted before tool execution starts. Frontend uses this for spinner."""
    return {
        "event": "tool_call",
        "data": json.dumps({
            "tool": tool_name,
            "label": _TOOL_LABELS.get(tool_name, tool_name),  # user-friendly label
            "status": status,
        }),
    }

def emit_tool_result(
    self,
    tool_name: str,
    status: str,            # "ok" | "error" | "empty"
    item_count: int = 0,
) -> dict[str, str]:
    """Emitted after tool execution completes. Frontend uses this to close spinner."""
    return {
        "event": "tool_result",
        "data": json.dumps({
            "tool": tool_name,
            "status": status,
            "item_count": item_count,
        }),
    }

_TOOL_LABELS: dict[str, str] = {
    "search_documents":        "Searching documents...",
    "get_entity_graph":        "Building entity map...",
    "traverse_graph":          "Traversing knowledge graph...",
    "search_entity_relations": "Mapping relationships...",
    "search_claims":           "Checking analyst claims...",
    "search_events":           "Looking up corporate events...",
    "get_contradictions":      "Detecting contradictions...",
    "get_portfolio_context":   "Loading portfolio context...",
    "get_price_history":       "Fetching price history...",
    "get_fundamentals_history":"Fetching fundamentals...",
}
```

`input_summary` deliberately excludes sensitive fields — log only tool name + label in the event (not the full query parameters that might contain PII).

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_sse_tool_call_event_has_label` | known tool_name → `label` set to user-friendly string | unit |
| `test_sse_tool_call_unknown_tool_uses_name_as_label` | unknown tool → `label = tool_name` | unit |
| `test_sse_tool_result_event_has_item_count` | `item_count=5` → data contains `"item_count": 5` | unit |

Minimum: 3 unit tests.

---

##### T-W11-3-02: `TOOL_USE_ENABLED` config + `ChatOrchestratorUseCase._tool_use_path()`
**Type**: impl
**depends_on**: T-W11-1-04, T-W11-2-02, T-W11-3-01
**blocks**: none
**Target files**:
- `services/rag-chat/src/rag_chat/infrastructure/config/settings.py` (modify — add `tool_use_enabled: bool = False`)
- `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` (modify — add `_tool_use_path()`)

**What to build**:

Add to `Settings`:
```python
tool_use_enabled: bool = Field(default=False, alias="TOOL_USE_ENABLED")
```

In `ChatOrchestratorUseCase`, add `_tool_use_path()` private async method:
```python
async def _tool_use_path(
    self,
    request: ChatRequest,
    messages: list[dict],           # system + history + user turn
    resolved_entities: list,
    sse: SSEEmitter,
) -> AsyncIterator[dict]:
    """
    Full tool-use path:
    Step 1. Build tool definitions from ToolRegistry.
    Step 2. First LLM turn (non-streaming) → LLMToolResponse.
    Step 3. If tool_calls: emit tool_call SSE events → execute tools → emit tool_result events.
    Step 4. Inject tool results into messages as tool_result turns.
    Step 5. Apply reranking to collected RetrievedItems.
    Step 6. Second LLM turn (streaming) → yield token SSE events.
    Step 7. Output processing → yield citations, metadata, done events.
    """
    tool_definitions = self._tool_registry.to_openai_tool_definitions()

    # Step 2: First turn
    yield sse.emit_status("tool_classification")
    response = await self._llm.chat_with_tools(messages, tool_definitions)

    all_retrieved_items: list[RetrievedItem] = []

    # Step 3: Execute tools
    if response.has_tool_calls:
        # Handle preamble text: OpenAI format allows content + tool_calls in the same response.
        # If the LLM prefaced its tool calls with text (e.g. "Let me check the data..."),
        # prepend it to the final answer rather than discarding it.
        preamble_text: str | None = response.text if response.text else None

        for tool_call in response.tool_calls:
            yield sse.emit_tool_call(tool_call.name, {})

        tool_items_list = await self._tool_executor.execute_all(response.tool_calls)

        for i, call in enumerate(response.tool_calls):
            item = tool_items_list[i] if i < len(tool_items_list) else None
            yield sse.emit_tool_result(
                call.name,
                status="ok" if item else "empty",
                item_count=1 if item else 0,
            )

        non_none_items = [i for i in tool_items_list if i is not None]

        # All-tools-failed guard: if every tool returned None/empty, the second LLM turn
        # would have zero tool context and WILL hallucinate. Fall back to classical path.
        if not non_none_items:
            log.warning(
                "all_tools_failed",
                tool_count=len(response.tool_calls),
                tools=[tc.name for tc in response.tool_calls],
                query_preview=request.query[:100],
            )
            yield sse.emit_status("fallback_classical")
            # Return without a second LLM turn — the caller will stream the classical
            # pipeline context as the final answer.
            return

        all_retrieved_items.extend(non_none_items)

        # Step 4: Inject tool results into messages.
        # Token budget: each item's content is already capped at _TOOL_RESULT_MAX_CHARS (4000)
        # by ToolExecutor. This guard is a second-line check — if somehow a large content
        # slips through, truncate here before injecting into the LLM context.
        _MSG_CONTENT_MAX_CHARS = 4000
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [tc.__dict__ for tc in response.tool_calls],
        })
        for call, item in zip(response.tool_calls, tool_items_list):
            raw_content = item.content if item else "No results found."
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": raw_content[:_MSG_CONTENT_MAX_CHARS],
            })

    elif response.text:
        # LLM returned text directly (no tool calls) — this is a "stop" turn.
        # Proceed to Step 6 with just the text.
        preamble_text = None
    else:
        # finish_reason == "length" or unknown — log and degrade gracefully.
        log.warning("llm_unexpected_finish_reason", finish_reason=response.finish_reason)
        return

    log.info(
        "tool_use_path_first_turn_complete",
        tools_called=len(response.tool_calls) if response.has_tool_calls else 0,
        items_retrieved=len(all_retrieved_items),
    )

    # Step 5: Rerank
    if all_retrieved_items:
        all_retrieved_items = await self._reranker.rerank(
            query=request.query, items=all_retrieved_items
        )

    # Step 6: Second LLM turn (streaming)
    yield sse.emit_status("generating")
    if preamble_text:
        # Stream the preamble text first so it's not lost.
        for char in preamble_text:
            yield sse.emit_token(char)
    async for token in self._llm.stream_chat(messages):
        yield sse.emit_token(token)

    # Step 7: Output processing (citations, metadata, done)
    # ... (same as classical path output processing)
```

In `execute_streaming()` / `execute_sync()`, add the feature-flag branch:
```python
if self._config.tool_use_enabled and self._tool_executor is not None:
    async for event in self._tool_use_path(request, messages, resolved_entities, sse):
        yield event
    return
# Existing classical pipeline follows unchanged
```

**Cap**: tool loop max 3 turns (up from 2 in PLAN-0066 MVP) — allows the LLM to call tools, receive results, and potentially request one more clarifying tool call before final answer.

**Unknown tool name guard**: `ToolExecutor.execute()` already logs `unknown_tool_name` warning (see T-W11-2-02). The orchestrator additionally detects this via SSE: if a `tool_call` SSE event is followed by a `tool_result` with `status="empty"` for an unrecognized name, it is visible in the SSE stream for debugging.

**Structured logging summary**:
```python
log.info("tool_use_path_start", query_len=len(request.query), tool_count=len(tool_definitions))
# ... first turn ...
log.info("tool_use_path_first_turn_complete", tools_called=N, items_retrieved=K)
# ... if all failed ...
log.warning("all_tools_failed", tool_count=N, tools=[...], query_preview=...)
# ... second turn ...
log.info("tool_use_path_complete", total_items=K, latency_ms=X)
```

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_orchestrator_tool_use_disabled_follows_classical_path` | `tool_use_enabled=False` → `_tool_use_path` never called | unit (mock) |
| `test_orchestrator_tool_use_enabled_calls_tool_use_path` | `tool_use_enabled=True` → classical pipeline skipped | unit (mock) |
| `test_orchestrator_tool_calls_emit_tool_call_events` | LLM emits tool_use → `tool_call` SSE event yielded | unit (mock LLM) |
| `test_orchestrator_tool_results_injected_into_messages` | after execute_all → tool_result turn added to messages | unit |
| `test_orchestrator_tool_use_path_applies_reranking` | retrieved items from tools → reranker called | unit |
| `test_orchestrator_all_tools_failed_returns_early` | all execute_all items None → `all_tools_failed` warning, second LLM turn NOT called | unit |
| `test_orchestrator_preamble_text_streamed_before_answer` | `response.text="Let me check..."` + `response.has_tool_calls=True` → preamble tokens yielded first | unit |
| `test_orchestrator_tool_result_content_capped_at_4000_chars` | item.content > 4000 chars → message content ≤ 4000 chars | unit |
| `test_orchestrator_logs_tool_use_path_complete` | successful path → `tool_use_path_complete` log emitted | unit (log capture) |

Minimum: 9 unit tests.

**Acceptance criteria**:
- [ ] `TOOL_USE_ENABLED=false` (default) → classical pipeline completely unchanged
- [ ] `TOOL_USE_ENABLED=true` → tool loop runs; IntentClassifier + RetrievalPlanBuilder skipped
- [ ] Tool loop cap at 3 LLM turns (not infinite)
- [ ] All-tools-failed → `all_tools_failed` warning logged, second LLM turn NOT called (no hallucination on empty context)
- [ ] Preamble text (`response.text` set alongside tool_calls) → streamed to user, not discarded
- [ ] Tool result content in messages capped at 4000 chars (context budget enforced)
- [ ] `tool_use_path_complete` log emitted on every successful path (observable in prod)

---

##### T-W11-3-03: Metrics update + dev env config
**Type**: config + impl
**depends_on**: T-W11-3-02
**blocks**: none
**Target files**:
- `env/dev/rag-chat.env` (modify — add `TOOL_USE_ENABLED=true` for dev)
- `env/dev/rag-chat.env.example` (modify — document the variable)
- `services/rag-chat/src/rag_chat/application/metrics/` (modify — add tool-use metrics)

**What to build**:

New Prometheus metrics (alongside existing intent-based metrics):
```python
tool_call_total = Counter(
    "rag_tool_call_total",
    "Number of tool calls executed",
    ["tool_name", "status"],   # status: "ok" | "empty" | "error"
)
tool_call_latency_seconds = Histogram(
    "rag_tool_call_latency_seconds",
    "Tool call execution latency",
    ["tool_name"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
tool_use_path_total = Counter(
    "rag_tool_use_path_total",
    "Requests handled by tool-use path vs classical path",
    ["path"],    # "tool_use" | "classical"
)
```

Emit these from `ToolExecutor.execute()` and `ChatOrchestratorUseCase`.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_tool_call_total_incremented_on_success` | successful execute → `tool_call_total` counter incremented | unit |
| `test_tool_use_path_total_classical_when_disabled` | `tool_use_enabled=False` → `path="classical"` recorded | unit |

Minimum: 2 unit tests.

**Acceptance criteria**:
- [ ] `TOOL_USE_ENABLED` documented in `rag-chat.env.example` with default `false` and explanation
- [ ] `env/dev/rag-chat.env` has `TOOL_USE_ENABLED=true` so dev environment tests tool-use path

---

#### Validation Gate — Wave W11-3
- [ ] `ruff` + `mypy` pass
- [ ] 14 new tests pass (3 from T-W11-3-01 + 9 from T-W11-3-02 + 2 from T-W11-3-03)
- [ ] Existing 50-query golden set (PLAN-0063 Wave W5-1) still passes with `TOOL_USE_ENABLED=false` — classical pipeline unchanged
- [ ] `TOOL_USE_ENABLED=false` → `tool_use_path` never called in any test
- [ ] `TOOL_USE_ENABLED=true` → SSE stream contains `tool_call` events for appropriate queries
- [ ] `test_orchestrator_all_tools_failed_returns_early` passes — hallucination on zero context is blocked

#### Break Impact — Wave W11-3
| Broken file | Why | Fix |
|---|---|---|
| `services/rag-chat/tests/unit/use_cases/test_chat_orchestrator.py` | new `tool_use_enabled` config field; new `_tool_executor` constructor arg | pass `tool_use_enabled=False` in fixtures; pass `tool_executor=None` |
| `services/rag-chat/src/rag_chat/infrastructure/wiring/dependencies.py` | `ChatOrchestratorUseCase` constructor gains `tool_executor` + `llm_chat` args | wire in new providers |

#### Regression Guardrails — Wave W11-3
- The feature flag default is `False`. Every existing test runs with the classical pipeline unless the test explicitly sets `tool_use_enabled=True`. This is the hard safety net for regression prevention.
- `TOOL_USE_ENABLED=false` must be verified in CI — do not set it to `true` in test fixtures by default.
- **All-tools-failed**: the `all_tools_failed` guard prevents the single most dangerous failure mode — the LLM answering financial questions with no retrieved context. Any future refactor of `_tool_use_path()` must preserve this guard. The test `test_orchestrator_all_tools_failed_returns_early` is the enforcement mechanism — never skip or delete it (R19).
- **Token budget**: the `_MSG_CONTENT_MAX_CHARS = 4000` limit in Step 4 is a second-line defence after `ToolExecutor`'s per-handler truncation. If either limit is changed, update both and adjust the test.

---

### Wave W11-4: Integration Tests + Golden Eval for Tool-Use Path

**Goal**: Validate that the tool-use path produces valid responses for representative queries, with embedding search and graph traversal tools being called for appropriate question types.
**Depends on**: Wave W11-3 complete
**Estimated effort**: 60 min
**Architecture layer**: integration test + eval

#### Pre-read
- `tests/eval/golden/` — existing 50-query golden set (PLAN-0063 Wave W5-1)
- `scripts/eval_retrieval.py` — existing eval harness
- `services/rag-chat/tests/integration/` — existing integration test patterns

#### Tasks

##### T-W11-4-01: Tool-use golden eval (20 queries)
**Type**: test
**depends_on**: none
**blocks**: none
**Target files**:
- `tests/eval/golden/tool_use_queries.json` (new — 20 labeled queries for tool-use path)
- `scripts/eval_tool_use.py` (new — tool-use eval harness)

**What to build**:

20 representative queries with expected tool calls and expected answer properties:
```json
[
  {
    "query": "What risks does Apple mention in their latest 10-K?",
    "expected_tools": ["search_documents"],
    "expected_source_types": ["sec_filing"],
    "min_retrieved_items": 3,
    "label": "factual_lookup"
  },
  {
    "query": "How is Sam Altman connected to Microsoft?",
    "expected_tools": ["traverse_graph", "get_entity_graph"],
    "min_retrieved_items": 1,
    "label": "relationship"
  },
  {
    "query": "What are conflicting analyst views on Tesla's profitability?",
    "expected_tools": ["search_claims", "get_contradictions"],
    "min_retrieved_items": 2,
    "label": "signal_intel"
  },
  {
    "query": "How has AAPL's revenue trended over 8 quarters?",
    "expected_tools": ["get_fundamentals_history"],
    "label": "temporal"
  },
  ...
]
```

Eval harness `eval_tool_use.py`:
- Runs each query through `ChatOrchestratorUseCase` with `tool_use_enabled=True`
- Captures which tools were called (from SSE `tool_call` events)
- Asserts `expected_tools ⊆ actual_tools_called` (subset — LLM may call more)
- Asserts `min_retrieved_items` met
- Reports tool use rate per query type

**Acceptance criteria**:
- [ ] 18/20 queries (90%) produce a valid non-empty answer
- [ ] For "relationship" queries: `traverse_graph` or `get_entity_graph` called in ≥80% of cases
- [ ] For "factual_lookup" queries: `search_documents` called in ≥90% of cases

---

##### T-W11-4-02: Multi-tool integration tests
**Type**: test
**depends_on**: none
**blocks**: none
**Target files**:
- `services/rag-chat/tests/integration/test_tool_use_orchestrator.py` (new)

**Integration tests** (require running S6/S7/S3/S1 mocks or a test container):

| Test | What it verifies | Type |
|---|---|---|
| `test_factual_query_calls_search_documents` | "What did AAPL announce?" → `search_documents` in tool calls | integration (mock S6) |
| `test_relationship_query_calls_graph_tool` | "How is X connected to Y?" → `traverse_graph` or `get_entity_graph` | integration (mock S7) |
| `test_temporal_query_calls_price_history` | "AAPL last 3 months price" → `get_price_history` | integration (mock S3) |
| `test_portfolio_query_calls_portfolio_tool` | "How is my portfolio?" → `get_portfolio_context` | integration (mock S1) |
| `test_multi_tool_query_calls_multiple_tools` | "What risks for AAPL and how connected to suppliers?" → multiple tools | integration |
| `test_classical_path_unaffected_when_flag_off` | `tool_use_enabled=False` → no `tool_call` SSE events | integration |

Minimum: 6 integration tests.

---

##### T-W11-4-03: Tool use observability report
**Type**: test
**depends_on**: T-W11-4-01
**blocks**: none
**Target files**:
- `scripts/eval_tool_use.py` (modify — add reporting section)

Add a tool usage breakdown report to the eval harness output:
```
Tool Use Rate Analysis (20 queries):
  search_documents:       18/20 (90%)   ← embedding search — core differentiator
  get_entity_graph:        6/20 (30%)   ← graph tools
  traverse_graph:          4/20 (20%)
  search_claims:           5/20 (25%)
  get_price_history:       3/20 (15%)
  get_portfolio_context:   1/20 (5%)    ← only on portfolio question
  get_fundamentals_history: 2/20 (10%)
```

Assert that `get_portfolio_context` is called ≤ 2/20 times (over-calling = bad tool description).

**Acceptance criteria**:
- [ ] `search_documents` called in ≥ 85% of queries (it should be the most-called tool)
- [ ] `get_portfolio_context` called in ≤ 10% of queries (prompt engineering working correctly)

---

#### Validation Gate — Wave W11-4
- [ ] All 6 integration tests pass (mocked or containerized)
- [ ] 20-query eval: ≥ 18/20 produce valid responses
- [ ] Tool use rates within acceptable bounds (search_documents ≥ 85%, portfolio ≤ 10%)
- [ ] Existing 50-query classical eval still passes (with `tool_use_enabled=False`)

#### Break Impact — Wave W11-4
None — Wave W11-4 only adds new test files.

#### Regression Guardrails — Wave W11-4
- Eval queries must be representative of the thesis demo scenarios (portfolio questions, KG traversal, news lookup, temporal queries) — not just contrived edge cases.

---

### Wave W11-5: Frontend Tool-Call Progress UI

**Goal**: Show tool execution progress in the chat UI — spinners per active tool, user-friendly labels, completion signals.
**Depends on**: Wave W11-3 (SSE `tool_call`/`tool_result` events wired)
**Estimated effort**: 60 min
**Architecture layer**: worldview-web frontend

#### Pre-read
- `apps/worldview-web/features/chat/hooks/useChatStream.ts` — SSE event consumption hook (from PLAN-0059 Wave E-3-followup)
- `apps/worldview-web/features/chat/components/` — existing chat components (MessageBubble, StreamingBubble, etc.)
- `apps/worldview-web/app/(app)/chat/page.tsx` — chat page layout

#### Tasks

##### T-W11-5-01: `ToolCallIndicator` component
**Type**: impl
**depends_on**: none
**blocks**: T-W11-5-03
**Target files**:
- `apps/worldview-web/features/chat/components/ToolCallIndicator.tsx` (new)
- `apps/worldview-web/features/chat/components/__tests__/ToolCallIndicator.test.tsx` (new)

**What to build**:

```tsx
interface ToolCallIndicatorProps {
  tools: { name: string; label: string; status: "running" | "ok" | "empty" | "error" }[];
}

export function ToolCallIndicator({ tools }: ToolCallIndicatorProps) {
  const running = tools.filter(t => t.status === "running");
  const done = tools.filter(t => t.status !== "running");

  if (tools.length === 0) return null;

  return (
    <div className="flex flex-col gap-1 text-xs text-muted-foreground font-mono">
      {running.map(t => (
        <div key={t.name} className="flex items-center gap-2">
          <Loader2 className="h-3 w-3 animate-spin" />
          <span>{t.label}</span>
        </div>
      ))}
      {done.map(t => (
        <div key={t.name} className="flex items-center gap-2">
          {t.status === "ok" ? <Check className="h-3 w-3 text-green-500" />
                              : <X className="h-3 w-3 text-muted-foreground" />}
          <span className="line-through opacity-60">{t.label.replace("...", "")}</span>
        </div>
      ))}
    </div>
  );
}
```

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_tool_call_indicator_renders_running_spinner` | running tool → Loader2 icon + label | vitest |
| `test_tool_call_indicator_renders_completed_state` | status="ok" → Check icon + line-through text | vitest |
| `test_tool_call_indicator_returns_null_for_empty_tools` | `tools=[]` → renders nothing | vitest |

Minimum: 3 vitest tests.

---

##### T-W11-5-02: `useChatStream` — consume `tool_call` / `tool_result` events
**Type**: impl
**depends_on**: none
**blocks**: T-W11-5-03
**Target files**:
- `apps/worldview-web/features/chat/hooks/useChatStream.ts` (modify)

**What to build**:

Extend the SSE event handler to consume `tool_call` and `tool_result` events:

```typescript
// New state
const [activeTools, setActiveTools] = useState<ToolCallState[]>([]);

// SSE handler additions
case "tool_call": {
  const data = JSON.parse(event.data) as { tool: string; label: string; status: string };
  setActiveTools(prev => [
    ...prev.filter(t => t.name !== data.tool),
    { name: data.tool, label: data.label, status: "running" },
  ]);
  break;
}
case "tool_result": {
  const data = JSON.parse(event.data) as { tool: string; status: string; item_count: number };
  setActiveTools(prev => prev.map(t =>
    t.name === data.tool ? { ...t, status: data.status } : t
  ));
  break;
}
case "done": {
  setActiveTools([]);   // clear tool indicators when stream completes
  break;
}
```

New public return: `activeTools: ToolCallState[]` — exposed to the chat page for rendering.

```typescript
interface ToolCallState {
  name: string;
  label: string;
  status: "running" | "ok" | "empty" | "error";
}
```

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_useChatStream_tool_call_event_adds_to_active_tools` | SSE `tool_call` event → `activeTools` gains an entry | vitest |
| `test_useChatStream_tool_result_updates_status` | SSE `tool_result` event → matching entry status updated | vitest |
| `test_useChatStream_done_clears_active_tools` | SSE `done` event → `activeTools` cleared | vitest |

Minimum: 3 vitest tests.

---

##### T-W11-5-03: Chat page wiring — `ToolCallIndicator` in `StreamingBubble`
**Type**: impl
**depends_on**: T-W11-5-01, T-W11-5-02
**blocks**: none
**Target files**:
- `apps/worldview-web/app/(app)/chat/page.tsx` (modify — pass `activeTools` to `StreamingBubble`)
- `apps/worldview-web/features/chat/components/StreamingBubble.tsx` (modify — render `ToolCallIndicator`)

**What to build**:

In `page.tsx`: destructure `activeTools` from `useChatStream` and pass to `StreamingBubble`.

In `StreamingBubble.tsx`:
```tsx
// Show tool indicators above the streaming text
{activeTools.length > 0 && (
  <ToolCallIndicator tools={activeTools} />
)}
{streamText && <MarkdownContent content={streamText} />}
```

The `ToolCallIndicator` appears ABOVE the streaming text so the user sees which tools are running BEFORE the answer starts flowing.

**Tests to write**:
| Test | What it verifies | Type |
|---|---|---|
| `test_streaming_bubble_renders_tool_indicator_when_tools_active` | `activeTools.length > 0` → `ToolCallIndicator` rendered | vitest |
| `test_streaming_bubble_hides_tool_indicator_when_empty` | `activeTools=[]` → no `ToolCallIndicator` rendered | vitest |

Minimum: 2 vitest tests.

**Acceptance criteria**:
- [ ] Tool spinners appear in the chat bubble BEFORE the first text token arrives
- [ ] Completed tools show a strikethrough label (done signal, not just disappear)
- [ ] All existing chat tests pass (streaming, citations, metadata — unchanged)

---

#### Validation Gate — Wave W11-5
- [ ] `pnpm vitest` — all 8 new tests pass; no regressions (1354+ tests green)
- [ ] `pnpm build` succeeds
- [ ] Dev server: chat page renders tool indicators for a test question that triggers tools
- [ ] TypeScript clean

#### Break Impact — Wave W11-5
| Broken file | Why | Fix |
|---|---|---|
| `features/chat/hooks/__tests__/useChatStream.test.tsx` | `useChatStream` return shape gains `activeTools` | add `activeTools` to destructuring in existing tests; assert initial value `[]` |

#### Regression Guardrails — Wave W11-5
- `activeTools` cleared on `done` event — if the stream ends without a `done` event (e.g., network error), the `cancel()` function must also clear `activeTools`. Add `setActiveTools([])` to the `cancel()` handler.

---

## 5. Cross-Cutting Concerns

### 5.1 No Kafka / Avro / DB changes
This plan is pure application-layer + frontend. No migrations, no topics, no contracts.

### 5.2 New env var
`TOOL_USE_ENABLED` — add to:
- `env/dev/rag-chat.env` → `TOOL_USE_ENABLED=true` (dev: enable the new path)
- `env/dev/rag-chat.env.example` → document with explanation
- GitOps: `values/rag-chat.yaml` + `env/dev/rag-chat.env` in worldview-gitops repo (set `false` initially in staging)

### 5.3 Documentation
- `docs/services/rag-chat.md` — update with tool-use architecture, capability manifest location, `TOOL_USE_ENABLED` flag
- `libs/tools/README.md` (new) — brief explanation of `ToolRegistry`, `ToolExecutor`, `capability_manifest.yaml`, and R29 enforcement

### 5.4 Architecture test for R29
PLAN-0066 Wave H defined `tests/architecture/test_tool_manifest_sync.py`. This plan expands it from 2 tools to 10. The test must:
- Assert every entry in `capability_manifest.yaml` has a `ToolRegistry.get_handler(name)` that is not `None`
- Assert every registered handler has a `capability_manifest.yaml` entry
- Run as part of the existing architecture test suite (CI gate)

---

## 6. Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| LLM emits tool calls on every query, including simple greetings | HIGH | `get_portfolio_context` description explicitly says when NOT to call; tool descriptions scoped narrowly. Monitor `rag_tool_use_path_total` counter and tool-call rate in staging before promoting to prod. |
| DeepInfra OpenAI-compat endpoint tool_call parsing breaks on model updates | MEDIUM | `_parse_tool_calls` wraps all access in `call.get(...)` with defaults; malformed JSON → `input={}` with warning log, not crash. |
| Tool-use path produces lower quality answers than classical pipeline | MEDIUM | `TOOL_USE_ENABLED=false` is the default + rollback. Wave W11-4 golden eval must show ≥90% valid responses before `TOOL_USE_ENABLED=true` is promoted to staging/prod. |
| `traverse_graph` Cypher tool over-calls KG with expensive queries | LOW | `depth` parameter capped at 4 in tool spec; `ToolExecutor` adds `asyncio.wait_for(timeout=5.0)`. |
| `LlmChatProvider.chat_with_tools()` adds latency (non-streaming first turn) | LOW | First turn is typically short (LLM returns just tool_calls, no long text). Measure P95 latency in staging and set alert threshold. |
| Ollama stub raises `NotImplementedError` in production if Ollama is primary | LOW | `ProviderChain` skips `NotImplementedError` and falls through to DeepInfra/OpenRouter. Add explicit log warning at chain construction time if Ollama is first in chain. |

---

## 7. Open Questions

| OQ | Question | Decision Needed By |
|---|---|---|
| OQ-1 | Should the `IntentClassifier`, `RetrievalPlanBuilder`, and `ParallelRetrievalOrchestrator` be deleted in a follow-on plan (PLAN-0068) or kept permanently as the feature-flag-off path? | Post-thesis validation (after staging proves tool-use quality ≥ classical) |
| OQ-2 | Should `TOOL_USE_ENABLED` be a per-request flag (in the API request body) or only a service-level config? Per-request would allow A/B testing in the UI. | Before Wave W11-3 |
| OQ-3 | Should `search_documents` pass the HyDE-expanded embedding or just `query_text` to `ChunkSearchRequest`? HyDE adds quality but requires the HyDE expander to still run on the tool-use path. | Before Wave W11-2 implementation |

---

## 8. Dependency Graph

```
PLAN-0066 Wave H (must ship first — ToolRegistry, ToolExecutor base, 2-tool manifest, tool loop)
      │
      ├── Wave W11-1 (LLM chat interface + function calling)
      │         │
      │    Wave W11-2 (Expand tool catalog — 8 new tools + ToolExecutor handlers)
      │    [W11-2 parallel-safe with W11-1 except ToolExecutor constructor — depends on ToolUseBlock types]
      │         │
      │    Wave W11-3 (ChatOrchestrator full migration — depends on W11-1 LlmChatProvider + W11-2 ToolExecutor)
      │         │
      │    Wave W11-4 (Integration tests + golden eval — depends on W11-3 complete)
      │         │
      │    Wave W11-5 (Frontend — depends on W11-3 SSE events; parallel-safe with W11-4)
      │
      └── PLAN-0063 Wave W5-x (golden eval CI gate — runs in parallel; W11-4 must not regress it)
```

---

## 9. PLAN-0066 Wave H Gaps — Summary Table

For reference: the specific items in PLAN-0066 Wave H that are left incomplete (not started by PLAN-0066):

| Gap | Fixed in Wave |
|-----|--------------|
| `deepinfra_adapter.py` has no `tools` parameter | W11-1 T-W11-1-03 |
| `LlmStreamProvider` port takes `prompt: str` not `messages: list[dict]` | W11-1 T-W11-1-02 |
| `ToolUseBlock` domain type never actually defined | W11-1 T-W11-1-01 |
| `ToolExecutor` only handles S3 (2 handlers) | W11-2 T-W11-2-02..05 |
| `capability_manifest.yaml` only has 2 entries | W11-2 T-W11-2-01 |
| `SSEEmitter` has no `tool_call` / `tool_result` methods | W11-3 T-W11-3-01 |
| Classical pipeline still runs for ALL queries | W11-3 T-W11-3-02 |
| Frontend has no tool progress UI | W11-5 T-W11-5-01..03 |
