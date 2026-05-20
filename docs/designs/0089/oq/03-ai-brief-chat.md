# PRD-0089 Cluster 3 — AI Brief + Chat / RAG Unification + AskAi Panel

> **Status**: investigation (2026-05-19) · **Author**: agent-cluster-3
> **Scope**: resolves OQs across `02-dashboard.md` (brief diff staleness), `05-instrument-quote.md` (B-Q-5 lazy brief), `06-instrument-financials.md` (AI brief panel surface), `07-instrument-intelligence.md` (StructuredBrief + narrative history), `10-chat-ai.md` (Q-1..Q-7).
> **Parent**: `docs/designs/0089/_INDEX.md`
> **Inventory**: `docs/designs/0089/00-backend-data-inventory.md` §1.5 + §2.4 + §3.7
> **Branch**: `feat/frontend-platform-hardening` (no worktree — design-only)

---

## 1. Cluster summary

The AI-generated narrative is the platform's single most asymmetric piece of
content: it costs cents/LLM-tokens to produce, lives only briefly in cache,
and is consumed across **five separate surfaces** (`MorningBriefCard`,
`AiBriefBanner` on Quote tab, `AI BRIEF` sidebar panel on Financials,
`StructuredBrief` on Intelligence, `WorkspaceBriefWidget`) using **three
different render styles** for the same `BriefingResponse` payload. The Chat
surface meanwhile shares the same S8 service, the same citation grammar, the
same SSE infrastructure — yet is built with a parallel set of components
(`MessageBubble`, `CitationBar`, `CitationList`, `AskAiPanel.parseCitationResponse`,
`renderWithCitations`) that overlap each other ~70% but diverge in subtle
visual details (font sizes, citation chip styles, sources block).

The cluster collapses on three questions:

1. **When does a brief exist, when does it get re-generated, and what does
   "stale" mean** — answered by adopting a lazy-generate endpoint
   (`POST /v1/briefings/instrument/{id}/generate`) plus a tiered TTL on top
   of the existing 24 h Valkey cache.

2. **Should AskAiPanel and the Chat page share rendering primitives** — yes.
   The chat redesign (`10-chat-ai.md` §5) already specifies `MessageTurn` +
   `CitationStrip` + `InlineCitationAnchor` as the canonical primitives;
   AskAiPanel must drop its custom `parseCitationResponse` / `renderWithCitations`
   helpers and reuse those, at `size="compact"`. This closes Q-7.

3. **What does the citation token look like across surfaces** — a single
   `<InlineCitationAnchor>` component with three render densities (terminal /
   compact / brief-footer). Brief footers stay anchor-only (no hovercard,
   per terminal density rules); chat + AskAiPanel get the hovercard.

The cluster ships net-positive (≈ 4 deletions for every 1 addition) because
the chat redesign already implies most of the deletion work — the brief
side simply joins it instead of forking again.

---

## 2. Per-OQ deep dive

### 2.1 OQ `02-dashboard.md` #4 — Brief diff staleness (3+ days unseen)

**Current behaviour** (`apps/worldview-web/features/dashboard/components/BriefDiffBadge.tsx:62` + `services/rag-chat/src/rag_chat/application/use_cases/brief_diff.py`):

`GET /api/v1/briefings/morning/diff` always compares the **two most-recent
morning briefs** for the authenticated user (see
`services/rag-chat/src/rag_chat/api/routes/public_briefings.py:448-514`). If
the user hasn't opened the dashboard for 3 days, the diff returned is
"today vs yesterday" — Tuesday/Monday/Sunday changes are silently dropped.

**Open question**: should the diff merge all unseen briefs, or stay
yesterday-only?

**Recommendation**: ship a **multi-day delta** with the cutoff anchored to a
client-stored "last seen brief id".

Concrete change:

- Frontend stores `wv:last-seen-brief-id` in `localStorage` (NOT
  `sessionStorage` — survives tab close).
- `BriefDiffBadge` now calls
  `GET /api/v1/briefings/morning/diff?since_brief_id={last_seen}` instead of
  the no-argument variant. Backend defaults to "yesterday" when the param is
  absent or invalid (forward compat).
- Backend: `BriefDiffUseCase.execute()` gains an optional `since_brief_id`
  param. Implementation:
  - Fetch all briefs between `since_brief_id.generated_at` and the latest
    brief, ordered ascending.
  - For each consecutive pair, run the existing bullet-diff routine; union
    `new_bullets` across all pairs, then dedupe by `(section_title, text)`
    (text-normalised).
  - `removed_bullets`: only the bullets that were never re-introduced in the
    accumulated window (set difference, not pairwise).
  - `delta_summary` becomes `"5 new bullets across 3 days, 1 removed since Monday"`.
- Cap window at **7 days** server-side (`since_brief_id` older than 7 d → clip
  to 7 d). Beyond that the diff is no longer useful — just show the headline.
- Frontend: when the response `delta_summary` matches `/across (\d+) days/`,
  the badge label changes from `+N new` to `+N since {weekday}`.

**Personalisation hook (out of scope, follow-up)**: tag each diff bullet
with the entity_ids it cites; future wave filters bullets the user has no
position / watchlist tie to.

**Decision**: implement multi-day diff (B-D-1). Defer entity-filtered
personalisation to a follow-up.

---

### 2.2 OQ `05-instrument-quote.md` OQs — Lazy brief endpoint (B-Q-5)

**Current behaviour** (`apps/worldview-web/components/instrument/brief/AiBriefBanner.tsx:72`):

`AiBriefBanner` calls `GET /v1/briefings/instrument/{entityId}`. The S8
public route (`public_briefings.py:238-341`) generates synchronously on cache
miss — typical latency on cold path: **5-12 s** (LLM call) for a brief; the
TanStack Query `retry: false` makes the second hit silently 404 if the brief
errored. Net effect: the banner returns `null` and renders nothing 95% of
visits → "AI brief has been deleted" complaint.

#### 2.2.1 Sync vs async + streaming

**Recommendation**: **two-endpoint contract**:

| Endpoint | Behaviour | Use case |
|---|---|---|
| `GET /v1/briefings/instrument/{entity_id}` | **Unchanged**: cache-or-generate-and-wait (5-12 s synchronous). Returns `200` with full `BriefingResponse` or `404 EntityNotFoundError`. | Bot consumers (S10 email), tests, CLI. |
| `POST /v1/briefings/instrument/{entity_id}/generate` | **New** lazy variant. Returns immediately. | Frontend `AiBriefBanner`. |

#### 2.2.2 Lazy-generate spec

```
POST /api/v1/briefings/instrument/{entity_id}/generate
X-Internal-JWT: <user>
Content-Type: application/json
Body: {}   # reserved for future overrides (model, length); currently unused

Responses
200 — { status: "ready",     brief: BriefingResponse }     // cache hit
202 — { status: "queued",    job_id: UUID, eta_seconds: 8 }  // generation started
202 — { status: "in_flight", job_id: UUID, eta_seconds: 3 }  // another caller already triggered
404 — { error: "entity_not_found" }
429 — { error: "rate_limit_exceeded", retry_after_seconds: int }
503 — { error: "providers_unavailable" }
```

Polling contract:

```
GET /api/v1/briefings/instrument/{entity_id}/generate/{job_id}
200 — { status: "running",  eta_seconds: int }
200 — { status: "ready",    brief: BriefingResponse }
200 — { status: "failed",   reason: "providers_unavailable" | "no_news_context" | "timeout" }
404 — job expired (>10 min after creation)
```

**Job is just a Valkey key**, no DB table:

```
rag:v1:brief_job:{job_id} = {entity_id, user_id, status, started_at, eta_seconds}  TTL 600 s
rag:v1:brief_inflight:{entity_id} = job_id   TTL 60 s
```

The `inflight:{entity_id}` SETNX gates dog-piling — when 50 users open AAPL
simultaneously, only the first triggers generation; the other 49 receive
`status:"in_flight"` with the same `job_id` and poll the same job.

#### 2.2.3 Streaming brief text (token-by-token)

**Recommendation: DEFER**. Not worth the complexity:

- Briefs are 200-400 tokens. Total generation: 6-8 s on DeepInfra.
- The user is already in the "lazy" mental model (`Generating…` pill).
  Showing tokens flow doesn't materially reduce perceived latency vs polling
  every 2 s and atomic swap. AskAiPanel already does SSE for chat; reusing
  that for briefs would double the SSE handler surface for marginal UX gain.
- Backend cost of an SSE variant: re-plumb `LLMProviderChain.stream_chat()`
  through the briefing pipeline (currently uses non-streaming `chat()` call).
  Non-trivial — affects `BriefParser` (depends on full text to split
  headline/sections/lead).

**If we change our mind later**: add `?stream=true` to the polling endpoint;
return SSE with `token`/`section_complete`/`done` events. Out of scope here.

#### 2.2.4 Rate limit + caching policy (B-Q-5 cost OQ)

Existing limits:
- `/internal/v1/briefings` (email path): **100/day per user** (`_DAILY_RATE_LIMIT` in `generate_briefing.py:39`)
- Valkey response cache: **24 h** for `briefing:instrument:v2:{entity_id}:{user_id}` and `briefing:morning:v2:{user_id}`

The instrument brief cache key is **per-user** which means user A's
generation doesn't help user B. That is the wrong tradeoff for instrument
briefs — the brief content is identical for all viewers of a public
instrument.

**Recommendation**: tiered cache keys + new rate limit dimension.

```
# Canonical (shared across all users)
brief:instrument:v3:{entity_id}                       TTL 1 h   # served to everyone
brief:instrument:v3:{entity_id}:job                   TTL 10 m  # inflight gate

# Per-user (only for briefs that surface portfolio context, e.g. morning)
brief:morning:v3:{user_id}                            TTL 24 h
```

The instrument brief generator already takes **zero per-user input**
(`execute_public_instrument(entity_id)` — signature in
`generate_briefing.py:501`); removing the `:{user_id}` suffix is safe.

Rate limits:

| Limit | Old | New | Rationale |
|---|---|---|---|
| Lazy-generate cold path (per user) | none | **60/hour per user_id** | Stops a script user from triggering 1000 briefs/hour. |
| Lazy-generate cold path (per instrument, global) | none | **10/hour per entity_id** | Global cap — if 10 users in an hour all hit AAPL with cold cache, the 11th gets the older cached brief or 429. |
| `/internal/v1/briefings` (email digest) | 100/day | **unchanged** | This is the S10 path, not user-driven. |
| `GET /briefings/morning/diff` | none | **120/min per user** | The redesign polls more aggressively after browser focus. |

Valkey keys for new limits:

```
rag:v1:rl:brief:user:{user_id}:{YYYY-MM-DD-HH}      INCR, EXPIRE 3700 s
rag:v1:rl:brief:entity:{entity_id}:{YYYY-MM-DD-HH}  INCR, EXPIRE 3700 s
```

When either trips: `429 { retry_after_seconds }`.

#### 2.2.5 Caching policy: who else gets the cached brief

After 2.2.4's per-entity (not per-user) key bump, the answer is **everyone**.
Lazy-generation cost amortises across all viewers in the 1 h TTL window. A
"force regenerate" param can be added behind admin auth later.

#### 2.2.6 Brief border style (instrument-page banner)

OQ from `05-instrument-quote.md` §6.5 — current `AiBriefBanner` uses
`border-b border-border/50 bg-card`. The redesign asks for a border style
consistent with other AI surfaces.

**Recommendation**: introduce an `accent-ai` left border on AI-generated
panels across all surfaces:

```css
border-l-2 border-[hsl(var(--accent-ai)/0.40)]  /* default state */
border-l-2 border-[hsl(var(--accent-ai))]       /* freshly generated, <60 s */
border-l-2 border-[hsl(var(--accent-ai)/0.20)]  /* stale brief, >24 h */
```

`--accent-ai` is the violet token used by the `<Bot>` chip on AskAiPanel
(`components/shell/AskAiPanel.tsx:449`). Promoting it from chip-only to a
2 px left rail across `AiBriefBanner`, `StructuredBrief`, the Financials AI
panel, and `MorningBriefCard` creates a single visual handshake: "this
content was LLM-generated".

#### 2.2.7 Failure modes

| Failure | Behaviour |
|---|---|
| LLM down (provider chain exhausted → `ProviderUnavailableError`) | `503` from sync path; lazy path returns `{status:"failed", reason:"providers_unavailable"}`; banner shows `BRIEF · unavailable — Try again` (existing fallback). |
| Generation timeout > 30 s | Job marked `failed`, reason `timeout`; banner falls through to unavailable state. |
| Entity has no news in last 90 days | Pipeline returns 422; banner shows `BRIEF · no news in last 90 days` (existing copy). |
| User rate-limited | 429 with `retry_after_seconds`; banner shows `BRIEF · cooling down — N min` muted. |
| Entity doesn't exist in KG (e.g. brand-new ticker) | 404; banner hidden (existing behaviour). |

---

### 2.3 OQ `06-instrument-financials.md` — Same brief, different surface

**Current state**: the Financials tab spec lists `BriefingResponse.sections + risk_summary` and `BriefingResponse.bullets` as data sources for the sidebar "AI BRIEF" panel (`06-instrument-financials.md:112-113`). But `BriefingResponse.bullets` does NOT exist as a field — the actual schema (see `docs/services/rag-chat.md` §3.7 + `00-backend-data-inventory.md` §3.7) has `sections[].bullets[]`. The spec implicitly assumes a flatter shape.

**Recommendation**: a single `<InstrumentBriefSurface>` component family with three sizes, all consuming the same `BriefingResponse`:

| Component | Surface | Reads | Layout |
|---|---|---|---|
| `<AiBriefBanner>` (existing, simplified) | Quote tab — collapsed strip above tab content | `narrative` only (preview) → `sections` (expanded) | 22 px collapsed; expands to 120 px max-height scroll. |
| `<AiBriefSidebar>` (NEW, replaces ad-hoc rendering) | Financials tab — right rail panel | `headline`, `sections[].title`, `sections[].bullets[]`, `risk_summary` top-3 | 320 × ~360 px panel; section headings 10 px UPPERCASE; bullets 11 px. |
| `<StructuredBrief>` (existing, polished) | Intelligence tab — left rail block | `headline`, `lead`, full `sections`, `citations` footer | Full-width 11 px prose; footer `generated_at · provider · latency_ms`. |

**One TanStack Query** (`qk.instruments.brief(entityId)`) feeds all three —
already the case for the Quote banner; we add the same key to the new
sidebar component and the Intelligence `StructuredBrief`. Cache hit rate
should be ~100% inside a single instrument-page session.

**Citations in the Financials sidebar** stay as a footer "Sources" list with
clickable titles only (no hovercard — terminal density rules). The
Intelligence `StructuredBrief` gets the full hovercard treatment, mirroring
the Chat citation strip.

---

### 2.4 OQ `07-instrument-intelligence.md` — StructuredBrief + narrative history

**StructuredBrief** is already specced (`07-instrument-intelligence.md:288` —
`intelligence/brief/StructuredBrief.tsx` ≤ 110 LOC). The OQ is about
**narrative-history disclosure** (line 346) — should the historical
narratives be paginated inline or in a drawer?

**Existing endpoint**: `GET /v1/entities/{id}/narratives` (paginated). Already
wired via `useEntityNarratives` (mentioned in inventory but no UI consumer).

**Recommendation**:

- `<StructuredBrief>` adds a `<NarrativeHistoryDisclosure>` accordion in its
  footer (`intelligence/context/NarrativeHistoryDisclosure.tsx`):
  - Collapsed default: `Narrative history ▾` (10 px mono, primary token).
  - Expanded: list of N versions, each 32 px tall: `2026-05-12 · DeepInfra
    Llama-3.1-8B · first-100-char snippet`.
  - Click a version row → inline drawer (shadcn `<Accordion>` content slot) —
    no modal, no route change.
- The disclosure is the **only** surface for narrative history (no rail
  duplication on the Intelligence tab; the inventory-flagged "right rail
  narrative history" gets folded into this disclosure).
- Pagination: lazy via `useInfiniteQuery`. Initial fetch 5 versions, "Load
  more" button at the bottom of the disclosure body.

**Brief border treatment on Intelligence**: full `border-l-2 border-[hsl(var(--accent-ai)/0.40)]` — this is the surface where "AI brief" is most prominently the user's primary task, so the AI accent rail is at its strongest. Per 2.2.6 above, the rail is consistent everywhere; it's just full-height here vs 22 px on the Quote banner.

---

### 2.5 OQ `10-chat-ai.md` Q-1..Q-7

Resolutions per question (Q-1..Q-7 from `10-chat-ai.md:665-695`):

#### Q-1 — `intent` field display

**Decision**: surface verbatim mono (`REASONING`, `COMPARISON`, `FACTUAL_LOOKUP`, ...). Render inside the `<MessageMetaStrip>` (`10-chat-ai.md:293`):
```
REASONING · via DeepInfra · 1.4s · 14:01:24
```
Verbatim matches Bloomberg `<HLP>` / `<TOPS>` convention. Add a `title` tooltip on hover that expands the human-readable name (`Reasoning`, `Comparison`) for new users.

Rendering rule: only on assistant turns, only when `intent` is non-null (legacy messages from before PLAN-0067 may lack it).

#### Q-2 — Citation flash colour

**Decision**: `primary` (existing yellow accent). No new token. Matches the
streaming gutter rail.

#### Q-3 — Pinned threads

**Backend support**: NOT present today. `threads` table
(`docs/services/rag-chat.md` §312-322) has no `pinned: bool` column.
`GET /v1/threads` paginates by `last_message_at desc` only.

**Decision**: ship the `[Pin]` button **hidden behind a feature flag**
(`NEXT_PUBLIC_CHAT_PINNED_THREADS=false` default). Two-wave plan:

1. **Wave 1 (current PRD-0089 scope)**: button hidden; no backend work.
2. **Wave 2 (follow-up)**: add `pinned BOOLEAN NOT NULL DEFAULT FALSE` to
   `threads` table; new `PATCH /api/v1/threads/{id}/pin` endpoint; `GET
   /api/v1/threads?pin=true` filter; flip the flag.

Backend additions for Wave 2 are tracked in §8 below.

#### Q-4 — Recent citations dedup

**Decision**: yes, dedup by `article_id`. Counter suffix `· 3×`. Pure
client-side computation in `ChatContextRail` from `messages[].citations[]`
union. No backend change. Already covered by §8.1 of
`10-chat-ai.md`.

#### Q-5 — `ActionConfirmModal` placement

**Decision**: dock to right rail (matches IBKR). **Out of scope** for this
cluster — defer to PLAN-0082 follow-up wave. Flagged so the redesign team
knows not to re-do the Radix Dialog layout if PLAN-0082-W2 lands first.

#### Q-6 — `Cmd+\` hotkey collision

**Decision**: own `Cmd+\` for the Chat ContextRail toggle. The global shell
spec (`01-global-shell.md`) reserves `Cmd+B` for the sidebar and `Cmd+/` for
the command palette; `Cmd+\` is free.

Cross-page collision check needed: `AskAiPanel` does NOT currently bind
`Cmd+\` (verified by reading
`apps/worldview-web/components/shell/AskAiPanel.tsx:251-260` — only `Escape`
is bound). Safe.

The `AskAiButton` in the TopBar (`apps/worldview-web/components/shell/AskAiButton.tsx`)
binds `Cmd+J` (per its existing test). No collision.

#### Q-7 — AskAiPanel render-primitive reuse

**Decision**: REUSE — AskAiPanel migrates to import `<MessageTurn>` +
`<CitationStrip>` + `<InlineCitationAnchor>` from `features/chat/components/`
at `size="compact"`. The existing custom `parseCitationResponse` (lines 71-111)
and `renderWithCitations` (lines 125-169) get **deleted entirely** —
they implement the same logic as `withCitationSups` on `LazyMarkdownContent`
but on raw text instead of markdown, which is the wrong abstraction (S8
emits markdown).

Concrete delta (`apps/worldview-web/components/shell/AskAiPanel.tsx`):

- DELETE: `parseCitationResponse`, `renderWithCitations`, the inline
  `<sup>` rendering, the bordered "Sources" list at lines 526-549, the local
  `ParsedSource` interface (lines 52-54).
- ADD: import `MessageTurn` (or a thin `<CompactMessageTurn>` variant that
  hides the gutter glyph + timestamp). Import `CitationStrip` (compact
  variant: just the bar, no row list — matches current bordered-list footprint).
- The SSE token-accumulation loop (lines 360-414) stays; it now feeds a
  `StreamingMessage` instead of raw `response: string`. About 10 lines of
  type adapter.

Net: AskAiPanel shrinks from 587 LOC to ~280 LOC, one bug surface instead
of two. Tests already cover the citation parsing
(`apps/worldview-web/__tests__/AskAiPanel.test.tsx`) — those test cases
migrate to the shared primitives' tests.

---

## 3. Unified citation pattern (cross-surface)

Single canonical token across **all five surfaces**:

| Surface | Citation atom | Hovercard? | Source list? |
|---|---|---|---|
| `<MessageBubble>` / `<MessageTurn>` (Chat page) | `<InlineCitationAnchor>` (`[c1]`-style 9 px sup) | YES — `<CitationHoverCard>` (Radix `HoverCard`) | YES — `<CitationStrip>` rows |
| `<AskAiPanel>` (floater) | `<InlineCitationAnchor size="compact">` | YES — same hovercard | NO — compact strip (bar only) |
| `<AiBriefBanner>` (Quote tab strip) | none (preview text shows no markers) | n/a | NO — banner is preview-only; expand to see |
| `<AiBriefSidebar>` (Financials) | clickable inline `[N]` (anchor only, no hovercard) | NO — terminal density | YES — footer text list, title-only |
| `<StructuredBrief>` (Intelligence) | `<InlineCitationAnchor>` (full chat parity) | YES | YES — `<CitationStrip>` full rows |
| `<MorningBriefCard>` (Dashboard) | clickable inline `[N]` | NO | YES — footer text list |

**Single shared component**: `features/chat/components/InlineCitationAnchor.tsx`
gains a `density` prop:

```tsx
type Density = "terminal" | "compact" | "brief-footer";

interface Props {
  number: number;
  citation: Citation;
  density?: Density;       // default "terminal"
  showHoverCard?: boolean; // default true; brief-footer surfaces pass false
}
```

`density` controls font-size + padding only (8/9/10 px). `showHoverCard`
gates the Radix wrapper.

**Citation badge type indicator**: `[SEC] [EARN] [NEWS] [KG]` per
`10-chat-ai.md:387` — derived from `Citation.source` string. Maps:

```ts
function citationKind(source: string): "SEC" | "EARN" | "NEWS" | "KG" {
  if (/sec_|10[kq]|8k/i.test(source)) return "SEC";
  if (/earnings/i.test(source)) return "EARN";
  if (/relation|claim|kg/i.test(source)) return "KG";
  return "NEWS";
}
```

Same helper used by `CitationStrip` rows and `InlineCitationAnchor` tooltip.

---

## 4. Lazy-brief endpoint spec proposal (consolidated)

```yaml
POST /api/v1/briefings/instrument/{entity_id}/generate:
  auth: X-Internal-JWT (user)
  body:
    type: object
    properties: {}     # reserved
  responses:
    200:
      description: cache hit, brief ready
      schema:
        type: object
        properties:
          status: {enum: [ready]}
          brief: { $ref: '#/components/schemas/BriefingResponse' }
    202:
      description: generation queued or already in flight
      schema:
        type: object
        properties:
          status: {enum: [queued, in_flight]}
          job_id: {type: string, format: uuid}
          eta_seconds: {type: integer, minimum: 1, maximum: 30}
    404: { description: entity not found }
    429:
      description: rate limit
      schema:
        type: object
        properties:
          error: {type: string, enum: [rate_limit_exceeded]}
          retry_after_seconds: {type: integer}
          dimension: {type: string, enum: [user_hour, entity_hour]}
    503: { description: all providers unavailable }

GET /api/v1/briefings/instrument/{entity_id}/generate/{job_id}:
  auth: X-Internal-JWT (user)
  responses:
    200:
      schema:
        oneOf:
          - { status: running, eta_seconds: integer }
          - { status: ready,   brief: BriefingResponse }
          - { status: failed,  reason: string }
    404: { description: job expired (>10 min) }
```

### 4.1 Implementation notes

- Use existing `GenerateBriefingUseCase.execute_public_instrument()` —
  wrap it in a background asyncio task spawned by the lazy endpoint; record
  the task into `app.state.brief_jobs: dict[UUID, asyncio.Task]`.
- Use Valkey `SETNX` on `rag:v1:brief_inflight:{entity_id}` with 60 s TTL
  to gate concurrent triggers. The first caller's `job_id` becomes the
  shared job for all 60 s of inflight callers.
- Task completion writes the canonical cache key
  (`brief:instrument:v3:{entity_id}`, 1 h TTL) and sets job state to
  `ready` in `rag:v1:brief_job:{job_id}` (10 min TTL).
- On task failure: state → `failed`, reason → `providers_unavailable` /
  `timeout` / `no_news_context`.
- ETA is computed from a rolling p50 of completion latency per provider
  (Prometheus histogram `rag_brief_generation_seconds`); fallback 8 s.

### 4.2 Tests required

- Unit: `lazy_generate_inflight_returns_same_job_id` (two SETNX calls under
  same TTL).
- Unit: `lazy_generate_rate_limit_user_hour` (61st call in same hour → 429).
- Unit: `lazy_generate_rate_limit_entity_hour` (11th call in same hour → 429).
- Integration: `lazy_generate_cold_path_returns_202_then_ready` (start, poll
  4 times at 2 s intervals, eventually `ready`).
- Integration: `lazy_generate_warm_path_returns_200_immediately`.
- Integration: `lazy_generate_provider_outage_returns_failed`.

---

## 5. AskAiPanel ↔ Chat unification recommendation

**Recommendation: full primitive reuse, ship as one component family** —
no separate render path.

### 5.1 Shared primitives

| Primitive | Lives in | Used by |
|---|---|---|
| `MessageTurn` | `features/chat/components/MessageTurn.tsx` (NEW, replacing `MessageBubble`) | Chat page, AskAiPanel |
| `CitationStrip` | `features/chat/components/CitationStrip.tsx` (NEW) | Chat page (full), AskAiPanel (compact prop), `StructuredBrief` (footer mode) |
| `InlineCitationAnchor` | `features/chat/components/InlineCitationAnchor.tsx` (NEW) | All surfaces with `[N]` markers |
| `CitationHoverCard` | `features/chat/components/CitationHoverCard.tsx` (NEW) | Chat page, AskAiPanel, `StructuredBrief` |
| `useChatStream` | `features/chat/hooks/useChatStream.ts` (existing) | Chat page, AskAiPanel |

### 5.2 State management

- **AskAiPanel** = ephemeral. No thread persistence, no thread_id sent in
  `POST /v1/chat/stream` body (already the case, line 348). Closing the
  panel discards the conversation.
- **Chat page** = persistent threads via `/v1/threads/*`.
- The shared `useChatStream` hook accepts an optional `threadId`. Absent →
  ephemeral; present → persisted.

### 5.3 Entity context handling

- AskAiPanel knows the current instrument when called from the instrument
  page (the existing `ticker` / `price` / `fundamentals` props at line
  181-186 build `system_context`).
- Chat page learns entity from a URL param: `/chat?entity={entity_id}` →
  uses the `/v1/chat/entity-context/stream` endpoint and renders an
  `<EntityContextChip>` above the composer (already specced in
  `10-chat-ai.md` §5).
- Same SSE event grammar in both endpoints (verified in `docs/services/rag-chat.md` §158-174).

### 5.4 Hotkey conflict ⌘\

- `AskAiPanel` binds: `Escape` only (line 251).
- Chat page binds: `Cmd+K` (thread search), `Cmd+N` (new chat), `Cmd+\`
  (context rail), `Cmd+.` (cancel stream), `[`/`]` (cycle citations).
- The `AskAiButton` (TopBar) binds: `Cmd+J` (per its test file).
- Global `Cmd+/` reserved for shell command palette (TBD).

**No conflict on Cmd+\\** — chat-page-scoped only.

The AskAiPanel SHOULD NOT bind Cmd+\ — when the panel is open, the user is
not in the chat page; nothing to collapse. Confirmed safe.

### 5.5 Migration path

1. Build the new chat primitives per `10-chat-ai.md` §5.
2. Migrate the chat page to them (covered by `10-chat-ai.md` Wave Z).
3. Replace AskAiPanel internals with the same primitives + compact density.
4. Delete `parseCitationResponse`, `renderWithCitations`, the local
   `ParsedSource` interface, the bordered Sources list in AskAiPanel.
5. Update `__tests__/AskAiPanel.test.tsx` to assert the shared
   `InlineCitationAnchor` + `CitationStrip` are rendered (instead of
   asserting against the local custom components).

Net LOC delta on AskAiPanel: -310 lines.

---

## 6. Rate-limit + caching policy (consolidated)

| Resource | Cache key | TTL | Rate limit | Notes |
|---|---|---|---|---|
| Morning brief (per-user, portfolio-aware) | `brief:morning:v3:{user_id}` | 24 h | 100/day per user (email path); 60/hour for lazy retries | Personal — cannot share across users. |
| Instrument brief (canonical) | `brief:instrument:v3:{entity_id}` | 1 h | 60/hour per user; 10/hour global per entity | Per-entity not per-user (entity briefs have no user input). |
| Brief diff | uncached (computed per call) | n/a | 120/min per user | Computation is fast (text normalisation only). |
| Brief job state | `rag:v1:brief_job:{job_id}` | 10 min | n/a | Cleared after ready/failed read. |
| Brief inflight gate | `rag:v1:brief_inflight:{entity_id}` | 60 s | n/a | SETNX-only. |
| Chat completion | `rag:v1:completion:{hash}` | 24 h | 10/min per (tenant, user) | Unchanged. |
| Chat stream | uncached | n/a | 10/min per (tenant, user) | Unchanged. |
| Brief history | uncached | n/a | none | Already paginated; `page_size ≤ 50`. |
| `narratives` history | uncached (DB direct) | n/a | none | KG service paginates. |

**Negative cache** (provider unavailable): existing 60 s per provider —
applies equally to chat and brief paths since both go through
`LLMProviderChain`. No change.

---

## 7. Recommended decisions table

| ID | Decision | Source OQ | Owner | Effort |
|---|---|---|---|---|
| D-1 | Lazy-generate brief endpoint `POST /v1/briefings/instrument/{id}/generate` returns `202 {status,job_id,eta}` | B-Q-5 | S8 + S9 | M (1 wave) |
| D-2 | Polling endpoint `GET .../generate/{job_id}` returns `running` / `ready` / `failed` | B-Q-5 | S8 | S |
| D-3 | Cache key bump `briefing:instrument:v2:{entity_id}:{user_id}` → `brief:instrument:v3:{entity_id}` (drop user suffix) | B-Q-5 (cost OQ) | S8 | S |
| D-4 | Rate limits: 60/hour per user; 10/hour global per entity; 429 carries `retry_after_seconds` + `dimension` | B-Q-5 cost | S8 | S |
| D-5 | Brief border treatment: `border-l-2 border-[hsl(var(--accent-ai)/0.40)]` across all 5 surfaces (full when fresh <60 s, dim when stale >24 h) | quote OQ 6.5 + financials | Frontend | S |
| D-6 | Brief diff supports `since_brief_id` param, multi-day union of new/removed bullets, 7-day cap | 02-dashboard OQ #4 | S8 + S9 + Frontend | S |
| D-7 | `<InlineCitationAnchor>` with `density` prop (terminal / compact / brief-footer) is the single citation atom across all surfaces | cross-cluster | Frontend | M |
| D-8 | AskAiPanel migrates to shared `MessageTurn` / `CitationStrip` / `InlineCitationAnchor`; deletes `parseCitationResponse`, `renderWithCitations`, local Sources list | Q-7 + cluster summary | Frontend | M |
| D-9 | Chat `intent` rendered verbatim mono in `<MessageMetaStrip>`; tooltip expands human-readable name | Q-1 | Frontend | XS |
| D-10 | Chat citation flash colour = `primary` (no new token) | Q-2 | Frontend | XS |
| D-11 | Pin threads: button hidden behind `NEXT_PUBLIC_CHAT_PINNED_THREADS` flag; backend support deferred to Wave 2 | Q-3 | Frontend (W1) + Backend (W2) | XS+M |
| D-12 | Recent-citations rail dedupes by `article_id` with `· N×` suffix | Q-4 | Frontend | XS |
| D-13 | `ActionConfirmModal` docks to right rail — DEFERRED (PLAN-0082 follow-up) | Q-5 | Frontend follow-up | — |
| D-14 | `Cmd+\` reserved for Chat ContextRail; no AskAiPanel collision | Q-6 | Frontend | XS |
| D-15 | `<NarrativeHistoryDisclosure>` accordion in `StructuredBrief` footer; inline drawer for version detail (no modal) | intelligence narrative history | Frontend | S |
| D-16 | Skip streaming brief tokens for now (defer to follow-up; LLM completion latency 6-8 s is acceptable with polling) | lazy brief streaming OQ | — | — |
| D-17 | Surface `intent`, `provider`, `latency_ms` in `<MessageMetaStrip>`; `contradictions` shown in right rail strip (existing chat spec, decision confirmed for analyst-visibility not debug-only) | inventory hidden-fields gap | Frontend | XS |

---

## 8. Backend additions required

### 8.1 S8 (rag-chat) — required for D-1..D-4, D-6

| Change | File | Effort |
|---|---|---|
| New endpoint `POST /api/v1/briefings/instrument/{entity_id}/generate` | `services/rag-chat/src/rag_chat/api/routes/public_briefings.py` (add new handler ~80 LOC) | M |
| New endpoint `GET /api/v1/briefings/instrument/{entity_id}/generate/{job_id}` | same file (~40 LOC) | S |
| New use case `LazyGenerateBriefingUseCase` wrapping `execute_public_instrument()` with Valkey job state | `services/rag-chat/src/rag_chat/application/use_cases/lazy_generate_briefing.py` (new) | M |
| Cache key migration v2 → v3 (drop `:{user_id}` for instrument briefs) | `public_briefings.py:255` (one line) — leave v2 reading code for 24 h grace before deleting | XS |
| New rate-limit dimensions: `rag:v1:rl:brief:user:{user_id}:{hour}` + `rag:v1:rl:brief:entity:{entity_id}:{hour}` | `services/rag-chat/src/rag_chat/application/caching/rate_limiter.py` (extend) | S |
| `BriefDiffUseCase` gains `since_brief_id: UUID \| None` param; multi-day union | `services/rag-chat/src/rag_chat/application/use_cases/brief_diff.py` | S |
| New Prometheus metric `rag_brief_generation_seconds` (histogram, label `entity_type`) | `infrastructure/metrics/prometheus.py` | XS |
| New Prometheus metric `rag_brief_job_state` (gauge, label `status`) | same file | XS |
| Background-task lifecycle wiring (`app.state.brief_jobs: dict[UUID, asyncio.Task]`; cancel-on-shutdown) | `app.py` lifespan | S |

### 8.2 S9 (api-gateway) — required for D-1, D-2, D-6

| Change | File | Effort |
|---|---|---|
| Proxy `POST /v1/briefings/instrument/{id}/generate` and `GET .../generate/{job_id}` | `services/api-gateway/src/api_gateway/proxy/briefings.py` (or wherever brief routes live post-refactor) | XS |
| Proxy `GET /v1/briefings/morning/diff?since_brief_id=...` (query-string passthrough) | same file | XS |

### 8.3 Future Wave 2 — for D-11 (pinned threads)

| Change | File | Effort |
|---|---|---|
| Alembic migration: `ALTER TABLE threads ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT FALSE` | `services/rag-chat/alembic/versions/0NNN_threads_pinned.py` | XS |
| New endpoint `PATCH /api/v1/threads/{id}/pin` (toggle) | `routes/threads.py` | S |
| Extend `GET /api/v1/threads?pin=true` filter | `routes/threads.py` | XS |
| New use case `PinThreadUseCase` | `application/use_cases/pin_thread.py` | XS |

### 8.4 No-backend-change items (frontend-only)

- D-5 (brief border)
- D-7 (citation primitive consolidation)
- D-8 (AskAiPanel migration)
- D-9 (intent display)
- D-10 (flash colour)
- D-12 (citation dedup)
- D-14 (hotkey assignment)
- D-15 (narrative history disclosure)
- D-17 (meta strip surfaces hidden fields)

---

## 9. Follow-up OQs for the user

1. **Stream brief tokens?** D-16 defers token-streaming for briefs (6-8 s
   polling is acceptable). Do you want me to escalate this — i.e. is the
   "first paint" UX worth the SSE plumbing for briefs? Default: defer.

2. **Force-regenerate for power users?** With the per-entity (not per-user)
   cache key in D-3, an analyst can no longer get a "fresh" brief in <1 h
   without admin tooling. Should we expose `POST .../generate?force=true`
   bypassing the cache (with a per-user 5/hour cap)? Default: no.

3. **Briefs in chat citations?** Should the chat `get_morning_brief` tool
   (trust_weight 0.92) cite its source brief inline so the analyst can
   audit "the chat told me X because the morning brief said X"? Default: yes,
   minor wiring change in `ChatOrchestratorUseCase`.

4. **Brief feedback in AskAiPanel?** The chat page surfaces a `<BriefRating>`
   on each morning-brief card. Should AskAiPanel offer a thumbs-up/down per
   answer (rolled up into `rag_citation_accuracy` or a new
   `rag_answer_quality` metric)? Default: yes, very low effort if reusing
   the existing `<BriefRating>` primitive.

5. **Pin endpoint priority?** D-11 defers pinned-thread backend support to
   Wave 2 (small migration + 1 endpoint, ~half-day work). If the user
   considers pinning a launch-blocker, we can fold the migration into the
   PRD-0089 main wave instead. Default: defer.

6. **Brief age display**: should `AiBriefBanner` show absolute `Updated 14:32`
   or relative `Updated 3 h ago`? Current Quote-tab banner uses relative
   (`formatRelativeTime`). The Financials sidebar redesign could surface
   absolute timestamps (Bloomberg parity). Default: relative everywhere
   except the Intelligence StructuredBrief footer (absolute + mono).

7. **Lazy generation visible to other users?** If user A's 8-second
   generation is interrupted (browser close), should user B's next visit
   pick up the same job, or start fresh? Current proposal: SETNX gate
   means user B joins the same job for 60 s; after that, fresh start.
   Acceptable?

---

## 10. Sanity-check against existing implementation

Cross-references the proposal against actual code paths to catch
contradictions before implementation:

| Proposal | Touchpoint | Verified |
|---|---|---|
| Lazy-generate uses existing `execute_public_instrument()` | `generate_briefing.py:501` | YES — signature `(entity_id: str)` is already user-agnostic |
| Removing `:{user_id}` from cache key is safe | `public_briefings.py:255` | YES — `tenant_id` is captured but already marked `# noqa: F841 — reserved for future cache-key scope` so was never meaningful |
| `BriefDiffUseCase` can accept new param | `brief_diff.py` (referenced from `public_briefings.py:468`) | YES — use case is constructed per-request in route handler; param addition is non-breaking |
| AskAiPanel can drop `parseCitationResponse` | `AskAiPanel.tsx:71-111` | YES — S8 emits markdown via SSE; the panel rebuilds full text then post-parses, but `LazyMarkdownContent withCitationSups` already does the inline-citation parse on assistant messages in `MessageBubble.tsx:142` — same job, better abstraction |
| `Cmd+\` doesn't collide with AskAiPanel | `AskAiPanel.tsx:251-260` | YES — only `Escape` is bound |
| `--accent-ai` token exists and is violet | `AskAiPanel.tsx:449` (`bg-[hsl(var(--accent-ai)/0.20)]`) | YES — token is defined and used; no new CSS needed |
| `user_briefs` table supports `brief_type='entity'` | `infrastructure/db/models/user_brief.py:56-57` | YES — `String(20) nullable=False` discriminator + `entity_id` nullable FK column already present |
| `<NarrativeHistoryDisclosure>` endpoint exists | inventory §1.4 | YES — `GET /v1/entities/{id}/narratives` paginated; `useEntityNarratives` hook exists per `07-instrument-intelligence.md:346` |
| `<MessageMetaStrip>` can read `intent`/`provider`/`latency_ms` from `done` SSE | `docs/services/rag-chat.md:169` (`metadata` event) | YES — S8 already emits all three in the `metadata` event payload |

All proposals are non-breaking. The cache-key bump v2 → v3 is the only
write-side change; v2 entries will simply expire naturally over 24 h
(same approach used by PLAN-0062-W4 and documented in
`public_briefings.py:143-145`).

---

## 11. Acceptance checklist for the cluster

- [ ] `POST /api/v1/briefings/instrument/{id}/generate` returns 200 on cache hit, 202 on cold start
- [ ] `GET .../generate/{job_id}` returns `ready` within 30 s of cold-start trigger (live test against AAPL)
- [ ] 61st lazy-generate call within an hour returns 429 with `retry_after_seconds`
- [ ] Concurrent lazy-generate calls (10 simulated users hitting same entity) result in exactly 1 actual LLM call
- [ ] Brief cache key `brief:instrument:v3:{entity_id}` shared across users (test: user A triggers, user B reads cache in 200 ms)
- [ ] `GET /api/v1/briefings/morning/diff?since_brief_id=...` correctly unions bullets across 3-day gap
- [ ] `<AiBriefBanner>` shows `BRIEF · Generating…` after 1 s of cold-start; settles to brief preview within 8 s
- [ ] `<AskAiPanel>` no longer imports `parseCitationResponse` / `renderWithCitations`; assertion against shared `<InlineCitationAnchor>` passes
- [ ] AskAiPanel and Chat-page citation hovercards render identical content (visual diff test)
- [ ] `<MessageMetaStrip>` renders `intent · via {provider} · {latency_ms}` under every assistant turn with non-null intent
- [ ] `<NarrativeHistoryDisclosure>` accordion expands inline (no modal); paginates 5 versions at a time
- [ ] Pinned-threads button hidden when `NEXT_PUBLIC_CHAT_PINNED_THREADS=false`; visible when flag flipped
- [ ] All 5 brief surfaces share `border-l-2 border-[hsl(var(--accent-ai)/0.40)]` left rail
- [ ] No new CSS variables introduced; everything resolves to existing tokens
- [ ] `vitest run` passes; `pnpm tsc --noEmit` clean; backend pytest passes for rag-chat (>= 549 tests as of 2026-05-06)
