# W7 — Instrument Intelligence Tab Redesign — Plan

**PRD**: 0089 platform page redesign
**Design**: `docs/designs/0089/07-instrument-intelligence.md` (iter-2, revised 2026-05-22)
**Sibling foundation**: F1 (shipped) / F2 (shipped) / W1 (shipped) / W2 (shipped) / W5 (shipped 2026-05-21) / W3 (pending — execute before or in parallel with W7 if separate branch)
**Status**: ✅ SHIPPED 2026-05-22 — Blocks A-H (T-01..T-24) complete; Block I (B-01/B-02 backend + EdgeDetailCard) deferred to next sprint
**Estimated**: 5–6 engineer-days
**Branch**: `feat/plan-0089-w2`

---

## §0. Design deltas from `07-instrument-intelligence.md` (post-audit)

All 10 corners fixed in the design doc on 2026-05-22. Summary of locked decisions:

| # | Corner | Plan locks |
|---|--------|------------|
| Δ1 | C-SB-01 | **Reuse** `components/brief/StructuredBrief.tsx` (variant="compact"). Do NOT create `intelligence/brief/StructuredBrief.tsx`. |
| Δ2 | C-BR-01 | Brief one-liner = `brief.lead ?? brief.summary`. NOT `brief.headline` (field does not exist). |
| Δ3 | C-BR-02 | Brief footer = `generated_at · {client-measured latency_ms} ms`. No `provider` field (not in BriefingResponse). Measure latency client-side via `performance.now()` in queryFn. |
| Δ4 | C-SD-01 | `SectionDivider` → import from `@/components/primitives/SectionDivider`. NOT `instrument/shared/`. |
| Δ5 | C-HK-01 | Use `useChordHotkeys` with `scope: "page"`. NOT `useHotkeys`. Push scope on mount, pop on unmount. |
| Δ6 | C-QK-01 | Add `qk.kg` to `lib/query/keys.ts`. Migrate `iqk.*` keys in `intelligence.ts` to `qk.kg.*`. Replace ad-hoc `['entity-detail', id]` with `qk.kg.entityDetail(id)` in `NodeDetailCard`. |
| Δ7 | C-TD-01 | `TopRelationsBlock` fetches depth=1 independently (`qk.instruments.entityGraph(entityId, 1)`, staleTime 10 min). Not "whatever is in cache." |
| Δ8 | C-OQ-05 | Severity: always `.toUpperCase()` before branching; fallback unknown → `'LOW'`. |
| Δ9 | C-AN-01 | Replace `analytics.track(...)` with `console.debug(...)` everywhere. |
| Δ10 | C-NG-01 | Add ↻ "Refresh narrative" icon button in `EntityOverviewBlock` → `POST /v1/entities/{id}/narratives/generate`. |
| E-01 | Enhancement | `confidence_breakdown` as `title` tooltip on health badge (EntityOverviewBlock). |
| E-02 | Enhancement | `data_completeness` badge next to type badge (EntityOverviewBlock). |
| E-03 | Enhancement | `BriefingResponse.risk_summary` surfaces via `StructuredBrief` variant="compact" for free — no extra code. |
| Δ11 | Δ11 | New `EdgeDetailCard` component (right rail edge-detail mode). Requires `selectedEdgeId` state in `IntelligenceTab`. ContextPanel adds third mode. |
| Δ12 | Δ12 | EdgeTooltipPanel: wire `evidence_snippets[0..2]` + `relation_summary` + `decay_class` badge. Data already in payload for depth=1. |
| Δ13 | Δ13 | Node hover: add `description` + `sector` to `GraphNode`. Requires S9 backend change B-01. |
| Δ14 | Δ14 | Edge `decay_class` exposed in S9 response (B-02). Used for edge opacity in sigma.js `edgeReducer`. |
| Δ15 | Δ15 | PathInsightsBlock: show `surprise_score` ("UNEXPECTED" badge) + `harmonic_score`. Zero backend cost. |
| Δ16 | Δ16 | ContradictionsBlock: show `claim_type` pill + per-side `confidence`. Zero backend cost. |
| Δ17 | Δ17 | EntityOverviewBlock: 40×18px confidence_trend sparkline (SVG polyline). Zero backend cost. |
| Δ18 | Δ18 | EntityOverviewBlock: source_distribution chips (max 4). Zero backend cost. |
| Δ19 | Δ19 | §3.3 clarification: key highlights = sections[0], risks = risk_summary; no new endpoint. |
| Δ20 | Δ20 | Edge-click → EdgeDetailCard. `selectedEdgeId` state lifted to IntelligenceTab. |
| Δ21 | Δ21 | S9 graph caching (B-03, non-blocking for W7). Document in §8.4. |
| Δ22 | Δ22 | Narrative polling: 3s interval × 10 polls after POST 202. |
| Δ23 | Δ23 | §3.4 added: 3 backend changes (B-01, B-02, B-03). |

**No blocking frontend-only work without backend changes (B-01 + B-02 are required for checks 26/28).** See §3 for backend dependency details.

---

## §1. Bloomberg-grade resemblance checks (acceptance gate)

After this wave lands, the page MUST:

1. Above-fold cell count ≥ 46 (30 news + 10 relations + 3 paths + 2 contradictions + 1 brief).
2. News column: ≥ 30 articles visible above the fold (18 px rows, 784 - 22 px filter strip).
3. News rows are `DenseArticleRow` (18 px, 2 px sentiment stripe, impact score right-aligned).
4. Brief renders `brief.lead ?? brief.summary` as 12 px bold, then `sections[]` structured, via `StructuredBrief variant="compact"`. No `MarkdownContent` blob.
5. Brief footer shows `generated_at · {latency_ms} ms` (client-measured).
6. Graph timeout is depth-adaptive: 1.5 s / 4 s / 8 s. Old constant 3 s is gone.
7. `GraphStats` strip visible below brief: `N nodes · M edges · depth D · T ms`.
8. Right rail (entity-overview mode) shows 5 distinct blocks: EntityOverview + TopRelations + PathInsights + Contradictions + NarrativeHistory.
9. EntityOverviewBlock shows: name, type badge, health badge (with confidence_breakdown tooltip), data_completeness badge, description (4-line clamp), key_metrics 4-cell strip, ↻ narrative refresh button.
10. TopRelationsBlock shows ≥ 1 row (or "No direct relations.") within depth=1 fetch.
11. PathInsightsBlock shows ≥ 1 path card (or "No multi-hop paths discovered.").
12. ContradictionsBlock shows ≥ 1 card (or "No contradictions detected.") with uppercase severity badge.
13. NarrativeHistoryDisclosure: collapsed by default; expands via shadcn Accordion into version list.
14. `NodeDetailCard` shows real description fetched from `GET /v1/entities/{id}` (not hardcoded "No description available.") — `qk.kg.entityDetail(nodeId)` key.
15. `EdgeTooltipPanel` on hover shows `evidence_snippets[0..2]` as 9 px lines.
16. Grid is `grid-cols-14` (requires tailwind.config.ts extension).
17. Hotkeys `j`/`k` navigate news rows; `1`/`2`/`3` set graph depth; `r` invalidates brief cache; `Esc` clears selection. All scoped via `useChordHotkeys` with `scope: "page"`.
18. `qk.kg` namespace exists in `lib/query/keys.ts`; `iqk.*` keys in `intelligence.ts` are migrated.
19. No `analytics.track` call anywhere in W7 code.
20. 4 arch tests pass: `no-off-palette-colors`, `animation-policy`, `data-table-grid-scope` (N/A for this tab), `empty-copy-dictionary`.
21. Vitest density test: `expect(visibleCells).toBeGreaterThanOrEqual(46)`.
22. 4 Playwright e2e tests pass.
23. `pnpm --filter worldview-web typecheck` + `lint` zero errors.
24. Edge click → right rail switches to EdgeDetailCard mode (source→relation→target breadcrumb visible).
25. EdgeDetailCard shows: decay_class badge (color-coded), relation_summary (if any), evidence_snippets[0..2] as blockquote rows, evidence count, latest_evidence_at.
26. Node hover tooltip shows: entity name + type badge + sector badge + description snippet (2-line clamp). Requires B-01 (S9 GraphNode enrichment).
27. Edge hover tooltip shows: relation label + strength + relation_summary + evidence_snippets[0..2]. Evidence snippets shown only at depth=1; fallback "Expand at depth 1" for depth>1.
28. Graph edges use decay_class-based opacity: PERMANENT/DURABLE full, SLOW/MEDIUM 70%, FAST/EPHEMERAL 40%. Requires B-02.
29. PathInsightsBlock: paths with `surprise_score > 0.7` show amber "UNEXPECTED" pill.
30. ContradictionsBlock: `claim_type` pill visible on each card.
31. EntityOverviewBlock: 40×18px sparkline shows trend direction from `confidence_trend[]`.
32. EntityOverviewBlock: source_distribution chips (max 4) visible below key_metrics strip.
33. S9 graph endpoint returns `decay_class` on edges and `description`/`sector` on nodes (B-01 + B-02 in §3.4).

---

## §2. Pre-flight (verify before writing any code)

1. `git log --oneline -30` — confirm F1/F2/W1/W2/W5 present. Ideally W3 done too (shares `InstrumentTabs.tsx`).
2. `cat apps/worldview-web/components/brief/StructuredBrief.tsx | head -30` — confirm `variant="compact"` prop exists.
3. `cat apps/worldview-web/components/primitives/SectionDivider.tsx | head -20` — confirm `label?` prop exists (or note that it's missing and we use bare divider).
4. `cat apps/worldview-web/lib/hotkey-registry.ts | grep HotkeyScope` — confirm scope values; note whether "intelligence" needs to be added or "page" suffices.
5. `grep -n "j.*hotkey\|hotkey.*j\|key.*j" apps/worldview-web/components/shell/GlobalHotkeyBindings.tsx` — confirm `j`/`k` are safe bare.
6. `grep -n "iqk\." apps/worldview-web/lib/api/intelligence.ts | head -10` — note all 3 `iqk.*` key names to migrate.
7. `grep -n "entity-detail" apps/worldview-web/components/instrument/intelligence/context/NodeDetailCard.tsx` — confirm the ad-hoc key location.
8. `grep -n "qk\.kg" apps/worldview-web/lib/query/keys.ts` — confirm `qk.kg` doesn't already exist (should not).
9. `grep -n "grid-cols-14" apps/worldview-web/tailwind.config.ts` — confirm not already present.
10. `cat apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx | grep -n "GRAPH_TIMEOUT_MS"` — confirm constant is still 3000 (we replace it with depth map).

---

## §3. Backend dependencies

Backend changes required (all S9 proxy additions — no new endpoints or workers):

| ID | Change | Blocking? |
|----|--------|-----------|
| B-01 | Add `description`, `sector`, `exchange` to S9 GraphNode proxy schema | YES — for acceptance checks 26 |
| B-02 | Add `decay_class` to S9 graph edge proxy schema | YES — for acceptance checks 28 |
| B-03 | Add 5-min Valkey cache to S9 graph endpoint | NO — non-blocking; add if time allows |

These changes are in the S9 api-gateway service (`routes/intelligence.py`). They are small additions to Pydantic schemas and do not require new migrations or workers.

All required S9 endpoints already exist:
- `GET /v1/entities/{id}` ✓
- `GET /v1/entities/{id}/graph?depth=N` ✓
- `GET /v1/entities/{id}/intelligence` ✓
- `GET /v1/entities/{id}/paths` ✓
- `GET /v1/entities/{id}/contradictions` ✓
- `GET /v1/entities/{id}/narratives` ✓
- `POST /v1/entities/{id}/narratives/generate` ✓
- `GET /v1/briefings/instrument/{id}` ✓
- `POST /v1/briefings/instrument/{id}/generate` ✓ (W5)
- `GET /v1/news/entity/{id}` ✓

---

## §4. File-by-file frontend change set (each sub-step = one commit)

### Block A — Foundation (query keys + tailwind + hotkey infra)

**T-01 (EDIT)** `apps/worldview-web/tailwind.config.ts`
  Add `gridTemplateColumns: { '14': 'repeat(14, minmax(0, 1fr))' }` to `extend`.
  Verify the existing `data-table-grid` tests still pass (no color change).
  Commit: "feat(w7): T-01 tailwind grid-cols-14 for Intelligence tab"

**T-02 (EDIT)** `apps/worldview-web/lib/query/keys.ts`
  Add `qk.kg` namespace (Δ6):
  ```ts
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
  ```
  Import `PathFilters` from `lib/api/intelligence.ts` (already exported there).
  Commit: "feat(w7): T-02 qk.kg namespace to lib/query/keys.ts"

**T-03 (EDIT)** `apps/worldview-web/lib/api/intelligence.ts`
  Migrate `iqk.intelligence/paths/narratives` → `qk.kg.intelligence/paths/narratives`.
  This is a rename-only inside the hook queryKey fields. No logic change.
  Commit: "feat(w7): T-03 migrate iqk.* → qk.kg.* in intelligence.ts"

### Block B — News column (DenseArticleRow)

**T-04 (NEW)** `apps/worldview-web/components/instrument/intelligence/news/DenseArticleRow.tsx` (≤ 90 LOC)
  18 px row (`h-[18px]`). Replaces `CompactArticleRow` (28 px / h-7).
  Layout: `px-3 flex items-center gap-2`.
  - Left edge: 2 px vertical bar `w-[2px] h-full self-stretch` with sentiment color:
    `sentiment === 'positive'` → `bg-positive`
    `sentiment === 'negative'` → `bg-negative`
    else → `bg-muted-foreground/40`
  - `text-[10px] mono tabular-nums text-muted-foreground w-[38px] shrink-0` — HH:MM
  - `text-[10px] mono text-muted-foreground w-[28px] shrink-0` — 3-letter source code
  - `text-[11px] flex-1 truncate` — headline
  - Impact score: `text-[10px] mono tabular-nums w-[20px] text-right` — 0-99 int (multiply float 0-1 by 100 and floor):
    `impact_score >= 0.70` → `text-positive`
    `impact_score >= 0.40` → `text-warning`
    else → `text-muted-foreground`
  Props: `interface DenseArticleRowProps { article: RankedArticle }` (same as CompactArticleRow — drop-in).
  On click: `window.open(article.url, '_blank', 'noopener,noreferrer')`.
  Commit: "feat(w7): T-04 DenseArticleRow 18px with sentiment stripe + impact score"

**T-05 (EDIT)** `apps/worldview-web/components/instrument/intelligence/news/NewsColumn.tsx`
  Replace `CompactArticleRow` import + usage → `DenseArticleRow`. No other changes.
  Commit: "feat(w7): T-05 NewsColumn → DenseArticleRow"

### Block C — Graph column (timeout + stats + brief)

**T-06 (EDIT)** `apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx`
  Changes:
  1. Replace `GRAPH_TIMEOUT_MS = 3000` with depth-adaptive map (Δ from design §5.3):
     ```ts
     const GRAPH_TIMEOUT_MS: Record<number, number> = { 1: 1500, 2: 4000, 3: 8000 };
     ```
     Use `GRAPH_TIMEOUT_MS[depth] ?? 4000` in the setTimeout.
  2. Brief rendering: replace `<MarkdownContent>` blob with
     `<StructuredBrief brief={brief} variant="compact" />` from `@/components/brief/StructuredBrief` (Δ1/Δ2).
  3. Add footer strip below StructuredBrief:
     ```tsx
     <span className="text-[9px] mono text-muted-foreground">
       {formatDatetime(brief.generated_at)} · {graphLatencyMs !== null ? `${graphLatencyMs} ms` : '—'}
     </span>
     ```
  4. Add `graphFetchStartRef = useRef<number>(0)` + `graphLatencyMs` state. In queryFn:
     `graphFetchStartRef.current = performance.now()`. In `onSuccess`:
     `setGraphLatencyMs(Math.round(performance.now() - graphFetchStartRef.current))`.
  5. Replace `analytics.track('graph.fetch', ...)` → `console.debug('[intelligence] graph.fetch', ...)` (Δ9).
  Budget: was 118 LOC → ≤ 180.
  Commit: "feat(w7): T-06 GraphColumn depth-adaptive timeout + StructuredBrief + latency"

**T-07 (NEW)** `apps/worldview-web/components/instrument/intelligence/graph/GraphStats.tsx` (≤ 40 LOC)
  `interface GraphStatsProps { nodeCount: number; edgeCount: number; depth: number; latencyMs: number | null }`
  18 px strip: `{nodeCount} nodes · {edgeCount} edges · depth {depth} · {latencyMs ?? '—'} ms`
  Typography: `text-[10px] mono tabular-nums text-muted-foreground`.
  Loading state: "loading…"; empty state: "0 nodes · 0 edges".
  Commit: "feat(w7): T-07 GraphStats strip"

### Block D — Right rail: qk.kg namespace wiring + new blocks

**T-08 (EDIT)** `apps/worldview-web/components/instrument/intelligence/context/NodeDetailCard.tsx`
  Replace `queryKey: ['entity-detail', node.id]` → `queryKey: qk.kg.entityDetail(node.id)` (Δ6).
  No other changes.
  Commit: "feat(w7): T-08 NodeDetailCard → qk.kg.entityDetail"

**T-09 (NEW)** `apps/worldview-web/components/instrument/intelligence/context/EntityOverviewBlock.tsx` (≤ 100 LOC)
  Two queries: `qk.kg.entityDetail(entityId)` (getEntityDetail, staleTime 30 min) + `qk.kg.intelligence(entityId)` (useEntityIntelligence, staleTime 60 s).
  Renders:
  - Name `text-[12px] font-semibold` + type badge `text-[9px] bg-muted px-1.5 py-0.5 rounded-[2px]`
  - Health badge: tone-colored, `title` = confidence_breakdown tooltip (E-01)
  - DataFreshnessPill: `${pct}% complete` from `data_completeness` (E-02) — import from `@/components/primitives/DataFreshnessPill`
  - Description `text-[11px] line-clamp-4 text-foreground/80` (fallback: "No description available." italic)
  - `intelligence.key_metrics` 4-cell strip: market_cap, employees, founded, hq_country (each a mini MetricCell)
  - ↻ icon button (lucide `RefreshCw` 10px): fires `POST /v1/entities/{id}/narratives/generate`; shows `animate-spin` + cooldown state (C-NG-01)
  Commit: "feat(w7): T-09 EntityOverviewBlock name/health/desc/metrics/refresh"

**T-10 (NEW)** `apps/worldview-web/components/instrument/intelligence/context/TopRelationsBlock.tsx` (≤ 90 LOC)
  Reads `qk.instruments.entityGraph(entityId, 1)` (useQuery, depth=1 INDEPENDENT fetch, staleTime 10 min — Δ7).
  Derives edges whose source === entityId, sorts by `edge.weight` desc, takes top 10.
  Renders 18 px rows: target label (truncate, flex-1) · relation label (9 px, muted) · weight (tabular-nums, 3 chars).
  Click → `onNodeSelect(edge.target_id)`.
  Empty: "No direct relations." | Loading: 6 skeleton rows | Error: "Relations unavailable".
  Commit: "feat(w7): T-10 TopRelationsBlock depth-1 independent fetch"

**T-11 (NEW)** `apps/worldview-web/components/instrument/intelligence/context/PathInsightsBlock.tsx` (≤ 110 LOC)
  Uses `useEntityPaths(entityId)` (now using `qk.kg.paths` after T-03 migration).
  Portfolio filtering (OQ-1): read `qk.portfolios.holdings(activePortfolioId)` from cache (read-only, no new fetch trigger); filter paths where any terminal node ticker is in holdings. Fallback to top-3 generic paths if holdings unavailable.
  Renders top 3 paths as 38 px cards: route arrows `→ Entity → Entity` · meta `N hops · relation_labels`.
  Click → `console.debug('[intelligence] path.viewed', { entityId, path })`.
  Commit: "feat(w7): T-11 PathInsightsBlock with portfolio post-filter"

**T-12 (NEW)** `apps/worldview-web/components/instrument/intelligence/context/ContradictionsBlock.tsx` (≤ 90 LOC)
  New `useQuery({ queryKey: qk.kg.contradictions(entityId), queryFn: () => gateway.getEntityContradictions(entityId), staleTime: 2 * 60 * 1000 })`.
  Verify `getEntityContradictions` exists in `lib/api/knowledge-graph.ts`; if not, add it.
  Renders top 5 as 60 px cards: severity badge (`.toUpperCase()`, fallback `'LOW'`, Δ8) · claim_a · "vs" · claim_b · sources · timestamp.
  Click → `window.open(contradiction.source_a.url ?? '#', '_blank', 'noopener,noreferrer')`.
  Empty: "No contradictions detected." | Loading: 1 skeleton card | Error: "Contradictions unavailable".
  Commit: "feat(w7): T-12 ContradictionsBlock severity-normalised"

**T-13 (NEW)** `apps/worldview-web/components/instrument/intelligence/context/NarrativeHistoryDisclosure.tsx` (≤ 70 LOC)
  Uses `useEntityNarratives(entityId)` (now using `qk.kg.narratives` after T-03 migration).
  Wraps in shadcn `Accordion`/`AccordionItem` (OQ-2). Default state: collapsed.
  Expanded: scrollable list of versions, each 32 px: `timestamp · model · 1-line snippet` (first 80 chars of narrative_text).
  Click version row → expand inline `<details>` showing full `narrative_text` (Accordion nesting or toggle). Max 400 px expanded height, `overflow-y-auto`.
  Empty (only current version): "Only the current version exists."
  Commit: "feat(w7): T-13 NarrativeHistoryDisclosure shadcn Accordion"

**T-14 (NEW)** `apps/worldview-web/components/instrument/intelligence/context/NodePathsBlock.tsx` (≤ 80 LOC)
  Node-detail mode version of PathInsightsBlock. Uses `useEntityPaths(selectedNodeId, { target_entity_id: entityId })`.
  Same 38 px card pattern. Limit 3. No portfolio filtering (node-specific paths don't need it).
  Commit: "feat(w7): T-14 NodePathsBlock node↔primary paths"

### Block E — ContextPanel refactor + IntelligenceTab grid

**T-15 (EDIT)** `apps/worldview-web/components/instrument/intelligence/context/ContextPanel.tsx`
  Refactor: was 289 LOC, target ≤ 260 LOC.
  Entity-overview mode (`selectedNodeId === null`) render tree:
  ```tsx
  <EntityOverviewBlock entityId={entityId} />
  <SectionDivider />
  <TopRelationsBlock entityId={entityId} limit={10} onNodeSelect={onNodeSelect} />
  <SectionDivider />
  <PathInsightsBlock entityId={entityId} limit={3} />
  <SectionDivider />
  <ContradictionsBlock entityId={entityId} limit={5} />
  <SectionDivider />
  <NarrativeHistoryDisclosure entityId={entityId} />
  ```
  Node-detail mode (`selectedNodeId !== null`) — keep existing NodeDetailCard + RelationsList structure; add NodePathsBlock below RelationsList.
  SectionDivider: import from `@/components/primitives/SectionDivider` (Δ4).
  Commit: "feat(w7): T-15 ContextPanel 5-block overview + node-detail with paths"

**T-16 (EDIT)** `apps/worldview-web/components/instrument/intelligence/IntelligenceTab.tsx`
  Change `grid-cols-12` → `grid-cols-14`. Update col-span values:
  - news: `col-span-4` (was `col-span-3`)
  - graph: `col-span-7` (was `col-span-6`)
  - context: `col-span-3` (unchanged)
  Push `"page"` hotkey scope on mount, pop on unmount (Δ5 via `useHotkeyScope`).
  Commit: "feat(w7): T-16 IntelligenceTab grid-cols-14 + page hotkey scope"

**T-17 (EDIT)** `apps/worldview-web/components/instrument/intelligence/news/NewsColumn.tsx`
  Add `j`/`k` hotkey handlers for news-row navigation (Δ5):
  - Maintain `highlightedIndex: number | null` state.
  - `j` → increment (wraps), `k` → decrement. `Enter` → open highlighted article.
  - Highlighted row gets `ring-1 ring-border bg-muted/20`.
  Use `useChordHotkeys` with `scope: "page"`.
  Confirm `j`/`k` are safe (pre-flight step 5 already verified).
  Commit: "feat(w7): T-17 NewsColumn j/k row navigation"

**T-18 (EDIT)** `apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx` (second pass)
  Add `1`/`2`/`3` hotkeys to set depth (call `onDepthChange(1/2/3)` — verify `GraphToolbar` exposes this via prop or ref).
  Add `g` hotkey to focus graph canvas (`sigmaRef.current?.getCamera().setState(...)` or `sigmaRef.current?.refresh()`).
  Verify `r` hotkey wires `queryClient.invalidateQueries({ queryKey: qk.instruments.brief(entityId) })` (OQ-6).
  Add `Esc` hotkey → `onClearSelection()` prop call.
  All via `useChordHotkeys` with `scope: "page"`.
  Commit: "feat(w7): T-18 GraphColumn hotkeys 1/2/3/g/r/Esc"

**T-19 (EDIT)** `apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx` (edge tooltip)
  Enhance `EdgeTooltipPanel` (or the sigma edge hover handler) to render `evidence_snippets[0..2]` as 9 px lines under the relation label. Data is already on the graph payload (no new fetch).
  Commit: "feat(w7): T-19 EdgeTooltipPanel evidence_snippets on hover"

### Block F — Gateway + types

**T-20 (EDIT)** `apps/worldview-web/lib/api/knowledge-graph.ts`
  Verify `getEntityContradictions(entityId)` exists. If not, add:
  ```ts
  async getEntityContradictions(entityId: string): Promise<ContradictionsResponse | null> {
    ...apiFetch(`/v1/entities/${encodeURIComponent(entityId)}/contradictions`)
  }
  ```
  Verify `ContradictionsResponse` type exists in `types/api.ts`; add if missing.
  Commit: "feat(w7): T-20 getEntityContradictions gateway method + type"

**T-21 (EDIT)** `apps/worldview-web/lib/api/knowledge-graph.ts`
  Verify `getNarratives(entityId, cursor?)` proxy exists (for `NarrativeHistoryDisclosure`). Add if missing.
  Commit: "feat(w7): T-21 getNarratives gateway method (if missing)"

### Block G — Arch tests + density gates + unit tests

**T-22 (NEW)** `apps/worldview-web/__tests__/instrument/intelligence-density.test.ts`
  Vitest: render `IntelligenceTab` with mock data → `expect(visibleCells).toBeGreaterThanOrEqual(46)`.
  Commit: "test(w7): T-22 intelligence density gate ≥46 cells"

**T-23 (NEW)** Unit tests for all new components (T-04/07/09/10/11/12/13/14):
  Minimum: empty state + populated state + click handler per component.
  Files:
  ```
  news/__tests__/DenseArticleRow.test.tsx
  graph/__tests__/GraphStats.test.tsx
  context/__tests__/EntityOverviewBlock.test.tsx
  context/__tests__/TopRelationsBlock.test.tsx
  context/__tests__/PathInsightsBlock.test.tsx
  context/__tests__/ContradictionsBlock.test.tsx
  context/__tests__/NarrativeHistoryDisclosure.test.tsx
  context/__tests__/NodePathsBlock.test.tsx
  ```
  Commit: "test(w7): T-23 unit tests all new intelligence components"

### Block H — Playwright e2e

**T-24 (NEW)** `apps/worldview-web/e2e/instrument-intelligence.spec.ts`
  4 tests:
  1. AAPL Intelligence tab: ≥ 30 news rows visible above fold.
  2. AAPL Intelligence tab: right rail shows 5 distinct section headers (EntityOverview, TOP RELATIONS, PATH INSIGHTS, CONTRADICTIONS, NARRATIVE HISTORY).
  3. Click a top-relation row → right rail switches to node-detail mode (NodeDetailCard visible, description non-empty).
  4. Press `j` 3× → 3rd news row highlighted; press `Enter` → new tab or navigation.
  Commit: "test(w7): T-24 Playwright e2e instrument-intelligence 4 tests"

### Block I — Backend S9 proxy additions + EdgeDetailCard

**T-25 (EDIT)** `services/api-gateway/src/api_gateway/routes/intelligence.py`
  Backend change B-01: Add `description: str | None = None`, `sector: str | None = None` to GraphNode schema.
  Backend change B-02: Add `decay_class: str | None = None` to GraphEdge/RelationResponse schema.
  In the graph handler, populate `description` and `sector` from the entity detail batch fetch (S7 should already have this data in EntitySummary — check S7 graph endpoint and add to EntitySummary if missing).
  Commit: "feat(w7): T-25 S9 graph proxy enrichment — node description/sector + edge decay_class (B-01/B-02)"

**T-26 (NEW)** `apps/worldview-web/components/instrument/intelligence/context/EdgeDetailCard.tsx` (≤ 110 LOC)
  Props: `interface EdgeDetailCardProps { edgeId: string; onBack: () => void; }`
  Data: read the edge from the graph query cache (`queryClient.getQueryData(qk.instruments.entityGraph(entityId, depth))`) — no new network request.
  Renders:
  - Back button `←` at top (calls `onBack()`)
  - Source → RELATION_TYPE → Target breadcrumb (12 px bold)
  - Strength: `Math.round(edge.weight * 100) / 100` as 0-100 bar + text "82 / 100" (10 px mono)
  - Decay badge: `decay_class` color-coded (PERMANENT/DURABLE→positive, SLOW/MEDIUM→warning, FAST/EPHEMERAL→negative)
  - LLM summary: `relation_summary` (11 px, 4-line clamp) — italic if null "No summary available."
  - Evidence header "EVIDENCE · {evidence_count} articles" (10 px uppercase)
  - Evidence snippets: `(evidence_snippets ?? []).slice(0, 5).map(s => <blockquote>)` (9 px, indented 8px, border-l-2 border-border/40)
  - Temporal: "Last seen: {format(latest_evidence_at)}"
  Commit: "feat(w7): T-26 EdgeDetailCard — source/relation/target/decay/evidence"

**T-27 (EDIT)** `apps/worldview-web/components/instrument/intelligence/IntelligenceTab.tsx`
  Add `selectedEdgeId: string | null` state.
  Pass `onEdgeSelect={setSelectedEdgeId}` down to `GraphColumn` → `EntityGraph` → `GraphEvents`.
  In `GraphEvents`, add `clickEdge` handler: `sigma.on('clickEdge', ({ edge }) => { onEdgeSelect(edge); onNodeSelect(null); })`.
  In `ContextPanel`, add `selectedEdgeId` prop and third branch for EdgeDetailCard mode.
  Commit: "feat(w7): T-27 edge-click → EdgeDetailCard wiring (IntelligenceTab + ContextPanel + GraphEvents)"

---

## §5. Hotkeys (Intelligence-tab scope only)

| Chord | Action | Scope |
|-------|--------|-------|
| `j` / `k` | Next / previous news row (highlight + scroll) | Intelligence tab |
| `Enter` | Open highlighted news article in new tab | Intelligence tab |
| `1` / `2` / `3` | Set graph depth to 1 / 2 / 3 | Intelligence tab |
| `t` | Toggle type-filter dropdown | Intelligence tab |
| `g` | Focus sigma.js graph canvas | Intelligence tab |
| `r` | Invalidate brief cache → lazy-generate | Intelligence tab |
| `Esc` | Clear node selection (→ entity-overview mode) | All tabs (global) |
| `?` | Hotkey legend overlay | Global |
| `e` | Open EdgeDetailCard for the last-hovered edge | Intelligence tab |

Tab-switch chords `q`/`f`/`i` remain owned by `InstrumentTabs`.

---

## §6. Tests

### 6.1 Unit (Vitest)

| # | File | Asserts |
|---|------|---------|
| U-1 | intelligence-density.test.ts (T-22) | ≥ 46 visible cells |
| U-2 | DenseArticleRow.test.tsx | 18px height, sentiment stripe colors, impact score tiers |
| U-3 | GraphStats.test.tsx | renders node/edge/depth/latency; null latency → "—" |
| U-4 | EntityOverviewBlock.test.tsx | health badge tooltip, data_completeness badge, ↻ button fires mutation |
| U-5 | TopRelationsBlock.test.tsx | renders top 10, sorts by weight desc, click → onNodeSelect |
| U-6 | PathInsightsBlock.test.tsx | portfolio filter applied, fallback to generic paths, route arrows |
| U-7 | ContradictionsBlock.test.tsx | toUpperCase severity, unknown severity → LOW, click opens source URL |
| U-8 | NarrativeHistoryDisclosure.test.tsx | collapsed by default, accordion expands, renders version list |
| U-9 | NodePathsBlock.test.tsx | uses selectedNodeId + entityId as path query |
| U-10 | EdgeDetailCard.test.tsx | renders source→target breadcrumb, decay badge colors, evidence snippets, back button |
| U-11 | GraphEvents.test.tsx (edge click) | clicking edge sets selectedEdgeId, clears selectedNodeId |

### 6.2 Playwright e2e

T-24 above (4 tests).

---

## §7. Acceptance criteria

All 33 checks in §1 must pass before merging.

---

## §8. Risk register

| # | Risk | Mitigation |
|---|------|------------|
| R-1 | `GraphToolbar.onDepthChange` not accessible as prop from `GraphColumn` | Pre-flight: read `GraphToolbar.tsx` interface; if depth is internal state, lift it to `GraphColumn` or use a callback ref |
| R-2 | `evidence_snippets` array may be null/undefined on some edges | Null-safe: `(edge.evidence_snippets ?? []).slice(0, 2)` |
| R-3 | `useEntityPaths` target_entity_id filter param may not be supported by S9 | Pre-flight: check intelligence.py `get_entity_paths` for `target_entity_id` param; if missing, NodePathsBlock shows generic paths with a note |
| R-4 | `ContradictionsResponse` type missing from types/api.ts | T-20 adds it if absent |
| R-5 | `qk.kg` migration breaks cached queries in-flight during deploy | Cache keys change → stale data cleared on first load; no functional impact (data refetched) |
| R-6 | grid-cols-14 Tailwind JIT class not generated (purged) | Ensure `IntelligenceTab.tsx` uses the literal `grid-cols-14` class (not dynamic) so JIT scanner picks it up |
| R-7 | S9 EntitySummary may not have description field; S7 graph endpoint may return null description | Pre-flight T-25: check S7 EntitySummary fields; if absent, add description to S7 graph handler batch fetch (1 extra SQL JOIN, manageable) |
| R-8 | `decay_class` may not propagate to S9 RelationResponse output model | Pre-flight T-25: grep RelationResponse Pydantic model in api-gateway for existing fields; add decay_class as Optional[str] |

---

## §9. Files touched (forecast)

**New** (15):
- `news/DenseArticleRow.tsx`
- `graph/GraphStats.tsx`
- `context/EntityOverviewBlock.tsx`
- `context/TopRelationsBlock.tsx`
- `context/PathInsightsBlock.tsx`
- `context/ContradictionsBlock.tsx`
- `context/NarrativeHistoryDisclosure.tsx`
- `context/NodePathsBlock.tsx`
- `context/EdgeDetailCard.tsx`
- `context/__tests__/EdgeDetailCard.test.tsx`
- 8 test files (1 density + 1 e2e + 6 unit)

**Modified** (~11):
- `IntelligenceTab.tsx` (grid-cols-14 + scope push + selectedEdgeId state)
- `services/api-gateway/src/api_gateway/routes/intelligence.py` (B-01, B-02)
- `graph/GraphColumn.tsx` (2 passes — timeout + brief + hotkeys + edge tooltip)
- `context/ContextPanel.tsx` (5-block refactor)
- `news/NewsColumn.tsx` (DenseArticleRow + j/k nav)
- `lib/query/keys.ts` (+qk.kg)
- `lib/api/intelligence.ts` (iqk→qk.kg migration)
- `context/NodeDetailCard.tsx` (ad-hoc key → qk.kg.entityDetail)
- `lib/api/knowledge-graph.ts` (+getEntityContradictions, +getNarratives if missing)
- `tailwind.config.ts` (+grid-cols-14)
- `types/api.ts` (+ContradictionsResponse if missing)

**Net LOC**: ~+1400 / -150.

---

## §10. Estimation

| Block | Days |
|-------|------|
| Block A — Query keys + tailwind (T-01/02/03) | 0.25 |
| Block B — DenseArticleRow (T-04/05) | 0.5 |
| Block C — Graph column (T-06/07) | 0.75 |
| Block D — Right rail blocks (T-08..14) | 2.0 |
| Block E — ContextPanel + IntelligenceTab + hotkeys (T-15..19) | 1.0 |
| Block F — Gateway + types (T-20/21) | 0.25 |
| Block G/H — Tests (T-22..24) | 0.75 |
| Block I — Backend + EdgeDetailCard (T-25/26/27) | 1.0 |
| Validation + QA + deploy | 0.25 |
| **Total serial** | **6.75** |

---

## §11. Definition of Done

1. All 33 acceptance checks in §1 pass.
2. 9 Vitest unit tests + 4 e2e tests pass.
3. `pnpm --filter worldview-web typecheck` + `lint` zero errors.
4. Container `worldview-web` rebuilt and healthy.
5. Live walk-through `/instruments/AAPL` → Intelligence tab confirms: 30+ news rows, 5 right-rail blocks all populated, graph stats strip visible, brief rendered via StructuredBrief (not blob), node click shows real description, edge click shows EdgeDetailCard with evidence sentences and decay badge, node hover shows description + sector.
6. Memory updated: W7 complete.
7. Commit log: ~24 commits, one per T-NN sub-step.
