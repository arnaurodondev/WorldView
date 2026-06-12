# Chat-Eval Failure Traceback — 2026-06-12

**Scope**: Diagnostic sweep of the chat-quality benchmark (`tests/validation/chat_quality_benchmark/questions/*.yaml`, 67 questions across 5 packs) against the live stack (S9 @ `http://localhost:8000`, dev-login → 200). Runner: `scripts/run_chat_quality_benchmark.py --max-runs-per-q 1` (no `--judge` — the goal is *why* answers fail, not judge scores).

**Run artifacts**: `tests/validation/chat_quality_benchmark/runs/run_20260612T055734Z/`

**Coverage note**: The benchmark is gated by DeepInfra Qwen3-235B latency (~30–60 s/question; some grounding-rewrite questions hit 130 s = the harness timeout). The single live stack runs questions sequentially, so a full 67-question sweep takes ~60–90 min. This audit fully triaged **pack `00_real_user_and_aggregate` (24 q)** — the highest-signal pack carrying the user-reported failures — plus the leading edge of **pack `10_tool_coverage`** (alerts, earnings, entity-graph surfaces). Every genuine failure was root-caused to a concrete file/service. The remaining `10`/`20`/`30`/`40` questions were still running at write time; the structural root causes below are catalogue-wide and will recur there (`tc_*` screener/graph, `chain_*` multi-tool, `da_*` graph/screener questions). `chain_apple_suppliers_high_margin` and `tc_relations_msft_acquisitions` will hit the same KG-supplier-sparsity + grounding-latency path already observed in `tc_entity_graph_filtered_relations` (130 s, 11 tool calls).

**Distinct root causes found (8)**: across 4 services — rag-chat (5), knowledge-graph (1), market-data (1), S6/nlp-pipeline (1). No DeepInfra-402 / injection-classifier (category c) failures surfaced.

---

## Failure table (pack 00, fully triaged)

| Question | Symptom | Traced component | Root cause | Category | Severity |
|----------|---------|------------------|------------|----------|----------|
| `agg_q1_apple_competitors` | Answer: "Apple's main competitors are not explicitly listed… not available in retrieved context" despite tools `ok` | `chat_orchestrator.py:1456` (`entity_context = entities[0]`) + `handlers/narrative.py:111` (`entity_context_override`) + S6 `resolve_entities` ranking | LLM passed correct `entity_id: "AAPL"` to `get_entity_intelligence`, but the orchestrator scoped `entity_context` to **`entities[0]` from S6 resolve = "Alexandria Real Estate Equities" (f5d35022…)** and the NarrativeHandler override **discarded the LLM's AAPL**, loading the wrong company's bundle. Log: `entity_context_override llm_entity_id=AAPL scoped_entity_id=f5d35022…`. | (a) platform + (b) agent design | **HIGH** |
| `ru_openai_msft_paths` | "I cannot reach the knowledge graph… 504 Gateway Timeout" non-answer | `services/knowledge-graph/.../use_cases/cypher_path.py:126` (`_STATEMENT_TIMEOUT_MS="5000"`) + `chat_orchestrator.py:752` (`_FALLBACK_MAP` has no `traverse_graph` entry) | `traverse_graph` → `POST /api/v1/graph/cypher/path` with undirected `(s)-[*1..3]-(t)` between two hub entities (Microsoft, e03e64b8…) exceeds the **5 s** AGE `statement_timeout` → `cypher_path_timeout` → 504. No fallback to `get_entity_paths`, so a single 504 dead-ends the answer. | (a) platform | **HIGH** |
| `ru_nvda_amd_compare_qtr` | Final answer is raw tool-call JSON: ```{"get_fundamentals_history": {"ticker": "NVDA", "periods": }}``` (degenerate, malformed) | `chat_orchestrator.py:1720-1758` (`direct_text` path) + `:205-245` (`_strip_tool_call_json` regex shape) | On a later agent iteration `chat_with_tools` returned **prose `text` that was actually a malformed tool-call stub** (`{<tool_name>: {<args>}}`, `"periods":` empty). That `direct_text` becomes `full_text` and is streamed **without `_strip_tool_narration`** (the scrubber only runs on the streaming second-turn branch, skipped here via `_skip_final_stream=True`). Even if it ran, the BP-675 scrubber (`_is_json_tool_call_object`) only matches `{"name":…, "arguments":…}` shape — it does **not** cover the `{tool_name: {args}}` leak shape. Log: `numeric_grounding_rewrite_rejected_tool_call_stub`. | (b) agent | **HIGH** |
| `ru_ai_semi_screener` | Heuristic PASS, but answer relies on a hardcoded "AI-semi allowlist" + **LLM-hand-computed** YoY %; `numeric_grounding_failed unsupported_count=39` | `services/rag-chat/.../handlers/market.py:1245-1271` (`_handle_screen_universe` row formatter) | The screener `POST /v1/fundamentals/screen` **returns** `revenue_growth_yoy` (NVDA 0.852), `revenue`, `pe_ratio`, `roe`, `market_cap` per instrument, but the rag-chat formatter renders **only `ticker | name | MCap | P/E`** and drops the metric the user filtered on. The LLM therefore can't ground "YoY revenue growth", calls `get_fundamentals_history_batch`, hand-computes ratios, and those LLM-derived numbers fail `NumericGroundingValidator`. | (a) platform (rag-chat) | **MEDIUM-HIGH** |
| `iter3_top5_tech_marketcap` | Confidently WRONG top-5: NVDA, AAPL, MSFT, **CRM ($143B), IBM** (should be GOOGL/AVGO/META) | `services/market-data` screener (no default `ORDER BY`) + `handlers/market.py` (`limit=20`, no sort param) | `POST /v1/fundamentals/screen` returns rows in **arbitrary order** (live: CRM, AAPL, MSFT, NVDA, MSTR, IBM, …) and truncates at `limit` while `total=96`. The LLM "sorted" only the first 20 it saw, so the true #4–#5 (GOOGL/AVGO/META) were never in the sample. Heuristics miss this (answer is well-formed). | (a) platform (market-data) | **MEDIUM-HIGH** |
| `agg_q3_tim_cook` | "platform's corpus doesn't contain detailed biographical data on Tim Cook's pre-Apple career" (rubric wants Compaq/IBM) | KG entity intelligence bundle + S6 `search_documents` corpus | `get_entity_intelligence` for Tim Cook returns a bundle with no biographical/employment history; `search_documents` (8+10 hits) doesn't surface Compaq/IBM. Genuine **data-coverage gap** in the KG/corpus for person-entity biography. | (a) platform data gap | LOW |
| `agg_q5_tsla_macro` | WARN (slow); agent called `get_economic_calendar` **5×** + `search_documents` 4× (10 calls), most returning 0–1 items | `chat_orchestrator.py` per-turn `_tool_result_cache` (dedup keyed by `(tool, frozenset(args))`) + sparse economic-calendar data | Repeated near-identical `get_economic_calendar` calls were not deduped (different args each time → cache miss) while the calendar legitimately returns ~0 forward events; the agent thrashed tools and blew the latency budget. Partly data sparsity, partly weak dedup across arg-variant retries. | (b) agent + (a) data | LOW-MEDIUM |
| `agg_q7_tsla_contradictions` | `get_contradictions` empty → "no contradictions detected" | n/a | **Expected.** Rubric notes "Empty finding allowed"; the answer correctly explains the empty result. | (d) expected | none |
| `agg_a10_apple_anthropic_premise`, `iter3_tsla_yesno_speculation` | Refusals | n/a | **Expected.** False-premise / speculation guardrails — these SHOULD refuse. | (d) expected | none |

---

## Failure counts by category (pack 00, n=24)

- **(a) Platform/backend bug or data gap**: 5 — `agg_q1_apple_competitors` (entity resolve), `ru_openai_msft_paths` (AGE 5 s timeout), `ru_ai_semi_screener` (rag-chat field-drop), `iter3_top5_tech_marketcap` (market-data no sort), `agg_q3_tim_cook` (KG biography gap). (`agg_q5_tsla_macro` straddles a+b.)
- **(b) Agent/LLM behaviour**: 2 — `ru_nvda_amd_compare_qtr` (tool-call-stub leak), `agg_q5_tsla_macro` (tool thrash). `agg_q1` also has an agent-design component (blind `entities[0]` override).
- **(c) Infra (DeepInfra-402 / injection-classifier)**: 0 observed in pack 00. (Owned by the separate `injection-fix` agent; none surfaced.)
- **(d) Expected refusals**: 3 — `agg_q7_tsla_contradictions`, `agg_a10_apple_anthropic_premise`, `iter3_tsla_yesno_speculation`.
- **Clean PASS**: the remainder (e.g. `ru_mstr_news`, `iter3_apple_revenue_precision` with `[get_fundamentals_history row 0]` citation, `iter3_nvda_pe_conditional`, `iter3_tesla_revenue_since_2023`).

---

## Top platform root causes (highest leverage first)

### 1. AGE Cypher path timeout — 5 s is too tight for hub entities (PLATFORM, HIGH)
**Failing**: `ru_openai_msft_paths` (and any `traverse_graph`/path question with a well-connected node — will also hit `tc_relations_msft_acquisitions`, `chain_apple_suppliers_*`, `da_*` graph questions).
**Where**: `services/knowledge-graph/src/knowledge_graph/application/use_cases/cypher_path.py:126` — `_STATEMENT_TIMEOUT_MS = "5000"`. The neighborhood query gets **20 000 ms** (`cypher_neighborhood.py:65`); the path query gets only 5 000 ms for a strictly harder `(s)-[*1..N]-(t)` undirected variable-length match. Microsoft resolved to `e03e64b8-…`; the `[*1..3]` walk between two hubs exceeds 5 s. Log chain: rag-chat `upstream_5xx path=/api/v1/graph/cypher/path status=504 elapsed_ms=5083`; KG `cypher_path_timeout` → `504 Gateway Timeout`.
**Recommended fix**:
- Raise `_STATEMENT_TIMEOUT_MS` for the path query to **15–20 s** (match the neighborhood budget), AND
- Add a `traverse_graph → get_entity_paths` entry to `_FALLBACK_MAP` (`chat_orchestrator.py:752`) so a single 504 falls back to the pre-computed S9→S7 `/paths` endpoint instead of dead-ending. (`get_entity_paths` was the rubric's co-expected tool but was never attempted.)
- Longer term: bound the path search (cap on intermediate degree / shortest-first early exit) so hub-to-hub paths don't scan O(degree^N).

### 2. Entity-context override discards the LLM's correct entity_id (PLATFORM + AGENT, HIGH)
**Failing**: `agg_q1_apple_competitors` (and any intelligence/narrative/paths question whose first S6-resolved entity ≠ the LLM's intended ticker — silent wrong-entity answers).
**Where**: `chat_orchestrator.py:1456-1465` blindly takes `entity_context = entities[0]` from `resolve_entities(question_text)`; `handlers/narrative.py:111-119` (`_resolve_intel_entity_id`) then **always** lets the scoped context win and logs `entity_context_override` — discarding the LLM's `entity_id: "AAPL"`. S6 `resolve_entities("Who are Apple's main competitors?")` ranked **Alexandria Real Estate Equities** as `entities[0]`. The correct `ticker_resolved_twin_disambiguated → Apple Inc. (01900000…001001)` fired only for `search_documents` (the separate `entity_tickers` path), too late to help.
**Recommended fix**:
- When the LLM supplies a concrete `entity_id`/ticker AND it resolves to a valid entity, **do not override it** with the question-level `entities[0]`; reserve the override for the pinned entity-context endpoints (`/chat/entity-context`) where scoping is intentional. At minimum, only override when the LLM arg is empty/unresolvable.
- Independently, fix S6 resolve ranking so an exact company token ("Apple") outranks an unrelated REIT; the multi-entity `entities[0]` heuristic is fragile for relationship/comparison questions that name one primary company.

### 3. Tool-call-stub leaks into the final answer (AGENT, HIGH)
**Failing**: `ru_nvda_amd_compare_qtr` (degenerate JSON answer; same shape seen historically on `ru_nvda_amd_revenue_4q`).
**Where**: `chat_orchestrator.py:1720-1758` — the `direct_text` branch streams `chat_with_tools`'s `text` content as the final answer and sets `_skip_final_stream=True`, **bypassing `_strip_tool_narration`** (which runs only at `:2823` in the streaming-second-turn branch). Confirmed by log `numeric_grounding_rewrite_rejected_tool_call_stub response_len=3025` while the delivered answer was 45 output tokens of stub.
**Intermittency / reproducibility**: This is a **stochastic** LLM-behaviour failure, ~1-in-6 across runs (prior dirs `run_20260612T051019Z` and `run_..T053413Z` ran `ru_nvda_amd_compare_qtr` 3× each; 1 of 6 leaked, plus 1 in this sweep — the other 4-5 produced clean comparison tables). Critically, the prior leak had shape `{"name": "get_fundamentals_history_batch", "arguments": {…}}` — **exactly the `{name, arguments}` shape the BP-675 scrubber `_is_json_tool_call_object` (`:227`) DOES target** — yet it still shipped. That proves the **primary defect is the `direct_text` path never invoking the scrubber at all** (`:1743`), not the regex shape. The shape gap (`{tool_name:{args}}`, seen in this sweep) is a secondary issue that matters only once the scrubber is wired into the direct-text path.
**Recommended fix**:
- Run `_strip_tool_narration` on `direct_text` **before** streaming it (line ~1743), not just on the second-turn path.
- Extend the scrubber to detect the `{<known_tool_name>: {…}}` shape (match against the live tool registry names) in addition to `{name, arguments}`. If after scrubbing the `direct_text` is empty/degenerate, fall through to the normal streaming synthesis turn rather than shipping the stub.

### 4. Screener drops the metric fields it was filtered on (PLATFORM rag-chat, MEDIUM-HIGH)
**Failing**: `ru_ai_semi_screener` (forces hand-computed YoY → `numeric_grounding_failed unsupported_count=39`).
**Where**: `services/rag-chat/src/rag_chat/application/pipeline/handlers/market.py:1245-1271` — `_handle_screen_universe` renders only `ticker | name | MCap | P/E` even though the live `POST /v1/fundamentals/screen` response carries `revenue_growth_yoy`, `revenue`, `operating_margin`, `roe`, `forward_pe`, `eps_ttm`, etc. per row.
**Recommended fix**: Render every filter metric the LLM supplied (and a small core set: `revenue_growth_yoy`, `revenue`, `pe_ratio`) into the screener table, with raw values for the numeric-grounding validator. This removes the need for the LLM to re-fetch fundamentals and hand-compute ratios, eliminating the grounding failure.

### 5. Screener has no default ORDER BY → wrong "top-N by X" answers (PLATFORM market-data, MEDIUM-HIGH)
**Failing**: `iter3_top5_tech_marketcap` (CRM/IBM in the top-5 instead of GOOGL/AVGO/META). Will also corrupt any "biggest/top/highest N" screener question.
**Where**: market-data `POST /v1/fundamentals/screen` returns rows in arbitrary order (live first-20: CRM, AAPL, MSFT, NVDA, MSTR, IBM, ANET, …; `total=96`) and the rag-chat handler caps at `limit=20` with no sort param.
**Recommended fix**: Add `sort_by` / `sort_dir` to the screen request and default ordering to the primary filter metric descending; have `_handle_screen_universe` request `sort_by=market_capitalization desc` for "top by market cap" intents and pass a larger `limit` when the user asks for an explicit ranking, so the true top-N is in the rendered sample.

---

---

## Pack 10 (`10_tool_coverage`) — partial triage

| Question | Symptom | Traced component | Root cause | Category | Severity |
|----------|---------|------------------|------------|----------|----------|
| `tc_create_alert_nvda_below` | "Set an alert when NVDA drops below $400" → agent calls **`get_entity_intelligence`**, never `create_alert`; only asks "Shall I go ahead?" and appends two grounding warnings. **No alert created, no `pending_action` emitted.** | LLM tool selection (first-turn planning) + `tool_registry_builder.py` `create_alert` description | The write-action question routed to the wrong read tool (`get_entity_intelligence(entity_id=f25d59e5…)`) instead of `create_alert`. The PLAN-0082 `pending_action` confirmation flow never triggered because `create_alert` was never selected. The "$400"/"NVDA" in the prose then trip numeric/entity grounding (nothing tool-sourced them). | (b) agent (mis-route) | MEDIUM |
| `tc_get_alerts_list_active` | WARN (latency) | `get_alerts` ok (20 items) | Functionally correct (lists 12 alerts); only the latency budget tripped. | (d) acceptable | none |

**Implication**: `create_alert` is under-selected vs `get_entity_intelligence`. Tighten the `create_alert` tool description ("**Use this — not get_entity_intelligence — when the user asks to set/create/notify/alert on a price or condition**") the same way the fundamentals-batch directive was hardened (`.claude-context.md` PLAN-0097 pattern), and confirm `pending_action` fires for confirmed write actions.

### Pack-10 root cause: entity-grounding guard FALSE-REFUSES universe/aggregate questions (PLATFORM rag-chat, HIGH)
**Failing**: `tc_earnings_next_week_universe` ("Which S&P 500 names report earnings next week?") → refusal **"I cannot find information about the entities in your question… data returned referenced different entities"** despite `get_earnings_calendar` returning a valid calendar.
**Where**: `chat_orchestrator.py` `_check_entity_grounding()` (BP-604/605, `.claude-context.md` PLAN-0100 W1) + `handlers/market.py:1505-1511` (earnings-calendar item built with `entity_name=None`).
**Root cause** (from log `entity_grounding_failed`): the universe question has **no specific company**, so S6 mis-resolved the "question entities" to garbage (`question_ids=["41c379f9…", "p", "pandora"]`). The earnings-calendar `RetrievedItem`s carry `item_entity_names=[null, null]`. Zero overlap between (garbage) question entities and (null) item entities → the grounding gate refuses, replacing a valid answer with a fixed "I cannot find information…" string. The guard assumes every question is single-entity-scoped; for universe/screener/aggregate questions there is no anchor entity to ground against and the gate should be **bypassed**, not fire a refusal.
**Recommended fix**: Skip `_check_entity_grounding` (or treat as auto-pass) when the resolved question-entity set is empty/low-confidence OR the intent is universe/aggregate/screener; AND populate `entity_name` on calendar/screener/movers `RetrievedItem`s so multi-entity tool output can ground at all. This is the same class as the `agg_q1` override bug — both stem from rag-chat assuming a single primary entity per question.

### Pack-10 root cause: `grounding_validation` latency blowup (PLATFORM rag-chat, MEDIUM)
**Observed**: `tc_entity_graph_filtered_relations` ("companies that are suppliers to Apple") ran **130.5 s** (= harness timeout) with **11 tool calls** (most empty: `search_entity_relations` ×2 empty, `search_documents` ×3 empty, `get_entity_paths` empty) and `grounding_validation: 69310 ms` inside `total_ms: 130435`. Combines KG supplier-relation sparsity + tool thrashing + grounding-rewrite latency. The numeric/entity grounding rewrite turns issue **additional** `stream_chat` LLM calls (each 18–50 s on Qwen3-235B); when both numeric and entity grounding flag and re-prompt, latency compounds past 2 minutes.
**Recommended fix**: Cap total grounding-rewrite wall-clock (single shared budget across numeric + entity rewrites), and skip the rewrite entirely when the flagged tokens are an error code or a universe-level enumeration the validator structurally cannot verify.

### Pack-10 confirmation: `get_entity_graph` (neighborhood) is healthy — the AGE timeout is path-query-specific
`tc_entity_graph_tesla_neighbors` returned Tesla's neighbors (Elon Musk `has_executive`, …) correctly via `get_entity_graph` (depth=1). This isolates root cause #1 to the **`cypher/path`** endpoint's 5 s `statement_timeout`, NOT to AGE/neighborhood queries generally.

### Pack-10 minor: `get_earnings_calendar` has no ticker filter
`tc_earnings_apple_next` ("When does Apple next report earnings?") → "not available in retrieved context" because `_handle_get_earnings_calendar` (`handlers/market.py:1451`) takes only `from_date`/`to_date`, fetches a **global** calendar, and renders the first 30 rows — AAPL's date wasn't in the window/sample. `appropriate_refusal_ok=true` so this is borderline, but adding a `ticker` parameter would let single-company earnings-date questions answer directly. LOW.

---

## Notes / methodology

- Triage flags (`tests/validation/chat_quality_benchmark/runs/.../q_<id>.json` → `result.{answer_text,tool_calls,tool_results,raw_events,phase_timings_ms,status_code}` cross-referenced with `docker logs worldview-{rag-chat,knowledge-graph,market-data}-1`).
- The runner's heuristic `bucket` (PASS/WARN/FAIL) under-reports: degenerate-but-non-empty answers (`ru_nvda_amd_compare_qtr`), wrong-entity answers (`agg_q1`), and confidently-wrong ordered lists (`iter3_top5_tech_marketcap`) all bucket **PASS** because they are non-empty, non-refusal, and within latency. The genuine signal is in answer content + tool-result status + backend logs, not the bucket.
- No DeepInfra-402 / injection-classifier failures (category c) surfaced in pack 00; if they appear in `40_safety_adversarial`, tag and defer to the `injection-fix` agent per the mission.
- `READ-ONLY`: no source/test/config edited. Only this report + the benchmark run dir were created.
