# Cluster 6 — Knowledge Graph Visualization & Intelligence Tab Behavior

**Status**: design only — no implementation
**Owner**: agent-graph-intelligence
**Date**: 2026-05-19
**Parent**: `docs/specs/0089-platform-page-redesign.md`
**Sibling design**: `docs/designs/0089/07-instrument-intelligence.md` (layout-level decisions; this doc handles cross-cutting OQs)
**Backend ref**: `services/knowledge-graph/src/knowledge_graph/` (S7)
**Frontend refs**:
- `apps/worldview-web/components/instrument/EntityGraph.tsx`
- `apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx`
- `apps/worldview-web/lib/api/knowledge-graph.ts`

---

## 1. Cluster summary

The Intelligence tab today surfaces ~5 % of the data S7 produces. Path insights, contradictions, narrative history, and structured-brief sections are all backend-ready but not rendered. The graph itself defaults to depth 2 with a single hardcoded 3 s timeout which makes depth 3 functionally unreachable on cold cache. This cluster pins down **eight open questions** that block the Intelligence tab redesign and **two master-PRD OQs** (D14, D21) that touch shell-wide behavior.

Headline decisions:

1. **Default graph depth = 2** — same as today. Depth 1 is too shallow to motivate the graph viewer; depth 3 is too slow to be a default.
2. **Depth-adaptive timeouts**: 1500 / 4000 / 8000 ms. Existing fixed 3 s kills depth-3 and over-allocates for depth-1.
3. **Performance ceiling**: backend `limit` already scales by depth (15/40/80/120/160). We add a server-side `max_neighbors_per_node` cap and a pre-computed `entity_graph_snapshot` table to keep AAPL-scale entities renderable.
4. **Path insights = visible by default** (top 3 in right rail). Hiding behind a click contradicts the whole point of shipping pre-computed paths.
5. **Contradictions = severity badge derived from `strength = min(c_a, c_b)`** bucketed at 0.75 / 0.55 thresholds. Banner promotion only at strength ≥ 0.85 AND polarity diff ≥ 0.7 (rare; high-signal).
6. **Narrative history = collapsed disclosure** ("3 prior versions") expanding inline; no version diff in v1.
7. **Node selection = sticky within instrument route only**. Cleared on entity change; not sticky across the Quote ↔ Intelligence tab toggle in v1 (re-evaluate in v1.1).
8. **WS dot = single global, in StatusBar, fires only on sustained drops > 5 s** (per OQ-D14 default). Live-quote freshness is rendered per surface via the existing `LiveQuoteBadge`, NOT through the shell dot.
9. **Visual path highlight on the graph = deferred to v1.1**. Ship list-based path insights in v1; add canvas overlay only after the path computation worker stabilizes.

---

## 2. Per-OQ deep dive

### OQ-2.1 — `07-intelligence` OQ#1 — Path-to-portfolio filtering

**Question**: `/v1/entities/{id}/paths` does not filter by user holdings. Where do we filter?

**Options**:
- (a) Ship without portfolio filtering. Show top-3 generic paths.
- (b) Post-filter on the client: fetch holdings, then intersect with `path.path_nodes[-1].entity_id`.
- (c) Backend extension: accept `target_entity_ids[]` query param on `/paths`.

**Discussion**: The page MUST surface "AAPL → ANTH → my-portfolio-name" as a thesis-relevant insight, but the path computation worker stores generic anchor paths (`PathInsightRepository.list_by_anchor`), not user-targeted ones. Client-side filtering is the cheapest path to value: holdings are already cached (`qk.portfolio_holdings`); the intersection is O(paths × holdings) ≤ 50 × 100 = 5000 comparisons. For 90 % of analysts this returns 0–3 hits — exactly what the right rail can show.

Backend extension (option c) is correct long-term: with 10 holdings and `max_hops=3`, the database can prune millions of irrelevant paths at the source. But it requires a new index (`(anchor_entity_id, terminal_entity_id, composite_score)`) and a query-planner change in `PathInsightRepository`. Not feasible in this redesign cycle.

**Decision**: ship (b) in v1. Open backend ticket for (c) in v1.1 (see §6 Backend Additions).

### OQ-2.2 — `07-intelligence` OQ#2 — Narrative history drawer

**Question**: Does shadcn `Accordion` suffice, or do we need a custom inline drawer?

**Discussion**: `Accordion` is a Radix wrapper with 6 ARIA attributes pre-wired and 120 LOC of keyboard handling we'd otherwise rebuild. Narrative versions are short (~200 chars each) and rarely viewed; the only feature we need is a click-to-expand row with a chevron. shadcn already handles trigger styling and animation override (we'd kill animation per `R-PLAN-0028`).

**Decision**: use `components/ui/accordion` with `defaultValue=""` (collapsed) and `[data-state=open]:animate-none` to suppress motion. No diff view in v1 — just version timestamp + LLM model + the full narrative_text body. v1.1 may add a `<ins>/<del>` diff via `diff-match-patch` (1.4 KB).

### OQ-2.3 — `07-intelligence` OQ#3 — Hotkey collision (`j`/`k`)

**Question**: News-row `j`/`k` collides with the global watchlist navigator from `01-global-shell.md`.

**Discussion**: Bloomberg convention is that the focused pane "wins" — when the news rail has focus (last-clicked / `Tab` highlighted), `j`/`k` navigates rows; otherwise it navigates the watchlist. Implementing a focus-scoped registry requires changes to `hooks/useHotkeys`. The simpler fix is namespacing: `n j` / `n k` for news. Bloomberg power users routinely chain a function key (e.g. `News1 GO`) so a 2-keystroke pattern is acceptable.

**Decision**: scope news-row navigation under `n j` / `n k` for v1. Re-evaluate focus-scoped hotkeys in v1.1 once `01-global-shell.md` solidifies the navigator.

### OQ-2.4 — `07-intelligence` OQ#4 — AGE depth=3 materialization

**Question**: 8 s timeout for depth=3 is generous but not sustainable.

**Discussion**: `cypher_neighborhood.py` already has a `_STATEMENT_TIMEOUT_MS = 20_000` server-side bound. The real fix is materialization: pre-compute 3-hop neighborhoods for the top-1000 entities (by news mentions) into a `entity_graph_snapshot(anchor_entity_id, depth, nodes_json, edges_json, computed_at)` table refreshed nightly. The KG scheduler already runs nightly; adding a `GraphSnapshotWorker` is ~200 LOC. Hot-cache hit drops depth=3 latency to a SELECT-by-PK lookup (~50 ms).

**Decision**: out of scope for this design doc. Open backend ticket (see §6 — KG-SNAP-01). Frontend keeps the 8 s timeout + "Try depth 2" fallback in the interim.

### OQ-2.5 — `07-intelligence` OQ#5 — Contradiction severity enum

**Question**: `00-backend-data-inventory.md` mentions `severity` but no sample. Confirm enum values.

**Discussion**: S7's `ContradictionData` exposes `strength: float` (0–1), NOT a categorical severity. The frontend must derive the badge category from `strength`. Today S9 forwards `strength` unchanged; PLAN-0090 spec line in `00-backend-data-inventory.md` §1.4 calls it `severity` only as a UI label, not a backend field.

`strength = min(new_claim_confidence, opposing_claim_confidence)` per `application/blocks/contradiction.py` line 131. Bounded 0–1 by extraction-confidence ceiling.

**Decision**: derive client-side using the rubric in §4 below. Backend continues to expose `strength: float`. Optionally, S9 can compute `severity: "high"|"medium"|"low"` server-side as a derived field to centralize the mapping — see §6 (S9-CONTRA-01).

### OQ-2.6 — `07-intelligence` OQ#6 — Regenerate-brief endpoint

**Question**: Is there `POST /v1/briefings/instrument/{id}/regenerate`?

**Discussion**: `00-backend-data-inventory.md` §1.5 lists only `GET /v1/briefings/instrument/{entity_id}`. The brief is computed by rag-chat on cache miss and TTL'd at 30 s on the API gateway. `POST .../regenerate` would need a rate-limit (per OQ-D13 default: 10/hr/user). Cost: ~$0.02 per regen (DeepSeek R1 Distill 32B via DeepInfra). Total cap if 100 users × 10/hr × 24h = 24 000 regens = $480/day — overkill for an MVP.

**Decision**: v1 — `r` hotkey simply calls `queryClient.invalidateQueries(qk.instruments.brief(entityId))`. The next access either re-fetches the cached brief (no LLM cost) or triggers fresh generation on cold cache. v1.1 — add explicit `POST .../regenerate` with rate-limit if analysts request it.

### OQ-2.7 — `07-intelligence` OQ#7 — Telemetry shape

**Question**: Confirm `analytics.track` signature.

**Discussion**: `apps/worldview-web/lib/telemetry.ts` already exposes `track(event: string, props: Record<string, unknown>)`. The redesign emits at most 5 new events: `graph.fetch`, `graph.node.selected`, `path.viewed`, `contradiction.opened`, `narrative.version.expanded`. All match the existing shape.

**Decision**: no change to telemetry layer. PRD-0089 codifies the canonical key set as a follow-up doc.

### OQ-2.8 — `07-intelligence` OQ#8 — Workspace pin for paths

**Question**: Pinning a path to a workspace note requires a new endpoint.

**Decision**: out of scope. Recorded in `09-workspace-predictions-alerts.md` for follow-up.

### OQ-2.9 — Master PRD OQ-D21 — Default GraphColumn depth

**Question**: Default depth 1 or 2?

**Discussion**:

| Default | Pro | Con |
|---------|-----|-----|
| 1 | < 600 ms cold cache; no AGE; "instant" feel; matches sidebar SVG | shallow — only direct neighbors; defeats the purpose of the dedicated graph viewer |
| 2 | < 1500 ms cold; 40 nodes default; reveals 2-hop reasoning ("Anthropic → invests in → AI-chip-research") | 50–500 ms slower; clutter on dense entities |
| 3 | research-grade exploration | 2–8 s cold; default would frustrate 95 % of users |

Competitor reference points:

- **Bloomberg Industry Dashboard**: default = direct peers + 1 hop (effectively depth 2 with a curated peer set). Bloomberg precomputes the peer graph hourly.
- **Refinitiv Knowledge Map**: default depth 2 with ~50 visible nodes; aggressive force layout.
- **Kensho Event Studies**: starts at depth 1 (single hop) but auto-expands when the user pans toward a peripheral node — adaptive.
- **TradingView**: no native KG viewer; "Connections" widget shows 8–12 supplier/customer entities flat (depth 1, curated).

For worldview, depth 2 dominates: our graphs are sparse outside the top-100 entities (median = 4 neighbors at depth 1, 18 at depth 2), and the right rail's TOP RELATIONS block already covers the depth-1 use case textually.

**Decision**: default = **2** (preserved from PLAN-0090). The GraphToolbar exposes depth 1/2/3 buttons. Hotkeys `1`/`2`/`3` set depth.

### OQ-2.10 — Master PRD OQ-D14 — WS connection dot semantics

**Question**: Show every disconnect or only sustained drops > 5 s?

**Discussion**: WebSocket disconnects are common and mostly invisible (TCP reset, NAT timeout, laptop sleep). Showing every disconnect generates panic and trains users to ignore the dot. The signal of value is **sustained loss of real-time data**, which is what an analyst actually cares about.

Two distinct freshness signals exist:
- **Live-quote freshness** (per-instrument): "Is this price stale because the WS feed dropped, or because the market is closed?" — handled per-surface by `LiveQuoteBadge` (already shipped). 4 states: LIVE / DELAYED / STALE / N/A.
- **Entity-update freshness** (system-wide): "Are we receiving KG enrichment updates / alert pushes?" — answered by a single global dot.

Conflating them in one shell dot is wrong: an analyst staring at MSFT during a market holiday will see a "STALE" badge on the quote but a green WS dot in the shell (because alerts still flow). That's correct.

**Decision** (matches default in PRD): **Single global WS dot in StatusBar. Green = connected ≥ 5 s. Amber = disconnect within last 5 s (transient — most reconnects happen here). Red = sustained drop > 5 s with retry-loop active. Hidden when no WS subscriptions are mounted (e.g. landing / login).** Per-surface freshness stays on `LiveQuoteBadge`.

---

## 3. Performance budget per depth

| Depth | Cold-cache backend p50 | Cold-cache backend p95 | Client timeout | Node-count target | Hard cap (S7 `limit`) |
|-------|-----------------------|-----------------------|----------------|-------------------|----------------------|
| 1 | 200 ms | 600 ms | 1500 ms | ≤ 15 | 15 |
| 2 | 700 ms | 1500 ms | 4000 ms | ≤ 40 | 40 |
| 3 | 2.0 s | 6.0 s | 8000 ms | ≤ 80 | 80 |
| 4 | 5.0 s | 12.0 s | (disabled in v1) | ≤ 120 | 120 |
| 5 | 8.0 s | 20.0 s | (disabled in v1) | ≤ 160 | 160 |

**Rendering budget** (frontend, sigma.js / WebGL):

| Visible nodes | Layout iterations | Time to first paint | Notes |
|--------------|--------------------|----------------------|-------|
| ≤ 40 | 100 | < 200 ms | default depth-2; no auto-prune |
| 41–80 | 150 | < 500 ms | depth-3; auto-apply 30 % edge-strength floor (already implemented `DENSE_GRAPH_EDGE_THRESHOLD = 50`) |
| 81–200 | (n/a) | (n/a) | depth-3 with `top_neighbors_per_node` cap kicks in (§4 Backend Additions); never visible in v1 |
| > 200 | force-layout collapses to hairball | reject | backend `limit` already caps at 200 in S9 |

**Source-of-truth metrics to emit on every fetch**:
- `graph.fetch`: `{depth, latency_ms, node_count, edge_count, source: "live" | "snapshot"}`
- `graph.render.frame`: `{node_count, fps_p95}` once per second while interactive
- `graph.timeout`: `{depth, timeout_ms, elapsed_ms}` on abort

Frontend SLOs (per redesign):
- Depth-1 cold p95 < 1500 ms
- Depth-2 cold p95 < 4000 ms
- Depth-3 cold p95 < 8000 ms (relaxed; tracked but not user-facing as a failure if `snapshot` available)

---

## 4. Contradiction severity rubric

Backend exposes `strength: float ∈ [0,1]` per `ContradictionData.strength`. Frontend derives badge category:

| Bucket | `strength` range | Visual | Action |
|--------|------------------|--------|--------|
| **HIGH** | ≥ 0.75 | `bg-negative/15 text-negative` badge; left-edge 2 px stripe on card | Always visible in right rail; PROMOTE to brief banner when ALSO `polarity_delta ≥ 0.7` (both sides confident, opposite polarity) |
| **MEDIUM** | 0.55 – 0.74 | `bg-warning/15 text-warning` badge | Visible in right rail |
| **LOW** | < 0.55 | `bg-muted text-muted-foreground` badge | Hidden by default; surfaced when user expands the block ("Show low-severity (n)") |

`polarity_delta` for banner promotion:

```ts
// ContradictionData.sides is [side_a, side_b]
const polarityDelta = Math.abs(
  (sides[0].polarity === "positive" ? sides[0].confidence : -sides[0].confidence) -
  (sides[1].polarity === "positive" ? sides[1].confidence : -sides[1].confidence)
);
// banner-eligible: strength >= 0.85 && polarityDelta >= 0.7
```

**Banner placement** (the rare promote-to-banner case):
- Above the brief, inside `GraphColumn`. 28 px tall. `bg-negative/8 border-y border-negative/30`.
- Copy: `"CONTRADICTION (HIGH) · BBG says positive · Reuters says negative · 14:32 UTC · [view]"`.
- Click → scroll to + flash the contradiction card in the right rail.
- Dismissible (closes for the session; never permanently).

**Why the dual threshold**: `strength` alone can be high when both claims are highly confident but talk about the SAME polarity (e.g. both positive but at different magnitudes — not really a contradiction). Requiring `polarity_delta` ensures the banner truly indicates a dissenting view. This matches Bloomberg's "discordant analyst note" surfacing pattern (only when analyst ratings flip, not when target prices drift).

---

## 5. Recommended decisions table

| Decision ID | Topic | Recommendation | Rationale |
|-------------|-------|----------------|-----------|
| **C6-D01** | Default graph depth | **2** | Matches PLAN-0090; depth 1 too shallow, depth 3 too slow |
| **C6-D02** | Graph timeout | **Depth-adaptive: 1500 / 4000 / 8000 ms** | Fixed 3 s kills depth-3, over-allocates depth-1; per `project_age_cypher_fix_2026_05_11.md` |
| **C6-D03** | Path-to-portfolio filter | **Client-side intersect in v1; backend `target_entity_ids[]` in v1.1** | Holdings cache is sufficient for 90 % of cases |
| **C6-D04** | Path insights visibility | **Top 3 always visible in right rail; no click required** | Pre-computed paths are useless if hidden |
| **C6-D05** | Visual path highlight on canvas | **Deferred to v1.1; v1 = text-only list** | Backend path-worker stability + sigma.js highlight tooling not ready |
| **C6-D06** | Contradiction severity buckets | **HIGH ≥ 0.75 / MEDIUM 0.55–0.74 / LOW < 0.55** | Derived from `strength = min(c_a, c_b)`; matches three-tone token palette |
| **C6-D07** | Contradiction banner promotion | **Show only when `strength ≥ 0.85` AND `polarity_delta ≥ 0.7`** | Avoids banner fatigue; targets the true dissenting-view case |
| **C6-D08** | Narrative history disclosure | **Collapsed accordion ("3 prior versions"); no diff in v1** | Versions are short; users rarely revisit; v1.1 may add diff |
| **C6-D09** | Node selection stickiness | **Sticky within Intelligence tab; cleared on entity change OR tab change (Quote ↔ Intelligence)** | Tab switch implies context switch; v1.1 may persist across tabs via URL hash |
| **C6-D10** | NodeDetailCard description | **Lazy `getEntityDetail()` on node click; 30 min `staleTime`** | Replaces "No description available." placeholder; minimal cost |
| **C6-D11** | Graph stats strip | **Always rendered above toolbar: `n nodes · m edges · depth d · t ms`** | Analyst context; informs depth-switch decision |
| **C6-D12** | Right rail empty state | **Always populated (overview + relations + paths + contradictions + history)** | Right rail represents 25 % of pixels; blank is worst-case UX |
| **C6-D13** | Regenerate-brief hotkey (`r`) | **v1 = invalidate cache (no LLM call); v1.1 = `POST .../regenerate` with 10/hr cap** | Cost containment until usage telemetry justifies |
| **C6-D14** | WS connection dot scope | **Single global in StatusBar; sustained drop > 5 s only** | Per-surface live-quote freshness stays on `LiveQuoteBadge` |
| **C6-D15** | WS connection dot states | **Hidden (no subs) / Green (≥ 5 s) / Amber (transient) / Red (sustained > 5 s)** | Matches OQ-D14 default; minimal cognitive overhead |
| **C6-D16** | Top-N relations rendering | **10 in right rail; sort by `edge.weight` desc; click → node-detail mode** | Bloomberg-style flat list; 18 px row × 10 = 180 px budget |
| **C6-D17** | Edge `evidence_snippets` surface | **Hover-only on canvas (`EdgeTooltipPanel`); top 2 snippets** | Already on payload; no extra round-trip |
| **C6-D18** | Type-filter group-by-relation toggle (Koyfin-style) | **Out of scope for v1; record in v1.1 backlog** | Adds menu state; the `selectedEntityTypes` filter already covers the common case |

---

## 6. Backend additions / changes required

All additions are **optional for v1 launch** unless marked `[BLOCKING]`. The frontend can ship the redesign with current S7 capabilities, but performance and richness improve once these land.

### 6.1 S7 — Path-to-portfolio filtering (KG-PATH-01)

**Endpoint extension**: `GET /v1/entities/{id}/paths` accepts repeated `target_entity_id` query param.

```http
GET /v1/entities/{id}/paths?target_entity_id=...&target_entity_id=...&limit=10
```

**Effect**: filter `path_insights` rows where `terminal_entity_id IN (target_entity_ids)`.

**Index required**: `CREATE INDEX path_insights_terminal_idx ON path_insights (anchor_entity_id, terminal_entity_id, composite_score DESC);`

**Migration owner**: `intelligence-migrations` repo.
**Estimated effort**: 1 engineer-day.
**Priority**: v1.1 (not blocking redesign launch).

### 6.2 S7 — Graph snapshot table (KG-SNAP-01)

**New table**: `entity_graph_snapshot(anchor_entity_id UUID PK, depth INT PK, nodes JSONB, edges JSONB, node_count INT, edge_count INT, computed_at TIMESTAMPTZ)`.

**Worker**: `GraphSnapshotWorker` runs nightly. Picks top-N entities by `news_mention_count` (24h) and computes 3-hop neighborhoods, writing JSONB. Read path: `CypherNeighborhoodUseCase` checks snapshot first; falls back to live AGE traversal on miss.

**Effect**: depth=3 hot-cache latency drops from 2–8 s to ~50 ms.

**Estimated effort**: 3 engineer-days (worker + use-case branch + tests).
**Priority**: v1.1.

### 6.3 S7 — Max neighbors per node (KG-LIMIT-01)

**Endpoint extension**: `GET /v1/entities/{id}/graph?max_neighbors_per_node=N` (default 20).

**Effect**: in `RelationRepository.list_for_entity`, post-process neighbors to keep top-N by `relation_strength` per node. Prevents AAPL-scale explosion at depth 2–3.

**Estimated effort**: 0.5 engineer-day.
**Priority**: v1 (avoids 200+ node payloads that lock up sigma.js).

### 6.4 S9 — Derived `severity` on contradictions (S9-CONTRA-01)

**Endpoint extension**: `GET /v1/entities/{id}/contradictions` response items gain `severity: "high"|"medium"|"low"` and `polarity_delta: float`.

**Mapping**: as defined in §4. Computed in S9's `KnowledgeGraphProxy` to centralize the rubric.

**Why server-side**: keeps the bucket boundaries in one place; multiple frontends (potential v1.1 mobile / desktop terminal) get consistent labels.

**Estimated effort**: 0.25 engineer-day.
**Priority**: v1 (avoids hard-coding the rubric in TS).

### 6.5 S9 — Brief regeneration endpoint (S9-BRIEF-01)

**New endpoint**: `POST /v1/briefings/instrument/{entity_id}/regenerate` → `{status, cooldown_remaining_sec}`. Rate-limited 10/hr/user via Valkey.

**Estimated effort**: 1 engineer-day.
**Priority**: v1.1.

### 6.6 [BLOCKING] S7 — `path_insights.terminal_entity_id` column

Currently `PathInsightRow` carries `path_nodes` as a list of dataclasses; the terminal is `path_nodes[-1].entity_id` extracted at query time. For (6.1) to be efficient we need a materialized `terminal_entity_id` column populated by the path worker. **Blocking** for KG-PATH-01 but NOT for v1 (client-side filter works).

---

## 7. Follow-up OQs

These surfaced during this investigation and need a decision before implementation, but are not blocking the redesign spec:

| Follow-up | Question | Owner | Suggested default |
|-----------|----------|-------|-------------------|
| **FU-6.1** | Should `r` hotkey work both on the Quote AiBriefBanner AND the Intelligence brief, or only Intelligence? | agent-instr-quote + agent-instr-intelligence | Both — same brief object |
| **FU-6.2** | When the user toggles depth 1 → 3, should we cancel the in-flight depth-1 request? | agent-instr-intelligence | Yes — TanStack `queryClient.cancelQueries` |
| **FU-6.3** | If `getEntityDetail(node_id)` 404s for a node visible on the graph, what do we render? | agent-instr-intelligence | Italic "Description unavailable" + show node type only |
| **FU-6.4** | Should top-relation row clicks scroll the graph canvas to center on the target node? | agent-instr-intelligence | Yes — calls `centerEntityId` prop; existing sigma.js camera tween |
| **FU-6.5** | Is the contradiction banner one-per-page or one-per-entity (could change if user pivots via path-click)? | agent-instr-intelligence | One-per-entity; resets on entity change |
| **FU-6.6** | Should narrative-history rows show the LLM model that generated each version? | agent-instr-intelligence | Yes — already on payload (`llm_model`), 9 px mono right-aligned |
| **FU-6.7** | When `paths` endpoint returns `explanation_pending: true`, do we poll or rely on a subsequent fetch? | agent-instr-intelligence | Single poll at +3 s; if still pending render "Explanation generating…" italic and stop polling |
| **FU-6.8** | What happens to the right rail's overview block when the user is on a non-instrument entity (e.g. a Person)? | agent-instr-intelligence | Replace `key_metrics` with person-specific fields (`title`, `current_org`, `notable_roles`); fallback empty strip if absent |
| **FU-6.9** | Should the GraphStats strip surface `source: live|snapshot` once KG-SNAP-01 lands? | agent-instr-intelligence | Yes — append "· snapshot 04:00 UTC" when served from snapshot |
| **FU-6.10** | If two contradictions tie at `severity=HIGH`, which goes in the banner? | agent-instr-intelligence | Highest `strength`, then most recent `detected_at`. Never more than one. |
| **FU-6.11** | Sticky node-selection across tab switches — confirm v1.1 mechanism (URL hash vs. tab-store)? | agent-global-shell + agent-instr-intelligence | URL hash `#node=<entity_id>` — survives reload and is shareable |
| **FU-6.12** | WS dot — should "red" trigger a toast as well, or stay silent? | agent-global-shell | Toast only at red transition + every 30 s while red; never in green/amber |

---

## 8. Mapping to existing spec lines

| This doc | `07-instrument-intelligence.md` | `0089-platform-page-redesign.md` |
|----------|-----------------------------------|-----------------------------------|
| §2.1 path-to-portfolio | §10 OQ-1 | — |
| §2.2 narrative drawer | §10 OQ-2 | — |
| §2.3 hotkey collision | §10 OQ-3 | OQ-D18 (sibling) |
| §2.4 AGE materialization | §10 OQ-4 | — (new backend ticket) |
| §2.5 severity enum | §10 OQ-5 | §3 backend inventory line 105 |
| §2.6 regenerate brief | §10 OQ-6 | OQ-D13 |
| §2.7 telemetry | §10 OQ-7 | — |
| §2.8 workspace pin | §10 OQ-8 | (deferred to `09-workspace-…`) |
| §2.9 default depth | §9 Decision 4 (timeout) — adjacent | **OQ-D21** |
| §2.10 WS dot | — | **OQ-D14** |

---

## 9. Implementation hand-off checklist (informational)

When this cluster is merged into Wave E of PLAN-0028 implementation:

- [ ] `GRAPH_TIMEOUT_MS` in `GraphColumn.tsx` becomes `GRAPH_TIMEOUT_MS_BY_DEPTH: Record<number, number>` per C6-D02
- [ ] `severity` derivation lives in `lib/api/knowledge-graph.ts` until S9-CONTRA-01 lands; then frontend reads `severity` from response
- [ ] `polarity_delta` is computed client-side until S9-CONTRA-01
- [ ] `ContradictionsBlock` renders banner-promotion logic and dismissible state
- [ ] `PathInsightsBlock` post-filters by holdings (queryKey `qk.portfolio_holdings`); also renders generic top-3 as fallback when intersection = 0
- [ ] `NarrativeHistoryDisclosure` uses `Accordion`; rows render `version_id, generated_at, llm_model, narrative_text` (full body in expanded panel)
- [ ] `GraphStats` (new component) renders `node_count · edge_count · depth · latency_ms` from `useRef<number>` timing + payload counts
- [ ] `NodeDetailCard` adds `useQuery(qk.kg.entityDetail(node.id))` per C6-D10
- [ ] Telemetry events from §3 wired through `lib/telemetry.ts`
- [ ] StatusBar `WSConnectionDot` (in `01-global-shell.md` scope) implements 4-state machine from C6-D15
