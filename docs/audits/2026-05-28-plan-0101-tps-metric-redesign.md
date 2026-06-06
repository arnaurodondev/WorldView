# PLAN-0101: TPS (Tokens-Per-Second) Metric Redesign

**Audit Date**: 2026-05-28
**Context**: PLAN-0100 W2 introduced `tool_call` and `status` events as user-visible content, causing TTFT to drop from 69.7s to < 5s. This caused the denominator of the TPS formula to become dominated by tool execution time, making the metric measure tool latency instead of streaming responsiveness.
**Current Status**: TPS gate failing at p50 = 5.29 tok/s vs. threshold 30 tok/s (FAIL by 24.71 tok/s).
**Data Source**: `tests/validation/chat_eval/runs/20260528T143346Z/agg_q*.json` (9 questions).

---

## Problem Statement

### Current TPS Formula

From `tests/validation/chat_eval/harness.py:_compute_ttft_and_tps()` (lines 582–630):

```python
# Line 627–628:
tps = output_tokens / (latency_s - ttft_s)
```

Where:
- `output_tokens` = tokens in the final answer (from provider envelope or 4-chars-per-token estimate)
- `latency_s` = wall-clock end-to-end time (request submit to final SSE event)
- `ttft_s` = time-to-first **user-visible** event (status/tool_call/content token)

### Why the Gate Fails

#### Q1 Example (Simple one-tool query)
- **Latency**: 12.46s
- **TTFT**: 1.04s (first `status` event at ~1s, tool dispatch happens, first token at ~11.7s)
- **Output tokens**: 69
- **Denominator**: 12.46 - 1.04 = 11.42s
- **Computed TPS**: 69 / 11.42 = **6.04 tok/s**
- **Phase breakdown**: `llm_tool_planning` (9.2s) >> `tool_execution` (0.1s) — tool decision and thinking takes 9.2s before the tool even runs.

#### Q6 Example (Multi-tool screen + fundamentals)
- **Latency**: 175.50s
- **TTFT**: 0.66s (first `status` event at ~0.66s)
- **Output tokens**: 425
- **Denominator**: 175.50 - 0.66 = 174.84s (!!!)
- **Computed TPS**: 425 / 174.84 = **2.43 tok/s**
- **Phase breakdown**:
  - `llm_tool_planning` (94.5s, 54%)
  - `grounding_validation` (76.1s, 43%)
  - `tool_execution` (1.9s, 1%)
  - Actual token streaming: **last few seconds only**

### Root Cause

After PLAN-0100 W2 added `status` and `tool_call` to `_CONTENT_EVENT_KINDS`, TTFT now ticks on the early "Loading …" UI badge (~0.66–1.04s) rather than waiting for the first content token (~11.7s for Q1, ~99.2s for Q6). This is **correct for user-facing responsiveness** (the UI is interactive ~1s in), but **incorrect for measuring streaming throughput**, because:

1. Most of the time between TTFT and E2E is **tool execution + LLM decision**, not token generation.
2. The denominator `(e2e − ttft)` is now dominated by non-streaming overhead.
3. **TPS becomes a proxy for tool latency, not streaming speed.**

Example: Q6 takes 175s total, but only the final ~6s streams tokens (if `425 tokens / 6s ≈ 70 tok/s`, a healthy rate). The 169s gap is tool planning + validation + execution — valid query complexity, not a streaming regression.

---

## Proposed Solutions

### Option A: TPS Streaming (Recommended)

**Formula**: `tps_streaming = output_tokens / phase_timings_ms["llm_synthesis_streaming"] * 1000`

**Pros**:
- Measures **actual token generation speed** (synthesis phase only).
- Decouples from tool fan-out complexity.
- Most accurate: uses backend instrumentation directly.
- Gate threshold ~20 tok/s is realistic for 8B-class models on DeepInfra (30–60 tok/s typical, 1.5–3× headroom for variance).

**Cons**:
- Requires `llm_synthesis_streaming` to be present in `phase_timings_ms`. (Currently absent; infrastructure work needed at the backend.)
- Falls back to NaN when timings missing → gate neither passes nor fails (safer than false-OK, but requires full instrumentation first).

**Prerequisite**: Backend must emit `llm_synthesis_streaming` (or similar synthesis-phase label) in the `done` SSE event's `phase_timings_ms` dict. Currently: `llm_tool_planning`, `grounding_validation`, `tool_execution`, etc. present, but no explicit synthesis timing.

---

### Option B: Net Streaming Time

**Formula**: `tps_streaming = output_tokens / (latency_s − sum(non_streaming_phases))`

**Pros**:
- Same as Option A numerically (when phase timings are complete).
- Doesn't require a new backend field — computes from existing phases.

**Cons**:
- Fragile: must manually enumerate which phases are "non-streaming" (tool_execution, grounding_validation, llm_tool_planning).
- If new phases are added, the set must be updated in harness.
- Harder to debug: unclear whether a phase mismatch is a missing timing or a miscategorization.

---

### Option C: Redefine TPS as Overall Throughput

**Formula**: Keep `tps = output_tokens / (latency_s − ttft_s)` but relax gate to **3–5 tok/s**.

**Pros**:
- No infrastructure changes needed.
- Metrics continue to work immediately.

**Cons**:
- Accepts a "throughput" metric that measures tool latency, not streaming responsiveness.
- A 10× slowdown in actual token generation (30 → 3 tok/s) would still pass the gate if tool latency masked it.
- Loses precision on the most important signal (did the LLM degrade?).

---

## Recommendation: Option A

**Rationale**: PLAN-0100 W2 instrumented the backend with per-phase timings precisely to solve this problem. Option A uses that data directly and measures what we care about: **streaming speed**. The prerequisite (adding `llm_synthesis_streaming` label) is a one-line backend change and aligns with the PLAN-0100 W6 phase-timings aggregation work.

---

## Data Analysis: Run 20260528T143346Z

8 questions (Q1–Q8), current TPS p50 = 5.29 tok/s vs. gate 30 tok/s.

| Q | Prompt | TTFT(s) | E2E(s) | Tokens | TPS(current) | TPS(hypothetical A, if synthesis=200ms) | Notes |
|---|--------|---------|--------|--------|--------------|----------------------------------------|-------|
| Q1 | Apple competitors | 1.04 | 12.46 | 69 | 6.04 | ~345 | One-tool; 74% time in llm_tool_planning |
| Q2 | Top 5 market cap | 0.69 | 52.97 | 114 | 2.18 | ~570 | Tool fan-out visible; large denominator |
| Q3 | Sentiment analysis | 0.53 | 9.30 | 54 | 6.16 | ~270 | Short query; synthesis fast |
| Q4 | Commodity trends | 0.60 | 48.26 | 252 | 5.29 | ~1260 | Long answer; tool latency dominates |
| Q5 | Negative news impact | 1.25 | 61.96 | 66 | 1.09 | ~330 | Minimal synthesis, mostly tool time |
| Q6 | Semiconductor screen | 0.66 | 175.50 | 425 | 2.43 | ~2125 | 3-tool fan-out; 97% of time non-synthesis |
| Q7 | Price prediction | 1.50 | 12.29 | 56 | 5.19 | ~280 | Refusal path; short synthesis |
| Q8 | Insider activity | 0.52 | 36.58 | 204 | 5.66 | ~1020 | Long answer; moderate tool time |

**Hypothetical column assumption**: If synthesis phase = ~200ms (typical for 425 tokens @ 60 tok/s), Option A would yield 1260–2125 tok/s for the longest answers, 270–570 for short ones. **These are clearly too high** — indicates either the assumption is wrong or the synthesis time should include some buffering overhead.

**Conclusion**: Without actual `llm_synthesis_streaming` data from the backend, we cannot yet quantify Option A. The prerequisite work must land first (see §5 below).

---

## Implementation Sketch for Option A

### Backend Changes (PRD-0101 T-??-??): TBD by W? owner

1. **Chat orchestrator** (`services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py`):
   - Add `llm_synthesis_streaming` timer around the synthesis turn (when the LLM streams tokens only, excluding tool dispatch and validation).
   - Emit in `done` event's `phase_timings_ms` dict.

2. **Harness changes** (`tests/validation/chat_eval/harness.py`):

   **Line 539–544** (in `_compute_ttft_and_tps()`), add a new parameter:
   ```python
   def _compute_ttft_and_tps(
       *,
       timings: list[tuple[str, int]],
       latency_s: float,
       answer_text: str,
       usage_output_tokens: int | None,
       phase_timings_ms: dict[str, float] | None = None,  # NEW
   ) -> tuple[float, float, float, int | None]:
   ```

   **Lines 625–630** (new TPS computation):
   ```python
   # TPS: prefer synthesis-phase-only measurement if available.
   tps = float("nan")
   tps_streaming = float("nan")

   if phase_timings_ms and "llm_synthesis_streaming" in phase_timings_ms:
       synthesis_s = phase_timings_ms["llm_synthesis_streaming"] / 1000.0
       if output_tokens is not None and output_tokens > 0 and synthesis_s > 0:
           tps_streaming = output_tokens / synthesis_s

   # Legacy overall TPS (for backward compat, artifact diagnostics).
   if output_tokens is not None and output_tokens > 0 and math.isfinite(ttft_s) and latency_s > ttft_s:
       tps = output_tokens / (latency_s - ttft_s)

   return ttft_s, tps, tps_streaming, output_tokens
   ```

   **Line 215** (in `ChatRunResult.to_json_dict()`), add:
   ```python
   "tps_streaming": _opt(self.tps_streaming),
   ```

   **Line 182** (in `ChatRunResult` dataclass), add:
   ```python
   tps_streaming: float = float("nan")
   ```

3. **Event parsing** (`_events_to_result()`, lines 457–561):
   - Extract `phase_timings_ms` from the `done` event.
   - Pass to `_compute_ttft_and_tps()`.
   - Unpack tuple: `ttft_s, tps, tps_streaming, output_tokens = …`
   - Store in result: `result.tps_streaming = tps_streaming`

4. **Gate update** (`tests/validation/chat_eval/test_aggregate_score.py`, lines 72–78):
   ```python
   # NEW gate (supersedes tps_p50 when phase data present)
   _TPS_STREAMING_P50_MIN = 20.0  # tok/s for synthesis phase only

   # Keep legacy for backward compat
   _TPS_P50_MIN = 30.0  # (may deprecate after W1)
   ```

   **Lines 160–170** (gate logic):
   ```python
   # Extract tps_streaming if available; fall back to legacy tps
   tps_streaming_values: list[float] = []
   for result in <all_results>:
       if math.isfinite(result.tps_streaming):
           tps_streaming_values.append(result.tps_streaming)

   if tps_streaming_values:
       tps_streaming_p50 = statistics.median(tps_streaming_values)
       if tps_streaming_p50 < _TPS_STREAMING_P50_MIN:
           failures.append(f"TPS streaming p50 {tps_streaming_p50:.2f} < {_TPS_STREAMING_P50_MIN}")
   else:
       # Fall back to legacy gate
       finite_tps = _finite_only(tps_values)
       if finite_tps and statistics.median(finite_tps) < _TPS_P50_MIN:
           failures.append(f"TPS p50 {statistics.median(finite_tps):.2f} < {_TPS_P50_MIN} (legacy fallback)")
   ```

### Backward Compatibility

- Artifact JSON includes both `tps` (legacy) and `tps_streaming` (new).
- Historical runs still comparable on the old metric.
- Harness continues if `phase_timings_ms` is missing (degrades gracefully).
- Gate uses `tps_streaming` when available; falls back to `tps` if not.

---

## Pain Point → Solution (PLAN-0101 Entry)

**Pain Point**: PLAN-0100 W2 correctly moved TTFT to "first user-visible event," but this exposed a deeper issue — the TPS gate now measures tool latency instead of streaming speed. A 3-tool query with legitimate 60s tool fan-out will always fail the gate, even if synthesis is healthy. The binary choice (gate on tool-inclusive latency vs. synthesis-only latency) requires infrastructure to emit per-phase timings.

**Solution**: PLAN-0101 W? (scope TBD) adds `llm_synthesis_streaming` to the backend `phase_timings_ms` dict (one-line timer around synthesis loop in `chat_orchestrator`), then updates the harness to compute `tps_streaming = output_tokens / phase_timings_ms["llm_synthesis_streaming"]` and gate on `tps_streaming_p50 ≥ 20 tok/s`. This decouples streaming quality from query complexity and unblocks PLAN-0100 W2 pass criteria (TPS gate flipped to "no-op" pending the infrastructure work).

---

## Conclusion

The current TPS gate is structurally flawed post-PLAN-0100 W2 because TTFT now measures user-visible event arrival (~1s) rather than synthesis start, making the denominator dominated by tool execution. **Option A (synthesis-phase-only TPS)** is the correct long-term solution and requires a single backend change (add `llm_synthesis_streaming` timer). Until that lands, the gate should either be **relaxed to 3–5 tok/s (Option C)** or **marked as provisional with a TBD PLAN-0101 dependency**. The data exists in the `phase_timings_ms` dict; the synthesis timing is the single missing piece.
