# Intelligence Tab — Layout & Information-Design Audit (2026-06-23)

READ-ONLY assessment. No code changed. Scope: instrument Intelligence tab layout +
information coverage + entity-click detail. (KG filter bug is a sibling investigation —
out of scope here.)

Entry point: `apps/worldview-web/app/(app)/instruments/[ticker]/page.tsx`
→ `components/instrument/intelligence/IntelligenceTab.tsx`.

## 1. Current layout map

Three-zone investigation grid (`grid-cols-14`), `IntelligenceTab.tsx:136`:

| Zone | cols | File | Renders |
|------|------|------|---------|
| LEFT dossier | 3 (~21%) | `dossier/EntityDossier.tsx` | Identity (name/type/health badge), ticker·exchange, alias chips (cap 6), description (clamp-5 + scroll-on-expand), `enriched_at`, Discuss btn, **AI Brief** (StructuredBrief), **Top Relations** (≤8, click→edge inspector, dir glyph + type + counterpart + confidence), **Related Entities** chips (`RelatedEntitiesPanel`) |
| CENTRE top | 7 (~50%), flex-[3] | `graph/GraphColumn.tsx` + `GraphStats.tsx` | Sigma KG canvas + toolbar; stats strip = `N nodes · N edges · depth · latency` |
| CENTRE bottom | 7, flex-[2] | `detail/SelectionDetailPanel.tsx` | Selection inspector (node / edge / empty) — see §3 |
| RIGHT top | 4 (~29%), flex-1 | `news/NewsColumn.tsx` | Infinite-scroll article rows + time/sentiment filters |
| RIGHT bottom | 4, flex-1 scroll | `events/EventsBlock.tsx`, `context/ContradictionsBlock.tsx`, `context/NarrativeHistoryDisclosure.tsx` | Temporal events (type·title·lifecycle·date), contradictions (≤5), narrative history (collapsed accordion) |
| BOTTOM | full | `EntityChatPanel` (reuse) | Entity-scoped chat strip, collapsed by default |

Entity-click flow (`SelectionDetailPanel.tsx:62`): node→`NodeInspector`, edge→`EdgeInspector`,
none→named empty. Esc / X clears. Endpoint pills + top-relation rows let the analyst "walk"
the graph without leaving the inspector.

This is a recent, well-built rework (PLAN-0099 Wave 2). The layout is genuinely
finance-grade: dense 18–22px rhythm, accent-bar section headers, per-section error/empty
states, keyboard reachability.

## 2. GAP 1 — Layout / information coverage

The grid uses the screen well and the *primary* KG data is present. But three S9
intelligence products that the platform already computes (and in two cases already
**prefetches into cache on this very tab**) are NOT rendered:

### 2a. PATH-INSIGHTS — prefetched then discarded (MUST-FIX, highest leverage)
- `useEntityIntelligenceBundle` (fired on tab mount, `IntelligenceTab.tsx:95`) fetches the
  composite bundle whose `paths` leg is hydrated into `["entity-paths", entityId, {}]`
  (`useEntityIntelligenceBundle.ts:120-122`).
- **Nothing in the instrument IntelligenceTab reads that cache.** `PathInsightsBlock.tsx`
  exists and is wired to `useEntityPaths`, but its only importers are the bundle-hydrator
  comment, itself, and `components/intelligence/WeirdnessBreakdown.tsx` (the *separate*
  standalone `/intelligence/[entity_id]` page). The doc header even says "WHO USES IT:
  ContextPanel … entity-overview mode" — a surface that was **retired** in this rework.
- Net effect: we pay the network cost for multi-hop opportunity paths
  (`GET /v1/entities/{id}/paths`, the "Apple → TSMC → ASML" indirect-connection product —
  a headline differentiator per the memory/thesis) and show the analyst nothing.
- Recommendation: render `PathInsightsBlock` in the RIGHT rail (between Events and
  Contradictions, or as its own section). Zero new fetch — the cache is already warm.

### 2b. INTELLIGENCE AGGREGATE (key_metrics / confidence_breakdown / narrative) — orphaned
- `GET /v1/entities/{id}/intelligence` returns `health_score, narrative, confidence_breakdown,
  key_metrics`. The bundle hydrates it into `["entity-intelligence", entityId]`
  (`useEntityIntelligenceBundle.ts:126`).
- In the instrument tab, only `health_score` is consumed (dossier fallback badge,
  `EntityDossier.tsx:138/213`). `key_metrics`, `confidence_breakdown`, and the aggregate
  `narrative` are never shown.
- `context/EntityOverviewBlock.tsx` (which renders these) is **fully orphaned — no non-test
  importer.** The richer companions (`KeyMetricsGrid`, `ConfidenceTrendSparkline`,
  `SourceDistributionList`) live only under the standalone `/intelligence` page tree.
- Recommendation (enhancement): surface `confidence_breakdown` (the "why should I trust this
  KG view" signal — support/corroboration/contradiction split) somewhere on the tab, e.g. a
  compact strip near GraphStats or in the dossier. `key_metrics` is the lower-value of the two.

### 2c. PAIRWISE PATHFINDING ("is A connected to B?") — not offered here
- `GET /v1/paths/between` powers `PathBetweenPanel`, used ONLY on the standalone
  `/intelligence/[entity_id]` page. The instrument analyst cannot ask "how is THIS instrument
  connected to <other entity>" from the instrument page.
- Recommendation (enhancement): optional — this may be intentionally reserved for the
  dedicated intelligence explorer. Flag as a possible cross-link ("Open in graph explorer").

### 2d. Density / layout weaknesses (minor)
- The CENTRE column splits graph 60% / inspector 40% always; with no selection the inspector
  is a large named-empty placeholder eating ~40% of the best real estate. Consider collapsing
  the inspector (or shrinking to a thin strip) until a selection exists, giving the canvas
  more room by default.
- RIGHT rail bottom stacks Events + Contradictions + Narrative in one shared scroll; a busy
  entity can bury Contradictions/Narrative below a long Events list. Acceptable, but the
  Path-Insights addition (2a) will worsen it — consider light section caps or a tab/segment.
- GraphStats shows count/latency only; no legend of node-type colours inline (a legend exists
  in `graph/GraphLegend.tsx` — verify it is mounted; not referenced from IntelligenceTab).

## 3. GAP 2 — Entity-click detail (the "thin node panel" concern)

**The old "thin node panel" bug is FIXED.** `NodeInspector.tsx` does call the rich
per-entity endpoint and renders far more than the legacy label/type/weight card.

On node click (`NodeInspector.tsx:97`): fetches `GET /v1/entities/{id}` via
`getEntityDetail(nodeId)` keyed `["entity-detail", nodeId]` (same key the bundle pre-warms,
so the root node is instant; neighbours fetch once). Renders:
- name + normalised type chip + **health badge**
- actions: Open instrument (ticker nodes), Focus graph here, Discuss
- **description** (news-grounded, with zero-latency `graphNode.description` first paint)
- **alias chips** (≤6)
- node weight / ticker / `enriched_at`
- **Top relations** (≤6) with direction glyph, type, counterpart, confidence, **and the LLM
  relation_summary inline** — each row click opens the full edge dossier.

On edge click (`EdgeInspector.tsx`): fetches `GET /v1/relations/{id}` and renders the full
relation dossier — SUBJECT→TYPE→OBJECT, semantic_mode/decay_class/period/source chips,
confidence bar + STALE flag, temporal validity (valid_from→valid_to), contradiction stats,
LLM summary + provenance, and up to 25 **evidence rows** each with the raw `evidence_text`
chunk, polarity dot, source, date, extraction confidence, trust weight, and a client-resolved
article title/url (`GET /v1/articles/{document_id}`). This is genuinely deep — arguably the
strongest panel on the tab.

So GAP 2 is mostly already solved. Residual gaps on **node** click:
1. **No per-entity recent news inside the node inspector.** The right-rail NewsColumn is
   always scoped to the *root* instrument, never the clicked node. When the analyst clicks a
   neighbour (e.g. a supplier), there is no "recent news about THIS entity" — yet
   `GET /v1/entities/{id}/articles` exists and is exactly that. Recommendation (enhancement):
   add a small "Recent news" list to `NodeInspector` for non-root nodes (or repoint NewsColumn
   to the selected node when one is selected).
2. **No per-entity events/contradictions in the node inspector.** Same asymmetry: Events and
   Contradictions in the right rail are root-scoped. The richest "why is this node connected
   and what's happening to it" answer would combine its top-relations (have) + its recent news
   (missing) + its events (missing).
3. Health badge has no breakdown on hover beyond the title string; confidence_breakdown could
   enrich it.

## 4. Prioritised recommendations

### MUST-FIX
1. **Render Path-Insights on the instrument Intelligence tab.** The data is already fetched
   and cached by the on-mount bundle and then thrown away (§2a). Mount `PathInsightsBlock` in
   the right rail. Highest value-per-effort change on this tab — surfaces a headline product
   for ~zero cost.

### SHOULD-FIX
2. **Collapse the selection inspector when empty** (§2d) so the graph canvas gets ~40% more
   default height; expand it on selection.
3. **Add per-entity news to the node inspector** (§3.1) via `GET /v1/entities/{id}/articles`,
   so clicking a neighbour answers "what's happening to it", not just "how it links".

### ENHANCEMENT
4. Surface `confidence_breakdown` from the (already-cached) intelligence aggregate (§2b) —
   trust signal for the KG view; `EntityOverviewBlock` already renders it but is orphaned.
5. Per-entity events/contradictions inside the node inspector (§3.2).
6. Optional cross-link to the standalone `/intelligence/[entity_id]` explorer for pairwise
   pathfinding (`/v1/paths/between`) (§2c).

### CLEANUP (not user-facing)
7. `context/EntityOverviewBlock.tsx`, `context/TopRelationsBlock.tsx`,
   `context/RelationsList.tsx` appear orphaned (no non-test importers) post-rework — confirm
   and remove or re-wire to avoid dead-code drift.
