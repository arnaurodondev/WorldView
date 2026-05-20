# Chat / AI Panel — Design Spec (PRD-0089)

> Per-page design doc for the `/chat` route and the related `AskAiPanel`
> floater (TopBar trigger). Authored 2026-05-19 by `agent-chat`.
> Follows the skeleton mandated in `docs/designs/0089/_INDEX.md`.

---

## 1. Competitor research summary

### Bloomberg Terminal — AskBloomberg / `LP <GO>`

- Live "Conversational Bloomberg" assistant: dense left rail with prior
  conversations (mono titles, last-activity timestamp), and a centre column
  that streams answers in a flat text format using the same body type as
  the rest of the terminal — **no avatar bubbles, no rounded chat shells**.
- Source citations appear as inline tags such as `[BN 4-WK]` / `[ER]` —
  bracketed mono badges that double-click open the underlying news story
  or earnings transcript in a sibling pane.
- Tool calls visible as one-line "TICKER lookup → ok (12 rows)" status
  lines streamed *before* the answer text — the terminal explicitly shows
  the analyst what data is being consulted (Bloomberg calls this
  "transparent retrieval").
- Empty thread: 4–6 starter prompts laid out as a 2-col grid of compact
  cards labelled "Earnings", "Macro", "Filings", "My positions" — same
  rhythm we already use, just denser (no padding > 8px).
- Density: thread row ≈ 24px; answer column body 11px mono; citation badges
  9px mono.
- **What to steal**: bracketed citation tags, transparent tool-call lines,
  no-bubble flat text rendering, dense 24–28px thread rows.

### TradingView AI assistant (2024 chat sidebar)

- Right-hand drawer (340px) with shorter thread history; persistent
  context chip ("AAPL — Quote, Earnings") above the message stream so the
  user always sees the assistant's frame of reference.
- Suggested follow-ups appear at the *bottom* of each answer (3 chip
  buttons), not just on the empty state. Reduces blank-input anxiety
  after every turn.
- Streaming uses a static block-cursor (`▎`), not a blinking dot — matches
  our "no bounce" rule.
- **What to steal**: persistent entity-context chip above messages;
  bottom-of-answer follow-up chips; static cursor.

### Perplexity Finance / Stock-GPT

- Research-grade rendering: numbered superscript citations (`¹ ² ³`)
  interleaved with markdown body. Clicking the sup pops a hovercard with
  source title + 1-sentence excerpt + URL.
- "Sources" tray at the bottom of every answer renders sources as a
  horizontal strip of micro-cards (favicon + domain + 1-line title).
- Refresh / regenerate / share buttons appear in a `…` overflow per
  answer — never inline.
- **What to steal**: hovercard expansion on citation hover (not just
  click); per-answer "regenerate" affordance in `…` overflow.

### ChatGPT (code interpreter) & Claude.ai

- Mature dense chat patterns: assistant content uses a flat 14px text
  column (no bubble) with a thin vertical accent rail on the left edge
  when the assistant is "active" (streaming).
- Tool / code execution renders as collapsible blocks ("Analyzing… 0.8s")
  that the user can expand to see the raw tool result. Collapsed by
  default to keep the column scannable.
- Empty state: persona-targeted starter cards (4–6) plus a recent-prompts
  carousel for returning users.
- **What to steal**: collapsible tool-call blocks (default collapsed when
  complete, auto-expanded while running); thin vertical accent rail on
  active streaming text.

---

## 2. User intent for this page

### Primary persona

A **research-driven discretionary analyst or PM** who already has the
quote/news/screener data on screen and uses chat to *interpret* or
*compose*: "why did NVDA pop", "compare my top 5 to consensus", "find
filings that mention supply-chain risk". Secondary persona: a *quant
PM* who treats the panel as a queryable command line (`/screener
sector=tech roe>15`).

### Top-3 primary tasks

1. **Compose a research thread** that spans multiple turns about a single
   instrument or thesis ("AAPL margin headwind" → follow-ups about peers,
   guidance, options skew). The thread must persist and be searchable.
2. **Verify a claim with a citation**. The analyst must be able to find
   the supporting article *in one click* and read the relevant passage.
3. **Pivot from a page** ("I'm on AAPL, ask about it") without retyping
   the ticker. Entity-context chat is the lever.

### Secondary tasks

- Run a structured lookup via slash command (`/quote`, `/portfolio`,
  `/news`, `/watchlist`, `/alerts`, `/screener`).
- Export a thread as markdown for inclusion in an internal memo.
- Confirm a write-action proposed by the assistant (e.g. `create_alert`).
- Rename / delete / search threads.

### Anti-patterns this page MUST NOT become

- **A consumer chatbot.** No avatar bubbles, no animated typing dots,
  no rounded 16px text, no emoji reactions, no "Hi! I'm Claude" copy.
- **A blocking modal.** The full-page chat is at `/chat`; the in-context
  assistant lives in the floating `AskAiPanel` which must never cover
  the active page's data.
- **Lossy on citations.** Every assistant claim that came from a
  retrieved document must surface a clickable source. Silent dropping of
  KG citations is a known prior bug (see `useChatStream.ts` PLAN-0082).
- **Animation-heavy.** Bloomberg-grade UI mandate — no bounce, no pulse,
  no spinner-on-streaming-cursor.

---

## 3. Backend data available

Cited from `docs/designs/0089/00-backend-data-inventory.md` §1.5
(Chat & Briefings — S8 RAG/Chat).

### Endpoints in use today

| Endpoint | Currently displayed? | Notes |
|---|---|---|
| `POST /v1/chat/stream` | yes | Main SSE flow, `useChatStream` reader |
| `POST /v1/chat/entity-context/stream` | yes (sidebar) | Scopes RAG to one entity |
| `POST /v1/chat` (sync) | no | Available for non-streaming clients only |
| `GET /v1/threads` | yes | Sidebar list |
| `GET /v1/threads/{id}` | yes | History on selection |
| `PATCH /v1/threads/{id}` | yes | Rename via double-click |
| `DELETE /v1/threads/{id}` | yes | Trash icon on hover |
| `POST /v1/threads` | implicit | Server upserts thread on first send |

### Fields exposed but **not** displayed (gaps to fill in this redesign)

From inventory §2.4:

- `ChatResponse.intent` — `FACTUAL_LOOKUP | GENERAL | COMPARISON |
  FINANCIAL_DATA | PORTFOLIO | REASONING | RELATIONSHIP | SIGNAL_INTEL`.
  Could drive a small intent chip above the answer ("REASONING") to
  hint at depth.
- `ChatResponse.provider` — `deepinfra | openrouter | ollama`. Surfacing
  this in a small footer chip ("via DeepInfra · 1.4s") satisfies the
  thesis-grade "transparent provider" requirement.
- `ChatResponse.latency_ms` — paired with the provider chip.
- `ChatResponse.contradictions` — list of conflicting claims found in
  retrieved sources. **Not displayed anywhere today.** This redesign
  pulls them into a dedicated `Contradictions` strip below the answer.
- `BriefingResponse.sections[]` — structured `{title, bullets}` shape
  exists; today it renders as flat markdown. Should render as a labelled
  outline.
- `Citation.published_at` — present on the wire, hidden by current
  CitationList chip. Adding it gives the analyst a freshness signal.
- `Thread.message_count` — exposed but the sidebar row only renders
  title + date. A `· 12 msgs` suffix would help scanning long lists.

### SSE event types the frontend already consumes

From `useChatStream.ts`:

- `thinking` (no UI today — proposal: render a 1-line "Classifying
  query…" status before tool_call events appear)
- `tool_call` { tool, label, status: "running" } → `ToolCallIndicator`
- `tool_result` { tool, status: ok|empty|error, item_count } → updates
  the indicator
- `citations` (array, applied at finalise)
- `token` / inline `{text|token}` → streaming bubble
- `pending_action` → ActionConfirmModal
- `action_executed` / `action_rejected` (currently swallowed on the chat
  stream; primary delivery is on the separate confirm stream)
- `done` / `[DONE]` → finalise
- `error` { message } → destructive banner

### Data the user explicitly mentioned in the PRD-0089 brief

- Inline citation expansion (anchor hovercards).
- Tool-call visibility ("Fetching AAPL fundamentals…").
- Suggested questions on empty state.
- Entity-context chat that can be pre-filled from any page.

All four are wired into the redesign below.

---

## 4. Layout

### 4.1 ASCII wireframe (1440×900)

```
┌───────────────────────────────────────────────────────────────────────────── 1440 px ────────────────────────────────────────────────────────────────────────────┐
│  TopBar — global shell · 48 px high (out of scope, see 01-global-shell.md)                                                                                       │
├──────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────┬───────────────────────────────────────┤
│  THREAD RAIL — 224 px    │  MESSAGE COLUMN — 800 px (flex 1, max-w-[820px] centred when wider screen)                  │  CONTEXT RAIL — 320 px (collapsible) │
│                          │                                                                                             │                                       │
│  ┌──────────────────────┐│  ┌───────────────────────────────────────────────────────────────────────────────────┐    │  CONTEXT  ▼  [ × ]                    │
│  │ MKT  US  09:42 EDT   ││  │ THREAD HEADER · 28 px                                                              │    │  ┌──────────────────────────────────┐│
│  │ SPY +0.42% · VIX 14.1││  │  AAPL margin headwind H2-2026          [Pin] [Export ▾] [⋯]                       │    │  │ Entity: AAPL                     ││
│  └──────────────────────┘│  └───────────────────────────────────────────────────────────────────────────────────┘    │  │  $193.42  +1.2% · P/E 28.6       ││
│  ┌──────────────────────┐│                                                                                             │  │  Mkt cap 2.94T · vol 41.2M       ││
│  │ ⌕ Search threads…    ││  ┌───────────────────────────────────────────────────────────────────────────────────┐    │  └──────────────────────────────────┘│
│  └──────────────────────┘│  │ Tue 14 May 2026                                                                    │    │                                       │
│   THREADS · 28 px row   ▲│  │                                                                                    │    │  RECENT CITATIONS · 4                 │
│  ▒ AAPL margin h…  14:32 ││  │  ╎ U  14:01:22                                                                   │    │  [1] AAPL Q2-26 10-Q · SEC ·  98%    │
│    NVDA Hopper r…  13:11 ││  │  ╎    Why is AAPL margin under pressure into H2-26?                              │    │       2026-05-12                      │
│    Fed Q3 outlook  09:54 ││  │  ╎                                                                                │    │  [2] Apple earnings call · EARN · 92%│
│    Portfolio sec…  09:20 ││  │  ╎ A  14:01:24 · REASONING · via DeepInfra · 1.4s                                │    │       2026-05-02                      │
│    Search SEC su…  Mon   ││  │  ╎    [▼ tool calls — 2/2 done]                                                  │    │  [3] Bloomberg supply chain · NEWS·87│
│    Earnings drag…  Mon   ││  │  ╎      ✓ search_documents  (12 results)                                         │    │       2026-05-09                      │
│    INTC peers ROE  Sun   ││  │  ╎      ✓ get_entity_graph  (8 edges)                                            │    │  [4] AAPL Investor Day · KG · 71%    │
│    Spotify earn…   Sun   ││  │  ╎    AAPL¹ guided gross margin to 45.0–46.5% for the Sep'26 quarter,           │    │       2026-04-30                      │
│    Macro liquid…   Fri   ││  │  ╎    citing two compounding headwinds:                                          │    │                                       │
│    /quote NVDA     Fri   ││  │  ╎     • A 60 bp FX drag from the strengthening JPY/CNY².                        │    │  CONTRADICTIONS · 1                   │
│    /portfolio      Fri   ││  │  ╎     • Higher AI silicon ramp costs ahead of Pro-Vision launch³.               │    │  ⚠ FX impact estimated at 60 bp¹     │
│    Tariffs sect…   Thu   ││  │  ╎    Operating margin headwind is partially offset by services growth¹.        │    │     vs 80–120 bp²                     │
│    NVDA vs AMD     Thu   ││  │  ╎                                                                                │    │     [open contradictions ▸]          │
│    /alerts         Thu   ││  │  ╎    ┌─ CITATIONS ──────────────────────────────────────────────────┐         │    │                                       │
│   …14 more                ││  │  ╎    │ ▓▓▓▓▓▓ ▓▓▓▓▓ ▓▓ ▓▓▓▓ confidence strip                       │         │    │  RELATED TICKERS · 3                  │
│                          │  │  ╎    │ [1] SEC  AAPL Q2-26 10-Q · 98% · 2026-05-12                  │         │    │   $AAPL  $NVDA  $TSM                  │
│                          │  │  ╎    │ [2] EARN Apple earnings call · 92% · 2026-05-02              │         │    │                                       │
│                          │  │  ╎    │ [3] NEWS Bloomberg supply chain · 87% · 2026-05-09           │         │    │                                       │
│                          │  │  ╎    └───────────────────────────────────────────────────────────────┘         │    │                                       │
│                          │  │  ╎    [Follow-up ▾]  Compare to MSFT  ·  What does the option skew imply?       │    │                                       │
│                          │  │                                                                                    │    │                                       │
│                          │  │  ╎ U  14:04:11                                                                   │    │                                       │
│                          │  │  ╎    Compare to MSFT.                                                           │    │                                       │
│                          │  │  ╎ A  14:04:13 · COMPARISON · via DeepInfra · streaming…                        │    │                                       │
│                          │  │  ╎    ⟳ search_documents  (running…)                                            │    │                                       │
│                          │  │  ╎    ⟳ get_entity_graph  (running…)                                            │    │                                       │
│                          │  │  ╎    MSFT's commercial cloud gross margin…▎                                    │    │                                       │
│                          │  │                                                                                    │    │                                       │
│                          │  └───────────────────────────────────────────────────────────────────────────────────┘    │                                       │
│                          │                                                                                             │                                       │
│                          │  ┌───────────────────────────────────────────────────────────────────────────────────┐    │                                       │
│                          │  │ COMPOSER · 96 px                                                                   │    │                                       │
│                          │  │ Context: AAPL · $193.42 · +1.2% · P/E 28.6   [× drop]                            │    │                                       │
│                          │  │ Related: $AAPL  $NVDA  $TSM                                                        │    │                                       │
│                          │  │ ┌────────────────────────────────────────────────────────────────────────┐ [▶]   │    │                                       │
│                          │  │ │ Ask about markets, companies, news… / for commands                     │       │    │                                       │
│                          │  │ └────────────────────────────────────────────────────────────────────────┘       │    │                                       │
│                          │  │ Enter ↵ send · Shift+↵ newline · ⌘K threads · 1,082 / 2,000 chars               │    │                                       │
│                          │  └───────────────────────────────────────────────────────────────────────────────────┘    │                                       │
└──────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────┘
                                                                          900 px total height
```

### 4.2 Grid description

Three sticky columns, no top-level scroll. Each column owns its own scroll.

| Region | Width | Sticky? | Scroll axis |
|---|---|---|---|
| Thread rail | `w-[224px]` (unchanged from current implementation) | full-height fixed | Y inside thread list |
| Message column | `flex-1 min-w-[640px] max-w-[820px] mx-auto` | thread-header sticky-top, composer sticky-bottom | Y between header and composer |
| Context rail | `w-[320px]` (collapsible to `w-[0px]` via `Cmd+\`) | full-height fixed | Y inside the rail |

Above-fold density target (1440×900):

- Thread rail: **22 thread rows** visible (28px × 22 = 616px, leaving room
  for the market strip + search + section header).
- Message column: **3 full turns + a streaming turn** visible without
  scroll for an average response length of 6 lines.
- Context rail: **4 citations + 1 contradiction + 3 related-ticker chips**
  visible.

### 4.3 Density target

40+ data-dense cells visible above the fold (count includes thread rows,
citation rows, contradiction row, related-ticker chips, tool-call rows,
context-strip cells, and follow-up suggestions). Today the live `/chat`
page surfaces ~14 — this redesign is the **2.8× density bump** the
PRD-0089 master spec demands.

---

## 5. Component breakdown

Paths below are proposed. Components flagged "EXISTS" are already in the
repo; the rest are new or split out of inline JSX.

### 5.1 New / proposed components

| File | Status | LOC budget | Props | Renders |
|---|---|---|---|---|
| `apps/worldview-web/features/chat/components/ChatLayout.tsx` | NEW | ≤ 220 | `{children}` | Three-column grid wrapper; owns context-rail collapse state and the `Cmd+\` listener. |
| `apps/worldview-web/features/chat/components/ThreadRail.tsx` | NEW (extract) | ≤ 180 | `{threads, activeThreadId, onSelect, onRename, onDelete, isLoading, error}` | Market strip + search + thread list + new-chat button. Pulls existing logic from `page.tsx` lines 549–693. |
| `apps/worldview-web/features/chat/components/ChatMessageList.tsx` | NEW | ≤ 200 | `{messages, streaming, activeTools, threadId, onFollowUp}` | The flat (no-bubble) message column. Each turn is a `<MessageTurn>`. |
| `apps/worldview-web/features/chat/components/MessageTurn.tsx` | NEW (replaces `MessageBubble`) | ≤ 220 | `{turn: Message}` | One conversation turn (user OR assistant) rendered FLAT — no avatar bubble. Renders the role gutter, mono timestamp, metadata strip, body, citation strip, follow-ups. |
| `apps/worldview-web/features/chat/components/ToolCallTray.tsx` | NEW (replaces inline rendering in `StreamingBubble`) | ≤ 140 | `{tools, defaultCollapsed?: boolean}` | Collapsible "tool calls" block. Auto-expanded while any tool is running; auto-collapses to a one-line summary 1.5s after the last tool finishes. |
| `apps/worldview-web/features/chat/components/CitationStrip.tsx` | NEW (replaces `CitationBar` + `CitationList`) | ≤ 180 | `{citations, anchorPrefix}` | Single bordered strip: confidence bar on top + rows underneath, each row `[N] [TYPE] title · src · pct · date`. Hover row → hovercard (excerpt). |
| `apps/worldview-web/features/chat/components/CitationHoverCard.tsx` | NEW | ≤ 120 | `{citation}` | Radix `HoverCard` content: source name, title, excerpt (first 240 chars from `evidence_snippets[0]`), published_at, open-source button. |
| `apps/worldview-web/features/chat/components/InlineCitationAnchor.tsx` | NEW | ≤ 80 | `{number, citation}` | The inline `[c1]` superscript anchor. Hover → opens `CitationHoverCard`. Click → scrolls the CitationStrip row into view + flashes the row border for 600ms. |
| `apps/worldview-web/features/chat/components/MessageMetaStrip.tsx` | NEW | ≤ 90 | `{intent, provider, latencyMs, createdAt, role}` | One-line 9px mono strip under each assistant turn: `REASONING · via DeepInfra · 1.4s · 14:01:24`. Surfaces inventory gaps. |
| `apps/worldview-web/features/chat/components/FollowUpChips.tsx` | NEW | ≤ 90 | `{suggestions, onPick}` | 2–4 dense chips immediately under an assistant turn (TradingView pattern). Suggestions derived from `intent` + last entity context. |
| `apps/worldview-web/features/chat/components/ChatContextRail.tsx` | NEW | ≤ 240 | `{entity, citations, contradictions, relatedTickers}` | Right-hand rail: entity card, "Recent citations" feed (aggregated across turns), `Contradictions` strip, related tickers. |
| `apps/worldview-web/features/chat/components/ChatComposer.tsx` | NEW (extract) | ≤ 220 | `{value, onChange, onSend, onCancel, isStreaming, entityContext, relatedChips, autocomplete}` | Lifts the textarea + send button + slash autocomplete + entity context + related chips out of `page.tsx` (lines 887–994). |
| `apps/worldview-web/features/chat/components/ChatEmptyState.tsx` | NEW (extract) | ≤ 120 | `{onPickStarter, hasEntity}` | The empty-state grid of starter cards. Lifts `page.tsx` lines 714–762 and 817–855. |
| `apps/worldview-web/features/chat/components/ChatErrorBanner.tsx` | NEW | ≤ 80 | `{error, onRetry, onReauth}` | Replaces the inline 401-vs-generic logic in `page.tsx` 632–664. |
| `apps/worldview-web/features/chat/components/ContradictionStrip.tsx` | NEW | ≤ 120 | `{contradictions, onOpen}` | Renders the (currently-hidden) `ChatResponse.contradictions` list under the citation strip and in the right rail. |

### 5.2 Existing components — kept and lightly modified

| File | Status | Modification |
|---|---|---|
| `components/chat/MarketContextBanner.tsx` | EXISTS | unchanged; moves into ThreadRail |
| `components/chat/SlashCommandAutocomplete.tsx` | EXISTS | unchanged |
| `components/chat/SlashCommandCard.tsx` | EXISTS | `CardShell` chrome tightened: `min-w-[280px]` → `min-w-[260px]`; padding `px-3 py-2` → `px-2 py-1.5` to match new turn density |
| `features/chat/components/ThreadItem.tsx` | EXISTS | row height `py-1.5` → `py-1` (28 px → 24 px); add `· {message_count} msgs` suffix when > 0 |
| `features/chat/components/ToolCallIndicator.tsx` | EXISTS | rename and wrap inside new `ToolCallTray` (collapsible); existing 11px mono row visuals reused verbatim |
| `features/chat/components/LazyMarkdownContent.tsx` | EXISTS | new prop `withInlineCitationAnchors` (true on assistant turns) that swaps the existing `withCitationSups` for the new `InlineCitationAnchor` component |
| `features/chat/components/ActionConfirmModal.tsx` | EXISTS | unchanged contract; densify padding to match terminal scale (separate task, not blocking the redesign) |
| `features/chat/hooks/useChatStream.ts` | EXISTS | one addition: expose `intent`, `provider`, `latency_ms` from the `done` / final metadata event (S8 already emits them; the hook discards them today — see comment line 600). Required so `MessageMetaStrip` can render them. |
| `components/shell/AskAiPanel.tsx` | EXISTS | full restyle pass: drop the `text-sm` bubble in favour of the new flat-turn renderer (`MessageTurn size="compact"`); inherit `CitationStrip` instead of the bespoke `parsedSources` ad-hoc list. |

### 5.3 Components removed

- `features/chat/components/MessageBubble.tsx` (`TypingIndicator`,
  `StreamingBubble`, `MessageBubble`) — replaced wholesale by
  `MessageTurn` + a thin `StreamingTurn` (sibling export) that share one
  flat layout.
- `features/chat/components/CitationList.tsx` and
  `components/chat/CitationBar.tsx` — folded into the single
  `CitationStrip` component (one bordered region, no duplicate roles in
  the a11y tree).

### 5.4 Shared primitives reused

- `Skeleton` (shadcn) for thread + message loading states.
- `ScrollArea` (Radix) wraps each scrollable column.
- `HoverCard` (Radix) for `CitationHoverCard`.
- `cn` and `safeFormatClockTime` helpers from `lib/utils`.
- `qk.chat.*` keys from `lib/query/keys.ts` (add `qk.chat.contradictions(threadId)`).

---

## 6. Visual spec (numerical, not vague)

### 6.1 Typography

| Surface | Class | Notes |
|---|---|---|
| Thread row title | `font-mono text-[11px]` | mono per PRD-0089 brief |
| Thread row timestamp | `font-mono text-[9px] text-muted-foreground` | mono, 9px |
| Thread row message-count suffix | `font-mono text-[9px] text-muted-foreground/70` | new |
| Thread rail section header ("THREADS") | `font-mono text-[10px] uppercase tracking-[0.08em]` | matches existing |
| Thread header title | `text-[12px] font-semibold` | section title scale |
| Message body (user **and** assistant) | `text-[11px] leading-[1.5]` | NO bubble |
| Inline citation anchor | `font-mono text-[9px] text-primary` `<sup>` | bracketed `[c1]` not just `[1]` |
| Citation row (in strip) | `font-mono text-[10px]` | type badge + title |
| Citation pct + date | `font-mono text-[9px] text-muted-foreground` | freshness |
| Meta strip (intent · provider · latency · time) | `font-mono text-[9px] text-muted-foreground` | new |
| Tool-call row | `font-mono text-[11px]` | unchanged from existing `ToolCallIndicator` |
| Tool-call summary (collapsed) | `font-mono text-[10px] text-muted-foreground` | "tool calls — 2/2 done" |
| Follow-up chip | `text-[10px]` IBM Plex Sans | label, not data |
| Composer textarea | `text-[12px]` | section-title scale to keep the typing target visible |
| Composer footer hints | `font-mono text-[9px] text-muted-foreground` | shortcut hints |

Hero numbers banned in the chat column entirely — this is a research
surface, not a price column.

### 6.2 Spacing

| Spacing | px | Where |
|---|---|---|
| Thread row vertical padding | `py-1` (4 px) | 24 px row height total |
| Thread row gap | `space-y-0` | hairline border only, no gap |
| Thread rail body padding | `p-2` (8 px) | unchanged |
| Section gap inside thread rail (header → search → list) | `border-b` separator + 0 gap | borders are the rhythm |
| Message column inner padding | `p-3` (12 px) | matches inventory recommendation |
| Inter-turn gap | `gap-3` (12 px) — was `gap-2` (8 px) | one extra row of breathing room; turns no longer have bubbles so we need visible separation |
| Role gutter width (left of body) | `w-7` (28 px) | hosts `U` / `A` glyph + accent rail |
| Active-stream accent rail | `border-l-2 border-primary/50` on the gutter while `streaming.active === true` | replaces blinking cursor |
| Turn body left padding | `pl-3` (12 px) — relative to the gutter | |
| Citation strip outer margin | `mt-2 ml-7` | aligns under the body, not the gutter |
| Citation row vertical padding | `py-0.5` (2 px) | 18 px row height |
| Confidence bar height | `h-1` (4 px) — was `h-1.5` (6 px) | reduce vertical weight |
| Composer outer padding | `p-2` (8 px) — was `p-3` (12 px) | tightens the bottom dock |
| Context rail section gap | `space-y-3` (12 px) | between Entity / Citations / Contradictions / Related |
| Context rail item padding | `p-2` (8 px) | section card |

### 6.3 Color tokens (no new tokens)

| Surface | Token |
|---|---|
| Canvas | `bg-background` (#09090B) |
| Panel surfaces (thread row hover, citation card, context rail card) | `bg-card` (#0D0D10) |
| Hairlines (column dividers, row dividers, strip borders) | `border-border` (#1F1F23) |
| Body text | `text-foreground` |
| Secondary text (mono labels, timestamps, meta strip, hints) | `text-muted-foreground` |
| Active stream gutter rail | `border-primary/50` |
| Active thread row background | `bg-primary/10` |
| Citation badge `[SEC]/[EARN]/[NEWS]/[KG]` | `text-primary` on `bg-primary/10` |
| Confidence bar — high (≥0.7) | `bg-positive/70` |
| Confidence bar — medium (0.4–0.7) | `bg-warning/70` |
| Confidence bar — low (<0.4) | `bg-negative/70` |
| Tool ok | `text-positive` |
| Tool error/empty | `text-muted-foreground` |
| Contradiction strip | `text-warning` on `bg-warning/10` |
| Destructive banner | unchanged (`text-destructive` on `bg-destructive/10`) |
| Inline citation anchor hover | `bg-primary/20` |

No raw `text-amber-*`, `text-emerald-*`, etc. Architecture test
`no-off-palette-colors.test.ts` would catch a regression.

### 6.4 Row heights

| Element | Height |
|---|---|
| Thread row | 24 px (`py-1` + 11 px line + 9 px sub-line, overlapped via `leading-[1]`) — drop 12 px vs today |
| Citation row | 18 px |
| Tool-call row | 16 px |
| Composer textarea | `rows={2}` → 44 px (unchanged) |
| Thread header bar | 28 px |
| Market context strip (atop thread rail) | 24 px |

### 6.5 Border radii

`rounded-[2px]` on every clickable / panelled surface. Confidence bar
segments retain `rounded-[2px]`. No `rounded-md`, no `rounded-lg`.

### 6.6 Animations

Per the design index: **none on data surfaces.**
Exceptions, scoped:

- Inline citation flash on click: `border-primary` flicker for 600 ms via
  a single-shot CSS class toggle (not infinite). Implemented as a
  controlled `data-flashed="true"` attribute with a single keyframe; no
  `animate-pulse`.
- Tool-tray collapse: 100 ms `max-height` transition, then static.
- No blinking cursor — the streaming accent rail is the indicator.

---

## 7. Interaction model

### 7.1 Hotkeys

| Shortcut | Effect |
|---|---|
| `Enter` | Send |
| `Shift+Enter` | Newline |
| `⌘K` / `Ctrl+K` | Focus thread search box |
| `⌘N` / `Ctrl+N` | New chat |
| `⌘\` / `Ctrl+\` | Toggle context rail |
| `⌘.` / `Ctrl+.` | Cancel streaming response |
| `Esc` | If autocomplete open → close; else dismiss `ActionConfirmModal`; else blur textarea |
| `/` (first char of empty input) | Open slash-command autocomplete |
| `↑` in empty composer | Recall last user message into composer (Bloomberg `LP` convention) |
| `[` then `]` keys while a citation hovercard is open | Cycle through citations |
| `J` / `K` in message column (when composer unfocused) | Move focus between turns (vim-style — Bloomberg parity) |

### 7.2 Hover behaviour

- Thread row: background → `bg-muted`, trash icon fades in.
- Inline citation `[cN]`: 250 ms delay → `CitationHoverCard` appears
  (Radix HoverCard). Card shows source name, full title, 240-char excerpt,
  `Open ↗` link, `Copy ref` button.
- Citation strip row: subtle `bg-muted/40` + cursor `pointer`; click
  scrolls the body's inline anchor into view.
- Confidence bar segment: shows `title` tooltip (existing behaviour
  preserved).
- Tool tray header (collapsed): "tool calls — 2/2 done" with chevron;
  hover bg `bg-muted/40`, click expands.
- Follow-up chip: `bg-muted/40` → `bg-muted/80` on hover; click sets
  composer value and immediately sends (no double-click required —
  the chip's intent is "ask exactly this").

### 7.3 Click handlers

- Thread row → switch thread (`handleSelectThread`, existing).
- Thread row double-click → rename (existing).
- Inline citation `[cN]` → scroll matching strip row into view + flash
  (600 ms `data-flashed` toggle).
- Citation strip row → scroll inline `[cN]` anchor into view (the
  inverse).
- Citation `Open ↗` → open `cite.url` in new tab (`safeExternalUrl`).
- Tool tray header → toggle collapsed state; persisted per turn.
- Follow-up chip → set composer + `send()` immediately.
- Entity context "× drop" → clear the `?entity_id=` URL param via
  `router.replace`.
- Related ticker chip → append ` $TICKER` to composer (existing
  `appendToInput`).
- `[Pin]` thread header button → POST `/v1/threads/{id}` `pin=true`
  (BACKEND NOTE: this endpoint does not exist yet — see Open Q-3).
- `[Export ▾]` → opens menu with "Markdown" (existing) + "Copy as
  research note" (clipboard).
- `[⋯]` on thread header → menu: rename, delete, regenerate last
  answer.

### 7.4 Loading state

- **Threads loading**: 5 × `Skeleton h-6 w-full` in the rail.
- **Thread history loading**: 3 × `Skeleton h-12` alternating left/right
  alignment ratio dropped — flat list, all left-aligned `Skeleton`
  rectangles, full-width minus a 28 px gutter.
- **Streaming, pre-token (thinking + tool-use phase)**: the assistant
  gutter shows the accent rail + the role glyph `A`. The body region
  shows the `ToolCallTray` (expanded) only — no typing dots, no animated
  cursor. The terminal-grade signal that "something is happening" is the
  active accent rail.
- **Streaming, token phase**: `MessageMetaStrip` renders with provider
  + `streaming…` instead of `latency_ms` (latency only resolved at
  finalise). Body fills with tokens. A static block cursor `▎` appears
  at the trailing end. **No pulse, no blink.**
- **Reconnect after WS/SSE drop**: small inline banner under the
  composer: `Connection lost — reconnecting…` (`text-warning`). Existing
  `chatError` banner reused for hard failures only.

### 7.5 Error state

- **401 on threads**: same UX as today — "Your session expired" + Sign-in
  CTA (existing logic, now in `ChatErrorBanner`).
- **Generic threads error**: "Failed to load threads · Retry" (existing).
- **Stream error**: `ChatErrorBanner` under the streaming turn. Inline
  retry button (calls `send(question)` with last question).
- **Tool error**: tool indicator turns muted X with `(error)` suffix;
  the answer text below still renders if the LLM produced any tokens.
- **Reader exhausted without `done`**: append `[Response interrupted]`
  to body (existing behaviour from `useChatStream` finalize) +
  `Continue` chip in follow-ups.
- **Citation has javascript:/data: URL**: filtered at the hook level
  (existing security guard); the row still renders without an anchor
  (text only) so the analyst sees the source name.

### 7.6 Empty state

Two sub-states:

1. **No thread selected** (`!activeThreadId`):
   `ChatEmptyState` shows the 6 `PORTFOLIO_STARTER_QUESTIONS` in a
   2 × 3 grid + a `[New conversation]` primary button (existing copy
   retained). Above the grid: small "Analyst Intelligence" label + the
   one-liner about RAG grounding (existing).

2. **Thread exists, zero messages** (rare — only when user opens a
   freshly-created thread before sending): shows the entity-aware
   starters when `?entity_id=` is present (existing `entityStarters`),
   otherwise the generic `STARTER_QUESTIONS`. Behaviour preserved from
   the live page.

---

## 8. Data fetching

### 8.1 TanStack Query keys (add to `lib/query/keys.ts`)

| Existing key | Reuse |
|---|---|
| `qk.chat.threads()` | thread list — staleTime 30 s (unchanged) |
| `qk.chat.thread(id)` | thread history — staleTime 30 s (unchanged) |
| `qk.chat.entityResolve(id)` | UUID → ticker resolve (unchanged) |

| New key | Purpose | staleTime |
|---|---|---|
| `qk.chat.contradictions(threadId)` | aggregated contradictions across turns (computed client-side from `messages[].contradictions`) — keyed so the right rail's `ChatContextRail` can subscribe to it as a derived query | n/a (derived, no fetch) |
| `qk.chat.recentCitations(threadId)` | aggregated last-N citations across turns | derived |
| `qk.chat.pinned()` | `GET /v1/threads?pin=true` — once endpoint exists (Q-3) | 60 s |

### 8.2 Resources reused by other pages

- `qk.market_snapshot` (30 s) — drives the top market strip on the
  thread rail; the dashboard already subscribes (`02-dashboard.md`).
  Dedup is automatic via TanStack's cache.
- `qk.instrument_overview` — used by the entity-context resolver, shared
  with the instrument detail pages.

### 8.3 SSE flow (unchanged contract)

- `POST /api/v1/chat/stream` with `{message, thread_id}` (or
  `POST /api/v1/chat/entity-context/stream` with `{message, thread_id,
  entity_id}`).
- Events consumed: `thinking`, `tool_call`, `tool_result`, `citations`,
  `pending_action`, `action_executed`, `action_rejected`, `token`,
  `done`, legacy `[DONE]`.
- New: `MessageMetaStrip` reads `intent`, `provider`, `latency_ms` from
  the `done` event payload (S8 emits them today; the hook needs to add
  ~5 lines to capture and forward them).

### 8.4 Network safety reminders

- Authorization header from `useAuth().accessToken`.
- Abort on unmount + on `cancel`.
- 2,000-char input cap (existing).
- All external URLs go through `safeExternalUrl`.
- KG citations may have `url=null`; render as plain text (existing
  guard).

---

## 9. Tradeoffs & decisions

### 9.1 Flat text vs bubbles

**Decision:** flat text, role gutter on the left, accent rail while
streaming.
**Alternative considered:** bubble layout but tightened (drop
`max-w-[70%]` to `max-w-[88%]`, drop bubble padding by 2 px).
**Why flat wins:** Bloomberg / Refinitiv / Perplexity all use flat text.
Bubble shells (Slack/Claude/ChatGPT consumer) waste 12–18% of the
horizontal column to chrome and inflate per-turn vertical space by ~20%.
Density target requires reclaiming both axes. The role-gutter+accent-rail
keeps user-vs-assistant boundary clear without bubble chrome.

### 9.2 Context rail vs no rail

**Decision:** ship the 320 px context rail, collapsible with `⌘\`.
**Alternative considered:** keep the 2-column layout (rail + messages
only) and surface citations/contradictions inline under each turn.
**Why rail wins:** inventory §2.4 exposes 4 chat fields that nothing
renders today (`intent`, `provider`, `latency_ms`, `contradictions`).
Plus `Citation.published_at` and aggregated freshness. Squeezing them
into the inline strip would either swamp the message column or get
hidden behind "…show more" affordances. A dedicated rail is the only
honest fit. Collapsibility means screens narrower than 1280 px get the
2-column experience automatically (rail auto-collapsed below `lg`).

### 9.3 Citation expansion: hovercard vs inline footnotes

**Decision:** Radix HoverCard on the inline anchor; persistent rows in
`CitationStrip` below the turn.
**Alternative considered:** Perplexity-style hovercard *only* (no strip),
or Bloomberg-style strip only (no hover).
**Why both win:** the strip is the canonical source list a researcher
needs to *audit* the answer. The hovercard is the impatient-skim
affordance for *reading* the inline claim. The two paths reinforce
rather than duplicate: hover for "what does `[c2]` mean?", strip for
"where did all of this come from?".

### 9.4 Tool call: collapse vs always-on

**Decision:** auto-expand while running, auto-collapse 1.5 s after
finish (collapsed shows `tool calls — 2/2 done`).
**Alternative considered:** always-collapsed (Perplexity); always-on
(Claude code-interpreter).
**Why hybrid wins:** during running, the analyst wants to *see* the
transparent retrieval (Bloomberg signal). Once done, the lines become
visual noise above the answer — collapsing them recovers the vertical
real estate without hiding the audit trail (one click to re-expand).

### 9.5 Follow-up chips: per-answer vs empty-state-only

**Decision:** show on every assistant turn that has at least 1 citation.
**Alternative considered:** keep the existing empty-state-only behaviour.
**Why per-answer wins:** the dropoff rate on chat threads happens
*between* turns ("now what do I ask?"), not at session start. TradingView
ships per-answer; ChatGPT added it in 2024. Backend cost: zero — we
derive 2–4 follow-ups client-side from `intent` + last entity. If S8
later provides `follow_up_suggestions[]`, swap to that without
changing the component contract.

### 9.6 Avatar bubble removal

**Decision:** remove the `Bot` icon avatar on assistant turns. The
left-gutter `A` glyph + accent rail provides equivalent semantic cues at
a quarter of the horizontal cost.
**Alternative considered:** keep the 28 px Bot avatar.
**Why removal wins:** the avatar buys nothing on a terminal where the
column already costs us 60–80 px of pure visual chrome per turn (avatar
+ bubble padding). Bloomberg, Refinitiv, Perplexity all run avatar-less.
The role glyph is the minimum sufficient affordance.

---

## 10. Open questions

- **Q-1 (must answer pre-implementation):** Should the `intent` field be
  surfaced verbatim (`REASONING`, `COMPARISON`) or translated to UX
  language (`Analysis`, `Comparison`)? Current preference: verbatim
  mono, because that's the Bloomberg convention (`<HLP>`, `<TOPS>`).
- **Q-2:** Should the inline-citation flash colour use `primary` or a
  dedicated "interaction echo" token? Current preference: `primary`
  (no new token; matches the accent rail).
- **Q-3:** Pinning threads — backend support? `/v1/threads` does not
  expose `pinned: bool` today (inventory §1.5). Either (a) defer the
  `[Pin]` header button to a follow-up wave, (b) ship the button hidden
  behind a flag, or (c) request the S8 schema change in the PRD-0089
  master spec. Current preference: **(a) defer** so the redesign is
  not blocked.
- **Q-4:** Should the right rail's "Recent citations" feed deduplicate
  by `article_id` across turns? Current preference: yes, with the
  highest-relevance occurrence winning the displayed row (and a `· 3×`
  suffix showing how many times the article was cited in this thread).
- **Q-5:** Confirmation modal (`ActionConfirmModal`) is currently a
  centred Radix Dialog. Should it move to a docked drawer attached to
  the right rail so it doesn't cover the message column? Current
  preference: dock it; matches IBKR's order-confirm pattern. Out of
  scope for this design (touches PLAN-0082 territory), flagged for a
  follow-up.
- **Q-6:** Should `Cmd+\` clash with the global shell's sidebar toggle
  (if any)? Need to check `01-global-shell.md` once it lands.
- **Q-7:** `AskAiPanel` floater is a separate doc area — should it
  reuse `MessageTurn` at `size="compact"` (currently proposed) or get a
  fully separate render path? Current preference: reuse; one component,
  one bug surface.

---

## State block (pencil.dev canvas)

Not required for this surface. The chat page is the most code-heavy
surface in the platform but visually the simplest of the per-page docs
(three columns, no charts, no candlesticks). The ASCII wireframe above
is the canonical design artefact; a pencil.dev canvas would not add
information beyond what the wireframe already encodes. If the
coordinator disagrees, opening a canvas is a 30-minute follow-up — the
component spec in §5 fully drives the layout.
