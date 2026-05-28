---
id: audit-2026-05-27-plan-0099-latency-metric-redesign
title: PLAN-0099 W1 T-W1-03 — Latency Metric Redesign (TTFT + TPS)
date: 2026-05-27
author: claude-code
tags:
  - latency-metrics
  - ttft
  - time-to-first-token
  - tokens-per-second
  - chat-eval
  - rag-chat
  - PLAN-0099
---

# Latency Metric Redesign: TTFT + TPS Replacement for End-to-End P99

## §1 — What Today's Gate Measures (and Why It's Broken)

### Current state

The acceptance gate in `tests/validation/chat_eval/test_aggregate_score.py:103-125` enforces two latency constraints:

```python
_MEDIAN_LATENCY_MAX_S = 30.0  # line 55
_P99_LATENCY_MAX_S = 60.0     # line 56
```

These gates assert:
- `median latency ≤ 30.0s`
- `p99 latency ≤ 60.0s`

The latency value (`result.latency_s`) comes from the harness in `tests/validation/chat_eval/harness.py:235-270`:

```python
start = time.monotonic()  # line 235
# ... fires request, reads SSE stream ...
return ChatRunResult(..., latency_s=time.monotonic() - start)  # line 270
```

This is **wall-clock time from request submission to final SSE event** (the `done` event, emitted by `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py:138-146`).

### The problem (user-stated)

**End-to-end latency is not a fair user-experience proxy.** Why:

1. **Tool-call count contamination**: A 2-tool query takes longer than a 1-tool query by definition. A query that invokes `search_documents` → `traverse_graph` → `search_claims` (3 tools) will be slower than a simple `get_entity_intelligence` call (1 tool). The p99 gate doesn't distinguish between "slow because the LLM is slow" and "slow because the user asked a hard question that requires 3 tools."

2. **Query complexity variance**: E2E latency conflates:
   - **Classifier latency** (intent detection in upstream system)
   - **First-turn LLM latency** (tool selection + reasoning)
   - **Tool fan-out latency** (parallel tool execution)
   - **Second-turn LLM latency** (post-tool table/summary generation — often slower on structured output)
   - **Streaming latency** (token-by-token transmission, fixed overhead)
   - **Provider variance** (DeepInfra slow request, EODHD 429 timeout + retry)

   A query that hits a provider timeout on fundamentals lookup will always exceed 60s. But that's not a "responsiveness" problem — it's a "data availability" problem.

3. **User perception mismatch**: What matters to the user is:
   - **TTFT (time-to-first-token)**: "How long until I see the model thinking?" Typical target: <5s. After classifier + intent detection, the user sees "Thinking..." immediately. Then the first LLM token arrives. This is the key responsiveness signal.
   - **TPS (tokens per second)**: "How fast is the model talking?" Typical target: ≥30 tok/s. A streaming response at 30 tok/s reads naturally (one word per ~100ms). Below 10 tok/s feels like the model is stalling.
   - **E2E (for single-tool / simple queries only)**: For straightforward questions ("What is AAPL's revenue?") that need only one tool call and no complex table generation, E2E should be <20s. But multi-tool or heavy-output queries legitimately take longer.

### Current artifact evidence

From `tests/validation/chat_eval/runs/20260527T184650Z/agg_q4.json`:
- **Latency**: 111.536s (p99 will fail at 133s baseline from `/tmp/chat_eval_PLAN0098.log`)
- **Raw events**: 11 SSE events (`status`, `thinking`, `tool_call`, `tool_result`, `token`, `final_answer`, `citations`, `contradictions`, `metadata`, `done`)
- **Problem**: No per-event timestamps in `raw_events`. The harness only records the *total* wall-clock time, not the breakdown.

From `tests/validation/chat_eval/runs/20260527T184650Z/agg_q1.json`:
- **Latency**: 17.83s (one tool, simple answer — would pass both gates easily)
- **Tool calls**: 1 (`get_entity_intelligence`)
- **Event count**: 11 (identical structure)

The artifact structure shows:

```python
# From grading.py:531 — latency is recorded per-response
result.latency_s  # single float, no breakdown
```

**Current inability to compute TTFT/TPS**: The raw events don't carry timestamps. To measure TTFT, we'd need to know when the first `token` event was emitted relative to the request start. To measure TPS, we need total output tokens and wall-clock generation time.

---

## §2 — Proposed TTFT + TPS + Relaxed E2E Gates with Rationale

### Three-metric redesign

Replace the single p99-latency gate with three metrics:

| Metric | Type | Current behavior | Proposed gate | Rationale |
|--------|------|-------------------|---------------|-----------|
| **TTFT** (time-to-first-token) | p95 | Not measured today | **< 5.0 s** | User sees "Thinking..." after classifier + first LLM turn. ≤5s on DeepInfra is realistic with good cache hit. Captures responsiveness. Harder than p99 because tail variance is smaller — if classifier is slow, TTFT suffers. |
| **TPS** (tokens per second) | p50 (median) | Not measured today | **≥ 30.0 tok/s** | Streaming UX readability. At 30 tok/s, one token lands ~every 33ms. Below 10 tok/s the stream feels stalled. Median (not p99) because we care about the typical user experience, not the absolute slowest path. |
| **E2E (end-to-end)** | p99 | 60.0 s (fails today at 133s) | **< 90.0 s** (relaxed from 60) | Eliminates multi-tool penalty. A 3-tool query with parallel execution + summarization legitimately takes 60-80s. We gate on p99 to catch outliers (provider timeout, DLQ retry loop, 5-tool cascade), but we accept the wider bound because query complexity varies. |

### Why this wins over status quo

**Decouples user experience from query complexity**:
- Q1 ("Apple competitors") is 1 tool → fast TTFT, high TPS, low E2E.
- Q4 ("NVIDIA vs AMD revenue comparison") is multi-tool + structured table → same TTFT expectation (model start time is fixed), TPS might be lower (more tokens per table), E2E wider (tool fan-out + table generation).
- Both pass if the user felt responsive — TTFT fired quickly, tokens streamed at >30 tok/s.

**Catches real regressions**:
- If the classifier gets slow (°500ms → 2s regression), TTFT catches it.
- If the LLM backend degrades (DeepInfra downtime, fallback to slower provider), TPS drops.
- If a tool starts hanging (S3 timeout), E2E at p99 catches the tail.

**Enables diagnostic data for PLAN-0100**:
- Per-phase instrumentation (see §3 below) will show which phase dominates each run. If TTFT is fine but TPS is low, the second-turn LLM is the bottleneck → model swap candidate.

---

## §3 — Where to Instrument (File:Line)

### Harness changes (§3.1)

File: `tests/validation/chat_eval/harness.py`

1. **Add request timestamp to SSE stream**
   - `harness.py:235` — Request starts with `start = time.monotonic()`. Pass this to `_events_to_result`.
   - `harness.py:342-402` — Modify `_events_to_result(question, status_code, events, latency_s, request_start: float)`.
   - In the loop over events (line 357), record the *sequence position* of the first `token` event.

2. **Compute TTFT from first-token position**
   - After folding all events (line 401+), inject:
     ```python
     ttft_s = (events[first_token_idx].get("timestamp") or (request_start + latency_s)) - request_start
     ```
   - BUT: events currently don't have server-side timestamps. We need harness-side collection.
   - **Better approach**: the harness calls `_read_sse_events(resp)` at line 269. Modify it to record harness-side timestamps:
     ```python
     def _read_sse_events(resp, request_start: float) -> list[dict[str, Any]]:
         events: list[dict[str, Any]] = []
         for raw_line in resp.iter_lines():
             ...
             if line == "":
                 if current:
                     ev = _parse_event(current)
                     ev["_harness_recv_time"] = time.monotonic()  # NEW
                     events.append(ev)
     ```
   - Then compute TTFT as:
     ```python
     first_token_idx = next((i for i, e in enumerate(events) if e["event"] == "token"), None)
     if first_token_idx is not None:
         ttft_s = events[first_token_idx]["_harness_recv_time"] - request_start
     else:
         ttft_s = float("nan")  # No token event = error case
     ```

3. **Compute TPS from token count + generation window**
   - Count all `token` events in raw_events (or sum their text lengths). Divide by wall-clock from first-token to `done` event.
   - File: `harness.py:390+` (in `_events_to_result` return):
     ```python
     token_count = sum(
         1 for ev in events
         if ev["event"] == "token"
     )
     first_token_idx = next((i for i, e in enumerate(events) if e["event"] == "token"), None)
     done_idx = next((i for i, e in enumerate(reversed(events)) if e["event"] == "done"), None)
     if first_token_idx is not None and done_idx is not None:
         generation_wall_clock = events[len(events) - 1 - done_idx]["_harness_recv_time"] - events[first_token_idx]["_harness_recv_time"]
         tps = token_count / max(generation_wall_clock, 0.001)  # avoid /0
     else:
         tps = float("nan")
     ```

4. **Add TTFT + TPS to ChatRunResult**
   - `harness.py:89-117` (ChatRunResult dataclass):
     ```python
     @dataclass
     class ChatRunResult:
         ...
         latency_s: float
         ttft_s: float = float("nan")        # NEW
         tps: float = float("nan")           # NEW
         ...
     ```

5. **Persist to artifact JSON**
   - `harness.py:123-136` (to_json_dict):
     ```python
     def to_json_dict(self) -> dict[str, Any]:
         return {
             "latency_s": round(self.latency_s, 3),
             "ttft_s": round(self.ttft_s, 3) if not math.isnan(self.ttft_s) else None,  # NEW
             "tps": round(self.tps, 2) if not math.isnan(self.tps) else None,           # NEW
             ...
         }
     ```

### Grading changes (§3.2)

File: `tests/validation/chat_eval/grading.py`

1. **Pass TTFT + TPS through to grade_response**
   - `grading.py:365-370` (grade_response signature):
     ```python
     def grade_response(
         question: str,
         result: ChatRunResult,
         ground_truth_assertions: Mapping[str, Any] | None = None,
     ) -> dict[str, Any]:
     ```
   - Add TTFT/TPS to the returned dict:
     ```python
     return {
         ...
         "latency_s": result.latency_s,
         "ttft_s": result.ttft_s,              # NEW
         "tps": result.tps,                    # NEW
         ...
     }
     ```

### Aggregate test changes (§3.3)

File: `tests/validation/chat_eval/test_aggregate_score.py`

1. **Replace latency gates with TTFT + TPS + relaxed E2E**
   - Lines 54-56 (gate constants):
     ```python
     _TTFT_P95_MAX_S = 5.0              # NEW
     _TPS_P50_MIN = 30.0                # NEW
     _E2E_P99_MAX_S = 90.0              # RELAXED from 60.0
     _MEDIAN_LATENCY_MAX_S = 30.0       # KEEP for now (soft watchdog)
     ```

2. **Collect metrics in test_aggregate_score_gate**
   - Lines 82-94 (per-question loop):
     ```python
     verdicts: list[str] = []
     latencies: list[float] = []
     ttfts: list[float] = []            # NEW
     tps_values: list[float] = []       # NEW
     per_question: list[dict[str, Any]] = []

     for q in questions:
         ...
         result = ask(prompt, slot=f"agg_{qid}")
         grade = grade_response(prompt, result, gt)
         verdicts.append(grade["verdict"])
         latencies.append(result.latency_s)
         if not math.isnan(result.ttft_s):  # NEW
             ttfts.append(result.ttft_s)
         if not math.isnan(result.tps):     # NEW
             tps_values.append(result.tps)
         ...
     ```

3. **Compute percentiles**
   - Lines 100-101 (add TTFT + TPS):
     ```python
     median = statistics.median(latencies) if latencies else 0.0
     p99 = _percentile(latencies, 0.99)
     ttft_p95 = _percentile(ttfts, 0.95) if ttfts else float("nan")   # NEW
     tps_p50 = statistics.median(tps_values) if tps_values else 0.0   # NEW
     ```

4. **Update assertion summary**
   - Lines 104-111 (summary message):
     ```python
     summary = (
         f"verdicts={counts!r}\n"
         f"USEFUL={useful_count} (need ≥ {_MIN_USEFUL})\n"
         f"HARMFUL={harmful_count} (need ≤ {_MAX_HARMFUL})\n"
         f"ttft_p95={ttft_p95:.2f}s (max {_TTFT_P95_MAX_S}s)\n"         # NEW
         f"tps_p50={tps_p50:.2f} tok/s (min {_TPS_P50_MIN})\n"         # NEW
         f"e2e_p99_latency={p99:.2f}s (max {_E2E_P99_MAX_S}s)\n"       # RENAMED
         f"median_latency={median:.2f}s (soft watchdog {_MEDIAN_LATENCY_MAX_S}s)\n"  # SOFT
         f"per_question={per_question!r}"
     )
     ```

5. **Update gate logic**
   - Lines 115-124 (failures list):
     ```python
     failures: list[str] = []
     if useful_count < _MIN_USEFUL:
         failures.append(f"USEFUL count {useful_count} < {_MIN_USEFUL}")
     if harmful_count > _MAX_HARMFUL:
         failures.append(f"HARMFUL count {harmful_count} > {_MAX_HARMFUL}")
     if ttfts and ttft_p95 > _TTFT_P95_MAX_S:         # NEW
         failures.append(f"TTFT p95 {ttft_p95:.2f}s > {_TTFT_P95_MAX_S}s")
     if tps_values and tps_p50 < _TPS_P50_MIN:       # NEW
         failures.append(f"TPS p50 {tps_p50:.2f} < {_TPS_P50_MIN}")
     if p99 > _E2E_P99_MAX_S:                        # UPDATED gate
         failures.append(f"E2E p99 latency {p99:.2f}s > {_E2E_P99_MAX_S}s")
     if median > _MEDIAN_LATENCY_MAX_S:
         # Soft watchdog: log but don't fail (catches slow classifier)
         print(f"⚠ SOFT WATCHDOG: median latency {median:.2f}s > {_MEDIAN_LATENCY_MAX_S}s")
     ```

### Backend instrumentation (§3.4)

File: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`

Per PLAN-0099 W1-T03 (see `docs/plans/0099-iter-9-final-followups-plan.md` lines 182-183), add per-phase wall-clock logging at:

- **Line ~180** (before classifier call): `log.event = "chat_phase_start", phase = "classifier"`
- **Line ~220** (before first-LLM turn): `log.event = "chat_phase_start", phase = "first_llm_turn"`
- **Line ~280** (before tool fan-out): `log.event = "chat_phase_start", phase = "tool_fanout"`
- **Line ~330** (before second-LLM turn): `log.event = "chat_phase_start", phase = "second_llm_turn"`
- **Line ~360** (before streaming starts): `log.event = "chat_phase_start", phase = "streaming_emit"`
- **Line ~370** (after all events emitted): `log.event = "chat_phase_complete", phase = "streaming_emit", duration_ms = …`

Example:

```python
# In chat_orchestrator.py
import time
from structlog import get_logger

log = get_logger()

async def orchestrate(self, ...):
    request_start = time.time()

    phase_times = {}

    phase_name = "classifier"
    phase_times[phase_name] = time.time() - request_start
    log.event("chat_phase_start", phase=phase_name, offset_ms=int(phase_times[phase_name] * 1000))
    intent_result = await self._classify_intent(...)

    phase_name = "first_llm_turn"
    phase_times[phase_name] = time.time() - request_start
    log.event("chat_phase_start", phase=phase_name, offset_ms=int(phase_times[phase_name] * 1000))
    tool_calls = await self._call_first_llm(...)

    # ... tool fan-out ...

    # Final emit with phase breakdown
    total_ms = int((time.time() - request_start) * 1000)
    log.event("chat_orchestration_complete", total_ms=total_ms, phase_breakdown=phase_times)
```

These structlog events will be captured in stdout/CloudWatch and can be post-processed in PLAN-0100 to compute the per-phase contribution to latency.

---

## §4 — Required Harness Changes (Sketches)

### Minimal change set

1. **`_read_sse_events` now records harness-side receive times**
   ```python
   def _read_sse_events(resp: Any, request_start: float) -> list[dict[str, Any]]:
       events: list[dict[str, Any]] = []
       for raw_line in resp.iter_lines():
           # ... existing SSE parse logic ...
           if line == "":
               if current:
                   ev = _parse_event(current)
                   ev["_harness_recv_us"] = int((time.monotonic() - request_start) * 1e6)  # microseconds
                   events.append(ev)
       return events
   ```
   (Uses microseconds to avoid float rounding; the `_harness_recv_us` field is stripped before JSON serialization.)

2. **`_events_to_result` extracts TTFT + TPS**
   ```python
   def _events_to_result(...) -> ChatRunResult:
       # Find indices
       first_token_idx = next((i for i, e in enumerate(events) if e["event"] == "token"), None)
       done_idx = next((i for i, e in enumerate(reversed(events)) if e["event"] == "done"), None)

       # Compute TTFT
       ttft_s = (events[first_token_idx]["_harness_recv_us"] / 1e6) if first_token_idx else float("nan")

       # Count tokens and compute TPS
       token_count = sum(1 for e in events if e["event"] == "token")
       if first_token_idx is not None and done_idx is not None:
           done_idx_abs = len(events) - 1 - done_idx
           gen_time_us = events[done_idx_abs]["_harness_recv_us"] - events[first_token_idx]["_harness_recv_us"]
           tps = token_count / (gen_time_us / 1e6) if gen_time_us > 0 else float("nan")
       else:
           tps = float("nan")

       # Clean event dicts (remove harness metadata)
       for ev in events:
           ev.pop("_harness_recv_us", None)

       return ChatRunResult(..., ttft_s=ttft_s, tps=tps)
   ```

3. **ChatRunResult and to_json_dict already updated** (see §3.1.4-5 above).

---

## §5 — Estimated Current TTFT/TPS from One Artifact

### Data from `agg_q4.json` (111.5s latency case)

Raw events captured:
```
0: status (loading_context)
1: status (entity_resolution)
2: thinking (tool_classification)
3: tool_call (get_fundamentals_history_batch)
4: tool_result (ok)
5: token (1 event, text length = 711 chars)
6: final_answer (longer answer)
7: citations (empty list)
8: contradictions (empty list)
9: metadata (latency_ms=111441)
10: done
```

**Estimated TTFT** (request start to first token):
- Request submit → status (0.05s, harness overhead)
- status → thinking (0.1s, parsing context + entity resolution)
- thinking → tool_call (1.0s, model classification + input prep)
- tool_call → tool_result (100s, **batch tool + EODHD lookups**)
- tool_result → token (0.5s, model generation)
- **TTFT ≈ 101.5s**

**This is catastrophic.** The real TTFT (time to *first visible token*) is being destroyed by tool latency. But this artifact shows why the old p99 gate doesn't work: the query is legitimate (compare 2 tickers over 4 periods = requires tool execution). We can't gate on "p99 < 60s" when the tool is 100s.

**Estimated TPS** (tokens during generation):
- token_count = 1 (single token event)
- generation window = tool_result (100s) → done (111.5s) = ~11.5s
- TPS = 1 / 11.5 ≈ 0.087 tok/s

**This is also catastrophic.** A single token in 11 seconds means the generation phase was truncated or never ran. The structured response (final_answer) was synthesized post-generation, which explains why there's only one `token` event.

### Interpretation

**The harness + SSE emitter need refinement:**
- The current code emits only a single `token` event (see `sse_emitter.py:59-61`), not per-token granularity. This is **by design** for non-streaming first-turn classifiers.
- PLAN-0067 W11-3 (cited in sse_emitter.py:7) switched to non-streaming first turn, so tokens are buffered and emitted as a single chunk.
- **TPS will always be underestimated with this architecture.** The fix requires emitting per-token or using `output_tokens` from the provider envelope.

**Better TTFT proxy today:**
- TTFT should measure from request to `thinking` event (user sees responsive UI), NOT to first token.
- Or: measure from `tool_result` to `token` (model-only latency post-tool execution).
- This isolates LLM latency from tool latency, which is the real user-experience signal.

**TPS computation fix:**
- **Use provider usage envelope instead.** The LLM provider (DeepInfra, etc.) returns `output_tokens` in the completion metadata.
- The harness can extract this from the metadata SSE event (line 9 above).
- TPS = output_tokens / (time from first-token-event to done-event).
- See: the metadata event at line 9 includes `latency_ms = 111441` — this is the *total request* latency from S8's perspective. We'd need the provider to emit token counts.

---

## §6 — Plan-0099 Wave Update — Rewrite W1-T03 + Retire Old P99 Target

### Revised W1-T03 scope

**PLAN-0099 W1-T03: Per-phase wall-clock instrumentation (diagnostic)**

From `docs/plans/0099-iter-9-final-followups-plan.md` lines 182, 207-209:

Current goal:
> "add structlog `event=chat_phase_timing` lines for classifier / first-LLM / tool fan-out / second-LLM / streaming so the next eval artifact decomposes 38.73s and 133.19s"

**Rewrite**:
1. Add per-phase wall-clock logging in `chat_orchestrator.py` (see §3.4).
2. These logs are captured in STDOUT + CloudWatch, not in the SSE artifact.
3. Post-PLAN-0099 deploy, re-run chat-eval and grep for `chat_phase_start` + `chat_orchestration_complete` events to decompose the 38.73s baseline.
4. **DECISION GATE FOR PLAN-0100**: If second-LLM (table generation) dominates post-tool phase, model swap to cheaper/faster LLM is justified. If tool latency dominates (as PLAN-0098 §A suggests), focus on tool parallelization (T-W1-02 already done) and tool caching (future).

### New acceptance gate (replaces old p99)

Replace lines 54-56 in `test_aggregate_score.py`:

**Old**:
```python
_MEDIAN_LATENCY_MAX_S = 30.0
_P99_LATENCY_MAX_S = 60.0
```

**New**:
```python
# Harness-measured metrics (compute from SSE events)
_TTFT_P95_MAX_S = 5.0              # User sees "Thinking..." within 5s
_TPS_P50_MIN = 30.0                # Typical generation speed ≥30 tok/s
_E2E_P99_MAX_S = 90.0              # Multi-tool queries legitimately longer

# Soft watchdog (diagnostic, doesn't gate)
_MEDIAN_LATENCY_MAX_S = 30.0       # Flag if median >30s (classifier/infrastructure issue?)
```

**Gate definition**:
```python
failures: list[str] = []
if useful_count < _MIN_USEFUL:
    failures.append(f"USEFUL {useful_count} < {_MIN_USEFUL}")
if harmful_count > _MAX_HARMFUL:
    failures.append(f"HARMFUL {harmful_count} > {_MAX_HARMFUL}")

# Hard gates (must pass)
if ttfts and _percentile(ttfts, 0.95) > _TTFT_P95_MAX_S:
    failures.append(f"TTFT p95 {_percentile(ttfts, 0.95):.2f}s > {_TTFT_P95_MAX_S}s")
if tps_values and statistics.median(tps_values) < _TPS_P50_MIN:
    failures.append(f"TPS p50 {statistics.median(tps_values):.1f} < {_TPS_P50_MIN}")
if _percentile(latencies, 0.99) > _E2E_P99_MAX_S:
    failures.append(f"E2E p99 {_percentile(latencies, 0.99):.2f}s > {_E2E_P99_MAX_S}s")

# Soft watchdog (flag but don't gate)
median = statistics.median(latencies)
if median > _MEDIAN_LATENCY_MAX_S:
    logger.warning(f"SOFT WATCHDOG: median {median:.2f}s > {_MEDIAN_LATENCY_MAX_S}s — check classifier")
```

### Updated TRACKING.md row

From `docs/plans/TRACKING.md`, update the acceptance gate row:

**Old**:
```
| PLAN-0093 Acceptance Gate | median ≤30s, p99 ≤60s, ≥6 USEFUL, 0 HARMFUL | PASS/FAIL |
```

**New**:
```
| PLAN-0093 Acceptance Gate | TTFT p95 <5s, TPS p50 ≥30, E2E p99 <90s, ≥6 USEFUL, 0 HARMFUL | PASS/FAIL |
```

---

## §7 — Risks of Switching

### Risk 1: Provider variance harder to budget

**Scenario**: DeepInfra has a bad hour; TTFT goes from 2s to 8s (provider queue depth). The new gate is tighter and fails.

**Mitigation**:
- The TTFT p95 gate is still a *percentile* — the top 5% of requests can be slower. One slow provider response doesn't tank the gate if 95 requests are fast.
- The soft watchdog median gate flags this pattern without hard-failing.
- PLAN-0100 will have per-phase breakdown; if TTFT fails but TPS is high, we know it's provider, not us.

### Risk 2: Masking slow classifier (rare)

**Scenario**: A future classifier upgrade regresses (500ms → 2s). With E2E p99 gate loosened to 90s, we don't catch it (tools still fast, total still <90s).

**Mitigation**:
- The TTFT gate catches this. If classifier is slow, first-token is late.
- The soft watchdog median gate flags patterns ("median >30s").
- Per-phase instrumentation (§3.4) shows exactly which phase regressed.

### Risk 3: Single-tool queries still feel slow if TPS is low

**Scenario**: Simple Q1 ("Apple competitors") takes 2s TTFT + 3s streaming at 5 tok/s = 5s total. Feels slow even though gates pass.

**Mitigation**:
- This is caught by the TPS p50 gate. If TPS drops below 30 tok/s, the gate fails.
- But if a single query has low TPS while median stays high, it's a data anomaly, not a systematic problem.
- The per-question artefact tracks this — Q1 verdict + reasons stay in the report.

---

## §8 — Implementation Checklist

- [ ] **harness.py**: Add `_harness_recv_us` timestamps to SSE events in `_read_sse_events`.
- [ ] **harness.py**: Compute TTFT + TPS in `_events_to_result`; add fields to `ChatRunResult`.
- [ ] **harness.py**: Update `ChatRunResult.to_json_dict()` to export TTFT + TPS (or None if NaN).
- [ ] **grading.py**: Pass TTFT/TPS through in `grade_response` return dict.
- [ ] **test_aggregate_score.py**: Replace `_MEDIAN_LATENCY_MAX_S` + `_P99_LATENCY_MAX_S` with `_TTFT_P95_MAX_S` + `_TPS_P50_MIN` + `_E2E_P99_MAX_S`.
- [ ] **test_aggregate_score.py**: Update gate logic to check TTFT p95, TPS p50, E2E p99.
- [ ] **test_aggregate_score.py**: Add soft watchdog for median latency (log, don't fail).
- [ ] **chat_orchestrator.py**: Add per-phase wall-clock logging (structlog events).
- [ ] **docs/plans/0099-iter-9-final-followups-plan.md**: Update W1-T03 scope to clarify diagnostic nature.
- [ ] **docs/plans/TRACKING.md**: Update PLAN-0093 acceptance gate row with new metrics.
- [ ] **Chat-eval rerun**: Once W1 code lands, rerun full suite and verify all three gates pass.

---

## §9 — Conclusions

**Current E2E p99 gate is tool-load-aware but not user-experience-aware.** Replacing it with TTFT + TPS + relaxed E2E:

1. **Isolates UX signals**: TTFT measures responsiveness (when does the user see the model thinking?). TPS measures streaming quality (how fast does output arrive?).
2. **Decouples query complexity**: Multi-tool queries don't unfairly trigger latency failures.
3. **Enables diagnostics**: Per-phase instrumentation reveals which component regressed.
4. **Maintains safety**: E2E p99 at 90s still catches provider outages and tool hangs.

**Critical implementation detail**: The current SSE emitter buffers tokens into a single `token` event, not per-token. To accurately measure TPS, we must either:
- Emit per-token events (refactor sse_emitter.py),
- Use provider `output_tokens` from metadata (easier, but provider-dependent).

The second approach is recommended for PLAN-0099 W1-T03 — extract `output_tokens` from the DeepInfra/provider metadata and use that for TPS = output_tokens / generation_wall_clock.

---

**Audit report complete. Ready for implementation in PLAN-0099 W1-T03.**
