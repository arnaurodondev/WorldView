---
id: PRD-0089-FU-D-graph-chart
title: PRD-0089 Follow-Up Decisions — Cluster 6 (Graph/Intelligence) & Cluster 7 (Chart/Technicals)
status: pending-user-review
created: 2026-05-19
parents:
  - docs/designs/0089/oq/_DECISIONS.md §C (DISCUSS-11, DISCUSS-12 already LOCKED)
  - docs/designs/0089/oq/06-graph-intelligence.md
  - docs/designs/0089/oq/07-chart-technicals-peers.md
---

# Follow-Up Decisions — Graph + Chart

> Locked upstream (user, this session):
> - **DISCUSS-11**: 1Y default chart, viewport resets on timeframe change, NO volume profile re-add in v1.
> - **DISCUSS-12**: Brief banner uses `border-l-2` Bloomberg amber rail (reconciled across OQ-D3 + OQ-D20).
>
> This file resolves the remaining smaller FU questions raised by the cluster
> investigations and by the user-prompt enumeration. Default-accept any row
> unless flagged for pushback.

---

## §1 — Graph + Intelligence (Cluster 6)

| ID | Question | Recommendation | Why / cite |
|----|----------|----------------|------------|
| **FU-6.1** | In-flight request cancellation on depth switch (user clicks depth-3 then depth-2 mid-request) | **Implicit cancel via TanStack query-key change is SUFFICIENT.** `queryKey: qk.instruments.entityGraph(entityId, depth)` includes `depth`, so a depth switch triggers a new query; the prior fetch's `signal` is aborted by TanStack automatically. **Action**: confirm the `signal` from `queryFn({signal})` is forwarded to the gateway `fetch` call (currently the gateway client builds its own `AbortController` and ignores the upstream `signal` — see `GraphColumn.tsx:56-63`). Wire `signal` into `createGateway(...).getEntityGraph(entityId, depth, { signal })`. Cost ~5 LOC in `gateway.ts`. | `apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx:54-67` — local `AbortController` only enforces the 3 s timeout; the TanStack `signal` is currently bridged via `addEventListener` but never propagated to `getEntityGraph`. |
| **FU-6.2** | Node missing description: fetch entity detail on first hover, or eagerly when graph loads? | **First hover, with 200 ms debounce.** Eager fetch for every node = N round-trips on a 200-node graph (worst case ≈400 ms HTTP per node, even with TanStack batching). Lazy on hover keeps initial render fast; debounce avoids storms when the user sweeps the cursor across the canvas. Cache via TanStack so a re-hover is free. **Open knob**: prefetch on `selectedNodeId` change too (clicking a node should fetch its detail immediately, no debounce). | `apps/worldview-web/components/instrument/intelligence/context/RelationsList.tsx:67-72` — `resolveLabel` already falls back to `entityId` when `nodesById` lacks a label; the same fallback path applies to descriptions. Aligns with `06-graph-intelligence.md` FU-6.3 ("Italic 'Description unavailable' + node type only"). |
| **FU-6.3** | Contradiction banner tie-breaking when 2+ contradictions clear `strength≥0.85 AND polarity_delta≥0.7` simultaneously | **Highest `strength` wins; on `strength` tie, most recent `detected_at`; never show more than one in the banner.** Additional contradictions are accessible from the `ContradictionCard` list below the banner — the banner is a single-slot triage signal, not an exhaustive list. | Matches `06-graph-intelligence.md` FU-6.10 verbatim. Implement in `ContradictionCard.tsx`. |
| **FU-6.4** | WS connection drop visual: toast or silent dot-only? | **Dot-only for green ↔ amber transitions; toast on red transition AND every 30 s while red.** Toast spam at amber would fatigue the user during normal Kafka rebalances; red = sustained loss → user must know. Matches `06-graph-intelligence.md` FU-6.12. | Existing global shell pattern. |
| **FU-6.5** | V1.1 URL-hash node stickiness so page refresh preserves selection — confirm v1.1 scope | **Confirmed v1.1.** Mechanism: `#node=<entity_id>` URL hash; on mount, parse hash → `onNodeSelect(hash_value)`; on `onNodeSelect` change, `history.replaceState` (no scroll). Hash also makes the selection shareable in Slack/email. NOT v1: avoids a refactor of the existing `useEffect(() => onNodeSelect(null), [entityId])` reset path. | `GraphColumn.tsx:72` currently resets selection on `entityId` change — v1.1 must distinguish "entity changed" (reset) from "page reloaded with hash" (restore). |
| **FU-6.6** | Path insights label format: minimal ("AAPL → MSFT (1 hop)") or richer ("AAPL supplies MSFT chips · 0.85 confidence")? | **Richer, but only when the data is already present.** `RelationsList.tsx` already renders `source → target`, a `relation_summary` (LLM-generated), and `edge.weight` (confidence) — same shape applies to path-insight rows. Format: `source → target` (row 1, 11 px mono) + `relation_label · weight.toFixed(2)` (row 2, 9 px mono uppercase) + `relation_summary` or "No summary available." (row 3, 11 px relaxed). Fallback to minimal `"hops=N"` only when relation rows are unavailable. | `apps/worldview-web/components/instrument/intelligence/context/RelationsList.tsx:114-180` already implements exactly this 3-row layout; reuse the component for path-insights. No new design needed — pass the path's edges through `RelationsList`. |
| **FU-6.7** | Narrative history default open vs closed (when there are multiple versions)? | **Closed by default; show count chip `History (3)` in header.** The current narrative is the primary signal; older versions are diagnostics. Click expands an accordion. Tier-2 animation (≤200 ms) per DISCUSS-4 — already allowed. | Aligns with `06-graph-intelligence.md` FU-6.6 ("show LLM model right-aligned, 9 px mono") — applies inside the expanded accordion. |
| **FU-6.8** | Graph layout algorithm — ForceAtlas2 default or user-selectable (circular/hierarchical)? | **ForceAtlas2 default; no user-selectable in v1.** Reasons: (1) ForceAtlas2 handles all our entity shapes (suppliers, peers, holders) acceptably; (2) per-user layout state = new persistence path with no clear demand; (3) circular/hierarchical are useful only for narrow tree-like data (board, supply chain) that v1 doesn't expose distinctly. **V1.1 candidate**: per-relation-type layout hint (e.g. employment edges → hierarchical sub-cluster) — needs PRD. | `apps/worldview-web/components/instrument/EntityGraph.tsx` uses sigma.js; ForceAtlas2 is the default sigma layout. |
| **FU-6.9** | Graph performance test fixture size: which Ns should the Playwright test assert? | **Assert at 200, 500, 1000 nodes.** 200 = typical real-world entity (depth-2 from Apple ≈ 80-160 nodes); 500 = stress (depth-3 dense); 1000 = upper bound before we cut over to snapshot tier. Budget: render < 1500 ms p95 at 1000 nodes on CI machine. Fail loud — graph perf is a known regression magnet (PLAN-0090 history). | New Playwright spec under `apps/worldview-web/tests/e2e/graph-perf.spec.ts`; fixtures generated via `scripts/gen-graph-fixture.ts`. |
| **FU-6.10** | Telemetry sampling rate for `graph.*` events — 100% or 10%? | **100% for v1.** Graph use is rare (single tab on a single page); the volume is bounded. 10 % would lose signal on perf regressions (depth-3 timeout, layout slow path). Re-evaluate at 10 k DAU. | Aligns with existing PRD-0088 telemetry plan (100% for low-volume events, 10% for high-volume chat token streams). |
| **FU-6.11** | Path query timeout when user has 100+ portfolio entities (large N for "path from instrument → portfolio") | **Cap at top-20 portfolio entities by `current_value_usd` DESC, server-side.** Reasons: (1) Path-from-instrument-to-portfolio is a *triage* signal — "does this instrument touch my book at all?"; (2) cardinality blow-up beyond top-20 is dominated by holdings <1 % of NAV (noise); (3) the existing path use case has a 5 s wall-clock — 100 path queries × 50 ms each = 5 s already. **UI copy** when truncated: "Showing paths to your 20 largest holdings". | Filed as backend FU on S7 path worker; not in `06-graph-intelligence.md` §6.1 (KG-PATH-01) — extend that ticket. |
| **FU-6.12** | Edge bundling for dense graphs (visual clarity at high edge counts) — v1.1 candidate confirm? | **Confirmed v1.1, NOT v1.** Sigma.js does not bundle edges natively; we'd need d3-force-edge-bundling or a custom WebGL shader. Cost ≥3 days. V1 mitigation: type-filter chips (already implemented in `GraphToolbar`) and depth slider let users de-clutter manually. | `GraphColumn.tsx:81-88` — existing `filteredGraph` already prunes edges by node-type filter; sufficient for v1. |

---

## §2 — Chart + Technicals (Cluster 7)

| ID | Question | Recommendation | Why / cite |
|----|----------|----------------|------------|
| **FU-7.1** | Brief border style — confirm Left-2px and update PRD spec table OQ-D20 (currently "Top-only 1px") to match DISCUSS-12 lock | **Locked: `border-l-2 border-[hsl(var(--accent-amber))]` on both OQ-D3 (dashboard brief) and OQ-D20 (instrument brief).** Update `docs/specs/0089-platform-page-redesign.md:392` row OQ-D20 from "Top-only 1px" → "Left-2px Bloomberg amber rail" in the same edit that closes DISCUSS-12. **Frontend action**: replace `border border-border/50 rounded-[2px]` in `GraphColumn.tsx:97` with `border-l-2 border-[hsl(var(--accent-amber))] rounded-none bg-card`. Also note: per DISCUSS-3, `rounded-[2px]` → 0px everywhere, so drop the radius even if rail were kept. | `apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx:97` is the v1 brief banner site; same treatment applied to the dashboard brief banner (separate component). |
| **FU-7.2** | Default chart timeframe 1Y — confirm with DISCUSS-11 lock | **Locked: 1Y daily default.** Change `useState<Timeframe>("1D")` → `useState<Timeframe>("1Y")` at `OHLCVChart.tsx:41`. Also confirm `useChartSeries` fetches 1Y of daily bars on first mount (it should — it already keys on `timeframe`). **Watch-out**: BP-376 (chart scrolls to 1985) regressed once on a timeframe-change path; add a Playwright assertion that on 1Y mount the rightmost visible bar is within 1 trading day of `today`. | `apps/worldview-web/components/instrument/chart/OHLCVChart.tsx:41` — single LOC change. |
| **FU-7.3** | Pivot computation cache TTL — 5 min market hours / 60 min after-hours (proposed) | **Accept. Add a 3rd tier: weekend = 24 h.** Pivots are derived from `prior_close + high + low` — they ONLY change when a new daily bar closes. During market hours, the *current-session* pivot lines don't move; what changes is the price line crossing them. So even 5 min is conservative; 60 min after-hours is fine; 24 h weekend matches `intraday-stats` cache tier in `07-chart-technicals-peers.md` §2.5. | Aligns with the cache-TTL table in `07-chart-technicals-peers.md:255-262`. |
| **FU-7.4** | IPO baseline copy: "—" / "since IPO (Xd)" / "<1Y history"? Pick one for consistency | **`—` (em-dash) with a hover tooltip "Insufficient history — listed YYYY-MM-DD".** Matches `07-chart-technicals-peers.md` §2.3 recommendation (Option A). Reasons: (1) consistent with every other missing-cell rendering on the page; (2) symmetric strip width across all instruments (no jitter); (3) "since IPO 142d +400%" is actively misleading for a triage strip — better to render nothing than the wrong thing. Backend returns JSON `null` for any period predating first bar; frontend maps `null` → `—` via the central `MetricValue` component. **No "since IPO" copy anywhere on the strip in v1.** | `07-chart-technicals-peers.md:160-176`. No current site renders this (MultiPeriodReturnsStrip not yet built); decision locks now to avoid future drift. |
| **FU-7.5** | Peers manual override table for top-50 instruments — yes/no | **No for v1.** Peer ranking is the EODHD-sourced sector/industry cohort already returned by `00-backend-data-inventory.md` peers fields. Manual overrides would require a new admin surface, a versioned override store, and an audit log — pure carry cost for a benefit (better peers for top tickers) that only emerges once users complain. **V1.1 candidate** if telemetry shows users dismissing peer rows > 30 % of the time. | Aligns with `07-chart-technicals-peers.md` §3 (peer endpoint spec uses EODHD cohort directly). |
| **FU-7.6** | Camarilla pivots — add behind user-settings toggle in v1.1 or v2? | **V2.** Camarilla = niche intraday-trader indicator (S1-S4 levels = 1.1 × range). The user base for PRD-0089 is the analyst/PM persona, not the day-trader. V1 ships Classic (Floor/Pivot/R1/R2/S1/S2) only. V1.1 already has Fibonacci pivots in scope per the cluster doc; Camarilla can wait until a user explicitly asks. | `07-chart-technicals-peers.md` §2.2 (OQ-D11). |
| **FU-7.7** | Volume profile overlay — confirm DISCUSS-11 decision (do NOT re-add in v1) | **Locked: do NOT re-add in v1.** Was removed in PLAN-0090 T-B-01. Rationale per DISCUSS-11: Bloomberg has it, Finviz doesn't, the user didn't ask for it back, and `lightweight-charts` doesn't ship one out of the box (custom canvas overlay = ≥2 day cost). Re-evaluate in v2 when chart gains advanced-indicator subscription tier. | `_DECISIONS.md` DISCUSS-11 (locked). |

---

## §3 — Edit summary (for whoever applies these)

- `apps/worldview-web/lib/gateway.ts` — thread `signal?` through `getEntityGraph(entityId, depth, opts)` (FU-6.1).
- `apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx:56` — pass `signal` to gateway call (FU-6.1).
- `apps/worldview-web/components/instrument/intelligence/graph/GraphColumn.tsx:97` — swap brief banner border to `border-l-2 border-[hsl(var(--accent-amber))] rounded-none` (FU-7.1 / DISCUSS-12).
- `apps/worldview-web/components/instrument/chart/OHLCVChart.tsx:41` — default `Timeframe = "1Y"` (FU-7.2 / DISCUSS-11).
- `docs/specs/0089-platform-page-redesign.md:392` — reconcile OQ-D20 row to "Left-2px" (FU-7.1).
- New Playwright spec `apps/worldview-web/tests/e2e/graph-perf.spec.ts` — 200/500/1000-node assertions (FU-6.9).
- New backend FU on S7 path worker — top-20 holdings cap (FU-6.11); deferred v1.1.
- Deferred to v1.1: URL hash `#node=` (FU-6.5), edge bundling (FU-6.12), Camarilla v2 (FU-7.6).

---

## §4 — Pushback flags

Reply with the FU-ID if you want to revisit:

- **FU-6.2** — could push to eager-prefetch if hover-debounce feels laggy in QA.
- **FU-6.8** — circular/hierarchical layouts may matter sooner if a "supply chain" view ships in v1.1.
- **FU-6.10** — drop graph telemetry to 10 % if event volume actually exceeds budget post-launch.
- **FU-7.5** — top-50 manual peer override could move to v1 if users complain in dogfood.

All other rows lock on doc sign-off.
