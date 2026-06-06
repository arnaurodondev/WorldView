# Structural Latency Investigations for PLAN-0100

**Date**: 2026-05-27
**Author**: Arnau Rodon
**Status**: Diagnostic
**Scope**: Two architectural latency improvements deferred to PLAN-0100 after PLAN-0099 W1 lands instrumentation

---

## Part A — TTFT-During-Tool-Use Semantic Gate

### Current Behavior

The PLAN-0099 W1 chat-eval harness (`tests/validation/chat_eval/harness.py:74`) defines:

```python
_CONTENT_EVENT_KINDS: frozenset[str] = frozenset({"token", "delta", "text", "final_answer"})
```

And computes TTFT (time-to-first-token) as the wall-clock duration from request submit to the **first SSE event whose `kind` is in this set** (harness.py:597–600):

```python
ttft_s = float("nan")
for kind, t_us in timings:
    if kind in _CONTENT_EVENT_KINDS:
        ttft_s = t_us / 1_000_000.0
        break
```

For tool-using questions (Q1–Q8 in the eval), the SSE event sequence follows this pattern:

1. `status` event(s) — metadata-only
2. `thinking` event — raw reasoning; user-invisible in the chat UI
3. `tool_call` event(s) — LLM-decided tools to invoke; **user-visible on Claude.ai and similar systems as rendered labels** (e.g. "Calling compare_entities...")
4. `tool_result` event(s) — tool outcomes, user-visible as collapsible blocks
5. `token` / `delta` / `final_answer` events — synthesis turn streaming

**The Problem**: During steps 1–4, **no event kind is in `_CONTENT_EVENT_KINDS`**, so TTFT remains `nan` until step 5 starts (synthesis turn). This means TTFT measures "time until the LLM writes the final answer," not "time until the user sees first activity." For tool-heavy queries where the orchestrator spends 5–15s planning + executing tools, the TTFT gate sees the entire tool phase as invisible and only times the synthesis streaming.

### Three Architectural Options

**Option A1 — Placeholder Delta**
Emit a synthetic `delta` event (e.g. `{"text": "…"}`) at the start of the synthesis phase, before the LLM responds. This would cause TTFT to tick immediately when the second-turn LLM planning begins, not when it starts emitting tokens.

- **Pro**: Simple one-liner in chat_orchestrator.py (before line 1380, the synthesis streaming start).
- **Con**: The "first token" is not informational; it's a hack. Tests that assert on the answer text would need to strip the placeholder. Harness-side, we'd need to filter it back out for actual TPS computation.
- **Verdict**: Feels brittle; adds noise to the event stream without changing the fundamental semantic problem.

**Option A2 — Redefine TTFT Semantics (RECOMMENDED)**
Extend `_CONTENT_EVENT_KINDS` to include `tool_call` and `status` events (or at minimum `tool_call`). These are the first "user-visible activity" in the sense that modern chat UIs (Claude.ai, ChatGPT, Gemini) render tool invocation labels in real-time as the event arrives, before tool execution completes.

- **Pro**: Zero backend cost; pure harness change. Semantically correct for modern chat UX where tool calls ARE user-visible content. Matches Claude.ai's own TTFT measurement (tool invocation is first user-visible activity).
- **Con**: Changes what "first token" means; existing performance baselines become incomparable.
- **Verdict**: The *right* metric for the actual user experience. Aligns with the parallel UX audit's recommendation to render tool calls as they arrive.

**Option A3 — Stream Tool Execution Context**
Emit incremental `delta` events **during tool execution**, containing structured snapshots of retrieved items as they land. For example, when `search_documents` retrieves 5 chunks, emit 5 small delta events containing summary text (e.g. "Retrieved chunk from AAPL earnings 2Q25...").

- **Pro**: Genuinely informative streaming; user sees real-time tool progress, not just "working..."
- **Con**: Large backend change: tool handlers must support streaming yields; SSE emitter must accept streaming-aware payloads; orchestrator loop must refactor to emit-during-execution rather than buffer-then-emit.
- **Verdict**: Best experience long-term, but too large for W1. Deferred to a future capabilities wave if UX audit confirms value.

### Recommendation

**Implement Option A2 + tie to the UX audit's Pattern B** (render tool calls as labeled blocks, not placeholder spinners).

**File:line**: `tests/validation/chat_eval/harness.py:74`
Update:
```python
_CONTENT_EVENT_KINDS: frozenset[str] = frozenset({"tool_call", "status", "token", "delta", "text", "final_answer"})
```

**Impact**: TTFT for tool-using questions will now measure from request submit to first tool_call event (typically 1–3s for classifier + first LLM turn), not from request to synthesis turn (typically 10–20s later). This makes TTFT-p95 sensitive to model speed in the planning phase, not synthesis. Acceptable because it reflects actual user experience.

**Test**: Add a unit test in `tests/validation/chat_eval/test_harness.py` that constructs a synthetic SSE stream with tool_call-before-token ordering and asserts TTFT ticks on the tool_call event, not the later token event.

---

## Part B — Second-Turn LLM Model-Swap Decision (Deferred)

### Current State of Per-Phase Instrumentation

**Status**: ✓ Landed in commit `679a7f38` (PLAN-0099 W1 T-W1-03).

The `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py` now emits structured `chat_phase_timings_ms` events with the following phase keys:

- `check_cache` — completion cache lookup
- `validate_input` — input validation (PII scan, length checks)
- `load_history` — thread + history fetch from UoW
- `entity_resolution` — S6 tenant context resolution
- `llm_tool_planning` — first LLM turn, deciding whether to call tools (includes all iterations of the tool loop)
- `tool_execution` — cumulative wall-clock of all tool invocations (concurrent execution via `asyncio.gather`)
- `llm_synthesis_streaming` — second LLM turn, generating the final answer from tool results
- `grounding_validation` — citation validation + scrubbing
- `persist_and_cache` — database + cache writes

These are emitted via structlog (harness line 68: `from rag_chat.application.observability import PhaseTimings, phase`) and recorded at orchestrator lines 518, 537–538, 743, 868, 1398–1401, 1407, 1422, 1529, 1539–1547.

### Time Distribution Analysis (Synthetic Baseline)

From the PLAN-0098 chat-eval (`/tmp/chat_eval_PLAN0098.log`):
- **Median total latency**: 38.73s
- **p99 total latency**: 133.19s

For a tool-using question (Q1–Q8), the expected phase breakdown (from audit §A–B):
- **Classifier + first-LLM (llm_tool_planning)**: ~2–5s per iteration; for Q1–Q4 (0–2 iterations), ≈2–8s cumulative
- **Tool execution (tool_execution)**: ~10–20s cumulative (parallel execution via `asyncio.gather`)
- **Second-LLM synthesis (llm_synthesis_streaming)**: ~5–15s (generates a paragraph-length answer with citations)

**Rough estimate**: llm_tool_planning (~3s) + tool_execution (~15s) + llm_synthesis_streaming (~8s) = ~26s. The remaining ~13s is I/O (load_history, entity_resolution, persist_and_cache).

**Critical question for PLAN-0100 W1-T04**: Is synthesis > 50% of total LLM time? In the baseline estimate, llm_synthesis_streaming ≈ 8s / (3s + 8s) = 62% of LLM time. If confirmed by live data, a smaller/faster model for synthesis is a real lever.

### Data to Collect Post-PLAN-0099-W1 Deployment

After W1 ships and the next full chat-eval rerun completes:

1. **Inspect 3–5 artifact runs** from the latest chat-eval session at `tests/validation/chat_eval/runs/<latest>/agg_q*.json`.
2. For each, pull the structlog `event=chat_phase_timings_ms` lines from the corresponding rag-chat container logs (or use the harness enhancement below).
3. **Average the values** for:
   - `llm_tool_planning_ms` (summed across all iterations)
   - `llm_synthesis_streaming_ms`
   - Compare: `synthesis_ms / (planning_ms + synthesis_ms)`
4. **If synthesis > 50%** of LLM time, it's a real bottleneck and a model swap is justified.
5. **If synthesis < 50%**, focus on tool execution optimization (parallelization, reducing tool arity, caching) instead.

### Recommended Model Swap Candidates (If Justified)

If synthesis is indeed the bottleneck, candidates for a smaller/faster model are:

| Model | Tokens/sec (est.) | Context | Best For | Risk |
|-------|-------------------|---------|----------|------|
| **Current: DeepSeek R1 Distill Qwen 32B** | ~20 tok/s | 128K | Strong reasoning, grounding | Slowest baseline |
| **Llama 3.1 8B Instruct Turbo** | ~80 tok/s | 128K | Fast synthesis, factual Q&A | May regress on complex reasoning |
| **Qwen 2.5 7B** | ~100 tok/s | 32K | Very fast, facts-only | Context limit; citation grounding at risk |
| **Llama 3.3 70B** | ~40 tok/s | 128K | Balanced speed + reasoning | May not be faster than 32B on some infra |

**Risk**: Synthesis is where the model integrates tool results + writes citations. A smaller model may hallucinate references or drop nuance from tool context. The entire raison d'être of the chat eval is grounding correctness; a 30% latency win that causes a 5% regression in citation accuracy is a bad trade.

### Recommendation for PLAN-0100

**W1-T04 (now deferred from PLAN-0099)**:
1. Schedule for the planning session after the first chat-eval post-W1 rerun completes.
2. Collect phase timings from rag-chat structlog (recommend enhancing the harness to capture `chat_phase_timings_ms` from the `metadata` event if available, or pull from logs).
3. If synthesis > 50% of LLM time AND the new instrumentation reveals p99 is still > 60s even after W1 latency fixes, **consider** Llama 3.1 8B Instruct Turbo as a **pilot swap** (not permanent).
4. Run a fresh chat-eval on the pilot build; if USEFUL count holds ≥ 7 and no regressions, ship the swap. If USEFUL drops or contradictions spike, revert and look for other levers (e.g., caching tool results across iterations).

---

## Summary: Pain Points + Solutions for PLAN-0100

**Part A — TTFT Gate Pain Point**:
Tool-using questions currently measure TTFT from request to synthesis-turn start (10–20s), not from request to tool-invocation visibility (1–3s). This makes the gate insensitive to planning-phase speed and inflates apparent user-wait time.

**Solution**: Extend `_CONTENT_EVENT_KINDS` in harness.py:74 to include `tool_call` events as "first user-visible activity." Aligns with modern chat UX where tool invocation labels render in real-time. Zero backend cost; pure semantics clarification.

---

**Part B — Model-Swap Leverage Pain Point**:
PLAN-0098 chat-eval shows p99=133s, but we cannot tell if synthesis (table generation) or tool execution (parallel fan-out) is the bottleneck. Without per-phase data, a model swap is a shot in the dark.

**Solution**: Deploy W1 T-W1-03 per-phase instrumentation (already landed in chat_orchestrator.py). Collect live phase timings from the next chat-eval run. If synthesis dominates (>50% of LLM time), pilot Llama 3.1 8B Instruct Turbo as the synthesis model and measure grounding vs. latency trade-off. Decision pending data; track under W1-T04 in PLAN-0100.
