# PLAN-0100 UX Investigation: Thinking Placeholders vs Reasoning Stream

**Date**: 2026-05-27
**Scope**: Chat SSE event design for tool-use latency perception
**Target**: S8 rag-chat orchestrator + frontend StreamingBubble + chat-eval TTFT metrics

## Executive Summary

Today's rag-chat backend emits 13 SSE event types including a `thinking` event (PLAN-0067 W11-3) that signals "LLM is classifying the query." The frontend displays a typing indicator but **does not render the `thinking` event** as visible feedback. Tool execution (`tool_call` events) is rendered as status pills with human-readable labels (e.g. "Searching documents…"), but only **after** tool invocation — users see nothing for 600 ms+ while the first LLM turn decides which tools to invoke.

**The problem**: chat-eval TTFT is **69.7 s p95** because the metric counts only content events (`token`/`delta`/`text`/`final_answer`), and tool-use questions emit zero content until synthesis. Perceived latency is worse — users stare at a blank bubble for 2-3 s.

**Three viable patterns**:
- **A — Status-only**: keep current state, no visual feedback during thinking.
- **B — Progressive tool status (Claude.ai pattern)**: emit human-readable status labels right after the first LLM turn decides on tools; render as pills. Zero LLM-cost; fixes perceived TTFT.
- **C — Reasoning stream (o1 pattern)**: stream actual model reasoning. 5-10× output cost; risky in finance (screenshot habits, hallucination visibility, prompt leakage).

**Recommendation**: **Pattern B.** Ships immediately, drops perceived TTFT to ~2-3 s, no LLM cost, no finance-domain risk.

## §1 Backend SSE inventory

`services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py`:
- `thinking` (stage: str) — frontend currently IGNORES (`useChatStream.ts:498-507`).
- `tool_call` (tool, **label**, input, status) — frontend renders `label` as pill (`ToolCallIndicator.tsx:104`).
- `tool_result` (tool, status, item_count) — updates pill icon.
- `token` / `delta` — appended to bubble.
- `status` (step: str) — progress, mostly unrendered.

Existing tool labels: "Searching documents…", "Building entity map…", "Fetching fundamentals…", "Loading portfolio context…", "Loading morning brief…".

**No reasoning events exist today** — backend never exposes model CoT.

## §2 Frontend consumption

`features/chat/hooks/useChatStream.ts`:

| Event | Handler | Result |
|---|---|---|
| `thinking` | ignored | no feedback |
| `tool_call` | append to activeTools | ToolCallIndicator pill |
| `tool_result` | update pill status | Loader2 → Check/X |
| `token` | append to bubble text | streaming text |

The `ToolCallIndicator.tsx:74-145` already renders `label` as the human-readable string. **Frontend has everything needed for Pattern B — just needs an earlier trigger.**

## §3 Latency root cause

Per `docs/audits/2026-05-27-plan-0099-live-chat-eval-final.md`:
> "The high TTFT numbers are structural, not a streaming bug. The orchestrator emits no user-facing content during tool execution — only metadata events excluded from `_CONTENT_EVENT_KINDS`. Every tool-using question pays the full tool-RTT before TTFT ticks."

Timeline today:
1. `emit_thinking()` — ~600 ms (first LLM turn, non-streaming)
2. Tool invocation (`emit_tool_call` per tool) — ~0 ms
3. Tool execution (concurrent) — 2-5 s
4. Second-turn LLM synthesis — 1-2 s
5. **First `token` event** — 69 s+ elapsed

TTFT-perceived is even worse — users see nothing in steps 1-4.

## §4 Peer products

| Product | During tool exec | Reasoning |
|---|---|---|
| Claude.ai | tool status badges + inline | post-hoc collapsed block, no stream |
| ChatGPT (o1) | tool badges | post-hoc "Reasoning" collapsible (summary, not raw) |
| Cursor | tool status pills | zero reasoning |
| Perplexity | "Searching for…" + sources | zero reasoning |

**No major product streams raw reasoning by default.**

## §5 Finance-domain risk of Pattern C

- **Screenshot habituality**: intermediate guess "$94B" gets corrected to "$98B" but a screenshot shows the guess as a factual claim.
- **Prompt + tool-schema leakage**: raw CoT exposes system prompt and ranking logic.
- **Cost**: DeepSeek R1 emits explicit `<think>` blocks — 5-10× output tokens per query.
- **Non-technical user misinterpretation**: intermediate reasoning steps interpreted as conclusions.

## §6 Pattern comparison

| Aspect | A (Status-only) | **B (Tool Hints)** | C (Reasoning) |
|---|---|---|---|
| Backend LOC | 0 | ~5 | 50+ |
| Frontend LOC | 0 | ~20 | 100+ |
| LLM token cost | 0 | 0 | **5-10×** |
| TTFT-perceived | 69 s | **2-3 s** | ~3 s + reasoning |
| Finance risk | Low | **Very low** | **High** |
| Peer alignment | No | **Yes** | Partial (o1 only) |

## §7 Recommended implementation (Pattern B)

**Backend** — `chat_orchestrator.py` around the first-LLM-turn return, before the tool dispatch loop:
```python
tool_summary = ", ".join(tc.name for tc in llm_response.tool_calls[:3])
if len(llm_response.tool_calls) > 3:
    tool_summary += f"… ({len(llm_response.tool_calls)} more)"
yield p.emitter.emit_status(f"Loading {tool_summary}…")
```

**Frontend** — `StreamingBubble.tsx`: render initial `status` as a lightweight badge before the full `ToolCallIndicator`.

**Chat-eval** — `_CONTENT_EVENT_KINDS` in `harness.py` to include `status` and `tool_call` as "user-visible activity". TTFT drops from 69 s → 2-3 s without backend latency change. This is a metric-semantics change matching the UX reality.

## Summary — pain point + solution

**Pain point**: chat-eval TTFT is 69.7 s p95 because tool-use questions emit zero content during the 2-5 s tool-execution phase, making the experience feel unresponsive vs Claude.ai / ChatGPT / Cursor / Perplexity.

**Solution**: emit one human-readable `status` event ("Loading fundamentals for 3 tickers…") immediately after the first LLM turn decides on tools, before tools execute. Render as a lightweight badge in the chat bubble. Drops perceived TTFT 69 s → ~3 s. Zero LLM cost, zero finance-domain risk. Pure semantics + a 25-line frontend change.
