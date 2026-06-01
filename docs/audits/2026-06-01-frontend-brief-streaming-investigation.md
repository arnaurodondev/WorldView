# Frontend P0 Investigation — Morning Brief Summary Missing & Chat Streaming UX

**Date:** 2026-06-01
**Branch:** `feat/plan-0099-w4` (no code modified)
**Scope:** Two user-reported regressions on `http://localhost:3001/`
**Verdict:** Both issues are **real**. Root causes identified for each; the brief summary issue has THREE layered causes (one backend, two frontend); the streaming issue has TWO layered causes (one frontend wiring + one Next.js rewrite buffering).

---

## §1 — Executive Summary

| # | Issue | Root cause | Severity |
|---|-------|-----------|----------|
| A1 | `summary_paragraph` not visible | **Backend response carries `summary_paragraph: null`** for the current cached payload | P0 |
| A2 | `summary_paragraph` not visible | **Expanded-view render path never reads `summary_paragraph`** even when populated | P0 |
| A3 | `summary_paragraph` not visible | Cached pre-PLAN-0103 payload still in Valkey (`cached:true`, `id:null`, `sections:[]`) — fallback to narrative-only path | P1 |
| B1 | Intermediate steps "not displayed" | `thinking` event is a documented no-op; `status` events with stage markers (`loading_context`, `entity_resolution`) are silently filtered; only ONE free-text status line is ever rendered | P0 |
| B2 | "Response not in stream mode" | Tokens *are* applied per-chunk in state, but Next.js `rewrites()` proxies SSE through the Node server which **buffers** by default in dev — perceived latency = network buffer, not React | P0 |
| B3 | `final_answer` vs token stream | Hook explicitly **ignores** `final_answer` (it's a `void data;` no-op at `useChatStream.ts:693-698`). If the backend's grounded rewrite differs from streamed tokens, the user sees the **streamed tokens**, not the corrected text | P0 (correctness) |

**The user is observing real, reproducible issues** — none are perceptual artifacts.

---

## §2 — Brief Summary Missing

### 2.1 Backend evidence (live)

```bash
curl /v1/briefings/morning →
  summary_paragraph: None
  summary:           None
  lead:              None
  sections:          []
  cached:            True
  id:                None
  narrative:         "## Details\n**Tape**\n- SPY +0.74%..." (populated)
```

The live backend response shows `summary_paragraph: None`, `summary: None`, `lead: None`,
`sections: []`. The narrative is the canonical v4.2 "## Details" body with the 6 mandatory
sections (Tape / Your Portfolio Today / Macro Today / News That Matters / Risks +
Opportunities / Bonus context).

This **contradicts** the user-supplied premise that the endpoint already returns a
populated `summary_paragraph`. The cached payload predates PLAN-0103 W3 (`888da4b2`) +
W11 v4.5 because:

- `cached: True` + `id: null` is the pre-W3 shape (the W3 commit started persisting `id`).
- `sections: []` indicates the v2.2 `## SUMMARY / --- / ## DETAILS` divider is absent
  AND the v4.2 structured parser did not run server-side (or its result was not cached).

The brief parser **does** support the v4.2 `## Summary` heading at
[`services/rag-chat/src/rag_chat/application/use_cases/brief_parser.py:103-196`](services/rag-chat/src/rag_chat/application/use_cases/brief_parser.py),
and the parser-side injection at
[`brief_parser.py:272-300`](services/rag-chat/src/rag_chat/application/use_cases/brief_parser.py)
synthesises a paragraph from the first bullet **when sections is non-empty**. With
`sections=[]`, `inject_missing_summary` falls through to `(narrative, None)` — line 289:
*"If no bullet at all → return (narrative, None)."*

**Cache key:** see [`public_briefings.py`](services/rag-chat/src/rag_chat/api/routes/public_briefings.py)
around line 354-398 — the route writes both `cache_key` and `lastgood_key`. Until both
TTLs expire OR the cache is purged, every request returns the stale shape.

### 2.2 Frontend evidence — collapsed view DOES handle the field

[`MorningBriefCard.tsx:320-322`](apps/worldview-web/components/dashboard/MorningBriefCard.tsx) reads
`brief?.summary_paragraph?.trim() ?? ""` into `safeSummaryParagraph`.

[`MorningBriefCard.tsx:382-384`](apps/worldview-web/components/dashboard/MorningBriefCard.tsx)
builds `collapsedSource = summaryParagraphWithLinks || summaryWithLinks || narrativeWithLinks`.

So in the **collapsed view** (`expanded === false`) the fallback chain IS correct. With
the current backend payload (`summary_paragraph: null && summary: null`), `collapsedSource`
falls all the way to `narrativeWithLinks` and the user sees the full "## Details" body
clamped (or not — see below).

### 2.3 Frontend evidence — expanded view IGNORES the field

The user's screenshot shows **"show less"** in the top-right corner, which means
`expanded === true` ([`MorningBriefCard.tsx:502-510`](apps/worldview-web/components/dashboard/MorningBriefCard.tsx)).

The expanded branch ([line 573-635](apps/worldview-web/components/dashboard/MorningBriefCard.tsx)) is:

1. If `brief.sections && brief.sections.length > 0` → render `<StructuredBrief lead={brief.lead} sections={...} />`.
2. Else → render `<ReactMarkdown>{narrativeWithLinks}</ReactMarkdown>` (a single `data-testid="brief-narrative"` block).

**Neither branch renders `summary_paragraph` as a lead line.** `<StructuredBrief>` is
passed `lead={brief.lead}` (which is `null` in the live payload) but **not**
`summary_paragraph`. Even when the backend correctly populates `summary_paragraph`, the
expanded view will never show it.

This is the design specified in PLAN-0103 W3 (commit `49e23709` — "render
`summary_paragraph` in MorningBriefCard collapsed view") — only the **collapsed** view was
wired. The expanded view was left to render lead + sections per W1/W2 + W5.

### 2.4 Verdict & fix priorities

| Priority | Fix | File |
|----------|-----|------|
| P0 | **Purge the morning-brief Valkey cache** so the next request regenerates with v4.2 parser → populates `summary_paragraph` | infra: `valkey-cli DEL briefing:public_morning:<user_id>` + `briefing:lastgood:<user_id>` |
| P0 | **Render `summary_paragraph` as a lead line in the EXPANDED view** of `MorningBriefCard` — above `<StructuredBrief>` AND above the narrative fallback. The image makes it clear the user expected to see the summary at the top of the expanded card. | [`MorningBriefCard.tsx:573-635`](apps/worldview-web/components/dashboard/MorningBriefCard.tsx) |
| P1 | If summary is rendered in BOTH collapsed and expanded views, ensure the parser's "strip from narrative" logic (so summary doesn't double-render). The parser already returns `(summary, remainder)`; the narrative passed to the card is the remainder, so this is safe. | N/A — already correct |
| P2 | Add an integration test that fetches a real brief and asserts `summary_paragraph` is non-null when `sections.length > 0`. Current cached-shape regression would have been caught. | New test |

---

## §3 — Streaming UX

### 3.1 SSE event-by-event audit

[`useChatStream.ts:441-737`](apps/worldview-web/features/chat/hooks/useChatStream.ts) is the SSE read loop. Map of event handlers:

| SSE event | Hook handler | User-visible result | File:line |
|-----------|--------------|---------------------|-----------|
| `status` (`step: "loading_context"`) | **Filtered out** — line 725 requires `/[\s…]/.test(statusText)`. `"loading_context"` has no space. | **NOTHING SHOWN** | `useChatStream.ts:707-729` |
| `status` (`step: "entity_resolution"`) | Same filter — no space → filtered. | **NOTHING SHOWN** | `useChatStream.ts:707-729` |
| `status` (`step: "Loading get_fundamentals_history…"`) | Passes filter (has `"…"`). Stored as `streaming.initial_status`. | Renders as `<div data-testid="chat-initial-status">` ([`MessageTurn.tsx:334-341`](apps/worldview-web/features/chat/components/MessageTurn.tsx)). One single status line. | `useChatStream.ts:719-729` |
| `thinking` (`stage: "tool_classification"`) | **Explicit no-op** — line 498-507 comments "WHY no-op: the TypingIndicator already covers the blank-stream phase". | NOTHING SHOWN | `useChatStream.ts:498-507` |
| `tool_call` | Appends to `activeTools` state → renders in `<ToolCallTray>` ([`MessageTurn.tsx:347-349`](apps/worldview-web/features/chat/components/MessageTurn.tsx)) | Tool pill appears (status=running) | `useChatStream.ts:508-537` |
| `tool_result` | Updates pill status (ok / empty / error) | Pill turns green/grey/red | `useChatStream.ts:538-552` |
| `token` | Appended to `streaming.text`, also to `finalContent` | Chunk appears in streaming bubble | `useChatStream.ts:596-609` |
| `final_answer` | **Explicit no-op** — line 693-698: `void data;` — comment says "The token stream itself is already complete by then, so there is nothing for the UI to do" | NOTHING SHOWN — final_answer text discarded | `useChatStream.ts:693-698` |
| `citations` | Collected into `pendingCitations`, applied on `finalize()` | Citation chips appear after `done` | `useChatStream.ts:610-659` |
| `metadata` | Stored; applied to final message | Provider/latency strip after `done` | `useChatStream.ts:660-681` |
| `contradictions` | Stored; applied to final message | Contradiction strip after `done` | `useChatStream.ts:682-692` |
| `done` | Calls `finalize()` → promotes streaming bubble → message | Stream ends, bubble locks | `useChatStream.ts:475-479` |

### 3.2 Why the user perceives "no intermediate steps"

Backend emits SIX status/thinking events during the typical 11–60s tool-planning phase
(per user trace). FIVE of them are silently filtered:

- `status loading_context` → filtered (no space)
- `status entity_resolution` → filtered (no space)
- `thinking tool_classification` → explicit no-op
- (any other `status` stage marker like `cache_hit`) → filtered

Only the single `status "Loading get_fundamentals_history…"` line (emitted right after
tool selection at iteration 0) is rendered, and it renders as one muted 10px line above
the tool tray. The tool tray itself only appears AFTER `tool_call` fires, which on a slow
LLM-tool-planning path (the user's example shows 11.7s for `llm_tool_planning`) means the
user sees a **blank** typing indicator for ~12 seconds before anything appears.

This is **by design** in PLAN-0100 W2 (the comment at line 713-720 explains "Earlier
status events are stage keywords, not user-facing copy") — but the user-facing result is:
*"no intermediate steps are being displayed"*. The design intent and the UX outcome
disagree.

### 3.3 Why streaming "doesn't feel streamed"

The hook DOES append tokens per chunk ([`useChatStream.ts:602-608`](apps/worldview-web/features/chat/hooks/useChatStream.ts)).
Each token triggers `setStreaming` → React re-render. So the React layer is correct.

Suspect causes for the buffered feel:

1. **Next.js dev-mode `rewrites()` buffers SSE.** [`next.config.ts:119-128`](apps/worldview-web/next.config.ts)
   proxies `/api/:path*` → `http://localhost:8000/:path*` via Next's built-in rewrite. Next
   15's rewrites use the Node HTTP proxy which **does not pass `X-Accel-Buffering: no`
   through** and may aggregate chunks (especially in dev with HMR active). The trace shows
   a 25s gap before a `: ping` keepalive (`: ping - 2026-06-01 06:57:24`) — that gap would
   feel like a frozen UI to the user.
2. **`LazyMarkdownContent` re-parses on every token.** Used at
   [`MessageTurn.tsx:319-323`](apps/worldview-web/features/chat/components/MessageTurn.tsx) for
   assistant turns including the streaming bubble. Each token = full markdown parse of the
   accumulated content. On long answers (1KB+ token stream), this drops frames and looks
   "chunky" rather than smooth.
3. **No explicit `Cache-Control: no-transform` or `X-Accel-Buffering: no`** on the chat
   stream route response headers — checked `services/rag-chat/src/rag_chat/api/routes/chat.py`:
   the route uses `EventSourceResponse` (sse-starlette) which DOES set the right headers
   on the FastAPI side, but Next.js rewrites can drop them.

### 3.4 `final_answer` correctness bug (B3)

The trace shows the backend's `final_answer` event carries *different* text from the
preceding `token` stream:

```
token "Apple's (AAPL) P/E ratio is 37.7x as of Q4 FY2026..."
final_answer "I cannot find evidence that Apple's P/E ratio is 37.7x..."
```

This is the PLAN-0093 numeric-grounding rewrite — the backend caught hallucinated numbers
post-generation and emitted a corrected version. The hook **ignores** `final_answer`
([`useChatStream.ts:693-698`](apps/worldview-web/features/chat/hooks/useChatStream.ts)) and
calls `finalize()` later using `finalContent` which is the **uncorrected** streamed text.

**Result:** the user sees the wrong (ungrounded) answer in chat history after the stream
ends. This is a correctness regression, not just a UX issue.

The hook comment at line 695 says *"The token stream itself is already complete by then,
so there is nothing for the UI to do"* — this was true under PLAN-0089 K but is no longer
true under PLAN-0093 numeric-grounding which produces a divergent `final_answer`.

---

## §4 — `final_answer`-vs-token contract recommendation

Two consistent designs:

**Option A — `final_answer` always wins (recommended for correctness).** When
`final_answer` arrives, replace `finalContent` (and the streaming bubble text) with its
payload. Add a subtle "ground-checked" badge on the message so the user understands the
text changed. Drawback: the previous token-stream visual is overwritten in the last frame
— momentary flicker.

**Option B — Tokens are canonical, `final_answer` is metadata only.** The backend stops
rewriting in `final_answer` and instead emits divergent answers as `correction` events the
hook applies optionally. Drawback: requires backend changes; current behaviour (B3 bug)
persists until shipped.

Recommend **Option A** — fix in the frontend immediately; keep backend semantics.

---

## §5 — Recommended fixes (prioritized)

| # | Priority | Fix | File:line | Effort |
|---|----------|-----|-----------|--------|
| 1 | P0 | Purge Valkey morning-brief cache + verify next response carries non-null `summary_paragraph` | infra | 5 min |
| 2 | P0 | Render `summary_paragraph` as a lead line at top of expanded view (above StructuredBrief AND above narrative fallback) | [`MorningBriefCard.tsx:573-635`](apps/worldview-web/components/dashboard/MorningBriefCard.tsx) | 1 h |
| 3 | P0 | Honour `final_answer`: replace `finalContent` + streaming bubble text on event | [`useChatStream.ts:693-698`](apps/worldview-web/features/chat/hooks/useChatStream.ts) | 1 h |
| 4 | P0 | Surface ALL `status` events (translate stage markers to user copy: `loading_context` → "Loading context…", `entity_resolution` → "Resolving entities…") AND show `thinking` with stage name (`tool_classification` → "Choosing tools…") | [`useChatStream.ts:498-507, 707-729`](apps/worldview-web/features/chat/hooks/useChatStream.ts) | 2 h |
| 5 | P1 | Replace Next.js `rewrites()` with a custom API route or direct call for `/api/v1/chat/stream` that pipes the upstream `Response.body` without buffering (or set `Cache-Control: no-transform` + flush after each write) | [`next.config.ts:119-128`](apps/worldview-web/next.config.ts) + new `app/api/chat/stream/route.ts` | 3 h |
| 6 | P1 | Stream-aware markdown rendering: render streaming bubble as plain text or use a debounced markdown render (e.g. only re-parse every 200ms during stream; final render after `done`) | [`MessageTurn.tsx:319-323`](apps/worldview-web/features/chat/components/MessageTurn.tsx) | 3 h |
| 7 | P2 | Add e2e test: stream → assert status, tool_call, token, final_answer all visible in DOM | new playwright spec | 2 h |

---

## §6 — Open questions for the product team

1. **Should the morning-brief summary be visible in BOTH collapsed and expanded views?**
   Current design: collapsed-only. Image suggests user expects expanded too.
2. **When `final_answer` rewrites streamed tokens, should the UI explain it?** A badge,
   tooltip, or strikethrough animation? Silently swapping may erode trust.
3. **What stage labels are user-friendly?** Engineering uses `entity_resolution`,
   `tool_classification`, `loading_context`. Product copy needed.
4. **Acceptable streaming latency budget?** Current 11.7s `llm_tool_planning` + 25s ping
   gap = ~37s of silence. Even with all fixes, a slow backend feels broken — is there an
   SLO?
5. **Should the brief cache be invalidated on every backend deploy?** The cached pre-W3
   payload survived multiple shipped commits — a deploy hook to flush `briefing:*` keys
   would prevent future shape-drift incidents.

---

## §7 — Files inventoried

- `/Users/arnaurodon/Projects/University/final_thesis/worldview/apps/worldview-web/components/dashboard/MorningBriefCard.tsx` — brief card, collapsed+expanded render
- `/Users/arnaurodon/Projects/University/final_thesis/worldview/apps/worldview-web/features/chat/hooks/useChatStream.ts` — SSE event handlers
- `/Users/arnaurodon/Projects/University/final_thesis/worldview/apps/worldview-web/features/chat/components/MessageTurn.tsx` — streaming bubble render
- `/Users/arnaurodon/Projects/University/final_thesis/worldview/apps/worldview-web/features/chat/lib/types.ts` — `StreamingMessage.initial_status` definition (line 50)
- `/Users/arnaurodon/Projects/University/final_thesis/worldview/apps/worldview-web/next.config.ts` — Next.js rewrites for SSE proxy
- `/Users/arnaurodon/Projects/University/final_thesis/worldview/services/rag-chat/src/rag_chat/application/use_cases/brief_parser.py` — `split_summary_paragraph`, `inject_missing_summary`
- `/Users/arnaurodon/Projects/University/final_thesis/worldview/services/rag-chat/src/rag_chat/api/routes/public_briefings.py` — morning brief route + Valkey cache
- `/Users/arnaurodon/Projects/University/final_thesis/worldview/services/rag-chat/src/rag_chat/api/routes/chat.py` — chat stream endpoint
