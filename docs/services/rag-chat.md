# RAG / Chat Service

> **Owner**: Chat domain · **Database**: `rag_db` (owned) · **Port**: 8008
> **Status**: PLAN-0080 Wave A (Intelligence-Layer LLM Tools) COMPLETE — 14 tools total (v2 manifest)

---

## Mission & Boundaries

**Owns**: Query rewriting, tool-use chat pipeline, 23-tool catalog, SSE streaming
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
| GET | `/internal/v1/instruments/{instrument_id}/ai-brief-flag` | PLAN-0089 Wave L-5a: returns `{has_ai_brief: bool, brief_generated_at: datetime\|null}` — does any `user_briefs` row exist for this instrument with `brief_type='entity'`? Source = entity-scoped public/cached briefs; user-keyed morning briefs are excluded. Non-failing — false + null + 200 if absent. | X-Internal-JWT (system) |

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
    "summary": str | None,         # PLAN-0048 — 1–2 sentence headline (v2.2 back-compat)
    "summary_paragraph": str | None,  # PLAN-0103 W3/W6 — v4.2 ``## Summary``
                                   # block, 1-3 sentences ≤300 chars, used by the
                                   # dashboard collapsed view; falls back to
                                   # `summary` then narrative head when None.
                                   # GUARANTEE (W6 / v4.3): when the LLM omits
                                   # ``## Summary``, the parser synthesises a
                                   # "Lead headline: <first portfolio/news
                                   # bullet>" string — never None unless the
                                   # entire brief has no bullets at all.
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
| `<MorningBriefCard>` (dashboard, collapsed) | `summary_paragraph` ▸ `summary` ▸ first 3 lines of `narrative` (fallback chain) | inline markdown paragraph |
| `<MorningBriefCard>` (dashboard, expanded) | `sections[]` + `citations[]` if `sections.length > 0`; otherwise `narrative` | structured 3-row layout *or* `<MarkdownContent>` fallback |
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
| `status` | `{"step": "loading_context" \| "entity_resolution" \| "query_expansion" \| "Loading <tool_a>, <tool_b>, <tool_c>… (N more)…"}` — **PLAN-0100 W2 T-W2-01**: in addition to the legacy stage markers, the orchestrator now emits ONE aggregate `status` event with summary text right after iteration-0's LLM picks tools and BEFORE the first `tool_call` event. This is the first user-visible feedback on tool-using questions (lands within ~1-3s vs. ~60s for first synthesised token); the frontend renders it as a badge above `ToolCallTray` and the chat-eval harness counts it toward TTFT (see `_CONTENT_EVENT_KINDS`). |
| `tool_call` | `{"type": "tool_call", "tool": str, "label": str, "input": dict, "status": "running"}` — emitted before each tool executes |
| `tool_result` | `{"type": "tool_result", "tool": str, "status": "ok" \| "error" \| "empty", "item_count": int}` — emitted after each tool completes |
| `token` | `{"text": "..."}` — streamed LLM output chunk. **PLAN-0099 W1 / BP-595**: the "LLM answered directly (no tool calls)" branch now emits one `token` frame per ~8-word chunk via `_chunk_text_for_streaming()` instead of one event for the whole answer (TPS ≈ 0.087 tok/s → real per-frame cadence). `SSEEmitter.emit_delta()` is a wire-compatible alias (same `event: token`) so frontends and the chat-eval harness need no changes. |
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

**PLAN-0095 W2 T-W2-03** reordered the orchestrator so `check_cache()` runs BEFORE `validate_input()`. On cache hit (~15% of traffic) the response is streamed straight from cache and the 5-8 s LLM injection classifier (`validate_input`) is skipped. Security argument: a cached completion was already classifier-validated on its first write (the writer ran through `validate_input → check_cache miss → classifier → cache.set`), so re-running the classifier on every read is defensive duplication, not a real gate.

**PLAN-0097 W2 (BP-579)** widened the Layer 2 classifier SAFE bucket with an explicit relationship/graph-discovery exemplar (`How is X connected to Y? Show me the relationship paths.`) — these queries were intermittently labelled UNSAFE despite `temperature=0.0`, causing Q8 `INPUT_REJECTED` regressions in chat-eval. The system-prompt change is paired with a new `CLASSIFIER_PROMPT_VERSION = "v3"` constant (`llm_injection_classifier.py`) so the on-disk classifier-result cache (P2 W4 T-W4-02) invalidates stale verdicts when the prompt rolls forward. The regression gate is `services/rag-chat/tests/unit/security/test_llm_injection_classifier_benign_relationships.py` — 13 mocked + 13 live-smoke parametrised cases; the live-smoke set is gated by `INTEGRATION_TEST=1` + `RAG_CHAT_DEEPINFRA_API_KEY` so it catches model drift even when the mocked suite passes.

**PLAN-0103 W13 (BP-632)** further widened the SAFE bucket with an explicit FINANCIAL-SCREENER exemplar after the chat-quality benchmark (audit `docs/audits/2026-05-31-plan-0103-final-qa-v44.md` §3.2) documented an INPUT_REJECTED [PROMPT_INJECTION] on `Screen for AI semiconductor companies with market cap above $50B and positive YoY revenue growth.` The L2 classifier latched on to `above $50B` as a data-exfiltration signal and rejected the prompt in ~0.4s — the request never reached the chat engine even though `screen_universe` is the canonical tool for exactly that ask. The fix adds a SAFE exemplar block listing five screener filter shapes (market cap, P/E, dividend, EBITDA, technical) and bumps `CLASSIFIER_PROMPT_VERSION` to `"v4"` (invalidates the on-disk classifier-result cache). Regression gate: `services/rag-chat/tests/unit/security/test_llm_injection_classifier_benign_screeners.py` — 5 mocked SAFE + 2 mocked UNSAFE asymmetric + 1 prompt-content guard + 5 live-smoke. This is the THIRD narrow-exemplar fix (FIX-LIVE-CC v2 conditional reasoning; BP-579 v3 relationship discovery; BP-632 v4 screeners) — the pattern is: an L2 false-positive surfaces a *category* of legitimate query the SAFE exemplar list never enumerated; add a verbatim exemplar from the failing audit prompt + a SAFE/UNSAFE asymmetric regression file; never tighten the UNSAFE rules to suppress the symptom.

**PLAN-0097 W2 T-W2-04** adds a `DEBUG_SKIP_CLASSIFIER` env-var short-circuit at the top of `LLMInjectionClassifier.classify()`. When set truthy (`1`, `true`, `yes`), the classifier returns False immediately and the LLM call is bypassed. **Security gate**: the env-var is honoured ONLY when `APP_ENV != "production"` (read at `classify()` invocation time, not import time) so a leaked flag in a prod environment is a no-op. The chat-eval conftest sets this alongside `RAG_COMPLETION_CACHE_DISABLED=true` so eval runs measure orchestrator behaviour without paying DeepInfra latency or flaking on the L2 model's non-determinism. The unit test `TestDebugSkipClassifier.test_production_app_env_ignores_skip_flag` pins the production guard.

**Chat-eval grader policy (PLAN-0097 W2 T-W2-03 / BP-580)** — `tests/validation/chat_eval/grading.py`:
- **Tool-name equivalence (`_TOOL_EQUIVALENTS`)**: `get_fundamentals_history ↔ get_fundamentals_history_batch` and `traverse_graph ↔ get_entity_paths` are treated as equivalent for the `required_tools_any_of` check. The batch tool retrieves the same logical data; PLAN-0097 W3 wires the intent map to prefer it for ≥2-ticker questions, so penalising the model for using it would be a false negative.
- **INPUT_REJECTED relaxation**: when the response has `error.code == "INPUT_REJECTED"`, the missing-required-tool reason is suppressed (the upstream classifier rejected the request before the model could choose any tool). The error itself still drives the USELESS verdict via the existing `result.error is not None` branch.
- **Refusal-vs-USELESS policy**: a SHORT (`< 300` chars) refusal with NO `[Nk]` citations is USELESS; a LONG or citation-bearing answer that mentions a refusal token is the agent doing the right thing under R19 (no fabrication) and is graded by its tool/citation correctness, not by the refusal token. Documented in the `grading.py` module docstring.

```
Input → Cache check → [hit? short-circuit ✓] → Validate → Rate limit → Load history → Release UoW
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

### Tool Catalog (24 tools — `libs/tools/src/tools/capability_manifest.yaml` v5)

| Tool | Target | Description | Since |
|------|--------|-------------|-------|
| `get_price_history` | S3 | OHLCV price data for a ticker | v1 |
| `get_fundamentals_history` | S3 | Quarterly financial metrics for ONE ticker. **PLAN-0097 T-W3-03** added a reciprocal "Do NOT call in a loop — use `get_fundamentals_history_batch` instead" warning so the LLM stops iterating this for multi-ticker comparisons (iter-9 chat-eval misroute). | v1 |
| `get_fundamentals_history_batch` | S3 | **PLAN-0095 W2** — quarterly metrics for MULTIPLE tickers in ONE call (cap 25). Backed by `POST /api/v1/fundamentals/batch`; collapses N×fundamentals tool-turns into one (5-10x latency reduction on screener-then-fundamentals workflows). **PLAN-0097 T-W3-03** strengthened the description to lead with a strict directive (`**Use this tool — NOT get_fundamentals_history — when …**`) so the planner picks it on the first turn. | v4 |
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
| `compare_entities` | S3 | Side-by-side comparison of 2-4 tickers: fundamentals highlights + latest quote in parallel. **PLAN-0103 W14 (FQA-04 carry)**: now widens the fundamentals window to `periods=4` and selects the latest period that has `revenue + eps + gross_profit` populated for ALL compared tickers ("latest fully populated common period"). Falls back to per-ticker latest only when no common period exists. Fixes the silent-NULL pattern where ticker A had Q1 reported but ticker B's Q1 row was still pending. | v4 |
| `screen_universe` | S9→S3 | Quantitative screener via S9 `POST /v1/fundamentals/screen`. Filter by market_cap, P/E, sector, region | v3 |
| `get_market_movers` | S9→S3 | Top gainers/losers/most-active via S9 `GET /v1/market/top-movers`. Default: gainers/1d | v3 |
| `get_economic_calendar` | S9→S3 | Macro events (CPI, FOMC, GDP) via S9 `GET /v1/fundamentals/economic-calendar` | v3 |
| `get_earnings_calendar` | S9→S3 | Earnings release dates + EPS via S9 `GET /v1/fundamentals/earnings-calendar` | v3 |
| `get_entity_news` | S6 | **PLAN-0103 W2** — entity-anchored news feed: resolves `entity_id` (or `ticker`) and fetches `/api/v1/entities/{eid}/briefing-articles`. Filters by `days_back` (client-side) + `max_results`. Catalogue gap fix from 2026-05-29 real-user audit (Q1: "latest news on MSTR" previously routed to broad `search_documents`). Prefer over `search_documents` when the user asks about ONE specific company / ticker. | v5 |

**v2 intelligence tools (PLAN-0080 Wave A)**: all 4 call S9-proxied endpoints (R14/R7 compliance — never S7 directly). All respect `EntityContext` scope: when the executor is bound to an entity via `ToolExecutorFactory.for_request(entity_context=...)`, the `entity_id` is auto-injected and LLM-supplied values are silently overridden (M-1 enforcement).

**v3 catalog tools (PLAN-0081 Wave A)**: 6 tools backed by `S3BriefPort` (new Protocol — screener/movers/calendars via S9 proxy) and `BriefArchivePort` (existing). `S3BriefClient` adapter wired in `app.py` lifespan. `BriefArchiveReadAdapter` creates per-call read sessions (R27). All tools are read-only — no UnitOfWork acquired.

**Fundamentals tool behavior — periodicity contract (PLAN-0097 W1 T-W1-02, defense-in-depth)**: every row rendered by the rag-chat `MarketHandler._format_fundamentals_table` carries an explicit per-row `Periodicity` column AND an `(Periodicity: QUARTERLY)` header tag above the table. The header tag is deliberately redundant with the column so the LLM sees the contract BEFORE reading any cell value — eliminating the failure mode where a long table is summarised on the column header only and an annualised number sneaks past the row-level label. Defense-in-depth complements the source-side `period_type="QUARTERLY"` filter enforced by `GetFundamentalsHistoryUseCase` (PLAN-0097 W1 T-W1-01).

All tool executions are independent; failures return empty results (safe degradation). The all-tools-failed guard prevents the second LLM turn from being called with zero context — the orchestrator short-circuits to a fallback answer in that case.

**Tool kwargs forwarding policy (PLAN-0103 W1, BP-622)**: every handler `execute()` MUST sanitise the LLM payload via `filter_kwargs_to_signature` (`handlers/base.py`) before dispatching to the per-tool `_handle_*` method. Unknown kwargs are logged as `tool_unknown_kwarg` + counted in the `rag_chat_tool_unknown_kwarg_total{tool_name, kwarg}` Prometheus counter. This replaces the previous failure modes where an unknown kwarg either (a) crashed the call with `TypeError` (swallowed by the executor as `tool_argument_error`) or (b) was silently dropped by a whitelist gate (`screen_universe` lost `revenue_growth_yoy_min` for ~3 weeks before BP-622 was filed). When the LLM keeps requesting an unsupported field, operators see the drift in real time and either (a) extend the handler signature or (b) tighten the tool description so DeepSeek stops asking.

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

## PLAN-0093 E-Wave Hardening (2026-05-24)

Wave E of PLAN-0093 rebuilt the chat agent's safety pipeline around five orthogonal layers, each addressing a distinct failure mode surfaced by the 2026-05-23 intelligence pipelines QA. Together they convert the chat orchestrator from a "trust the LLM" loop into a guarded pipeline where every numeric claim, entity reference, and tool result is independently validated before delivery.

- **PLAN-0093 E-1 — Intent inference (`application/services/intent_inference.py`)**: a deterministic, pure-Python classifier that maps the first batch of `ToolUseBlock`s emitted by the LLM into a `QueryIntent` enum. Priority order: `compare_entities` or ≥ 2 distinct `entity_id`s → `COMPARISON`; graph tools (`traverse_graph`, `get_entity_paths`) → `RELATIONSHIP`; fundamentals/screen → `FINANCIAL_DATA`; calendar/temporal → `MACRO`; doc/claim search → `FACTUAL_LOOKUP`; else `GENERAL`. The orchestrator (`chat_orchestrator.py:454-472`) re-derives intent on iteration 0 only and rewrites `messages[0]` in place with the per-intent style addendum, so iteration 1+ uses the right formatting. Intent is also the label for `rag_queries_total{intent=...}` and the audit log. Co-located with E-1 is the **tool-call dedup coalescer** (`_tool_result_cache` keyed by `(tool_name, frozenset((k, repr(v))))`): duplicate emits across iterations are served from memory and logged as `tool_dedup_hit`. The cache is allocated per call to `_execute_streaming_inner`, so the turn boundary clears it implicitly.

- **PLAN-0093 E-2 — Numeric grounding (`application/services/numeric_grounding.py`)**: `NumericGroundingValidator` extracts every signed number with optional `$`, thousands separators, decimal portion, and `B/M/K/T/%` suffix from the LLM response, classifies each via `classify_number()` into a `FieldKind` enum (`REVENUE`, `EPS`, `MARKET_CAP`, `RATIO`, `RETURN_PCT`, `HEADCOUNT`, `SHARES`, `PRICE`, `YEAR`, `QUARTER`, `UNKNOWN`), then matches against tool-result values **of the same kind first** with the per-kind tolerance from `libs/contracts/numeric_grounding.py:DEFAULT_TOLERANCES` (overridable via `NUMERIC_GROUNDING_TOLERANCES_JSON`). EPS at 11% off fails; headcount at 0.25% off passes. **Sign mismatches always fail** regardless of tolerance — a loss reported as a gain is a lie, not a rounding error. Quarter labels (`Q1 2026`, `Q1 FY26`, `Q1 fiscal 2027`) are canonicalised by `_normalize_quarter_label` and require verbatim presence in the tool text blob. On validation fail the orchestrator's `_run_grounding_validation` (chat_orchestrator.py:914+) re-prompts the LLM **once** with the unsupported numbers; if the rewrite also fails, a "⚠ Some numbers could not be verified" banner is appended so the user is warned rather than silently shown a hallucination.

- **PLAN-0093 E-3 — Name resolution in 4 KG tools (`application/pipeline/handlers/intelligence.py:161-196`)**: `_resolve_entity_by_name(tool_name, entity_name)` is the single helper invoked by `get_entity_graph`, `traverse_graph`, `search_entity_relations`, `search_claims`, `search_events`, and `get_contradictions` before any KG call. Resolution priority: (1) if `entity_context` is set and a case-insensitive substring match holds, return the scoped entity_id; (2) else call `S7.resolve_entity_by_name(entity_name, limit=3)` and take `candidates[0]`. The S7 alias index does the fuzzy matching; ties surface to the user via the LLM's normal answer flow because the handler logs `tool_entity_resolved_by_name` with the chosen alias + similarity for audit, and returns `None` (skipping the tool) when no alias matches — at which point the orchestrator's all-tools-failed guard or multi-tool fallback (E-4) takes over.

- **PLAN-0093 E-4 — Multi-tool fallback (`chat_orchestrator.py:594-607` + `_try_fallback_tools` at line 862)**: on iteration 0, if every tool returned empty AND no action is pending, the orchestrator consults the `_FALLBACK_MAP` whitelist — `search_documents → get_entity_intelligence`, `get_contradictions → search_claims` (with `polarity=negative` injected), `get_economic_calendar → get_temporal_events`, `search_claims → search_documents` — and retries with the same input args. Each fallback is a single attempt (no recursion) and consumes the same per-turn budget as the original call (`cumulative_tool_latency` is incremented in the surrounding loop). If the fallback also returns empty, `all_tools_failed` fires and the user gets an explicit error rather than a hallucinated answer.

- **PLAN-0093 E-5 — Citation validation (`chat_orchestrator.py:128-176` + invocation at line 774)**: two scrubbers run post-LLM, pre-delivery. `_scrub_orphan_citations(text, max_index)` strips any `[N\d+]` marker where the index exceeds `len(reranked)` (the number of items the user actually saw); valid markers `[N1]..[NK]` stay put. `_scrub_unseen_refs` replaces any `entity:UUID` or `article:UUID` reference whose lowercased ID is **not** in `seen_item_ids` (harvested from tool results across all iterations) with `[ref:redacted]`. The whitelist is sourced from the live retrieval, never from a static list. Stripped-citation text is retained — only the marker disappears — so the prose still flows; the orphan count is logged for monitoring LLM citation discipline.

See `docs/audits/2026-05-23-qa-intelligence-pipelines-report.md` F-CHAT-AGENT-001..005 for the original failure modes that drove each layer (AMD Q2 2026 revenue fabrication, MSTR empty-fallback hallucination, entity-name mis-resolution, citation marker drift, multi-iteration tool re-emission).

---

## PLAN-0095 W3 — Tool ergonomics & eval hygiene (2026-05-26)

Five tool descriptions in `application/pipeline/tool_registry_builder.py` were tightened with explicit "DO NOT use for…" anti-pattern clauses to stop the LLM misrouting peer / biographical questions:

- **`get_entity_graph`** — anchors on a SINGLE entity's direct neighbours. Anti-patterns now listed: (1) peer / competitor questions (KG sparse on `competitor_of`), (2) biographical / career-history about people, (3) two-entity relationship lookups. Each anti-pattern redirects to the correct sibling tool by name.
- **`traverse_graph`** — requires BOTH `start_entity` and `target_entity`. Anti-patterns: single-entity peer questions, biographical lookups, single-anchor pre-ranked path queries (→ `get_entity_paths`).
- **`get_entity_paths`** — pre-computed top-N paths anchored on ONE entity. Anti-patterns: two-entity questions (→ `traverse_graph`), full bundles (→ `get_entity_intelligence`), direct-neighbour structural lookups (→ `get_entity_graph`).
- **`get_entity_intelligence`** — promoted to the PREFERRED tool for: comprehensive overviews, biographical / executive-history questions, and peer / competitor questions (relations_summary surfaces competitor / partner buckets even when KG edges are sparse).
- **`compare_entities`** — explicitly flagged as a FINANCIAL-only tool (market cap, P/E, revenue, EPS). Anti-patterns: relationship questions between tickers, qualitative narrative, historical time-series for one entity.

The `_TOOL_TO_INTENT` map in `application/services/intent_inference.py` was extended with three new entries — `get_entity_intelligence`, `search_entity_relations`, `get_entity_narrative` — all mapped to `QueryIntent.RELATIONSHIP` so the second-turn prompt picks the relationship-specialised addendum instead of the GENERAL fallback.

A new env var `RAG_COMPLETION_CACHE_DISABLED` is honoured in `application/pipeline/chat_pipeline.py:check_cache()` — when set to `"true"` (case- and whitespace-tolerant) the cache lookup is short-circuited and the request runs cold-path. Intended for the chat-eval session (auto-set by `tests/validation/chat_eval/conftest.py`); production leaves it unset. The chat-eval harness (`tests/validation/chat_eval/harness.py:ask`) now also mints a fresh `thread_id = str(uuid4())` per call so two runs of the same prompt cannot collide on the cache key, even if the env var is missed. Both fixes are belt-and-suspenders defences against the iter3 "Unity Software" cache-poisoning artefact (audit §5).

The grader (`tests/validation/chat_eval/grading.py`) now treats a cache-hit response (detected via `metadata.cache_hit` or a `status` SSE event with `step="cache_hit"`) as automatically satisfying the `required_tools_any_of` rubric — the original cold-path request fired the tools, and punishing a legitimate latency optimisation is noise.

### Chat-eval acceptance gate — TTFT + TPS + relaxed E2E (PLAN-0099 W1 T-W1-03)

The aggregate gate in `tests/validation/chat_eval/test_aggregate_score.py` previously enforced `median latency ≤ 30s` AND `p99 latency ≤ 60s` on end-to-end wall-clock. That signal was contaminated by tool fan-out and query complexity (a legitimate 3-tool screener-then-fundamentals query routinely takes 60–80 s and is not a UX regression). The gate has been replaced with three responsiveness-centric metrics plus a relaxed E2E watchdog:

| Metric | Aggregation | Hard gate | Rationale |
|---|---|---|---|
| `ttft_s` (time-to-first-token) | p95 | `< 5.0 s` | Wall-clock from request submit to the FIRST user-visible SSE event. **PLAN-0100 W2 T-W2-02**: broadened from "content-only" to `{token, delta, text, final_answer, tool_call, status}` — matches what real users see in the chat UI (tool pills via `ToolCallIndicator`, aggregate status badge). Skips truly internal frames (`thinking`, `tool_result`, `metadata`). The 5s gate now means "first user-visible label arrives in <5s" instead of "first synthesised token in <5s"; before the change tool-using questions had p95 ≈ 69.7s because synthesis happens after the tool loop (see `docs/audits/2026-05-27-plan-0100-latency-structural.md` §A). |
| `tps` (tokens-per-second) | p50 | `≥ 30 tok/s` | `output_tokens / (latency_s - ttft_s)`. `output_tokens` prefers the provider usage envelope (`data.usage.output_tokens` on any event, or `metadata.usage.output_tokens`) and falls back to a `ceil(chars/4)` estimate over the joined answer when absent. Captures streaming readability. |
| `latency_s` (end-to-end) | p99 | `< 90.0 s` | Soft watchdog: catches provider hangs / DLQ retry loops / tool stalls. Relaxed from the old 60 s gate so multi-tool queries are not unfairly punished. |

The median E2E latency is now logged as a soft watchdog (`> 30 s`) but no longer fails the gate. Verdict gates (`USEFUL ≥ 6`, `HARMFUL = 0`) are unchanged. Per-question artefacts include `ttft_s`, `tps`, `output_tokens`, and a forensic `event_timings` list (`[event_kind, t_recv_us]` per SSE frame) so any gate failure is reproducible from the JSON alone. Audit: `docs/audits/2026-05-27-plan-0099-latency-metric-redesign.md`.

---

### Agentic brief generator (experimental, flag-gated)

PLAN-0099 Wave C scaffolds an alternative morning-brief code path,
`AgenticBriefGenerator` (`application/use_cases/agentic_brief_generator.py`),
that drives an iterative LLM tool-use loop instead of the single-turn
`GenerateBriefingUseCase.execute_public_morning` generator. **Off by default —
intended for A/B comparison only.**

Enable via two env vars (defaults already in
`services/rag-chat/configs/docker.env.example`):

| Env var | Default | Purpose |
|---------|---------|---------|
| `RAG_CHAT_BRIEF_AGENTIC_ENABLED` | `false` | Master flag. When `true`, the morning-brief route uses the agentic generator instead of the standard path. |
| `RAG_CHAT_BRIEF_AGENTIC_MAX_TOOL_CALLS` | `8` | Hard cap on tool calls per generation. Overrun triggers fallback. |

Loop shape:

1. **PLAN** — the agent gets a generic "you are an institutional analyst" prompt + the OpenAI-format schemas for a 6-tool subset (`get_portfolio_news`, `get_top_movers`, `screen_universe`, `search_documents`, `get_economic_calendar`, `get_morning_brief`).
2. **CALL / INJECT** — each `tool_call` is dispatched through the existing per-request `ToolExecutor` (same handlers chat uses), and the result is appended as a `role="tool"` message.
3. **LOOP** — repeat until the LLM returns `finish_reason="stop"`, OR the tool-call budget is hit, OR the LLM-hop safety cap (`max_tool_calls + 2`) is reached.
4. **ASSEMBLE** — the final text is wrapped in the same response envelope (`content` / `risk_summary` / `sections` / …) the standard generator returns, so the route layer is shape-compatible.

Fallback to the standard generator is automatic on any of: **exception** in the loop, **budget_exhausted**, or **empty_response**. Each reason increments `brief_agentic_fallback_total{reason}` so dashboards can compare fallback rate vs successful agentic runs.

Per-generation cost is visible via:

- `brief_agentic_llm_calls_total` — total LLM round-trips
- `brief_agentic_tool_calls_total{tool}` — per-tool invocation counter
- `brief_agentic_fallback_total{reason}` — fallback counter

The route-layer branch lives in `api/routes/public_briefings.py` (GET `/api/v1/briefings/morning`); it is a single `if settings.brief_agentic_enabled` block, so removing the experiment is a one-line revert plus deleting the module + tests.

### Morning brief signals (PLAN-0102 W2 T-W2-03/04)

`BriefingContextGatherer.gather_morning_context()` fans out two additional
upstream calls when a portfolio snapshot is available:

1. **S1 overnight P&L** — `GET /internal/v1/users/{user_id}/portfolio/pnl`
   via `S1Client.get_portfolio_pnl()`. Returns per-holding `overnight_pnl_usd`,
   `overnight_pnl_pct`, `last_close_usd`, `current_price_usd`, plus portfolio
   aggregates. Wrapped in `timed_upstream_call("portfolio_pnl")` so the SLO
   dashboards see latency + outcome.

2. **S7 sector lookup** — `GET /internal/v1/entities/sectors?entity_ids=...`
   via `S7Client.get_sectors_for_entities()`. Returns `{entity_id: SectorLabel}`
   for the user's held entities. Wrapped in `timed_upstream_call("sectors")`.

The gatherer combines both into `BriefingContext.portfolio_pnl`
(`PortfolioPnLSnapshot`) and `BriefingContext.sector_exposure`
(`SectorExposure` = `{sector_label: pct_of_portfolio_value}`). Both are
optional so legacy brief paths still produce output when either call fails.

`BriefContextFormatter.format_portfolio_morning()` renders:

* Per-holding lines like `"AAPL +1.45% pre-mkt — +$280"` (preferred when
  P&L snapshot is present).
* Total overnight P&L footer: `"Total overnight P&L: +$530 (+1.32%)"`.
* Sector mix footer: `"Sector mix: Tech 65% | Energy 18% | Financials 12%"`.

R9 safe degradation: when the P&L call fails the formatter falls back to
the legacy "Holdings (N positions): name — quantity, weight X%" line so a
single upstream outage never produces an empty brief.

#### Sector-exposure weight-fallback ladder (PLAN-0103 W12 / BP-631)

`_compute_sector_exposure()` (`application/use_cases/briefing_context.py`)
computes `{sector: pct_of_portfolio_value}` from a 4-tier ladder. Each tier
is tried in order; the first that yields a positive total wins. Telemetry
counter `brief_sector_exposure_weight_source{source}` (defined in
`application/metrics/prometheus.py`) increments with the winning tier so
operators can detect silent degradation (a spike in `equal` means the P&L
upstream regressed).

| Tier | Source label | Input | When it fires |
|------|--------------|-------|---------------|
| 1 | `pnl` | `pnl_snapshot.current_price_usd * qty` | Preferred — live P&L + live quotes |
| 2 | `quote` | `pnl_snapshot.last_close_usd * qty` | P&L row exists but no current quote |
| 3 | `db_weight` | `PortfolioSnapshot.current_weight` | P&L endpoint unreachable + DB weights populated |
| 4 | `equal` | `1.0 / N` per held entity | Last resort: no P&L AND no DB weights (BP-631) |

Tier 4 ensures the brief NEVER ends up with an empty `risk_summary` on a
non-empty portfolio. Without it, dev seed data (where `current_weight` is
typically NULL — BP-517) plus a transient P&L outage would silently
collapse `sector_breakdown` to `{}` and `concentration_score` to None,
exactly the failure shape audit `docs/audits/2026-05-31-plan-0103-final-qa-v44.md`
§4 caught (BP-631). For a 5-holding equal-weight portfolio Tier 4 gives
HHI = 1/N = 0.20 — a computable concentration metric instead of nothing.

### Tape + earnings calendar (PLAN-0102 W3 follow-up)

The morning brief also renders two additional sections sourced from the
market-data internal endpoints landed in PLAN-0102 W3:

1. **Tape** — `GET /internal/v1/market/tape?symbols=SPY,QQQ,VIX` via
   `MarketTapeClient.get_tape()`. The gatherer wraps it in
   `timed_upstream_call("market_tape")`; result lands on
   `BriefingContext.market_tape` (`MarketTapeResult`).
   `BriefContextFormatter.format_market_tape()` renders a single line
   `"Tape: SPY +0.20%, QQQ +0.45%, VIX 14.20"` — rows whose
   `session == "unavailable"` are skipped, and when every row is
   unavailable the formatter degrades to
   `"Tape data unavailable (as of YYYY-MM-DD)"` so a stale close never
   leaks through as a "fresh" pre-market level.

2. **Macro Today — earnings** — `GET /internal/v1/calendar/earnings`
   via `EarningsCalendarClient.get_earnings(days_ahead=7)`. The gatherer
   wraps it in `timed_upstream_call("earnings_calendar")`; result lands
   on `BriefingContext.earnings_calendar` (`EarningsCalendarResult`).
   `BriefContextFormatter.format_earnings_calendar(max_days=2)` renders
   a `Macro Today (earnings next 2 days):` block with one bullet per
   event (`- NVDA earnings 2026-06-02 AMC (consensus EPS $0.74)`).
   Returns the empty string when no in-window events so the existing
   macro placeholder upstream stays.

Both clients target the same market-data host as `S3Client`
(`settings.s3_base_url`); both default to `None` in the gatherer
constructor so unit tests and legacy code paths keep working unchanged.
DI happens in `app.py` (handler path) and
`infrastructure/scheduling/brief_scheduler_main.py` (pre-gen worker).

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
| `RAG_CHAT_CITATION_CRON_ENABLED` | `false` | No | Enable weekly citation accuracy cron (costs LLM tokens) |
| `RAG_CHAT_CITATION_JUDGE_PROVIDER` | `deepinfra` | No | `deepinfra` or `ollama` |
| `RAG_CHAT_CITATION_JUDGE_MODEL` | `meta-llama/Meta-Llama-3.1-8B-Instruct` | No | Model for citation accuracy scoring |
| `RAG_CHAT_CITATION_MIN_SAMPLES` | `10` | No | Min messages required to emit gauge (1-500) |
| `RAG_CHAT_CITATION_CALL_TIMEOUT_S` | `15.0` | No | Per-judge-call timeout (>0, ≤120s) |
| `RAG_CHAT_CITATION_RUN_BUDGET_S` | `600.0` | No | Total wall-clock budget per cron run |
| `RAG_CHAT_LOG_LEVEL` | `INFO` | No | structlog log level |
| `RAG_CHAT_LOG_JSON` | `true` | No | JSON-structured logs |
| `RAG_CHAT_OTLP_ENDPOINT` | `""` | No | OpenTelemetry collector endpoint |
| `RAG_CACHE_DEPLOY_TOKEN` | `""` | No | Opaque token compared against the last-seen value in Valkey on startup; on mismatch, rag-chat flushes every `rag:v*:completion:*` cache entry (SCAN-based, never KEYS — production-safe) so stale completions cannot be served after a prompt-pack or model rollout. Bump the token whenever you change a system prompt, swap a completion model, or alter the citation grader rubric. PLAN-0097 W4 T-W4-04 (documented in PLAN-0098 W4 T-W4-03 docs bundle). |

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
| `rag_tool_call_total` | counter | `tool_name`, `status` |
| `rag_tool_call_latency_seconds` | histogram | `tool_name` |
| `rag_tool_use_first_turn_latency_seconds` | histogram | — |

#### New Metrics (PLAN-0093 QA-7)

Four additional metrics were introduced in PLAN-0093 QA-7 to surface tool-use regressions and registry health:

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `rag_no_tool_calls_first_turn_total` | counter | `provider` | LLM answered on iteration 0 without calling any tool; a spike indicates prompt or provider regression |
| `rag_tool_result_items` | histogram | `tool_name` | Number of items returned per tool call (buckets: 0/1/3/5/10/20/50/100/250); p95 spike = retrieval bottleneck |
| `rag_chat_with_tools_failed_total` | counter | `provider` | Provider-level `chat_with_tools` failures; increments on every exception in the fallback chain |
| `rag_tool_registry_size` | gauge | `kind` | Set at startup by `validate_registry_parity()`; `kind=manifest` = tools declared in YAML, `kind=handled` = tools with a registered handler; if these two values diverge the service refuses to start |

**`rag_latency_seconds` per-tool threshold (PLAN-0093 QA-7)**: the existing histogram now also covers per-tool timing. A `tool_slow` warning fires whenever a single tool execution exceeds **2 seconds** (configurable); previously timing was only tracked at the full-turn level.

#### Retrieval Quality Metrics (PLAN-0063 W5-5)

`rag_retrieval_score_distribution` — histogram of per-chunk fusion scores (buckets `[0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0]`), labelled by `source_type`. Emitted in `retrieval_orchestrator._fetch_chunks`.

`rag_source_contribution_total` — counter incremented once per query per source that contributed ≥1 chunk to fusion. Together with the histogram, reveals whether lexical / KG / SQL sources are pulling weight.

`rag_reranker_position_change` — rolling gauge (window=100 queries) of the fraction of queries where the reranker's top-1 differs from the fusion top-1. Updated via `record_reranker_position_change()` after step 8 in `ChatOrchestrator`. A gauge near 0 means the reranker is redundant; near 1 means fusion ordering is unreliable.

`rag_citation_accuracy` — gauge set by the weekly citation-accuracy cron (`ScoreCitationAccuracyUseCase`). Values: 0 = irrelevant snippets, 1 = direct verbatim support.

### Per-Phase Timing (PLAN-0099 W1-T03)

The chat orchestrator emits a `chat_phase_timings_ms` structlog event at the
end of every `execute_streaming` run AND attaches the same dict to the
terminal SSE `done` event's `data.phase_timings_ms` field. This lets the
chat-eval harness decompose end-to-end latency into per-phase buckets
without parsing stderr.

Keys recorded (cumulative ms; agent-loop phases sum across iterations):

| Phase key | What it covers |
|-----------|----------------|
| `check_cache` | Valkey completion-cache lookup (always recorded) |
| `validate_input` | Layer 1 regex + PII scrub + Layer 2 LLM injection classifier |
| `load_history` | UoW read of prior thread messages |
| `entity_resolution` | S6 entity-resolution lookup |
| `llm_tool_planning` | Cumulative non-streaming `chat_with_tools` calls (first-LLM bucket) |
| `tool_execution` | Cumulative `tool_executor.execute_all` fan-out wall-clock |
| `llm_synthesis_streaming` | Second-turn `stream_chat` (post-tool synthesis) |
| `grounding_validation` | PLAN-0093 E-2 numeric-grounding pass + optional re-prompt |
| `persist_and_cache` | Postgres persist + Valkey completion-cache write |

On a cache hit only `check_cache` is recorded and the event carries
`cache_hit=true`. On an `llm_second_turn_failed` short-circuit the event
carries `terminated_at="llm_synthesis_streaming"` and only the phases
observed before the failure are present. The implementation lives in
`rag_chat.application.observability.phase_timings` (a `PhaseTimings`
accumulator + `phase(name, timings)` async context manager — exception
in the wrapped block still records elapsed time, so failed phases never
silently drop out of the breakdown).

**Phase-label invariant (PLAN-0101 W3)**: the exact string
`llm_synthesis_streaming` is part of the public SSE contract. The chat-eval
harness (`tests/validation/chat_eval/harness.py`) consumes this key from
`done.data.phase_timings_ms` to compute the `tps_streaming` metric — the
TPS gate in `test_aggregate_score.py` (≥ 20 tok/s p50) is defined against
this exact label. Renaming or removing it silently regresses the metric to
NaN and disables the gate. See
`docs/audits/2026-05-28-plan-0101-tps-metric-redesign.md`.

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
| GET | `/api/v1/briefings/instrument/{entity_id}` | X-Internal-JWT | Instrument briefing |

**`POST /internal/v1/briefings`**: consumed by S10 email scheduler. Rate-limited to
100/day per user. Uses `EMAIL_DEEP_BRIEF_PROMPT` system prompt. Returns `BriefingResponse`
(see API Surface section).

---

## Morning Brief — 5-Minute Investor Brief Structure (PLAN-0102 W1)

The morning brief is structured as a 5-minute investor summary, NOT a news
aggregator. The prompt at `libs/prompts/src/prompts/briefing/morning.py` (v4.5)
instructs the LLM to emit a leading `## Summary` paragraph followed by six
named sections in this exact order.

> **v4.5 release (PLAN-0103 W11, 2026-05-30)**: makes the `## Summary` length
> ADAPTIVE. v4.4's fixed `≤ 50 words` cap was the right shape for a
> 10-position portfolio on a quiet day but truncated useful synthesis on
> large books (30+ positions) or very active overnight sessions. v4.5
> replaces the fixed cap with a `target ~100 words` rule + explicit size
> bands keyed off portfolio breadth + market activity: small + quiet →
> 30-60w; medium + normal → 80-150w; large or very active (5+ material
> developments overnight) → up to 200w (hard cap 200w). Above 50w the
> LLM is instructed to "mention top 1-3 holdings by P&L impact"; Example
> A's Summary was re-shot at ~150 words to demonstrate the new shape.
> Parser `split_summary_paragraph` cap raised 300 → 1500 chars; schema
> field `summary_paragraph` max_length raised 600 → 1600 chars (both api
> and application schemas). NEVER write a fixed word cap for prose that
> must scale with the user's portfolio — anchor on a *target* + bands.
> Tests: `libs/prompts/tests/test_prompts.py::TestMorningBriefing::test_v45_six_section_spec`
> (asserts the adaptive language + the THREE size-band lines + version
> bump); `tests/test_brief_parser.py::test_split_summary_paragraph_caps_at_1500_chars`
> + `test_split_summary_paragraph_preserves_v45_adaptive_length`
> (~1000-char Summary passes through untrimmed); rag-chat version
> assertion bumped 4.4 → 4.5 in
> `tests/unit/application/test_briefing_context_gatherer.py::test_morning_prompt_v4_contains_required_sections`.

> **v4.4 release (PLAN-0103 W9, 2026-05-30, BP-630)**: SPLITS the single
> 250-word cap into TWO explicit caps + per-section guidance. The v4.3
> directive `Cap total brief at 250 words` was structurally incompatible
> with a 6-section investor brief that must carry depth — the LLM either
> truncated News bullets (the most signal-rich section) or compressed all
> sections to one-line skeletons.  v4.4 budgets `## Summary block: ≤ 50
> words, 1-3 sentences` (the collapsed dashboard surface the user reads at
> a glance) separately from `## Details block: ≤ 700 words across all 6
> sections combined` (Tape ≤ 25 words one line; Your Portfolio Today 3-6
> bullets ~20 words each; Macro Today 1-4 bullets; News That Matters To
> You 3-5 bullets ~25 words each; Risks + Opportunities 2-3 bullets;
> Bonus context 1-2 bullets). On quiet days the brief naturally lands
> ≤ 300 words; on busy days it can use the full ~700-word details budget
> without truncating signal. The parser's `split_summary_paragraph` still
> soft-caps the extracted summary at 300 chars (a tighter constraint than
> the 50-word prompt directive) so the schema invariant holds even if the
> LLM overruns.

> **v4.3 release (PLAN-0103 W6, 2026-05-30)**: adds TWO few-shot examples
> (Example A — rich day, Example B — quiet day) that teach the LLM the
> desired output shape. v4.2 imperative-only rules produced live runs that
> still dropped 2 of 6 sections AND skipped `## Summary` even though they
> were marked MANDATORY (audit
> `docs/audits/2026-05-29-plan-0103-final-qa.md` FQA-01). v4.3 pairs the
> example-driven prompt with **parser-side defensive injection** in
> `brief_parser.inject_missing_sections` (appends placeholder lines for
> missing sections in canonical order) and `brief_parser.inject_missing_summary`
> (synthesises a "Lead headline: …" string from the first portfolio/news
> bullet when the LLM omits `## Summary`). Net guarantee: **all 6 sections
> + `summary_paragraph` are present on every `BriefingResponse` regardless
> of LLM compliance**, with `brief_section_injected_total{section}` Prom
> counters + `brief_defensive_injection` structlog warning surfacing how
> often the LLM is degrading.

> **v4.1 cleanup release (PLAN-0103 W2, 2026-05-29)**: v4.0 carried TWO
> incompatible rubrics — the 6-section investor brief at the top AND the
> legacy v3.0 `## LEAD / --- / ## DETAILS` "STRICT" template (with "Maximum
> 4 sections, maximum 4 bullets") at the bottom. The lower block
> contradicted the upper spec on every axis (number of sections, section
> names, bullet caps, block structure). The live brief happened to follow
> the upper rubric, but the LLM was given conflicting instructions. v4.1
> deletes the legacy LEAD/DETAILS template and the 4/4 caps; citation rules
> moved to a single MANDATORY block; format rules collapsed to one bullet
> list (≤250 words, markdown headers, `**Section Name**` headings). The
> brief parser already degrades gracefully when the `---` divider is absent
> (`brief_parser.split_summary_and_details` returns `(None, full_content)`)
> so removing the divider does not break frontend rendering.
> Audit: `docs/audits/2026-05-29-plan-0102-phase-d-code-review.md` §1.
> Marker form migrated `[c1]` → `[N1]` (instrument brief still uses `[c1]`).

| Section | Read time | What it answers | Source data |
|---------|-----------|-----------------|-------------|
| 1. **Tape** | 20 s | "What did markets do overnight?" | `MarketOverview.indices` (SPY / QQQ / VIX from S3 batch) |
| 2. **Your Portfolio Today** | 60 s | "How am I positioned into today?" | `MarketOverview.holdings` per-holding quote, **leads with implication** |
| 3. **Macro Today** | 20 s | "What scheduled events could move me?" | `recent_events` rows tagged `source_tier="macro"` (Fed / CPI / jobless) |
| 4. **News That Matters To You** | 120 s | "What changed overnight that affects my book?" | `news_articles` re-ranked by overlap with held entities; **each bullet leads with implication, then fact, then `[N#]`** |
| 5. **Risks + Opportunities** | 60 s | "Where am I exposed today?" | LLM synthesises across Tape + Macro + Portfolio |
| 6. **Bonus context** | 30 s | "What else should I know?" | 1–2 generic high-impact items |

**Word budget (v4.5)**: `## Summary` is ADAPTIVE — target ~100 words; 30-60w
small + quiet day; 80-150w medium + normal day; up to 200w large book or very
active day; hard cap 200w. `## Details` ≤ 700 words total with per-section
guidance (see v4.4 release note above). The old single 250-word global cap is
GONE — it was too restrictive for the 6-section spec and forced the LLM to
drop signal. Citations use `[N1] [N2]` markers (the existing v3.0
output-format block is preserved beneath the new spec so the parser, deduper,
and citation gate continue to function).

### Context-gather pipeline — what we fetch vs. what we render

`BriefingContextGatherer.gather_morning_context()` runs five parallel upstream
calls and assembles a `BriefingContext`:

1. **S1 portfolio** — holdings, watchlist, total_positions. Drives ticker
   resolution + entity_ids for the news overlap join.
2. **S6 top news** — `GET /api/v1/news/top?hours=24&limit=30&min_display_score=0.15`,
   then re-ranked in-process so items whose `primary_entity_id` overlaps the
   user's held entities float to the top (1.5x multiplier; floor preserved —
   non-overlap items NEVER dropped so quiet-day briefs still surface).
3. **S5 pending alerts** — `medium`-or-higher severity only.
4. **S3 batch quotes** — single call with both the holdings ticker list AND
   the broad-market tape (`SPY`, `QQQ`, `VIX`). Result is repackaged into
   `MarketOverview.indices` (tape) and `MarketOverview.holdings` (per-holding)
   so the formatter can render BOTH explicitly.
5. **S7 events — TWO calls**:
   - **Portfolio-scoped** — `entity_ids=held, event_types=["earnings","analyst_action","corporate"]`, last 7 d.
   - **Macro-scoped** — `entity_ids=[], event_types=["macro","economic"]`, last 2 d.
   Merged into `recent_events`; each row tagged with `EventSummary.source_tier`
   ("portfolio" vs "macro") so the formatter groups them under the correct heading.

### Anti-pattern guard (BP-614 — silent data drop)

The brief is the canonical example of "the biggest bug is data we already
fetch but silently drop". Before PLAN-0102 W1, the gatherer fetched per-holding
quotes from S3, populated `BriefingContext.quotes`, but `format_market_overview()`
only rendered `MarketOverview.sector_performance` and the `market_overview`
field was NEVER set — so live quote data went into a black hole. Rule for
contributors:

- **Any new upstream data added to the gatherer MUST be paired with a render
  path in `BriefContextFormatter` in the same PR.** A dataclass field that no
  formatter method reads is functionally dead data and will be silently
  dropped at the prompt boundary.
- The gating site is `format_market_overview()` (Tape + Holdings + sector
  heatmap) and `format_news` / `format_events` / `format_alerts`. Audit each
  before claiming "the new field is wired".

See `docs/audits/2026-05-28-plan-0102-brief-redesign.md` for the full inventory
of fields the brief used to drop, and `docs/BUG_PATTERNS.md` BP-614 for the
detection / regression pattern.

---

## Morning Brief — Daily Pre-Generation (PLAN-0094)

PLAN-0094 W2 adds an APScheduler-driven worker (`rag-chat-brief-scheduler`
sidecar container) that pre-generates morning briefs for active users every
`N` hours. The handler now follows a **3-level lookup chain** so the user
never sees a 503 while regeneration is in flight or after a transient failure.

### 3-level lookup chain (`GET /api/v1/briefings/morning`)

1. **Fresh cache** — `briefing:morning:v2:{user_id}` (TTL `brief_fresh_ttl_hours`,
   default **30 h**). Hit → return with `is_stale=false`.
2. **Last-known-good** — `briefing:morning:lastgood:{user_id}` (TTL
   `brief_last_good_ttl_days`, default **7 d**). Hit → return with
   `is_stale=true`, `generated_at` from the cached payload. The handler also
   fires a background `asyncio.create_task` regeneration so the next request
   hits fresh — but does NOT wait for it. Increments
   `rag_brief_served_stale_total` + emits `brief_served_stale`.
3. **On-demand** — cold user (never had a brief): block while generating; on
   success write BOTH keys; on failure return 503 (preserves prior behaviour).

### Environment variables (prefix `RAG_CHAT_`)

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `BRIEF_PREGEN_ENABLED` | `true` | bool | Master switch for the scheduler. Disable to fall back to on-demand only (handler still serves lastgood). |
| `BRIEF_PREGEN_INTERVAL_HOURS` | `24` | 1–168 | Cadence between scheduler runs. **Recommended prod: 24.** Lower values waste LLM cost; higher risks stale-only serves between runs. |
| `BRIEF_PREGEN_ACTIVE_WINDOW_DAYS` | `7` | 1–90 | A user is "active" if they appear in the Valkey `active_users` sorted-set with score ≥ `now − window_days*86400`. **Recommended prod: 7.** |
| `BRIEF_PREGEN_BATCH_SIZE` | `50` | 1–500 | Users processed per concurrency batch. **Recommended prod: 50.** Tune up if LLM throughput is high; down if S6/S7 backpressure shows up. |
| `BRIEF_PREGEN_CONCURRENCY` | `4` | 1–20 | Max in-flight per-user generations within a batch (asyncio.Semaphore). **Recommended prod: 4.** Each user fans out 10+ tool calls; concurrency=4 means ~40 concurrent upstream calls. |
| `BRIEF_FRESH_TTL_HOURS` | `30` | 1–168 | TTL on the fresh cache key. Must be > interval so a missed run still serves fresh. **Recommended prod: 30** (= 24 h interval + 6 h safety margin). |
| `BRIEF_LAST_GOOD_TTL_DAYS` | `7` | 1–30 | Hard ceiling on staleness — older lastgood entries expire and fall through to on-demand. **Recommended prod: 7.** |

Out-of-range values raise `ValidationError` at startup so misconfiguration
surfaces immediately rather than at the first scheduler tick.

### Prometheus metrics (6 new)

| Metric | Type | Labels | Intent |
|--------|------|--------|--------|
| `rag_brief_pregeneration_runs_total` | Counter | `status` (`started` / `completed` / `failed`) | Scheduler run lifecycle. `started ≠ completed` over a window indicates crashes. |
| `rag_brief_pregeneration_users_total` | Counter | `outcome` (`success` / `generation_failed` / `skipped_stale_kept`) | Per-user pre-generation outcomes per run. `generation_failed` rate maps to lastgood ceiling pressure. |
| `rag_brief_pregeneration_run_duration_seconds` | Histogram | – | End-to-end run latency. Buckets up to 1800 s (= 30 min) — a healthy run should stay well under interval/4. |
| `rag_brief_pregeneration_user_duration_seconds` | Histogram | – | Per-user latency. Buckets up to 60 s — p99 should track typical brief-generation latency (~15–30 s). |
| `rag_brief_pregeneration_eligible_users` | Gauge | – | Active user count from the last run. Should approximately equal `ZCARD active_users` filtered by window. |
| `rag_brief_served_stale_total` | Counter | – | Times the handler served lastgood instead of fresh. Sustained non-zero rate = scheduler underperforming or interval too long. |

### structlog event taxonomy

The worker + handler emit a stable set of event names for log-based alerting:

| Event | Layer | Fired when |
|-------|-------|-----------|
| `brief_pregeneration_run_started` | worker | One scheduler tick begins |
| `brief_pregeneration_run_completed` | worker | Run finished (regardless of per-user failures); structured fields: `eligible_users`, `succeeded`, `failed`, `duration_ms` |
| `brief_pregeneration_run_failed` | worker | Run aborted by an unrecoverable error (e.g., Valkey hard-down). Never raised from `run()` — scheduler keeps firing. |
| `brief_pregeneration_user_started` | worker | Per-user attempt begins |
| `brief_pregeneration_user_succeeded` | worker | Per-user attempt landed both fresh + lastgood writes |
| `brief_pregeneration_user_failed` | worker | Per-user attempt raised; lastgood is **NOT** overwritten — preserves previous-day brief |
| `brief_served_stale` | handler | 3-level chain fell through to lastgood; carries `user_id`, `generated_at` |
| `brief_served_fresh` | handler | Fresh-cache hit (OPTIONAL — DEBUG level to avoid log noise) |

### `active_users` Valkey sorted-set contract

- **Key**: `active_users` (global, no tenant prefix — single-tenant deployment).
- **Member**: `str(user_id)` (UUID).
- **Score**: Unix epoch seconds at write time.
- **Writer**: S9 `OIDCAuthMiddleware` calls `await valkey.zadd("active_users", {user_id: int(time.time())})` after every successful internal-JWT validation. Fire-and-forget; Valkey errors logged at WARN but do NOT block the auth response.
- **Reader**: S8 `ActiveUsersReader.list_active()` runs `ZRANGEBYSCORE("active_users", now − window_days*86400, "+inf")` and parses each member as a UUID. Malformed members are skipped with a warning (don't abort the batch on one bad row).
- **Prune**: S9 fires a probabilistic prune (`if random.random() < 0.001`) running `ZREMRANGEBYSCORE("active_users", 0, now − 30*86400)` so entries older than 30 days clear out roughly once per 1 000 requests. 30 days is well above the maximum eligibility window (cap 90).

### Failure semantics — why lastgood matters

The lastgood TTL is the **staleness ceiling**. Within the window, any
per-user regeneration failure leaves the previous day's brief in place and
the frontend surfaces a "Previous day's brief — {date}" badge
(MorningBriefCard). The user never sees a 503 between failed-regeneration
and TTL expiry — UX continuity is preserved.

The worker **never overwrites** `briefing:morning:lastgood:{user_id}` on
failure — the only write path for lastgood is a successful regeneration.
This is the load-bearing invariant: if the worker overwrote on failure, a
transient LLM error could silently wipe the prior good copy.

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
weekly citation accuracy scoring (consumes LLM tokens).

## Chat Quality Benchmark

A standalone, descriptive benchmark runner that exercises `/v1/chat/stream`
on a curated question set and writes a structured run directory for offline
inspection. Distinct from the pytest acceptance gate in
`tests/validation/chat_eval/`: this script does NOT gate pass/fail on
percentiles — it captures everything (SSE events, tool calls, phase
timings, must_not_say hits, tracebacks) so a human can diagnose regressions
question-by-question.

### Files

* Catalogue: `tests/validation/chat_quality_benchmark/questions.yaml`
  — 22 prompts across `factual_lookup`, `screener`, `relationship`,
  `financial_data`, `news`, `comparison`, `signal`, `multilingual`,
  `adversarial`, `refusal_premise`. Tags include `real_user`,
  `smoke`, `aggregate`, `iter3`.
* Runner: `scripts/run_chat_quality_benchmark.py`
* Output: `tests/validation/chat_quality_benchmark/runs/run_<UTC-ts>/`

### Running

```
.venv312/bin/python scripts/run_chat_quality_benchmark.py \
    --base-url http://localhost:8000 \
    --questions-file tests/validation/chat_quality_benchmark/questions.yaml \
    --tags real_user,smoke \
    --out-dir tests/validation/chat_quality_benchmark/runs
```

Useful flags:

* `--tags A,B` — OR filter on tags (intersected with --ids).
* `--ids id1,id2` — run specific questions only.
* `--max-runs-per-q N` — repeat each question N times for flakiness check
  (artifacts get a `_runK` suffix).
* `--timeout-s` — per-request HTTP timeout (default 120s).

### Output layout

```
run_<UTC-ts>/
    _meta.json             base_url, started_at, ended_at, filters, totals
    _summary.json          bucket_counts + category_buckets + per_question list
    q_<id>.json            full structured artifact per question (one file)
    q_<id>.log             human-readable event-by-event trace
    q_<id>.error.txt       full traceback (only if the question raised)
```

`q_<id>.json` schema (top-level keys):

* `id`, `prompt`, `category`, `tags`
* `expected` — the YAML's expected_tools / entities / numeric_class /
  min_words / max_latency_s / must_not_say (for self-contained diffing).
* `bucket` — coarse PASS / WARN / FAIL / EXCEPTION (descriptive only,
  not an exit-code signal).
* `reasons` — bullet list of why a non-PASS bucket fired.
* `heuristics` — all advisory flags (see below).
* `result` — the full `ChatRunResult` dict including every SSE event in
  `raw_events`, all `tool_calls`, `tool_results`, `citations`,
  `phase_timings_ms`, etc.

### Interpreting heuristics

| Heuristic | Meaning |
|-----------|---------|
| `is_empty` | answer_text was blank after assembly |
| `is_refusal` | matched short-refusal detector (`grading.is_refusal`) — short answer with refusal token and no citations |
| `must_not_say_hits` | list of forbidden phrases from the YAML that appeared in the answer; non-empty drives `FAIL` |
| `entities_missing` | expected_entities_mentioned that did not appear (case-insensitive substring) |
| `tool_overlap_with_expected` | intersection of called vs expected tools (hint, not a gate) |
| `missing_expected_tools` | expected tools the agent did not call |
| `latency_s`, `ttft_s` | wall-clock E2E and time-to-first-user-visible event |
| `phase_timings_ms` | backend-reported phase timings from the `done` SSE event |
| `answer_meets_min_words` | True/False/None vs `expected_min_words` |
| `latency_within_budget` | True/False/None vs `expected_max_latency_s` |

Bucket derivation:

* `FAIL` — non-200 / error / empty answer / forbidden phrase hit.
* `WARN` — refusal, missing entity, short answer, slow answer, or no tools
  called when some were expected.
* `PASS` — none of the above.
* `EXCEPTION` — runner blew up (traceback in `q_<id>.error.txt`).

The runner always exits 0 on a completed run; non-zero only if the
question file is missing or filters match zero questions. Use it as an
artifact-producing job; gate pass/fail with `tests/validation/chat_eval/`.
