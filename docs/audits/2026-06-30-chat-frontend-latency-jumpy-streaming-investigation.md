# Chat Latency + Jumpy Streaming — Root-Cause Investigation

**Date:** 2026-06-30
**Scope:** Why the Intelligence Chat feels (a) laggy and (b) JUMPY — text appears in
bursts rather than streaming smoothly.
**Type:** Read-only investigation + ordered fix plan. No source changed.
**Surfaces traced:** `apps/worldview-web` (SSE reader + render), `services/rag-chat`
(orchestrator + LLM adapter + SSE emitter), the Next.js chat proxy.

---

## TL;DR

LATENCY and JUMPINESS are **different problems with a shared root cause**.

The single dominant defect is that **the DeepInfra LLM adapter buffers the entire
upstream token stream into a list before yielding a single token** (to detect the
zero-chunk failover case). This:

1. Makes time-to-first-token ≈ **full generation time** (the latency feel), and
2. Causes the whole answer to be flushed in **one event-loop tick → one/few network
   reads → one React render**, so the answer "pops in" in a burst (the jumpiness).

Everything downstream — the 8-words-per-chunk cadence, the absent frontend typewriter
buffer, the post-synthesis grounding rewrite, the end-of-stream refetch swap — adds
secondary jitter and tail latency, but the adapter buffer is the lever that returns the
most UX per line changed.

---

## Symptom → Root-Cause Map

### JUMPINESS (text appears in bursts, not smooth)

| # | Root cause | Location | Mechanism |
|---|-----------|----------|-----------|
| J1 | **Adapter buffers the whole stream** (PRIMARY) | `services/rag-chat/src/rag_chat/infrastructure/llm/deepinfra_adapter.py:540-591` | `stream_chat` does `async for chunk … primary_chunks.append(chunk)` over the ENTIRE upstream SSE, THEN `for chunk in primary_chunks: yield chunk`. Zero tokens leave the service until generation is fully done, then all chunks emit in one tick. Defeats the orchestrator's incremental loop at `chat_orchestrator.py:3755-3779`. |
| J2 | **Coarse 8-words-per-chunk cadence** | `chat_orchestrator.py:163` (`_STREAM_WORDS_PER_CHUNK=8`), `:656-695` (`_chunk_text_for_streaming`), emit sites `:2679-2680, :3861-3862, :3893-3894` | Direct-answer + fallback paths slice text into 8-word groups. Even with real streaming each event paints 8 words at once — visibly chunky. |
| J3 | **No frontend smoothing / typewriter buffer** | `apps/worldview-web/features/chat/hooks/useChatStream.ts:1004-1012` | Each `token` event directly `setStreaming(prev.text + chunk)`. React 18 auto-batches all setStates inside ONE `reader.read()` iteration; when chunks arrive coalesced (because of J1), the many appends collapse to a single re-render → the answer paints in one frame. No rAF/interval-paced reveal exists to decouple paint cadence from network framing. |
| J4 | **End-of-stream content swap (refetch)** | `apps/worldview-web/app/(app)/chat/page.tsx:417-421` | After `finalize()` calls `refetchThreads()`, the active-thread TanStack query lands and the effect unconditionally does `setLocalMessages(activeThread.messages)`, replacing the streamed text with the **server-persisted** text. If grounding rewrote the answer or appended the "⚠ numbers unverified" banner, the visible answer changes after settle — a late jump. |
| J5 | **`final_answer` ignored live, surfaces on refetch** | `useChatStream.ts:675` (`finalContent \|\| finalAnswerText`) + `chat_orchestrator.py:4361` (`emit_final_answer(rewritten)`) | The grounding-rewritten answer ships as `final_answer`, but the frontend prefers the token-accumulated `finalContent`, so the live view keeps the ORIGINAL text while the persisted/refetched copy (J4) is the rewritten one → guaranteed mismatch on rewrite turns. |

### LATENCY (laggy — long wait before/within the answer)

| # | Root cause | Location | Mechanism |
|---|-----------|----------|-----------|
| L1 | **No true streaming → TTFT ≈ full generation** | same as J1, `deepinfra_adapter.py:540-591` | Because tokens are buffered, the user waits the entire synthesis-generation duration before the FIRST visible character, not ~1 token. This is the biggest contributor to "it feels slow" even on answers that ultimately render fast. |
| L2 | **Serial agent phases** | `chat_orchestrator.py` phase wrappers (`check_cache → … → llm_tool_planning → tool_execution → llm_synthesis_streaming → grounding_validation → persist`) | All sequential. Observed live: `llm_tool_planning` (gpt-oss-120b first turn) **7.5–28s**; per-message totals **11–62s**. |
| L3 | **Grounding validation = a 2nd blocking LLM call** | `chat_orchestrator.py:4112-4151`, `_run_combined_grounding_validation` (def `:4541`) | When numeric/entity grounding fails (observed: **3 of 4** recent answers → `numeric_grounding_failed`), a rewrite completion fires AFTER synthesis, blocking the terminal `done`. Observed `grounding_validation` **1.8–30s** (one hit the 30s timeout). Runs on the buffered adapter path too, so it is pure dead time before settle. |
| L4 | **Heavy planning model** | first turn uses gpt-oss-120b @ `reasoning_effort=medium` | The tool-planning turn alone is multiple seconds before any tool or token. |

---

## What is NOT the problem (ruled out)

- **Proxy gzip/CRLF buffering (BP-668 class).** Already fixed and correct. The Next.js
  chat proxy `app/api/v1/chat/[...path]/route.ts` sets `Cache-Control: no-cache,
  no-transform` + `x-accel-buffering: no` and pipes the upstream `ReadableStream`
  zero-copy (`:147-159`). The SSE line parser strips the stray CR
  (`lib/sse-parser.ts:101`). These are healthy — the bursts are NOT introduced here.
- **Frontend "Response interrupted" false banner.** Hardened in Round 3/4
  (`useChatStream.ts:1168-1243`) with tail-flush + `sawAnswerComplete`. Not implicated.
- **Backend event ORDERING.** Correct and stable: `token…` → `verifying` status →
  `final_answer` → `citations` → `suggestions` → `metadata` → `done`
  (`chat_orchestrator.py:3907, 4361-4472`). No second answer is streamed as tokens —
  the grounding rewrite is awaited (`:4124`, not a generator) and only ships via
  `final_answer`, so there is no mid-stream token replacement. The visible end-jump is
  the refetch swap (J4), not an inline re-stream.

---

## Latency Quantification

Live `worldview-rag-chat-1` had no chat traffic in the inspected window (the timing
event `chat_phase_timings_ms` is emitted per turn but none were present in the last 24h
of logs — the container has been idle). Figures below are the operator-observed live
values carried into this audit, consistent with the code paths traced:

- `llm_tool_planning` (gpt-oss-120b first turn): **7.5–28 s**
- `grounding_validation`: **1.8–30 s** (one 30 s timeout)
- Per-message total: **11–62 s**
- `numeric_grounding_failed` → `completion_cache_skipped_grounding_failed`: **3 / 4**
  recent answers.

Because of J1/L1, **time-to-first-visible-token ≈ planning + tool_exec + full synthesis
generation** — i.e. the user stares at a blank/typing bubble for the large majority of
that 11–62 s, then the answer appears almost all at once.

---

## Ordered Fix Plan

### Quick wins

**F1 — Make the adapter stream incrementally (HIGHEST LEVERAGE; fixes L1 + J1).**
`deepinfra_adapter.py:562-591`. Yield each chunk as it arrives instead of buffering into
`primary_chunks`. Preserve the zero-chunk failover by counting yielded chunks: if the
primary yields ZERO before completing/erroring, fall back to
`_stream_chat_fallback_model`; once ≥1 chunk has been yielded you are already committed
(the current code already declines to fall back after partial output, so semantics are
unchanged for the only case that matters). This alone converts TTFT from "full
generation" to "first token" and turns the burst into a real trickle.
*Effort: M. Risk: M (touches the failover net — needs the existing zero-chunk and W36
degraded-synthesis tests to stay green).*

**F2 — Add a frontend typewriter/smoothing buffer (fixes J2 + J3 regardless of network framing).**
`useChatStream.ts:1004-1012`. Instead of appending each chunk straight to `streaming.text`,
push incoming text into a queue and drain it on a `requestAnimationFrame`/short-interval
loop at a steady characters-per-frame rate. This decouples paint cadence from both the
8-word server chunking and coalesced network reads, so even a one-burst arrival reveals
smoothly. Keep it bounded (flush remainder immediately on `done`/cancel so settle is
instant).
*Effort: M. Risk: L (purely presentational; gated by a feature constant). Pairs with F1
but ALSO masks J1 on its own — useful as an independent, low-risk shippable.*

**F3 — Gate the end-of-stream refetch swap (fixes J4 + J5).**
`page.tsx:417-421`. Do not blindly `setLocalMessages(activeThread.messages)` immediately
after a turn settles. Either (a) prefer the freshly-finalized optimistic message until
the user navigates away, or (b) reconcile by `message_id` so an unchanged answer is not
re-replaced. If the rewritten/bannered persisted text IS the intended final, instead
make `finalize()` prefer `final_answer` (J5) so the live view already matches the
persisted copy and the refetch is a no-op. Pick one source of truth.
*Effort: S–M. Risk: M (this effect was deliberately un-guarded in FR-5.1/HIGH-010 to fix
a different bug — must not reintroduce the "history never syncs after stream" regression;
reconcile-by-id is the safer route).*

**F4 — Tune chunk cadence (cheap mitigation for J2 if F2 is deferred).**
`chat_orchestrator.py:163`. Lower `_STREAM_WORDS_PER_CHUNK` (e.g. 8 → 2–3) on the
chunked branches so bursts are finer-grained. Cosmetic only; does nothing for L1 and is
strictly inferior to F2. Do NOT add an inter-chunk `asyncio.sleep` server-side — it would
add real latency to mask a framing problem better solved on the client.
*Effort: XS. Risk: L.*

### Larger structural fixes

**F5 — Decouple grounding validation from the visible-stream tail (fixes L3).**
`chat_orchestrator.py:4112-4151`. The rewrite blocks `done` for 1.8–30 s on the majority
of turns. Options, best-first: (a) emit the synthesized answer as the live answer, run
grounding asynchronously, and only PATCH/append a banner via a late SSE event if it
fails — the user reads while verification runs; (b) reduce rewrite frequency by fixing
the upstream cause of `numeric_grounding_failed` (3/4 is a very high false/real-fail
rate — investigate whether tool numbers simply aren't in the tolerance table); (c) cap
the grounding-rewrite model to a fast one (the `grounding_rewrite_model` override at
`:4120` already exists — ensure it points at gpt-oss-20b/120b, not the 235B path).
*Effort: L. Risk: M–H (touches the correctness/grounding guarantee — must keep the
"never cache an ungrounded answer" invariant, F-LIVE-008).*

**F6 — True provider streaming end-to-end (the "real" fix; subsumes F1).**
The adapter comment (`deepinfra_adapter.py:540-545`) and `chat_orchestrator.py:158`
both note "the provider client doesn't expose a streaming iterator today." DeepInfra's
OpenAI-compatible endpoint DOES support `stream=true`. Wire a genuine async generator
through `_stream_chat_one_model` → `stream_chat` → orchestrator so tokens flow the moment
the provider emits them, and replace the zero-chunk-failover-by-buffering with a
first-chunk-timeout failover. F1 is the minimal version of this; F6 is the clean version.
*Effort: L. Risk: M.*

**F7 — Parallelize/short-circuit planning (mitigates L2/L4).**
Investigate skipping the tool-planning LLM turn for obviously-direct questions, or using
a faster planning model. Out of scope for the streaming feel but the largest remaining
latency block after F1/F5.
*Effort: L. Risk: M.*

---

## Recommended sequencing

1. **F1 + F2 together** — restores real streaming AND guarantees smoothness. This is the
   highest-UX-per-line change and fixes both the latency feel and the jumpiness.
2. **F3** — kills the late end-of-answer content swap.
3. **F5** — removes the multi-second blocking verification tail.
4. **F6/F7** — structural follow-ups.

---

## Key file:line index

- Adapter buffering: `services/rag-chat/src/rag_chat/infrastructure/llm/deepinfra_adapter.py:540-591`
- Chunk size + chunker: `services/rag-chat/src/rag_chat/application/use_cases/chat_orchestrator.py:163, :656-695`
- Incremental synthesis loop (defeated by adapter): `chat_orchestrator.py:3755-3779`
- Direct-answer chunk emit: `chat_orchestrator.py:2679-2680`
- Grounding rewrite (blocking, post-synthesis): `chat_orchestrator.py:4112-4151`, def `:4541`
- Final emission order: `chat_orchestrator.py:3907, :4361-4472`
- SSE emitter event names: `services/rag-chat/src/rag_chat/application/pipeline/sse_emitter.py:207-353`
- Frontend token append (no smoothing): `apps/worldview-web/features/chat/hooks/useChatStream.ts:1004-1012`
- Frontend finalize (tokens preferred over final_answer): `useChatStream.ts:671-697`
- End-of-stream refetch swap: `apps/worldview-web/app/(app)/chat/page.tsx:417-421`
- SSE line parser (healthy): `apps/worldview-web/lib/sse-parser.ts:88-154`
- Streaming-safe proxy (healthy): `apps/worldview-web/app/api/v1/chat/[...path]/route.ts:147-159`
