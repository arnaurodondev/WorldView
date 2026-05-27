---
id: PLAN-0089-K
title: Wave K — Chat Polish (PRD-0089 /chat + AskAiPanel)
status: complete
created: 2026-05-25
shipped: 2026-05-26
shipped_branch: feat/plan-0089-wi-a
commit_range: b7e986da..9b83154a (26 commits = 23 task commits + 1 tooltip fix + 2 QA fix commits)
qa_verdict: SHIP_WITH_FIXES (resolved) — Security clean; UX 2 blockers + Arch 3 blockers all fixed in dc5e6c36 + 9b83154a; 13/13 arch tests + 87/87 features/chat + 23/23 AskAiPanel pass
parent_prd: docs/specs/0089-platform-page-redesign.md
parent_design: docs/designs/0089/10-chat-ai.md
waves: 1 (Wave K — Chat polish)
dependencies:
  - F1 design-system foundation (shipped)
  - F2 entity-id unification (shipped)
  - W1 global shell (shipped)
  - W3 instrument financials (shipped)
  - W5 instrument quote (shipped)
  - W7 instrument intelligence (shipped)
  - Backend Q-9 extension to MessageResponse (owned by parallel
    orchestration session; not branch-blocking — frontend ships with
    optional fields that gracefully degrade until S8 ships)
---

# Wave K — Chat polish (PRD-0089) — Implementation plan

**PRD**: 0089 platform page redesign
**Design**: `docs/designs/0089/10-chat-ai.md` (revised 2026-05-25 with
Decisions applied for Q-8..Q-12)
**Sibling foundation**: F1 / F2 / W1 / W3 / W5 / W7 (all shipped)
**Status**: ready-to-execute
**Estimated**: 5–6 engineer-days
**Branch**: `feat/plan-0089-k` (off `main` after W7 merge)

---

## §0. Decisions applied (locked from `10-chat-ai.md` §10 — 2026-05-25)

| OQ | Lock | Plan impact |
|----|------|-------------|
| Q-8 | Ship `ToolTraceDrawer`, gated behind `?debug=1` URL param (read once, no cookie) | T-19: implements `ToolTraceDrawer` + `useDebugFlag()` hook reading `useSearchParams()` once on mount |
| Q-9 | Extend `MessageResponse` with optional `provider`/`model`/`latency_ms`/`contradictions[]`/`resolved_entities[]`/`retrieval_plan` | T-04 / T-05: frontend `Message` interface extension; `MessageMetaStrip` + `ToolTraceDrawer` consume them. Backend work owned by parallel session. T-04 ships behind null-safe defaults so it compiles + renders even if the API hasn't shipped Q-9 yet (graceful degradation) |
| Q-10 | STAGED migration — introduce `CitationV2`, retain `Citation` with `@deprecated`, add `no-legacy-citation` arch test that fails CI on NEW imports | T-03 + T-21: define `CitationV2`; T-21 adds the arch test; atomic rename deferred to a v1.1 follow-up plan |
| Q-11 | DEFER `tool_data` SSE event and `InlineToolResultCard` to follow-up wave | OUT OF SCOPE; not in this plan's task list |
| Q-12 | Surface `extraction_confidence < 0.6` as low-confidence chip on `CitationStrip` row | T-10 includes the chip in `CitationStrip`'s row template |

---

## §1. Goals

1. Replace bubble-chat layout with flat, role-gutter, no-avatar terminal
   layout — matches Bloomberg / Refinitiv / Perplexity Finance.
2. Stop discarding 4 end-of-stream backend fields (`intent`, `provider`,
   `latency_ms`, `message_id`) and the entire `contradictions` SSE event —
   surface them via `MessageMetaStrip` + `ContradictionStrip`.
3. Fix the live Citation type drift (silent "NaN%" + `undefined` key
   bugs) via staged `CitationV2` migration; render `published_at` /
   `source_name` / `entity_name` / `confidence` for every citation.
4. Surface KG `relation_summary` + `evidence_snippets[]` and PLAN-0080
   intelligence-tool results (health_score, narrative version, paths,
   key_metrics) in the new `ChatContextRail`.
5. Add `?debug=1`-gated `ToolTraceDrawer` for thesis-grade "Why this
   answer" inspection of `retrieval_plan` + `resolved_entities` + the
   full tool-call/result trace.
6. Hit density target ≥ 50 cells visible above the fold at 1440×900
   (recount in §10 of the design doc lands 103 cells — comfortable
   margin).

## §2. Out of scope

- Backend orchestration changes (owned by parallel session). Wave K
  consumes them via the wire-shape contract.
- `tool_data` SSE event and `InlineToolResultCard` (Q-11 deferred).
- Pin/unpin thread feature (Q-3 deferred per design §10).
- `ActionConfirmModal` re-dock (Q-5 deferred — separate PLAN-0082
  territory).
- 👍/👎 feedback on assistant turns — no backing table exists
  (`chat_feedback` was hypothetical; design §10 revision log confirms).
- Atomic `Citation` → `CitationV2` rename across all call sites (Q-10
  staged; rename is a v1.1 follow-up).
- Slash-command card density tweak — captured as a non-blocking
  follow-up (§7 risk register).

## §3. Dependencies

| ID | Dependency | Blocking? | Notes |
|----|-----------|-----------|-------|
| D-1 | Backend Q-9 (`MessageResponse` extension) | NO | Frontend ships with optional fields. While Q-9 not landed: streaming SSE `metadata` event still populates the meta strip; history-reloaded turns silently render without it. No crash. |
| D-2 | F1 `InlineCitationAnchor` primitive | NO (shipped) | Reused verbatim; already wired into `AskAiPanel.tsx:81` |
| D-3 | F1 `AiContentRail` primitive | NO (shipped) | Candidate for the streaming accent rail in T-07 |
| D-4 | F1 `DataFreshnessPill` | NO (shipped) | Used by `MessageMetaStrip` for `created_at` |
| D-5 | F1 `Sparkline` | NO (shipped) | Used in `EntityHealthDot` confidence-trend mini-line (optional, time-permitting) |
| D-6 | F1 `SectionDivider` | NO (shipped) | Used between context rail blocks |
| D-7 | F1 `EmptyState` | NO (shipped) | Used by `ChatEmptyState` |
| D-8 | F2 `TickerLink` | NO (shipped) | Used by related-ticker chips in `ChatContextRail` |
| D-9 | Existing `qk.chat.*` keys | NO (shipped) | Extended in T-02 with `qk.chat.contradictions(threadId)` and `qk.chat.recentCitations(threadId)` |

**No backend block on Wave K landing.** Q-9 is required for full
end-to-end fidelity on history-reloaded turns but the frontend
degrades cleanly.

---

## §4. Bloomberg-grade resemblance checks (acceptance gate)

After Wave K lands, the `/chat` page MUST:

1. Above-fold cell count ≥ 50 at 1440×900 (target per §10 recount: 103).
2. Message column renders flat (no rounded bubble shell on either user
   or assistant turns).
3. Active streaming gutter shows a 2px accent rail (`border-primary/50`),
   no blinking cursor.
4. `MessageMetaStrip` renders `intent · via {provider} · {model} · {N}ms`
   on every assistant turn that has the data (streaming and Q-9-extended
   history).
5. `CitationStrip` renders `published_at`, `source_name`, `entity_name`,
   and `confidence` for every citation (no `NaN%` chips anywhere).
6. `ContradictionStrip` renders the SSE `contradictions` payload that
   was previously discarded — both inline under the turn and in the
   context rail.
7. `RelationEvidencePopover` renders ≥ 1 evidence snippet on KG-type
   citation rows when the originating graph query was depth=1.
8. `EntityHealthDot` renders a colour-coded dot in `ChatContextRail`
   when `get_entity_health` data is available; tooltip shows
   `{health_score} · {fields_populated}/{total_fields}`.
9. `?debug=1` query param toggles `ToolTraceDrawer` visibility; without
   the flag, the drawer is unreachable from the UI.
10. Tool-call tray auto-expanded while running, auto-collapsed 1.5s
    after the last tool finishes (collapsed label: `tool calls — N/N
    done`).
11. Follow-up chips appear under every assistant turn that has ≥1
    citation (2–4 chips, derived client-side from `intent` + last
    entity).
12. Citation hovercard appears within 250 ms of hover on `[cN]` anchor;
    excerpt falls back to title-only until backend ships extracts
    (acceptable today).
13. `is_fallback` / `fallback_of` on `tool_call` renders the row as
    `↻ Retrying with X (Y returned empty)` instead of a fresh spinner.
14. Arch tests `no-legacy-citation`, `no-off-palette-colors`,
    `animation-policy` all pass.
15. Vitest density test: `expect(visibleCells).toBeGreaterThanOrEqual(50)`.
16. 3 Playwright e2e tests pass:
    - density gate at 1440×900,
    - citation hover interaction (hover → hovercard within 300ms),
    - `?debug=1` toggle reveals `ToolTraceDrawer`.
17. `pnpm --filter worldview-web typecheck` + `lint` zero errors.
18. No `analytics.track(...)` call in Wave K code; `console.debug` used
    for telemetry (matches W7 convention Δ9).
19. No new top-level palette tokens; all surfaces use existing tokens
    (`bg-card`, `border-border`, `text-foreground`, `text-positive`,
    `text-warning`, `text-negative`, `text-muted-foreground`).
20. 22 px / 18 px row heights respected (thread rows 24px, citation
    rows 18px, tool-call rows 16px per design §6.4).

---

## §5. Pre-flight (verify before writing any code)

1. `git log --oneline -10` — confirm W7 commits present on `main`.
2. `rg "InlineCitationAnchor" apps/worldview-web/components/primitives/` —
   confirm primitive exists.
3. `rg "AiContentRail" apps/worldview-web/components/primitives/` —
   confirm primitive exists.
4. `rg "useChatStream" apps/worldview-web/features/chat/hooks/` —
   confirm hook at expected path; locate line 616 catch-all.
5. `rg "interface Citation\b" apps/worldview-web/types/api.ts` —
   confirm drifted shape at line 1332.
6. `rg "qk.chat" apps/worldview-web/lib/query/keys.ts` — confirm
   namespace exists.
7. `grep -n "class MessageResponse" services/rag-chat/src/rag_chat/api/schemas.py` —
   confirm current minimal shape (will be extended by parallel session).
8. `rg "MessageBubble" apps/worldview-web/features/chat/components/` —
   confirm legacy component exists for removal.
9. `rg "CitationList\|CitationBar" apps/worldview-web/` — locate the
   two existing renderers we are folding into `CitationStrip`.
10. Confirm Q-9 backend status with the parallel orchestration session
    BEFORE T-04 commits the optional fields to `Message`; if Q-9 is
    expected within the same week, ship the extension. Otherwise ship
    the type extension and surface fallbacks; do NOT block.

If any check fails, stop and report — don't improvise.

---

## §6. File-by-file change set (each task = one commit)

### Block A — Type layer + query keys

**T-01 (EDIT)** `apps/worldview-web/lib/query/keys.ts`
Add to `qk.chat` namespace:
```ts
contradictions: (threadId: string) => ['chat', threadId, 'contradictions'] as const,
recentCitations: (threadId: string) => ['chat', threadId, 'recent-citations'] as const,
```
Both are derived (no fetch); used as cache anchors only.
**Acceptance**: typecheck passes; existing `qk.chat.threads`/`thread(id)`
keys untouched.
**Budget**: ≤ 15 LOC.
**Commit**: `feat(plan-0089-k): T-01 qk.chat.contradictions + recentCitations`

**T-02 (EDIT)** `apps/worldview-web/types/api.ts`
1. Add `CitationV2` type mirroring the backend wire shape verbatim:
   ```ts
   /**
    * Canonical chat citation shape — matches SSEEmitter.emit_citations.
    * Use this for all new code. The legacy `Citation` interface is
    * retained for one wave and will be removed in PLAN-0089-K-FU.
    */
   export interface CitationV2 {
     ref: number;
     item_type: 'chunk' | 'relation' | 'claim' | 'event' | 'financial';
     id: string;
     title: string | null;
     url: string | null;
     source_name: string | null;
     published_at: string | null;
     entity_name: string | null;
     confidence: number | null;
   }
   ```
2. Mark legacy `Citation` interface with JSDoc:
   ```ts
   /** @deprecated Use `CitationV2`. Removed after PLAN-0089-K-FU. */
   ```
3. Extend `Message` interface with optional Q-9 fields:
   ```ts
   provider?: string | null;
   model?: string | null;
   latency_ms?: number | null;
   message_id?: string;
   contradictions?: Array<{ claim_type: string; strength: number; sides: unknown[] }>;
   resolved_entities?: Array<{ entity_id: string; ticker?: string | null }>;
   retrieval_plan?: Record<string, unknown> | null;
   is_fallback?: boolean;
   fallback_of?: string;
   ```
**Acceptance**: typecheck passes; `Citation` still importable; new fields
optional and default-undefined (no consumer break).
**Budget**: ≤ 40 LOC added.
**Commit**: `feat(plan-0089-k): T-02 CitationV2 + Message Q-9 extension`

**T-03 (EDIT)** `apps/worldview-web/features/chat/hooks/useChatStream.ts`
Around line 616 (catch-all comment), extend the SSE switch:
1. Parse `metadata` event → populate `streaming` state with `intent`,
   `provider`, `model`, `latency_ms`, `message_id`. Write through to
   the persisted message at `done`-time.
2. Parse `contradictions` event → store on the active turn's
   `contradictions[]` field.
3. Parse `tool_call.is_fallback` / `tool_call.fallback_of` and forward
   to the active tool-call state.
4. Acknowledge `final_answer` silently (PLAN-0093 E-5 sync path).
5. Map `cite.id` → `CitationV2.id` (legacy `cite.article_id` becomes a
   fallback read order only — do NOT remove `Citation` in this commit).
**Acceptance**: `__tests__/hooks/useChatStream.test.tsx` extended with
3 new cases (metadata / contradictions / fallback-tool); existing tests
pass.
**Budget**: ≤ 60 LOC added inside the SSE switch.
**Commit**: `feat(plan-0089-k): T-03 useChatStream parses metadata + contradictions + fallback flags`

### Block B — Layout shell + flat-turn renderer

**T-04 (NEW)** `apps/worldview-web/features/chat/components/ChatLayout.tsx`
Three-column grid wrapper. Owns context-rail collapse state and the
`Cmd+\` listener (chord scope: "page"). Width breakpoints:
- `lg`: 3-col (224 / flex / 320)
- `md`: 2-col (rail auto-collapsed, message + context)
- `sm`: 1-col (message only; rail accessible via slide-over — v1.1
  scope; v1 uses `lg` minimum gate from `apps/worldview-web/app/(app)/chat/page.tsx`)
**Props**: `{ children: ReactNode }`.
**Budget**: ≤ 220 LOC.
**Commit**: `feat(plan-0089-k): T-04 ChatLayout 3-col shell + Cmd+\\ collapse`

**T-05 (NEW)** `apps/worldview-web/features/chat/components/ThreadRail.tsx`
Lifts thread-rail JSX out of `page.tsx` lines 549–693 (per design §5.1).
Composes existing `MarketContextBanner` + new `SearchInput` + existing
`ThreadItem` (modified row height in T-08).
**Props**: `{ threads, activeThreadId, onSelect, onRename, onDelete,
isLoading, error }`.
**Acceptance**: a11y `nav` landmark preserved; existing rename / delete
handlers wired verbatim.
**Budget**: ≤ 180 LOC.
**Commit**: `feat(plan-0089-k): T-05 ThreadRail extracted from page.tsx`

**T-06 (NEW)** `apps/worldview-web/features/chat/components/ChatMessageList.tsx`
Flat message column; renders one `<MessageTurn>` per message + a
trailing `<StreamingTurn>` when `streaming.active`.
**Props**: `{ messages, streaming, activeTools, threadId, onFollowUp }`.
**Budget**: ≤ 200 LOC.
**Commit**: `feat(plan-0089-k): T-06 ChatMessageList flat renderer`

**T-07 (NEW)** `apps/worldview-web/features/chat/components/MessageTurn.tsx`
Replaces `MessageBubble` (deletion in T-22). One conversation turn
rendered FLAT — no avatar bubble. Renders:
- Role gutter `w-7` with glyph (U / A) + accent rail `border-l-2 border-primary/50`
  when `streaming.active` (reuse `AiContentRail` primitive if its
  existing chrome matches the spec; otherwise hand-roll the 2px border).
- Mono timestamp `text-[9px]` via `safeFormatClockTime` (existing helper).
- `<MessageMetaStrip>` (T-09) under timestamp.
- `<LazyMarkdownContent>` body with new prop `withInlineCitationAnchors`.
- `<ToolCallTray>` (T-08) when `turn.tool_calls.length > 0`.
- `<CitationStrip>` (T-10) when `turn.citations.length > 0`.
- `<ContradictionStrip>` (T-11) when `turn.contradictions.length > 0`.
- `<FollowUpChips>` (T-13) when ≥1 citation.
**Props**: `{ turn: Message; size?: 'default' | 'compact' }`.
**Budget**: ≤ 220 LOC.
**Commit**: `feat(plan-0089-k): T-07 MessageTurn flat layout + accent rail`

**T-08 (NEW)** `apps/worldview-web/features/chat/components/ToolCallTray.tsx`
Replaces inline rendering inside `StreamingBubble`. Auto-expanded while
any tool is running; auto-collapses to a one-line summary 1.5s after
the last tool finishes. Reuses existing `ToolCallIndicator` for each
row verbatim.
**Props**: `{ tools: ToolCallState[]; defaultCollapsed?: boolean }`.
**Acceptance**: hover bg `bg-muted/40`; click on header toggles
collapsed state (persisted per turn via `useState`, not the URL —
the per-turn DOM tree owns its state); 100ms `max-height` transition
only.
**Budget**: ≤ 140 LOC.
**Commit**: `feat(plan-0089-k): T-08 ToolCallTray collapsible`

**T-09 (NEW)** `apps/worldview-web/features/chat/components/MessageMetaStrip.tsx`
One-line 9px mono strip under each assistant turn:
`REASONING · via DeepInfra · deepseek-r1-distill-32b · 1.4s · 14:01:24`.
Reads `intent`, `provider`, `model`, `latency_ms`, `created_at`,
`is_fallback` from `turn` (all optional; component renders `null` if
nothing to show).
**Props**: `{ intent, provider, model, latencyMs, createdAt, role, isFallback }`.
**Acceptance**: when `streaming` and `latencyMs === null`, render
`· streaming…` in place of latency.
**Budget**: ≤ 90 LOC.
**Commit**: `feat(plan-0089-k): T-09 MessageMetaStrip 9px terminal strip`

### Block C — Citations + contradictions + popover + follow-ups

**T-10 (NEW)** `apps/worldview-web/features/chat/components/CitationStrip.tsx`
Replaces `CitationBar` + `CitationList` (deletion in T-22). Single
bordered region: confidence bar on top + 18px rows underneath, each row
`[N] [TYPE] title · src · pct · date · [low-conf chip if confidence<0.6]`.
Reads `CitationV2` shape verbatim.
Hover row → `<CitationHoverCard>` (T-12).
Click row → scrolls matching inline anchor into view + flash.
**Props**: `{ citations: CitationV2[]; anchorPrefix?: string }`.
**Acceptance**:
- arch test passes (T-21);
- no `(undefined * 100).toFixed(0)` paths;
- confidence chip Q-12 renders only when `confidence !== null && confidence < 0.6`;
- empty state when array empty: component returns `null`.
**Budget**: ≤ 180 LOC.
**Commit**: `feat(plan-0089-k): T-10 CitationStrip CitationV2 + Q-12 low-conf chip`

**T-11 (NEW)** `apps/worldview-web/features/chat/components/ContradictionStrip.tsx`
Renders the (previously-discarded) `contradictions` SSE payload under
the citation strip and in the right rail. Severity (HIGH/MEDIUM/LOW)
colour-coded via `text-warning` / `text-negative` / `text-muted-foreground`
(no new palette tokens).
**Props**: `{ contradictions: Array<{ claim_type; strength; sides[] }>; onOpen?: () => void }`.
**Budget**: ≤ 120 LOC.
**Commit**: `feat(plan-0089-k): T-11 ContradictionStrip from SSE contradictions event`

**T-12 (NEW)** `apps/worldview-web/features/chat/components/CitationHoverCard.tsx`
Radix `HoverCard` content: source name, title, excerpt (240 chars,
title-only fallback today), `published_at`, `Open ↗` button. Reads
`CitationV2` shape.
**Props**: `{ citation: CitationV2 }`.
**Budget**: ≤ 120 LOC.
**Commit**: `feat(plan-0089-k): T-12 CitationHoverCard Radix hover excerpt`

**T-13 (NEW)** `apps/worldview-web/features/chat/components/FollowUpChips.tsx`
2–4 dense chips under an assistant turn. Suggestions derived
client-side from `turn.intent` + last entity context (TradingView
pattern). Click → `onPick(suggestion)` which sets composer value and
immediately `send()`-s.
**Props**: `{ suggestions: string[]; onPick: (q: string) => void }`.
**Budget**: ≤ 90 LOC.
**Commit**: `feat(plan-0089-k): T-13 FollowUpChips per-answer chips`

### Block D — Context rail + KG enrichment

**T-14 (NEW)** `apps/worldview-web/features/chat/components/RelationEvidencePopover.tsx`
Anchored to KG-type citation rows. Reads `evidence_snippets[]` +
`relation_summary` from the cached `get_entity_graph` tool result (data
present today per design §3.3). Up to 3 snippets, each ≤ 200 chars,
mono 10px.
**Props**: `{ relation: GraphEdge; evidenceSnippets: string[]; summary?: string | null }`.
**Budget**: ≤ 130 LOC.
**Commit**: `feat(plan-0089-k): T-14 RelationEvidencePopover for KG citations`

**T-15 (NEW)** `apps/worldview-web/features/chat/components/EntityHealthDot.tsx`
8px circular dot keyed off `get_entity_health.health_score` from the
last turn's tool result. Colour ramp:
- ≥0.7 `bg-positive`
- 0.4–0.7 `bg-warning`
- <0.4 `bg-negative`

Tooltip via Radix Tooltip shows `{score} · {fields_populated}/{total_fields}`.
**Props**: `{ score: number; dataCompleteness?: { populated: number; total: number } }`.
**Budget**: ≤ 60 LOC.
**Commit**: `feat(plan-0089-k): T-15 EntityHealthDot 8px score indicator`

**T-16 (NEW)** `apps/worldview-web/features/chat/components/ChatContextRail.tsx`
Right-hand rail with 4 sections separated by `<SectionDivider>`:
1. Entity card: name + price + change + P/E + market_cap + employees +
   sector + `<EntityHealthDot>` + narrative-version badge
   (e.g. "Narrative v3 · 2026-05-22").
2. Recent citations: top-N citations across the thread, deduplicated
   by `id` (Q-4 lock: dedupe with highest-relevance occurrence winning;
   suffix `· {count}×`).
3. Contradictions: aggregated `<ContradictionStrip>` across turns.
4. Related tickers: `<TickerLink>` (F2 primitive) chips for entities
   resolved in this thread.

All data sourced from cached tool results captured during turns —
no extra fetch. Subscribes via TanStack derived queries
(`qk.chat.contradictions` + `qk.chat.recentCitations`).
**Props**: `{ threadId: string; activeEntity?: { id: string; ticker: string | null } | null }`.
**Budget**: ≤ 280 LOC.
**Commit**: `feat(plan-0089-k): T-16 ChatContextRail entity + citations + contradictions + tickers`

### Block E — Composer + empty / error + AskAiPanel restyle

**T-17 (NEW)** `apps/worldview-web/features/chat/components/ChatComposer.tsx`
Lifts the textarea + send button + slash autocomplete + entity context
+ related chips out of `page.tsx` (lines 887–994).
**Props**: `{ value, onChange, onSend, onCancel, isStreaming, entityContext,
relatedChips, autocomplete }`.
**Budget**: ≤ 220 LOC.
**Commit**: `feat(plan-0089-k): T-17 ChatComposer extracted from page.tsx`

**T-18 (NEW)** `apps/worldview-web/features/chat/components/ChatEmptyState.tsx`
+ `apps/worldview-web/features/chat/components/ChatErrorBanner.tsx`.
Lifts empty-state + 401-vs-generic error banner out of `page.tsx`.
**Budget**: ≤ 120 + ≤ 80 LOC.
**Commit**: `feat(plan-0089-k): T-18 ChatEmptyState + ChatErrorBanner`

### Block F — Debug-only ToolTraceDrawer (Q-8)

**T-19 (NEW)** `apps/worldview-web/features/chat/components/ToolTraceDrawer.tsx`
+ `apps/worldview-web/features/chat/hooks/useDebugFlag.ts`.
- `useDebugFlag()` reads `useSearchParams().get('debug') === '1'` once on
  mount (memoized; no cookie / no localStorage persistence per Q-8).
- `ToolTraceDrawer` right-docked 320px panel. Visible only when
  `useDebugFlag() && open`. Reads `retrieval_plan`, `resolved_entities`,
  `token_count_in/out`, full tool_call/tool_result trace from the
  selected `turn`.
- Toggle via `⌘D` while focused on an assistant turn — but only when
  `debug=1` is set (the chord is registered conditionally).
**Props**: `{ open, onClose, turn }`.
**Acceptance**: typecheck passes; component renders `null` if
`useDebugFlag()` returns false; arch test `no-stdlib-logging` not
applicable (this is frontend — no logger calls); `console.debug` only.
**Budget**: ≤ 200 LOC.
**Commit**: `feat(plan-0089-k): T-19 ToolTraceDrawer + useDebugFlag (Q-8 gated)`

### Block G — Existing component updates

**T-20 (EDIT)** Component renames / wiring:
1. `features/chat/components/ThreadItem.tsx`: row height
   `py-1.5` → `py-1` (28 px → 24 px); add `· {message_count} msgs`
   suffix when > 0. Reads `Thread.message_count` already on the wire
   (design §3.8 — newly surfaced field 12).
2. `features/chat/components/LazyMarkdownContent.tsx`: add prop
   `withInlineCitationAnchors?: boolean` (default false). When true,
   swap `withCitationSups` for `<InlineCitationAnchor>` per the F1
   primitive.
3. `components/shell/AskAiPanel.tsx`: drop the `text-sm` bubble in
   favour of `<MessageTurn size="compact">`; inherit `<CitationStrip>`
   instead of the bespoke `parsedSources` list. KEEP its existing
   `<InlineCitationAnchor>` usage (no regression).
4. `components/intelligence/EntityChatPanel.tsx`: shares `useChatStream`
   — inherits all wire-format fixes automatically. **No source change**;
   this is a verification-only step (commit-style: docs note in commit
   body confirming visual delta is intentional).
5. `app/(app)/chat/page.tsx`: rewrite to compose
   `<ChatLayout>` + `<ThreadRail>` + `<ChatMessageList>` +
   `<ChatComposer>` + `<ChatContextRail>` + `<ChatEmptyState>` +
   `<ChatErrorBanner>` + `<ToolTraceDrawer>`. Lines drop from ~1200
   to ≤ 350.
**Budget**: ~250 LOC delta total.
**Commit**: `feat(plan-0089-k): T-20 wire new components into page + AskAiPanel + ThreadItem + LazyMarkdownContent`

### Block H — Architecture tests

**T-21 (NEW)** `apps/worldview-web/__tests__/architecture/no-legacy-citation.test.ts`
Vitest arch test: greps for `\bCitation\b(?!V2)` imports in any file
under `features/chat/` or `components/chat/` modified after this
commit, EXCLUDING `types/api.ts` itself. Fails if found.
Use `tsm` + AST walker (re-use the helper from
`__tests__/architecture/no-off-palette-colors.test.ts`).
**Acceptance**: test passes on Wave K HEAD; intentionally fails on a
proof-of-concept new import.
**Budget**: ≤ 90 LOC.
**Commit**: `test(plan-0089-k): T-21 no-legacy-citation arch test (Q-10)`

### Block I — Unit tests + Playwright

**T-22 (NEW)** Unit tests + legacy removal:
1. `__tests__/components/chat/MessageTurn.test.tsx` (flat layout,
   role gutter, accent rail when streaming, no avatar)
2. `__tests__/components/chat/ToolCallTray.test.tsx` (auto-collapse 1.5s
   after last tool; click-to-expand)
3. `__tests__/components/chat/MessageMetaStrip.test.tsx` (intent
   variants; null fields hidden; streaming label)
4. `__tests__/components/chat/CitationStrip.test.tsx` (V2 shape;
   low-conf chip Q-12; click → flash; no NaN%)
5. `__tests__/components/chat/CitationHoverCard.test.tsx`
6. `__tests__/components/chat/ContradictionStrip.test.tsx`
7. `__tests__/components/chat/FollowUpChips.test.tsx`
8. `__tests__/components/chat/RelationEvidencePopover.test.tsx`
9. `__tests__/components/chat/EntityHealthDot.test.tsx`
10. `__tests__/components/chat/ChatContextRail.test.tsx`
11. `__tests__/components/chat/ToolTraceDrawer.test.tsx` (renders null
    when `?debug=1` absent; renders panel when present)
12. `__tests__/components/chat/chat-density.test.tsx` density gate ≥ 50

**Legacy deletions (same commit)**:
- `features/chat/components/MessageBubble.tsx`
- `features/chat/components/CitationList.tsx`
- `components/chat/CitationBar.tsx`
+ their `__tests__/` siblings.

**Budget**: 12 test files (~600 LOC) + 3 deletions.
**Commit**: `test(plan-0089-k): T-22 12 vitest specs + legacy bubble/CitationList/CitationBar removal`

**T-23 (NEW)** `apps/worldview-web/e2e/chat-polish.spec.ts`
3 Playwright tests:
1. **Density gate at 1440×900** — open `/chat`, send a fixture message,
   await `assistant-turn` selector, count visible cells via
   `page.locator('[data-cell]').count()` ≥ 50.
2. **Citation hover interaction** — hover the first `[c1]` anchor;
   expect `[role="tooltip"]` or `[data-radix-hover-card-content]`
   visible within 300ms; expect `source_name` text visible.
3. **`?debug=1` reveals `ToolTraceDrawer`** — navigate to
   `/chat?thread_id=…&debug=1`; press `⌘D` on the latest assistant
   turn; expect `[data-testid="tool-trace-drawer"]` visible. Repeat
   without `?debug=1` and assert it never appears.
**Budget**: ≤ 220 LOC.
**Commit**: `test(plan-0089-k): T-23 playwright density + hover + debug-drawer`

---

## §7. Validation gates (run after every block)

After each block:
- `pnpm --filter worldview-web typecheck`
- `pnpm --filter worldview-web lint`
- `pnpm --filter worldview-web test -- features/chat` (relevant slice)

Before commit/merge:
- `pnpm --filter worldview-web test` (full Vitest run)
- `pnpm --filter worldview-web exec playwright test e2e/chat-polish.spec.ts`
- `pnpm --filter worldview-web test -- __tests__/architecture` (arch tests)
- `pnpm audit` — 0 CVEs (per project rule: pnpm only, exact versions)

No backend `ruff` / `mypy` step required (Wave K is doc + frontend only;
backend Q-9 work is owned by parallel session and will run its own
gates).

---

## §8. Risks

| # | Risk | Mitigation |
|---|------|-----------|
| R-1 | Q-9 backend doesn't land before Wave K merges → history-reloaded turns lack `provider`/`model`/`latency_ms`/`contradictions` | All Q-9 fields optional on `Message`; `MessageMetaStrip` renders `null` when fields missing; no crash, only a missing strip on legacy turns. UI smoke test catches the visual delta. |
| R-2 | `useChatStream.ts` SSE switch is large; regressions risk | T-03 adds 3 new vitest cases + reuses existing switch block; deterministic line target (~616) |
| R-3 | `Cmd+\` clashes with global shell sidebar toggle (Q-6 still open) | Pre-flight step (§5) confirms global shell hotkey registry; if clash exists, fall back to `Cmd+Shift+\` |
| R-4 | `CitationV2` migration causes visual regressions in `AskAiPanel` | T-20 explicitly visually verifies AskAiPanel; existing `InlineCitationAnchor` usage preserved verbatim |
| R-5 | `ContradictionStrip` empty state vs full state styling drift | Component returns `null` when array is empty (per T-11 acceptance); design § 6.2 reserves `text-warning` token only |
| R-6 | `ToolTraceDrawer` debug param leaks via URL sharing | Acceptable — Wave K spec for Q-8 explicitly says no persistence; users sharing `?debug=1` URLs is the only intended affordance |
| R-7 | Existing `__tests__/hooks/useChatStream.test.tsx` breaks on T-03 | Run vitest slice after T-03; if existing assertions on `unknown event` path conflict, update them to new acknowledgement behaviour |
| R-8 | Density gate flakes (e2e) when fixture data has fewer than ~50 cells worth of citations / tools | Use a deterministic seed fixture with ≥ 4 citations + 2 tools; vitest density test (T-22 case 12) is the canonical guard, e2e is a secondary signal |

---

## §9. Files touched (forecast)

**New (16 components + 1 hook + 4 test sets + 1 e2e + 1 arch test)**:
- `features/chat/components/ChatLayout.tsx`
- `features/chat/components/ThreadRail.tsx`
- `features/chat/components/ChatMessageList.tsx`
- `features/chat/components/MessageTurn.tsx`
- `features/chat/components/ToolCallTray.tsx`
- `features/chat/components/MessageMetaStrip.tsx`
- `features/chat/components/CitationStrip.tsx`
- `features/chat/components/CitationHoverCard.tsx`
- `features/chat/components/ContradictionStrip.tsx`
- `features/chat/components/FollowUpChips.tsx`
- `features/chat/components/RelationEvidencePopover.tsx`
- `features/chat/components/EntityHealthDot.tsx`
- `features/chat/components/ChatContextRail.tsx`
- `features/chat/components/ChatComposer.tsx`
- `features/chat/components/ChatEmptyState.tsx`
- `features/chat/components/ChatErrorBanner.tsx`
- `features/chat/components/ToolTraceDrawer.tsx`
- `features/chat/hooks/useDebugFlag.ts`
- 12 Vitest specs + `__tests__/architecture/no-legacy-citation.test.ts`
- `e2e/chat-polish.spec.ts`

**Modified (~7)**:
- `lib/query/keys.ts` (+contradictions + recentCitations)
- `types/api.ts` (+CitationV2; Message Q-9 fields)
- `features/chat/hooks/useChatStream.ts` (metadata + contradictions + fallback parse)
- `features/chat/components/ThreadItem.tsx` (24px row + message_count suffix)
- `features/chat/components/LazyMarkdownContent.tsx` (+withInlineCitationAnchors prop)
- `components/shell/AskAiPanel.tsx` (use MessageTurn compact + CitationStrip)
- `app/(app)/chat/page.tsx` (rewrite as composition)

**Deleted (3 + tests)**:
- `features/chat/components/MessageBubble.tsx` + `__tests__/MessageBubble.test.tsx`
- `features/chat/components/CitationList.tsx` + `__tests__/CitationList.test.tsx`
- `components/chat/CitationBar.tsx` + tests if any

**Net LOC**: ~+2,200 / −900 (page.tsx alone drops ~850).

**Task count**: 23 (T-01..T-23). Within the W3/W7 12–25 calibration band.

---

## §10. Estimation

| Block | Days |
|-------|------|
| A — Types + query keys + hook patch (T-01..T-03) | 0.75 |
| B — Layout shell + flat-turn renderer (T-04..T-09) | 1.5 |
| C — Citations + contradictions + popover + chips (T-10..T-13) | 1.0 |
| D — Context rail + KG enrichment (T-14..T-16) | 1.0 |
| E — Composer + empty / error / AskAiPanel restyle (T-17..T-18, partial T-20) | 0.5 |
| F — ToolTraceDrawer + useDebugFlag (T-19) | 0.5 |
| G — Existing component updates (T-20) | 0.5 |
| H — Arch tests (T-21) | 0.25 |
| I — Unit tests + Playwright + legacy deletion (T-22..T-23) | 1.0 |
| Validation + QA + visual review | 0.25 |
| **Total serial** | **7.25 engineer-days** |

Plan estimate: **5–6 engineer-days** assuming Q-9 backend is already
landed (saves ~1d of degradation-mode test cases). If Q-9 is still in
flight, plan to 6–7 days and ship Wave K with Q-9-optional fields
graceful-degrading.

---

## §11. Rollout

1. Land Wave K behind no feature flag — the redesign IS the chat page.
2. `?debug=1` query param is the only "gated" surface; default UX is
   identical to the spec.
3. After Wave K ships, open PLAN-0089-K-FU for:
   - atomic `Citation` → `CitationV2` rename across all call sites
   - `tool_data` SSE event + `InlineToolResultCard` (Q-11)
   - Pin/unpin thread feature (Q-3)
   - Q-5 `ActionConfirmModal` dock
4. Memory updated post-merge: `project_plan0089_k_shipped.md` with
   density realized + cell count + arch-test status.

---

## §12. Definition of Done

1. All 20 acceptance checks in §4 pass.
2. 12 Vitest unit tests + 1 density test + 1 arch test + 3 Playwright
   e2e tests pass.
3. `pnpm --filter worldview-web typecheck` + `lint` zero errors.
4. No new palette tokens, no new font sizes outside the
   `text-[9..14]px` band, all rows respect 22 px / 18 px / 16 px
   heights per design §6.4.
5. Live walk-through `/chat`:
   - flat layout (no bubbles),
   - `MessageMetaStrip` visible on assistant turns,
   - citation hovercard within 300 ms,
   - `ContradictionStrip` visible if backend emits any,
   - `?debug=1` reveals `ToolTraceDrawer` via `⌘D`,
   - thread row shows `· N msgs` suffix.
6. Legacy `MessageBubble` / `CitationList` / `CitationBar` deleted;
   no stale imports remain.
7. `git log --oneline` shows 23 commits, one per task.
8. Memory entry written.

---

## Revision pass — 2026-05-25

Post-write audit against (a) the just-finalized `10-chat-ai.md`,
(b) existing F1 primitives, (c) `docs/ui/DESIGN_SYSTEM.md`,
(d) RULES.md R25/R27, (e) W1/W2/W3/W5/W7 plan calibration,
(f) `docs/designs/0089/oq/_DECISIONS.md`.

| # | Inconsistency | Fix applied |
|---|---------------|------------|
| RP-1 | Original draft included `InlineToolResultCard` in Block C task list; Q-11 lock defers it. | Removed from §6 task list; documented in §2 (out of scope) and §10 design doc §5.4. |
| RP-2 | Draft had `T-21` adding `InlineCitationAnchor` as a NEW component. Design doc §5.2 (post-revision) lists it as EXISTS. | Plan now reuses `<InlineCitationAnchor>` via `LazyMarkdownContent` prop (T-20.2). No new anchor component. |
| RP-3 | Draft missed the `qk.chat.recentCitations` key referenced in design §8.1 table. | Added to T-01 alongside `qk.chat.contradictions`. |
| RP-4 | Draft acceptance gate listed "5 right-rail blocks" — that's W7's phrasing; chat's design has 4 sections (entity / citations / contradictions / related). | §4 check #6 + T-16 spec corrected to 4 sections. |
| RP-5 | Draft referenced R25 / R27 (API uses use cases; read/write UoW split). These are BACKEND rules; Wave K is frontend + doc only. | Removed from §7 validation gates; kept the dependency note for the parallel backend session in §3 D-1. |
| RP-6 | Draft used "Cmd+\\" inconsistently with Q-6 (still open per design §10). | Added R-3 to risk register; pre-flight step instructs to verify against global shell hotkey registry. |
| RP-7 | Draft had T-23 as 4 Playwright tests; W7 ran 4 too, but Wave K is chat-only and density / hover / debug-drawer is sufficient. | Trimmed to 3 Playwright tests; density gate doubled-up via Vitest test in T-22 case 12 (cheaper, less flaky). |
| RP-8 | Draft did not call out that legacy `MessageBubble.tsx` deletion happens in same commit as test additions — risk of "test before code" inversion. | T-22 acceptance now reads: tests + deletions in one atomic commit (Vitest will not import the deleted files because new tests don't depend on them). |
| RP-9 | Draft missed the `data-cell` selector convention used by W3/W7 density e2e. | T-23 case 1 now explicitly counts `[data-cell]`. Components in Block B/C must tag dense cells with `data-cell`; added as an implicit ACCEPT in §4 #1 / T-22 density spec. |
| RP-10 | Draft estimate was 4–5 days; W3 (6–7d, 30+ tasks) and W7 (6.75d, 27 tasks) calibrate Wave K's 23 tasks closer to 5.5–6.5d. | §10 raised to 5–6 (Q-9 in) / 6–7 (Q-9 out). |
| RP-11 | Draft validation gates included `ruff` + `mypy`. Wave K touches zero Python files. | §7 trimmed to typecheck / lint / vitest / playwright / pnpm audit. |
| RP-12 | Draft's "Files touched" forecast missed `useDebugFlag.ts` (separate file under `hooks/`). | §9 corrected. |
| RP-13 | Draft missed mentioning the W3 Δ23 convention (replace `analytics.track` with `console.debug`). | §4 check #18 + §1 goal 5 explicit. |
| RP-14 | Draft's T-19 (`ToolTraceDrawer`) did not specify that `⌘D` hotkey is conditionally registered. | T-19 acceptance updated: "chord registered only when `useDebugFlag()` returns true". |
| RP-15 | Cross-checked `_DECISIONS.md` cluster 3 (AI brief + chat): FU-3.3 (binary thumbs feedback on AskAiPanel) is a separate v1 commitment NOT covered by Wave K. | Added to §2 out-of-scope and to §11 rollout follow-ups. |
| RP-16 | Cross-checked DISCUSS-6 (single `InlineCitationAnchor` across surfaces, AskAiPanel deletes ~310 LOC of duplicate parsing). Wave K's T-20.3 partially achieves this; the full 310-LOC purge is broader than chat. | Documented in §11 rollout: "AskAiPanel duplicate-parser purge to be tracked separately under DISCUSS-6". |
| RP-17 | Density target re-confirmed against design §10 recount (103 cells). Plan check #1 says ≥ 50 (matches design index 40+). | §4 check #1 reads ≥ 50 with explicit reference to the 103 design-doc recount. |

All inconsistencies fixed in place. No blocking issues prevent
`/implement-ui` from running on this plan.
