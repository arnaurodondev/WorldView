# Instrument — Intelligence Tab — Design Spec (PRD-0089)

**Status**: draft — design only, no implementation
**Owner**: agent-instr-intelligence
**Date**: 2026-05-22 (iter-3 — post-investigation amendments Δ11-Δ23)
**Parent index**: `docs/designs/0089/_INDEX.md`
**Prior art**: PLAN-0090 Wave D (the implementation we are rebuilding) — `apps/worldview-web/components/instrument/intelligence/*`

---

## 0. Diagnosis of the current page (PLAN-0090 Wave D)

The shipped Intelligence tab uses a 3-column `grid-cols-12` layout (`col-span-3 / col-span-6 / col-span-3`). Visual audit at 1440×900:

| Symptom | Component | Root cause |
|---------|-----------|-----------|
| ~45 % of the center column is whitespace around the graph | `GraphColumn.tsx` (mx-3, mt-3, p-3, mb-3, rounded card around brief) | Three concentric paddings (parent + brief card + graph card) eat ~96 px vertically |
| News rail only shows ~16 articles | `CompactArticleRow.tsx` `h-7` (28 px) + `border-b border-border/20` + 32 px filter strip | Row is 28 px tall when 18 px suffices (no avatar, no thumbnail, two-line layout is unused) |
| Context panel is a near-empty 280 px rail in entity-overview mode | `ContextPanel.tsx` lines 248-287 | Renders ONLY name + type badge + health badge + description paragraph → ~120 px of content above 600 px of blank space |
| `NodeDetailCard` always shows "No description available." | `NodeDetailCard.tsx` line 124 | Never calls `getEntityDetail()` for the selected node; only uses `GraphNode.label/type/size` from the graph payload |
| AI brief renders but no "graph stats" line | `GraphColumn.tsx` line 105-115 | No `node_count · edge_count · max_depth · latency_ms` strip — analyst has no idea how big the graph is |
| 3 s timeout often fires at depth=3 | `GraphColumn.tsx` line 31 (`GRAPH_TIMEOUT_MS = 3000`) | Comment admits depth=3 takes 4-8 s. Memory entry `project_graph_bugs_2026_05_11.md` records `504` at depth=3 due to AGE `O(degree³)` traversal |
| Contradictions never appear on this tab | `ContextPanel.tsx` | Endpoint `/v1/entities/{id}/contradictions` exists, never called |
| Path insights never appear | `lib/api/intelligence.ts` `useEntityPaths` exists | Hook is dead-code on this tab |
| Narrative version history never appears | `useEntityNarratives` exists | Same |

**The page surfaces ~5 % of the rich KG data the platform produces.**

---

## 1. Competitor research summary

### Bloomberg BI (Intelligence research notes layout)

- Bloomberg Intelligence research notes use a **3-pane reading layout**: TOC rail (12 %), prose column (55 %), inline data exhibits (33 %). Density is brutal — Plex Sans 10/13 px, no margins > 8 px between blocks.
- The "Industry Dashboard" cross-references: an analyst clicks a peer ticker inline and the **right rail** flips to that peer's mini-profile without losing the article context. We mirror this with `ContextPanel`.
- Footer of every BI piece carries an "Analyst contact + Last updated + Confidence" strip — we steal the "Last updated + provider + latency" strip for the AI brief.

### Bloomberg NLRT / NRGY (terminal news density)

- NLRT (Natural-Language Resource Terminal) renders **40-50 headlines per screen** at 1280×800 with 18 px rows: dot · HH:MM · 3-letter source · headline · 4-char tag.
- Sentiment is encoded by **left-edge 2 px color stripe**, not a dot — saves horizontal pixels and reads from peripheral vision.
- Filter row is **18 px tall** with kbd-style pill toggles ("[A]ll [P]os [N]eg") so power users hit the letter instead of mousing.
- Article preview opens in a **right-side overlay**, never a modal, never a navigation.

### TradingView Ideas + News

- The "News" tab in the instrument view uses a **two-column 60/40 split**: feed on the left, expanded article on the right. Click an item → the right pane updates, list keeps its scroll position.
- Each row carries a **sparkline thumbnail** of the underlying instrument's 1-hour reaction — premium signal we don't have but should aspire to.
- Rows are 24 px (not 18 px) because they carry social signal (vote count, comment count). We don't need that → 18 px is fine.

### Refinitiv Eikon (entity-aware news + KG)

- Eikon's "Company → News" view pairs a news list with a **"Mentioned entities"** rail: every entity that appeared in the visible articles gets a row with sentiment-weighted mention count. Clicking the entity pivots the news list to that entity.
- Eikon's "Knowledge Map" (Refinitiv Knowledge Graph) shows ~50 nodes inside a **400×400 canvas** with an aggressive force layout — they accept clutter because the **right rail** is always rendering the selected node's full dossier.
- Lesson: a graph viewer is only as useful as the right-rail dossier next to it. **The graph is a navigator, not the content.**

### Koyfin (visual KG patterns) + Kensho (financial KG)

- Koyfin's "Connections" widget renders a **horizontal swim-lane** of related companies grouped by relationship type (Supplier / Customer / Competitor) — flat, no force-directed clutter. We may borrow the **"group by relation type" toggle** in the GraphToolbar.
- Kensho's "Event Studies" page uses a **timeline-anchored graph**: nodes drift left/right by `first_mentioned_at`. Out of scope for v1 but a future GraphToolbar mode.

### Datawrapper / Observable (graph viz references)

- Datawrapper's force-directed examples cap at **80 visible nodes** on a 700 px canvas before falling back to a matrix view. We mirror: depth=3 with >80 nodes → propose a "Matrix" toggle (deferred, not in v1).
- Observable D3 examples use a **constant left-side legend** (entity-type color key) — we already have `GraphLegend`, keep it.

---

## 2. User intent for this page

### Primary persona

**Long/short equity analyst** at a multi-strategy fund. Owns 30-50 names, reviews each every 2 weeks. Lands on Intelligence tab to answer:

1. **"What happened with this name in the last 24 h that I missed?"** → news rail must show 20+ items at a glance with sentiment + impact-score.
2. **"What changed in the narrative arc?"** → AI brief on top, narrative version history in the right rail.
3. **"Who else is connected, and how strongly?"** → graph + top-relations list + path insights to portfolio.
4. **"Is anyone contradicting the consensus?"** → contradictions block surfaces dissenting claims.

### Secondary tasks

- Click an entity on the graph → read its 1-paragraph profile + outbound relations without leaving the tab.
- Filter news to the last 24 h, negative sentiment, score > 70 → 3-second scan.
- Bookmark a path ("AAPL → ANTH → AI-chip-research") for a thesis note (out of scope for v1; reserve a row in the spec).

### Anti-patterns this page MUST avoid

- **No tabs-within-tabs.** The current design has tabs at the page level (Quote / Financials / Intelligence). Adding internal tabs (Brief / Graph / News / Paths) hides surfaces that are meant to be **simultaneously** visible.
- **No modal pop-ups.** Clicking a node opens the right rail, not a Radix Dialog.
- **No carousel.** A horizontal scroll for paths/contradictions is a Bloomberg-cardinal-sin.
- **No empty whitespace.** Every pane must surface real data in its default state.

---

## 3. Backend data available

Citations are line-anchored to `docs/designs/0089/00-backend-data-inventory.md`.

### 3.1 Currently called by the page

| Endpoint | Hook / call site | Notes |
|----------|------------------|-------|
| `GET /v1/briefings/instrument/{entity_id}` | `GraphColumn.tsx` line 44-50 | Returns `narrative, headline, sections, citations, cached, generated_at` — **`headline` and `sections` arrays are dropped** (rendered as markdown blob) |
| `GET /v1/entities/{id}/graph?depth=N` | `GraphColumn.tsx` line 54 + `ContextPanel.tsx` line 137 | Two query keys with different depths → potentially two network calls. PLAN-0090 left this as a known dedup miss |
| `GET /v1/entities/{id}` | `ContextPanel.tsx` line 116 | Used for name + description |
| `GET /v1/entities/{id}/intelligence` | `useEntityIntelligence()` | Used ONLY for `health_score` — `confidence_breakdown`, `key_metrics`, `data_completeness` discarded |
| `GET /v1/news/entity/{entity_id}` | `useEntityNewsInfinite` | Paged. Filter params `sentiment, timeRange` honoured |

### 3.2 Available but NOT called on this tab (the redesign opportunity)

| Endpoint | Returns | Use in redesign |
|----------|---------|-----------------|
| `GET /v1/entities/{id}/paths` | `paths: [{nodes[], edges[], total_hops, llm_explanation}]` | New "Path insights" block in right rail (entity-overview mode) |
| `GET /v1/entities/{id}/contradictions` | `contradictions: [{claim_a, claim_b, source_a, source_b, severity}]` | New "Contradictions" block in right rail |
| `GET /v1/entities/{id}/narratives` (paginated) | `narratives: [{version_id, narrative_text, generated_at, llm_model}]` | "How the narrative evolved" disclosure in right rail (collapsed by default) |
| `GET /v1/entities/{id}` for the **selected** node | description, type, metadata | Replaces hardcoded "No description available." in `NodeDetailCard` |
| `GraphEdge.evidence_snippets` (already on graph payload) | top-3 text snippets per edge | Surfaced on hover and inside RelationsList |
| `GraphEdge.relation_summary` | LLM one-liner | Already rendered in RelationsList — keep |
| `GET /v1/search/relations` | semantic relation search across entities | Power-user search box at top of right rail (deferred to v1.1) |
| `BriefingResponse.sections` | `[{title, bullets[]}]` | New structured-brief renderer at top (replaces markdown blob) |
| `BriefingResponse.headline` | one-sentence summary | Surface as `text-[12px]` bold above the narrative |
| S9 GraphNode proxy enrichment (NEW) | `description?: string`, `sector?: string`, `exchange?: string` added to S9 `GraphNodeSchema` Pydantic model | Enables rich node hover tooltips (description + sector) and reduces need to call `getEntityDetail()` just for the tooltip. **Requires backend change B-01** (3-field addition to S9 proxy schema). |
| S9 RelationResponse proxy enrichment (NEW) | `decay_class: str` added to S9 edge schema | Enables temporal edge opacity in the graph. **Requires backend change B-02** (1-field addition to S9 proxy schema). Value is one of: PERMANENT, DURABLE, SLOW, MEDIUM, FAST, EPHEMERAL. |

### 3.3 Data the user **explicitly mentioned**

- **Health score** — surfaced as a badge (kept from PLAN-0090).
- **Relations** — top 10 connected entities (NEW).
- **Paths to portfolio** — `/v1/entities/{id}/paths` filtered to paths whose terminal node is in the user's holdings (NEW).
- **Contradictions** — full list with severity badge (NEW).
- **Narrative** — full brief at top (kept, but render `sections` instead of blob).
- **Key highlights** — surfaced via `BriefingResponse.sections[0]` with `title="Key highlights"` and `bullets[]`. NO separate endpoint exists. The `StructuredBrief variant="compact"` component renders this automatically as the first structured section. "Key highlights" is the first section the S8 prompt emits.
- **Risks to watch** — surfaced via `BriefingResponse.risk_summary.top_risk_signals[]` AND as `sections[N]` with `title="Risks to watch"`. Both are rendered by `StructuredBrief variant="compact"` automatically (E-03). No additional work required.
- **Depth controls** — exist in GraphToolbar (kept).
- **Graph stats** — node/edge counts + latency (NEW).

### 3.4 Backend changes required for W7 (3 S9 proxy additions)

No new endpoints. No new workers. All changes are additions to existing S9 Pydantic proxy schemas.

| ID | File | Change | Enables |
|----|------|--------|---------|
| B-01 | `services/api-gateway/src/api_gateway/routes/intelligence.py` (GraphNode schema) | Add `description: str \| None = None`, `sector: str \| None = None`, `exchange: str \| None = None` to the node proxy schema. Source: S7 `EntitySummary` already has `ticker`, `isin`, `exchange`; description requires a JOIN to `canonical_entities` — add to S7 graph endpoint response. | Node hover tooltips (Δ13) |
| B-02 | Same file (RelationResponse / edge schema) | Add `decay_class: str \| None = None` to the edge proxy schema. Source: `relations.decay_class` already exists in S7 domain layer. | Edge decay opacity (Δ14), EdgeDetailCard decay badge (Δ11) |
| B-03 | Same file (graph endpoint handler) | Add 5-min Valkey cache: `cache_key = f"graph:{tenant_id}:{entity_id}:{limit}:{depth}"`, TTL 300 s. Pattern identical to the existing intelligence endpoint cache. | Reduce S7 load on repeated depth=2/3 calls (Δ21). Non-blocking for W7. |

---

## 4. Layout

### 4.1 Recommended layout — Option A (3-column, **tightened**)

We considered three options:

- **Option A — 3-column 28 / 47 / 25 (recommended).** Same shape as PLAN-0090 but the news rail loses 2 % and the graph gains 2 %. Eliminates ALL outer padding on each column, replaces `mx-3 / mt-3` chrome with a single 1 px border.
- **Option B — stacked: AI brief (top, 110 px) → graph (middle, fluid) → news ribbon (bottom 200 px), with sticky relations rail on the right.** Rejected: the graph viewer is the page's hero; pushing it to the middle squeezes both the news AND the brief. Also wastes the 200 px ribbon on news that already fits a tall rail.
- **Option C — split-pane with `react-resizable-panels` and maximize toggles per pane.** Rejected for v1: adds 14 KB of bundle, the resize handles are non-trivial to a11y-test, and 95 % of analysts will leave the default split alone. **Re-evaluate in v1.1 as a power-user toggle.**

**Why Option A wins**: keeps the mental model from PLAN-0090 (faster QA), uses every available pixel by deleting nested padding, and lets us spend complexity budget on data density inside each pane rather than on pane plumbing.

### 4.2 ASCII wireframe @ 1440×900

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  TopBar (height 32 — global shell)                                                                               │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  InstrumentHeader (height 56 — ticker, price, %, badges)                                                         │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│  InstrumentTabs   QUOTE   FINANCIALS   [INTELLIGENCE]   (height 28)                                              │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ NEWS COLUMN (404 px / 28%)        │ GRAPH COLUMN (676 px / 47%)                  │ CONTEXT (360 px / 25%)        │
├───────────────────────────────────┼──────────────────────────────────────────────┼───────────────────────────────┤
│ ━━ INTELLIGENCE BRIEF ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │ ━━ ENTITY OVERVIEW ━━━━━━━━━━ │
│ FILTER STRIP    h=22              │  Apple Inc. — Q2 beats; FX a tailwind        │ Apple Inc.   COMPANY   88% ✓  │
│ ALL TODAY 3D 1W | POS NEU NEG     │  generated 2026-05-19 14:32Z · deepinfra ·   │ AAPL · Cupertino, CA          │
├───────────────────────────────────┤  latency 1.2 s    [↻ regenerate]             │ Apple Inc. is an American     │
│ ● 15:47  BBG  Apple beats Q2     0│  ┌──────────────────────────────────────────┐│ technology company that       │
│ ● 15:42  RTR  Services rev +18%  9│  │ Key highlights                           ││ designs consumer electronics… │
│ ● 15:34  FT   iPhone +5%        87│  │ • Services revenue up 18 % YoY          ││                               │
│ ● 15:21  WSJ  Margin 32%        82│  │ • iPhone sales beat by 5 %              │├ ━━ TOP RELATIONS (10) ━━━━━━━┤
│ ● 14:58  BBG  Cook AI invest   78 │  │ • Operating margin improved to 32 %     ││ Tim Cook       exec      0.95│
│ ● 14:32  RTR  China demand wk  71 │  │                                          ││ TSMC           supplier  0.92│
│ ● 14:14  CNBC New iPad spec    66 │  │ Risks to watch                           ││ Samsung        compete   0.87│
│ ● 13:58  BBG  EU probe         63 │  │ • China demand uncertainty              ││ NVIDIA         partner   0.81│
│ ● 13:42  FT   Buyback news     59 │  │ • Component-cost pressure on margin     ││ Anthropic      invests   0.79│
│ ● 13:21  WSJ  Insider buys     55 │  └──────────────────────────────────────────┘│ Foxconn        manufact  0.75│
│ ● 13:01  BBG  TSMC capex       54 │ ━━ GRAPH STATS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│ Microsoft      compete   0.72│
│ ● 12:48  RTR  Foxconn order    52 │  12 nodes · 18 edges · depth 2 · 285 ms      │ Alphabet       compete   0.69│
│ ● 12:32  CNBC Analyst upgrade  48 │ ━━ TOOLBAR ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│ Berkshire H.   holder    0.66│
│ ● 12:14  BBG  Lawsuit ruling   44 │  DEPTH ▱▱▲ 2   TYPE [All ▾]   LAYOUT ⊕ FA2   │ T-Mobile       partner   0.62│
│ ● 11:58  FT   Buyback Q3       41 │ ━━ GRAPH CANVAS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│                               │
│ ● 11:42  WSJ  Cook keynote     38 │                                              │├ ━━ PATH INSIGHTS (3) ━━━━━━━┤
│ ● 11:21  BBG  India growth     36 │              ▓ ANTH ▓                        ││ → Anthropic → AI-chip-rsrch  │
│ ● 11:01  RTR  Mac M5 leak      33 │       ╱             ╲                        ││   2 hops · invests, researches│
│ ● 10:48  CNBC EU ruling Q3     31 │  ▓ NVDA ▓ ─── ▓ AAPL ▓ ─── ▓ TSMC ▓          ││ → NVIDIA → AI-chip-rsrch     │
│ ● 10:32  BBG  ARM royalty      29 │       ╲             ╱                        ││   2 hops · partner, researches│
│ ● 10:14  FT   AI vendor list   27 │              ▓ FOX ▓                         ││ → Tim Cook → Stanford Univ.  │
│ ● 09:58  WSJ  Buffett comment  26 │                                              ││   2 hops · alum_of, founded   │
│ ● 09:42  RTR  Carbon target    24 │                                              ││                               │
│ ● 09:21  BBG  Software bug     22 │                                              │├ ━━ CONTRADICTIONS (2) ━━━━━━┤
│ ● 09:01  CNBC Q3 outlook       20 │                                              ││ HIGH  China demand strong vs │
│ ● 08:48  RTR  Used iPhone      19 │                                              ││       China demand collapsing │
│ ● 08:32  BBG  Dividend Q3      17 │                                              ││       BBG vs Reuters · 14:30  │
│ ● 08:14  FT   Vision Pro       15 │                                              ││ MED   Margin 32% vs 28%       │
│ ● 07:58  WSJ  Apple Pay EU     13 │                                              ││       WSJ vs Internal · 09:14 │
│ ● 07:42  CNBC TikTok deal      11 │                                              │├ ━━ NARRATIVE HISTORY ▾ ━━━━━┤
│ ● 07:21  BBG  Stock split?      9 │                                              ││ (3 prior versions, click)     │
│ … (scroll for more)               │                                              │└───────────────────────────────┘
└───────────────────────────────────┴──────────────────────────────────────────────┴───────────────────────────────┘
   ↑ 30 articles visible above fold      ↑ 1.2 s brief + 285 ms graph + 7 controls    ↑ 4 distinct data blocks, no whitespace
```

### 4.3 Grid description

```
Tab content area:           1440 - 0 (no side gutters within the tab) = 1440 px
Tabs strip:                 28 px  (above this region — global)
Available vertical:         900 - (32 topbar + 56 header + 28 tabs) = 784 px

Within tab content (grid):
  cols:                     grid-cols-100 (treat as %, but we map to grid-cols-12)
                            news       28%  ≈ 403 px  (col-span-4 of 14 — see below)
                            graph      47%  ≈ 677 px
                            context    25%  ≈ 360 px
  rows:                     single row that fills 784 px

NOTE on grid choice: we extend Tailwind to `grid-cols-14` for THIS tab only because
grid-cols-12 cannot represent 28/47/25 cleanly. Mapping:
  news    = col-span-4   (4 / 14 = 28.57 %)
  graph   = col-span-7   (7 / 14 = 50.00 %)   ← absorbs the rounding
  context = col-span-3   (3 / 14 = 21.43 %)
Trade-off: graph eats 3 % from context, news keeps 28%. Acceptable because the
context column does NOT need to fit a graph canvas — it's a vertical text list.

Sticky regions:             news filter strip (top of news column)
                            graph toolbar (above canvas; toolbar + stats both sticky)
                            context column header (entity name + back button)
Scroll containers:          news column (its own overflow-y-auto)
                            context column (its own overflow-y-auto)
                            graph column DOES NOT scroll — canvas fills remainder
```

### 4.4 Density targets (above the fold @ 1440×900)

| Pane | Target | Math |
|------|--------|------|
| News column | **30 articles** | 784 - 22 (filter) = 762 / 18 px row ≈ 42 rows. Conservatively 30 to allow padding. |
| Graph column | brief (110 px) + stats (18 px) + toolbar (28 px) + canvas (610 px) | 110 + 18 + 28 + 610 = 766; remainder for borders |
| Context column | overview (98) + relations (10 × 18 = 180) + paths (3 × 38 = 114) + contradictions (2 × 60 = 120) + narrative-disclosure (18) + headers (5 × 16 = 80) = 610 px | leaves ~150 px for scroll growth |
| **Total visible cells** | **30 + 10 relations + 3 paths + 2 contradictions + 1 brief = 46 items above the fold** | meets PRD-0089 §0 "40–60 cells" target |

---

## 5. Component breakdown

> All paths are relative to `apps/worldview-web/`. Each component lists **file path, line budget, props, rendered content**. We keep the PLAN-0090 file tree wherever possible to minimise churn.

### 5.1 Top-level orchestrator

**File**: `components/instrument/intelligence/IntelligenceTab.tsx`
**Budget**: ≤ 120 LOC (currently 103 — keep as-is, change only the grid class)

```tsx
<div className="grid grid-cols-14 h-full overflow-hidden">
  <div className="col-span-4 overflow-y-auto border-r border-border">
    <NewsColumn entityId={entityId} />
  </div>
  <div className="col-span-7 flex flex-col">
    <GraphColumn entityId={entityId} selectedNodeId={selectedNodeId} onNodeSelect={setSelectedNodeId} />
  </div>
  <div className="col-span-3 overflow-y-auto border-l border-border">
    <ContextPanel entityId={entityId} selectedNodeId={selectedNodeId} onClearSelection={() => setSelectedNodeId(null)} />
  </div>
</div>
```

**Tailwind config change**: add `gridTemplateColumns: { '14': 'repeat(14, minmax(0, 1fr))' }` to `tailwind.config.ts`. Confirm the no-off-palette test still passes (no color change).

### 5.2 News column

**File**: `components/instrument/intelligence/news/NewsColumn.tsx`
**Budget**: keep ≤ 110 LOC. **Key change**: switch row component to `DenseArticleRow` (new) replacing `CompactArticleRow`.

| Sub-component | File | Budget | Renders |
|---------------|------|--------|---------|
| `NewsFilters` | `news/NewsFilters.tsx` | 70 LOC (existing) | 22 px filter strip — UNCHANGED from PLAN-0090 |
| `DenseArticleRow` (NEW; replaces `CompactArticleRow`) | `news/DenseArticleRow.tsx` | ≤ 90 LOC | 18 px row: left-edge 2 px sentiment stripe · HH:MM · 3-letter source code · headline (truncate, flex-1) · impact score (0-99, right-aligned, 2 chars) |

**Props for `DenseArticleRow`** (same as `CompactArticleRow` — drop-in replacement):
```ts
interface DenseArticleRowProps { article: RankedArticle; }
```

### 5.3 Graph column

**File**: `components/instrument/intelligence/graph/GraphColumn.tsx`
**Budget**: ≤ 180 LOC (currently 118 — add 60 LOC for `GraphStats` + structured brief)

| Sub-component | File | Budget | Renders |
|---------------|------|--------|---------|
| `StructuredBrief` (REUSE — **do NOT create new**) | `components/brief/StructuredBrief.tsx` (already shipped) | 0 LOC (existing) | Pass `brief={brief} variant="compact"`. Renders `brief.lead ?? brief.summary` (12 px bold) + each `section.title` (10 px UPPERCASE) + `bullets.map` (11 px). Footer strip added **in GraphColumn** (not inside StructuredBrief): `generated_at · {client-measured latency_ms} ms`. Replaces the current `<MarkdownContent>` blob. **C-BR-01 fix**: `BriefingResponse.headline` does not exist — the equivalent is `brief.lead` (PLAN-0062-W4). **C-BR-02 fix**: `provider` does not exist on `BriefingResponse` — omit from footer. Measure `latency_ms` client-side via `performance.now()` around the queryFn (same pattern as §8.4 graph timing). **C-SB-01 fix**: the shared `StructuredBrief` at `components/brief/` already handles `variant="compact"` correctly; forking into `intelligence/brief/` would create two sources of truth. |
| `GraphStats` (NEW) | `intelligence/graph/GraphStats.tsx` | ≤ 40 LOC | 18 px strip rendering `{node_count} nodes · {edge_count} edges · depth {depth} · {latency_ms} ms`. `latency_ms` received as prop from `GraphColumn` (measured via `performance.now()` in queryFn; stored in `graphFetchStartRef` + `useState` for settled value). |
| `GraphToolbar` | `instrument/graph/GraphToolbar.tsx` | 155 LOC (existing) | UNCHANGED — already supports depth slider + type filter |
| `EntityGraph` | `instrument/EntityGraph.tsx` | 700+ LOC (existing) | UNCHANGED in this design pass; sigma.js canvas |

**Graph timeout policy** (changed from PLAN-0090):

```ts
const GRAPH_TIMEOUT_MS_BY_DEPTH: Record<number, number> = {
  1: 1500,   // 1-hop SQL: 200-600 ms typical → 1.5 s budget
  2: 4000,   // 2-hop AGE: 500-1500 ms typical → 4 s budget
  3: 8000,   // 3-hop AGE: 2-8 s observed → 8 s budget (with skeleton)
};
```

Reason: PLAN-0090 hardcoded 3000 ms for all depths, which kills depth=3 unnecessarily (memory: `project_age_cypher_fix_2026_05_11.md` shows healthy depth=3 at 285 ms after BP-461 fix, but cold-cache traversals still take 4-6 s). On timeout, show `"Graph timed out at depth {d}. Try depth {d-1} or wait 30 s and retry."` — also surfaces a Retry button.

**Edge decay visualization (Δ14)**: When `decay_class` is present on a `GraphEdge` (after backend change B-02), apply it in the sigma.js `edgeReducer`:
```ts
const decayOpacity: Record<string, number> = {
  PERMANENT: 1.0, DURABLE: 1.0,
  SLOW: 0.7, MEDIUM: 0.7,
  FAST: 0.4, EPHEMERAL: 0.4,
};
// In edgeReducer:
const alpha = decayOpacity[edge.decay_class ?? 'MEDIUM'] ?? 0.7;
return { ...data, color: hexWithAlpha(edge.color, alpha) };
```
This makes the graph tell a temporal story — AAPL's durable supplier relations appear vivid while ephemeral news-cycle connections fade.

### 5.4 Context panel

**File**: `components/instrument/intelligence/context/ContextPanel.tsx`
**Budget**: ≤ 260 LOC (currently 289 — refactor into orchestrator + 4 blocks)

New rendering tree (entity-overview mode, `selectedNodeId === null`):

```tsx
<section className="flex flex-col h-full">
  <EntityOverviewBlock entityId={entityId} />        {/* name, type, health, description */}
  <SectionDivider />
  <TopRelationsBlock entityId={entityId} limit={10} />
  <SectionDivider />
  <PathInsightsBlock entityId={entityId} limit={3} />
  <SectionDivider />
  <ContradictionsBlock entityId={entityId} limit={5} />
  <SectionDivider />
  <NarrativeHistoryDisclosure entityId={entityId} />  {/* collapsed by default */}
</section>
```

Node-detail mode (`selectedNodeId !== null`):

```tsx
<section className="flex flex-col h-full">
  <NodeDetailCard nodeId={selectedNodeId} onBack={onClearSelection} />  {/* now fetches getEntityDetail */}
  <SectionDivider />
  <RelationsList edges={incidentEdges} nodesById={nodesById} />
  <SectionDivider />
  <NodePathsBlock entityId={selectedNodeId} fromEntityId={entityId} limit={3} />
</section>
```

Edge-detail mode (`selectedEdgeId !== null && selectedNodeId === null`):

```tsx
<section className="flex flex-col h-full">
  <EdgeDetailCard edgeId={selectedEdgeId} onBack={() => setSelectedEdgeId(null)} />
</section>
```

The `IntelligenceTab` parent must lift `selectedEdgeId: string | null` state alongside `selectedNodeId`. When the user clicks an edge, `setSelectedEdgeId(id)` and clear `selectedNodeId`.

### 5.5 New blocks (right rail)

| Block | File | Budget | Endpoint | Renders |
|-------|------|--------|----------|---------|
| `EntityOverviewBlock` | `intelligence/context/EntityOverviewBlock.tsx` | ≤ 100 LOC | `GET /v1/entities/{id}` + `GET /v1/entities/{id}/intelligence` | Name (12 px) · type badge (9 px) · health badge (9 px, tone-colored, with `title` tooltip showing `confidence_breakdown` detail: "127 high · 89 med · 34 low claims" — **E-01**) · data completeness badge "81% complete" derived from `intelligence.data_completeness` (**E-02**) · description (11 px, 4-line clamp) · `intelligence.key_metrics` 4-cell strip (market_cap, employees, founded, hq_country) · ↻ Refresh narrative button (icon-only, fires `POST /v1/entities/{id}/narratives/generate`, shows cooldown state — **C-NG-01**) · Confidence trend sparkline (Δ17): `confidence_breakdown.confidence_trend[]` (90-day rolling from IntelligenceResponse) rendered as a 40×18 px inline SVG sparkline below the health badge. No third-party chart library — raw SVG polyline. Color: positive trend → `stroke-positive`, negative trend → `stroke-negative`, flat → `stroke-muted-foreground`. Shows "stability of the narrative over time." · Source distribution chips (Δ18): `confidence_breakdown.source_distribution[]` rendered as max 4 `bg-muted/40 text-[9px] px-1.5 py-0.5 rounded-[2px]` chips inline: "Reuters 45%" · "Bloomberg 32%" · "SEC 23%". Sorted by share desc. If source_distribution is empty, omit entirely. |
| `TopRelationsBlock` | `intelligence/context/TopRelationsBlock.tsx` | ≤ 90 LOC | `GET /v1/entities/{id}/graph?depth=1` — fetched **independently** with `qk.instruments.entityGraph(entityId, 1)`, staleTime 10 min (**C-TD-01 fix**: this is a separate cache slot from GraphColumn's variable-depth slot; depth=1 is always fast <600 ms, SQL JOIN, not AGE; a second network call is acceptable and will be cache-hit after first load). | Header "TOP RELATIONS · (n)". List of 10 rows, 18 px each: target label (truncate) · relation label (lowercase, 9 px) · weight (0.00 tabular-nums, 3 chars). Sort by `edge.weight` desc. Click → triggers `onNodeSelect(target.id)` |
| `PathInsightsBlock` | `intelligence/context/PathInsightsBlock.tsx` | ≤ 110 LOC | `GET /v1/entities/{id}/paths?max_hops=3&limit=10` (via existing `useEntityPaths`) | Header "PATH INSIGHTS · (n)". For top 3 paths: 38 px card with route arrows ("→ Anthropic → AI-chip-rsrch"), 2-line meta ("2 hops · invests, researches"). Path scoring badges (second line): `surprise_score > 0.7` → amber "UNEXPECTED" pill (the connection is non-obvious); `harmonic_score` displayed as "Quality: {score}". Both fields are already in `PathInsightPublic` response — no backend change. Click → triggers a workspace event to log the path. |
| `ContradictionsBlock` | `intelligence/context/ContradictionsBlock.tsx` | ≤ 90 LOC | `GET /v1/entities/{id}/contradictions` (existing in knowledge-graph.ts) | Header "CONTRADICTIONS · (n)". For top 5: 60 px card per item — severity badge · claim_a · "vs" · claim_b · source_a vs source_b · timestamp. **C-OQ-05 fix**: raw `severity` may be uppercase or lowercase depending on S7; always call `.toUpperCase()` before rendering and branching (`'HIGH'/'MEDIUM'/'LOW'`). Fallback unrecognised values to `'LOW'` tier. Color map: `HIGH` → `bg-negative/15 text-negative`; `MEDIUM` → `bg-warning/15 text-warning`; `LOW` → `bg-muted text-muted-foreground`. Also show `claim_type` pill (e.g. "revenue_guidance", "market_cap") if present — 9 px, `bg-muted text-muted-foreground`, positioned inline with severity badge. Per-side extraction confidence shown as "(conf: 0.91)" next to each source. These fields (`claim_type`, `sides[].confidence`) are already in `ContradictionDetailResponse` — no backend change. |
| `NarrativeHistoryDisclosure` | `intelligence/context/NarrativeHistoryDisclosure.tsx` | ≤ 70 LOC | `GET /v1/entities/{id}/narratives` (existing `useEntityNarratives`) | Collapsed by default ("Narrative history ▾"). Expanded: scrollable list of versions, each 32 px tall: timestamp · model · 1-line snippet. Click → opens version in a small inline drawer (no modal) |
| `NodePathsBlock` | `intelligence/context/NodePathsBlock.tsx` | ≤ 80 LOC | `GET /v1/entities/{selected_id}/paths?target_entity_id={primary_entity_id}` | Same row pattern as `PathInsightsBlock` but constrained to paths between the selected node and the primary entity (or user portfolio entities when available) |
| `EdgeDetailCard` (NEW) | `intelligence/context/EdgeDetailCard.tsx` | ≤ 110 LOC | `GET /v1/entities/{src}/graph?depth=1` (data already in graph payload — no new network request) | **Source → RELATION_TYPE → Target** breadcrumb (12 px). Relation type in UPPERCASE. Strength: `weight` as 0–100 bar + numeric (e.g. "82 / 100"). Decay badge: `decay_class` (PERMANENT/DURABLE/SLOW/MEDIUM/FAST/EPHEMERAL, color-coded). LLM relation summary: `relation_summary` (11 px, 4-line clamp). Evidence sentences: `evidence_snippets[]` (each as a 9 px blockquote-style indented row, max 5). Evidence count: "Based on {evidence_count} articles". Temporal: `latest_evidence_at` formatted as "Last seen: 14 May 2026". Back button (`←`) clears selection. |
| `SectionDivider` (REUSE) | `components/primitives/SectionDivider.tsx` (**C-SD-01 fix**: this is the actual path; `instrument/shared/SectionDivider.tsx` does NOT exist) | 0 LOC | — | Import from `@/components/primitives/SectionDivider`. Check existing props before planning — the label feature may already be present. |

### 5.6 NodeDetailCard upgrade

**File**: `components/instrument/intelligence/context/NodeDetailCard.tsx`
**Change**: Add an internal `useQuery` call to fetch `GET /v1/entities/{node.id}` so the description shows real text instead of "No description available." Cache `staleTime: 30 min` (descriptions are stable; Worker 13J updates overnight). **C-QK-01 fix**: use `qk.kg.entityDetail(node.id)` (not the ad-hoc `['entity-detail', id]` key) so the cascade-invalidation via `qk.kg.all` works.

```ts
const { data: detail } = useQuery({
  queryKey: qk.kg.entityDetail(node.id),  // C-QK-01: replaces ad-hoc ['entity-detail', id]
  queryFn: () => createGateway(token).getEntityDetail(node.id),
  enabled: !!token,
  staleTime: 30 * 60 * 1000,
  retry: 1,
});
```

Render `detail?.description ?? "Description unavailable."` (italicised when null).

---

## 6. Visual spec (numerical)

### 6.1 Typography map

| Surface | Token | Size / line | Weight | Notes |
|---------|-------|-------------|--------|-------|
| Brief headline | `text-[12px]` | 12 / 18 | 600 | sentence-case |
| Brief section title | `text-[10px]` | 10 / 14 | 500 | uppercase, tracking 0.07em |
| Brief bullets | `text-[11px]` | 11 / 16 | 400 | body |
| Brief footer (generated_at · provider · latency) | `text-[9px]` | 9 / 12 | 400 | mono, muted-foreground |
| Graph stats strip | `text-[10px]` | 10 / 14 | 400 | mono, tabular-nums |
| News row primary (headline) | `text-[11px]` | 11 / 16 | 400 | truncate |
| News row meta (time, source, impact) | `text-[10px]` | 10 / 14 | 400 | mono, tabular-nums |
| Section headers (right rail) | `text-[10px]` | 10 / 14 | 500 | uppercase, tracking 0.08em |
| Relation row label | `text-[11px]` | 11 / 16 | 400 | mono for entity names |
| Relation row weight | `text-[10px]` | 10 / 14 | 400 | mono, tabular-nums |
| Contradiction body | `text-[11px]` | 11 / 16 | 400 | foreground/80 |
| Description paragraph | `text-[11px]` | 11 / 16 | 400 | line-clamp-4 |
| Type / health badges | `text-[9px]` | 9 / 12 | 500 | uppercase, mono, px-1.5 py-0.5, rounded-[2px] |

### 6.2 Spacing map

| Surface | Padding | Gap | Border-radius |
|---------|---------|-----|---------------|
| Column edges | `p-0` (no outer padding — borders are vertical hairlines) | — | 0 |
| Brief block | `p-2` (8 px all sides) | `gap-y-1` between sections | 2 px |
| Graph canvas | `p-0` inside; `border border-border/40` 1 px frame | — | 2 px |
| News row | `px-3 py-0` (12 px horizontal, fixed 18 px height) | `gap-2` (8 px between atoms) | 0 |
| Section header row | `px-3 h-[16px]` | `gap-2` | 0 |
| Right-rail card row (relation, path, contradiction) | `px-3` + fixed row height (18 / 38 / 60) | `gap-2` | 0 (no per-row border-radius; divider lines instead) |

### 6.3 Row heights

| Row | Height |
|-----|--------|
| News row | **18 px** (down from 28 — saves 10 × 30 = 300 px reclaimed below the fold) |
| Top-relation row | **18 px** |
| Path-insight card | **38 px** (2 lines: route + meta) |
| Contradiction card | **60 px** (3 lines: severity+claim_a, "vs"+claim_b, sources+timestamp) |
| Narrative-history row | **32 px** (1 line of meta + 1 line snippet) |
| Brief footer | **16 px** |
| Graph stats strip | **18 px** |
| Graph toolbar | **28 px** (existing) |
| News filter strip | **22 px** (down from 32 — same convention as Quote tab) |

### 6.4 Colors (all from `globals.css`)

- News row left-edge sentiment stripe (2 px wide): `bg-positive` / `bg-negative` / `bg-muted-foreground/40` (neutral/mixed/null)
- Impact score column (≥ 70): `text-positive`; (40-69): `text-warning`; (< 40): `text-muted-foreground`
- Severity badge: HIGH `bg-negative/15 text-negative`; MEDIUM `bg-warning/15 text-warning`; LOW `bg-muted text-muted-foreground`
- Active filter pill underline: `border-b-2 border-primary` (Bloomberg yellow)
- Graph node selection ring: `ring-2 ring-primary` (handled inside sigma.js via nodeReducer; no DOM change)
- Edge decay opacity: PERMANENT/DURABLE → `opacity-100`; SLOW/MEDIUM → `opacity-70`; FAST/EPHEMERAL → `opacity-40`. Applied as sigma.js `edgeReducer` attribute `color` with alpha encoding. Stale edges (FAST/EPHEMERAL) visually recede, helping the analyst focus on durable connections.
- Decay class badge (in EdgeDetailCard): PERMANENT → `bg-positive/15 text-positive`; DURABLE → `bg-muted text-foreground`; SLOW/MEDIUM → `bg-warning/15 text-warning`; FAST/EPHEMERAL → `bg-negative/15 text-negative`

### 6.5 Animations

**Default**: none. (R-PLAN-0028: no Framer / GSAP / Lottie on the platform.)
Allowed exceptions:
- `RefreshCw` icon `animate-spin` during graph load (12 px, 1 s linear)
- TanStack Query skeleton `animate-pulse` on loading rows (cap 800 ms)

No transitions on row hover other than `bg-muted/20` opacity flip (CSS, no JS).

---

## 7. Interaction model

### 7.1 Hotkeys (scoped to Intelligence tab; registered via `useChordHotkeys` from `hooks/useChordHotkeys.ts`)

**C-HK-01 fix**: `hooks/useHotkeys.ts` does not exist. The platform uses `hooks/useChordHotkeys.ts` with `HotkeyScope` (`"global" | "page" | "table" | "chart" | "input" | "modal"`). Use `scope: "page"` — push on `IntelligenceTab` mount, pop on unmount. All hotkeys below fire only when `"page"` is active and `"modal"` is NOT active.

| Key | Action |
|-----|--------|
| `j` / `k` | Next / previous news row (visual highlight + scroll into view) |
| `Enter` | Open highlighted news row in a new tab |
| `1` / `2` / `3` | Set graph depth to 1 / 2 / 3 |
| `t` | Toggle type-filter dropdown |
| `g` | Focus the graph canvas (sigma.js takes keyboard) |
| `r` | Regenerate AI brief — `queryClient.invalidateQueries({ queryKey: qk.instruments.brief(entityId) })` which triggers `useInstrumentBrief` lazy-generate flow (W5). **OQ-6 resolved**: `POST /v1/briefings/instrument/{id}/regenerate` does NOT exist; the correct approach is cache invalidation → lazy generate on next read. |
| `Esc` | Clear node selection (`onClearSelection()`) — same as `Back` button |
| `?` | Open hotkey legend overlay (global) |

### 7.2 Hover behaviour

- **News row**: 100 ms `bg-muted/20` darken on hover. Title attribute exposes full headline if truncated.
- **Top-relation row**: title attribute shows `{source.label} → {target.label}` (full). Hover ring `ring-1 ring-border` to signal click affordance.
- **Graph node**: `NodeTooltipPanel` — **enhanced in W7**: shows entity name (12 px bold) · entity type badge (9 px) · sector badge (9 px, muted — requires `sector` field on GraphNode; see §3.2 backend change Δ13) · description (11 px, 2-line clamp, fetched lazily from `GraphNode.description` when available — same field used in `NodeDetailCard`; falls back to "No description." italic). Does NOT trigger a network call — description is added to the GraphNode payload in the S9 proxy (see §3.2).
- **Graph edge**: `EdgeTooltipPanel` — **enhanced in W7**: shows relation label (UPPERCASE, 10 px) · strength (weight × 100 as integer, "82 strength") · `relation_summary` (if non-null: 11 px, 1-line) · `evidence_snippets[0..2]` as 9 px indented lines (data already on GraphEdge payload for depth=1). For depth>1 edges, `evidence_snippets` is empty — show "Expand at depth 1 to see evidence". Decay class badge if `decay_class` is exposed (see Δ14).
- **Contradiction card**: title attribute shows source URLs.

### 7.3 Click handlers

| Target | Handler |
|--------|---------|
| News row | `window.open(article.url, '_blank', 'noopener,noreferrer')` |
| Top-relation row | `onNodeSelect(edge.target_id)` — triggers node-detail mode in the right rail AND highlights the node in the graph |
| Path card | `console.debug('[intelligence] path.viewed', { entityId, pathId })` — **C-AN-01 fix**: `analytics.track` / `lib/telemetry.ts` does not exist in the codebase; deferred to platform-wide telemetry initiative. Future v1.1: pin to a workspace note. |
| Contradiction card | `window.open(contradiction.source_a.url, '_blank')` (priority: highest severity source first) |
| Narrative history row | expand inline drawer (≤ 120 px) showing full `narrative_text` for that version; click again to collapse |
| Graph edge (click) | `setSelectedEdgeId(edge.id)` + `setSelectedNodeId(null)` — triggers EdgeDetailCard mode in the right rail. The `IntelligenceTab` lifts `selectedEdgeId: string \| null` state. **Cross-pane sync**: clicked edge highlighted in sigma.js via `edgeReducer` (ring color). |
| Graph node | existing `handleNodeClick` (toggle select) |
| Type-filter dropdown | existing `onEntityTypesChange` |
| Depth slider | existing `onDepthChange` |
| `Back` button (NodeDetailCard) | `onClearSelection()` |

**Narrative generate polling pattern (Δ22)**: After `POST /v1/entities/{id}/narratives/generate` returns 202, the frontend must poll `GET /v1/entities/{id}/narratives` every 3 s (up to 10 attempts = 30 s max). Show a "Generating…" spinner in `NarrativeHistoryDisclosure` header while polling. On 429 (rate-limited), show "Rate limited — retry in 1 h" with countdown. On timeout after 10 polls, show "Generation in progress — check back shortly." This is handled inside `NarrativeHistoryDisclosure` state machine.

### 7.4 Loading / Error / Empty states (per pane)

| Pane | Loading | Error | Empty |
|------|---------|-------|-------|
| News column | 8 skeleton 18 px rows (`animate-pulse bg-muted/20`) | "Failed to load news. [Retry]" — `text-[11px] text-negative`. Retry calls `refetch()` | "No articles for this entity." — italic 11 px |
| Brief | 4 skeleton lines (12 / 11 / 11 / 11 px) | "Brief unavailable. [Retry]" + `r` hotkey hint | `brief.lead ?? brief.summary` null → render fallback "No brief yet — analysis runs every 10 min" (**C-BR-01**: field is `lead`, not `headline`) |
| Graph stats strip | "loading…" muted-foreground | "stats unavailable" | "0 nodes · 0 edges" |
| Graph canvas | spinning `RefreshCw` 16 px | depth-aware copy (see §5.3); show `Retry` button | "No relations for this entity at depth {d}." + "Try depth +1" link |
| Top relations | 6 skeleton 18 px rows | "Relations unavailable" | "No direct relations." |
| Path insights | 2 skeleton 38 px cards | "Path engine offline (AGE)" | "No multi-hop paths discovered. Backend recomputes hourly." |
| Contradictions | 1 skeleton 60 px card | "Contradictions unavailable" | "No contradictions detected." (positive framing) |
| Narrative history | (collapsed by default; no skeleton) | inline error in drawer | "Only the current version exists." |
| Entity overview | combined skeleton (header + 4 description lines) | "Entity detail unavailable" | "No entity record." |
| Node detail | (no skeleton — payload already in graph) | description fetch error → fall back to "Description unavailable." italic | n/a |
| Edge detail | (no loading skeleton — data already in graph payload) | "Edge detail unavailable" if edge not found | n/a |

### 7.5 Cross-pane synchronisation

- Clicking a top-relation row OR a graph node **must** update both: (1) graph node highlight (sigma.js `selectedNode`), (2) right rail switches to node-detail mode. PLAN-0090 already lifts `selectedNodeId` to `IntelligenceTab` — we keep that.
- Filtering news by sentiment does NOT affect the graph (intentional — analysts often want negative news while exploring the full graph).

---

## 8. Data fetching

### 8.1 TanStack Query keys

All keys use the `qk.*` namespace from `lib/query/keys.ts`. We **extend** the namespace; we do NOT rename existing keys (cache-stable migration).

**C-QK-01 fix — migration required**: `lib/query/keys.ts` has NO `qk.kg` namespace today. The three intelligence hooks (`useEntityIntelligence`, `useEntityPaths`, `useEntityNarratives`) use a private `iqk` object local to `lib/api/intelligence.ts`. `NodeDetailCard` uses ad-hoc `['entity-detail', id]`. W7 must: (1) add `qk.kg` to `lib/query/keys.ts` as below; (2) migrate `iqk.intelligence/paths/narratives` → `qk.kg.*` inside `intelligence.ts`; (3) replace ad-hoc `['entity-detail', id]` with `qk.kg.entityDetail(id)` in `NodeDetailCard`. `PathFilters` type is already exported from `lib/api/intelligence.ts` — re-export or import from there.

| Resource | Key | staleTime | Hook |
|----------|-----|-----------|------|
| Instrument brief | `qk.instruments.brief(entityId)` | 10 min | existing in `GraphColumn` |
| Entity graph (depth=d) | `qk.instruments.entityGraph(entityId, depth)` | 10 min | existing; dedup across `GraphColumn` + `ContextPanel` |
| Entity detail | `qk.kg.entityDetail(entityId)` (NEW — replaces ad-hoc `['entity-detail', id]`) | 30 min | NEW |
| Entity intelligence | `qk.kg.intelligence(entityId)` (NEW namespace; `useEntityIntelligence` already uses a similar key) | 60 s | existing wrapped |
| Entity paths | `qk.kg.paths(entityId, filters)` (NEW) | 5 min | existing `useEntityPaths` |
| Entity contradictions | `qk.kg.contradictions(entityId)` (NEW) | 2 min | NEW |
| Entity narratives (infinite) | `qk.kg.narratives(entityId)` (NEW) | 5 min | existing `useEntityNarratives` |
| Entity news (infinite) | `qk.news.entity(entityId, filters)` | 30 s | existing |
| Edge detail | `qk.kg.edgeDetail(edgeId)` | instant (data in graph payload — no separate fetch) | read from graph query data |

Proposed addition to `lib/query/keys.ts`:

```ts
export const qk = {
  // ... existing ...
  kg: {
    all: ['kg'] as const,
    entityDetail: (id: string) => ['kg', 'entity', id, 'detail'] as const,
    intelligence: (id: string) => ['kg', 'entity', id, 'intelligence'] as const,
    paths: (id: string, filters?: PathFilters) =>
      filters ? (['kg', 'entity', id, 'paths', filters] as const)
              : (['kg', 'entity', id, 'paths'] as const),
    contradictions: (id: string) => ['kg', 'entity', id, 'contradictions'] as const,
    narratives: (id: string) => ['kg', 'entity', id, 'narratives'] as const,
  },
};
```

This lets `queryClient.invalidateQueries({ queryKey: qk.kg.all })` cascade-invalidate all KG state on entity change.

### 8.2 Dedup opportunities

- **C-TD-01 fix**: `TopRelationsBlock` fetches depth=1 independently using `qk.instruments.entityGraph(entityId, 1)`, staleTime 10 min. This is a separate cache slot from GraphColumn's variable-depth slot. If the user has moved the slider to depth=2, the depth=1 slot will be empty on first load but fast to fill (<600 ms, SQL JOIN, no AGE). After the first load it is cached for 10 min. The design's original phrase "accept whatever depth is in the cache" was ambiguous and incorrect — the keys are depth-specific.
- `BriefingResponse` is shared between this tab and the Quote tab's `AiBriefBanner` (if reintroduced per `01-global-shell.md`). Same `qk.instruments.brief(entityId)` key.
- `Entity detail` is reused by the Quote tab's `EntityDescriptionPanel` (legacy). New `qk.kg.entityDetail` key replaces the ad-hoc `['entity-detail', id]` everywhere — coordinate with `05-instrument-quote.md`.

### 8.3 Suspense vs. enabled-gating

We continue to **gate** by `enabled: !!accessToken && !!entityId` (no Suspense boundaries inside the tab). Reason: PLAN-0090 is non-Suspense; switching mid-PRD adds risk. Re-evaluate platform-wide in `01-global-shell.md`.

### 8.4 Graph performance budget

| Depth | Budget (cold cache) | Timeout | Backend mechanism |
|-------|--------------------|---------|-------------------|
| 1 | < 600 ms | 1500 ms | S7 SQL JOIN (no AGE) |
| 2 | < 1500 ms | 4000 ms | S7 AGE Cypher 2-hop |
| 3 | < 3000 ms target / 8000 ms hard | 8000 ms | S7 AGE Cypher 3-hop (currently O(degree³) — backend ticket required for materialisation; see `project_graph_bugs_2026_05_11.md`) |

Frontend MUST measure with `performance.now()` around the queryFn. Store elapsed time in `GraphColumn` state and pass as `latencyMs` prop to `GraphStats`. Also log: `console.debug('[intelligence] graph.fetch', { depth, latency_ms, node_count, edge_count })` — **C-AN-01 fix**: `analytics.track` does not exist; telemetry is deferred. This measurement powers the GraphStats strip in §5.3.

**Caching recommendation (Δ21)**: Currently the graph endpoint has NO server-side cache. Adding a 5-min Valkey TTL at S9 (cache key: `graph:{tenant_id}:{entity_id}:{limit}:{depth}`) would reduce repeated load by ~95% during analysis sessions. This is recorded as **backend change B-03** but is not blocking W7 frontend work. The TanStack Query `staleTime: 10 min` already provides a client-side cache; the S9 server cache would benefit multi-tab and mobile scenarios.

---

## 9. Tradeoffs & decisions

### Decision 1 — Layout shape: 3-column vs. stacked

**Chosen**: Option A (3-column, tightened to 28/47/25).
**Alternative**: Option B (stacked AI brief / graph / news ribbon + sticky right rail).
**Why A wins**: the graph is the page's distinguishing feature; pushing it to a middle band squeezes both the news rail (now horizontal, max 10 visible) and the brief (forced wide). Option A also preserves the PLAN-0090 mental model, reducing QA cost. Re-evaluate Option B as a "Reader mode" toggle in v1.1.

### Decision 2 — News row density: 28 px vs. 18 px

**Chosen**: 18 px (`DenseArticleRow`).
**Alternative**: keep 28 px (`CompactArticleRow`).
**Why 18 wins**: Bloomberg NLRT and Refinitiv ship 18 px rows. The current 28 px row carries no thumbnail, no avatar, no two-line meta — it's wasted vertical. We reclaim 10 × 30 = 300 px, which is exactly the height of the new right-rail PATH INSIGHTS + CONTRADICTIONS blocks.

### Decision 3 — Brief renderer: markdown blob vs. structured sections

**Chosen**: structured `BriefingResponse.sections` renderer (StructuredBrief).
**Alternative**: keep `<MarkdownContent>` blob.
**Why structured wins**: the backend already emits `lead + sections[].title + sections[].bullets[]` (see `00-backend-data-inventory.md` §3.7 — note: the inventory sample calls it `headline` but the actual `BriefingResponse` field is `lead` per PLAN-0062-W4; **C-BR-01**) — rendering it as a markdown blob discards the structure the LLM was prompted to produce. The structured renderer makes the brief scannable (each section is its own micro-card) and accessible (proper heading levels for a11y). The shared `StructuredBrief` component at `components/brief/StructuredBrief.tsx` already handles this with `variant="compact"` — no fork required (**C-SB-01**).

### Decision 4 — Graph timeout: fixed 3 s vs. depth-adaptive

**Chosen**: depth-adaptive (1.5 s / 4 s / 8 s).
**Alternative**: keep 3 s for all.
**Why adaptive wins**: a single 3 s budget guarantees depth=3 always fails on cold cache. Per memory `project_age_cypher_fix_2026_05_11.md`, hot-cache depth=3 is 285 ms but cold can be 4-6 s — and that's WITH the BP-461 fix. Depth-adaptive lets depth=1 fail fast (real error) while letting depth=3 actually return.

### Decision 5 — Right rail empty state: blank vs. populated

**Chosen**: always populated (overview + relations + paths + contradictions + narratives).
**Alternative**: blank when no node selected (current PLAN-0090 behaviour).
**Why populated wins**: the right rail is 360 × 784 = 282 240 px² of screen real estate. The user's primary entity ALWAYS has top relations and (usually) contradictions and paths. Leaving it blank because the user hasn't clicked anything yet is the single worst UX in PLAN-0090.

### Decision 6 — Description on NodeDetailCard: lazy fetch vs. "Description unavailable"

**Chosen**: lazy `getEntityDetail()` on selection.
**Alternative**: keep the hardcoded "No description available." string.
**Why lazy wins**: descriptions are SHORT (~200 chars), the endpoint is fast (< 50 ms warm), and the alternative makes the node-detail mode look broken. We rate-limit naturally because users click at most a few nodes per session.

### Decision 7 — Grid: 12-col vs. 14-col

**Chosen**: 14-col (scoped to this tab).
**Alternative**: 12-col with 3 / 6 / 3 (25/50/25).
**Why 14 wins**: 25 % is too narrow for news (only ~22 articles visible); 28 % gives ~30 with the 18 px row. The 14-col grid is added in `tailwind.config.ts` as a one-off; other tabs continue to use 12-col.

---

## 10. Open questions (all resolved — 2026-05-22 audit)

All OQs resolved during `/revise-prd` pass. Audit corners file: `docs/designs/0089/oq/07-instrument-intelligence-CORNERS-AUDIT.md`.

| # | Question | Decision |
|---|----------|----------|
| 1 | Path-to-portfolio filtering | **Option (b)**: client-side post-filter. Fetch `qk.portfolios.holdings(activePortfolioId)` (already in cache on most page loads). Filter paths where any terminal node ticker matches a held ticker. Fall back to top-3 generic paths if user has no holdings or holdings are unavailable. Option (c) deferred to v1.1. |
| 2 | Narrative-history drawer mechanism | Use **existing `components/ui/accordion`** (shadcn Accordion). `NarrativeHistoryDisclosure` renders an `AccordionItem`. No custom inline drawer needed. |
| 3 | `j`/`k` hotkey collision | **SAFE** — `GlobalHotkeyBindings.tsx` does NOT register bare `j` or `k`. WatchlistPanel does NOT register them. Use bare `j`/`k` for news-row navigation without chord prefix. |
| 4 | AGE depth=3 materialisation | Deferred. The 8 s budget is a frontend stopgap. A follow-up spec item (`entity_relationships_materialized` S7 worker) is recorded in `docs/specs/0089-platform-page-redesign.md §14`. Out of scope for W7. |
| 5 | Contradictions severity casing | Always call `.toUpperCase()` before branching. Fallback unknown values → `'LOW'`. Color map in §5.5 uses uppercase keys (`HIGH/MEDIUM/LOW`). |
| 6 | Regenerate-brief endpoint | `POST /v1/briefings/instrument/{id}/regenerate` does **NOT** exist. `r` hotkey → `queryClient.invalidateQueries({ queryKey: qk.instruments.brief(entityId) })`, which triggers `useInstrumentBrief`'s lazy-generate flow (shipped in W5). |
| 7 | Telemetry / analytics.track | `lib/telemetry.ts` does NOT exist. Replace all `analytics.track(...)` calls with `console.debug(...)`. Telemetry is a future platform initiative (deferred). |
| 8 | Workspace pin for paths | Future v1.1. Recorded in `09-workspace-predictions-alerts.md`. No action in W7. |

---

## 11. Enhancement opportunities (backend data not in original design — added 2026-05-22)

These three items come from the `/revise-prd` audit. Each ships with W7 as zero-backend-cost improvements because the data is already in existing API responses.

### E-01 — `confidence_breakdown` tooltip on health badge

`GET /v1/entities/{id}/intelligence` returns `confidence_breakdown: {fully_confident, high_confidence, medium_confidence, low_confidence}` (integer claim counts). Currently discarded.

**Implementation**: Add `title` prop on the health badge in `EntityOverviewBlock`:
```tsx
title={`${cb.fully_confident} high · ${cb.high_confidence} med · ${cb.medium_confidence} low · ${cb.low_confidence} uncertain claims`}
```
No new component. Single line. Surfaces data quality signal instantly on hover.

### E-02 — `data_completeness` percentage badge

`GET /v1/entities/{id}/intelligence` returns `data_completeness: {fields_populated: 34, total_fields: 42}`. Currently discarded.

**Implementation**: Render as a small secondary badge in `EntityOverviewBlock` using `DataFreshnessPill` from F1 primitives:
```tsx
const pct = Math.round((completeness.fields_populated / completeness.total_fields) * 100);
<DataFreshnessPill label={`${pct}% complete`} />
```
Positioned next to the type badge. Analysts can judge data quality at a glance.

### E-03 — `BriefingResponse.risk_summary` surfaced via `StructuredBrief`

`BriefingResponse.risk_summary` (top_risk_signals array) is already in the frontend type and the existing `StructuredBrief` component renders risk signals when `variant="compact"` is used. This enhancement is a **free by-product** of the C-SB-01 fix (reusing the shared component instead of forking). No additional implementation required — confirm `StructuredBrief` variant="compact" renders risk chips and document in acceptance criteria.
