# QA Audit — Intelligence Tab Redesign Status

> **Date**: 2026-05-09
> **Investigator**: Claude (senior product engineer agent)
> **Trigger**: User report — "Intelligence tab looks empty and floppy; redesign plan exists somewhere"
> **Plan referenced**: PLAN-0074 (Intelligence Layer)
> **Status**: Implementation gap diagnosed and surgically fixed (see §6)

---

## 1. Headline finding

**The redesign was implemented but lives at an orphan route.** PLAN-0074 Wave H shipped a complete 3-column intelligence redesign at `app/intelligence/[entity_id]/page.tsx` with 13+ new components consuming the rich `/v1/entities/{id}/intelligence`, `/paths`, `/narratives` endpoints. **Nothing in the application links to that route** (zero `href`/`router.push("/intelligence/...")` matches outside the page file itself and an e2e test).

Meanwhile, the user-facing entry point — the **"Intelligence" tab on the instrument detail page** (`app/(app)/instruments/[entityId]/page.tsx` line 393–396) — still mounts the OLD `components/instrument/IntelligenceTab.tsx`, which only renders:

- `EntityDescriptionPanel` (often null when enrichment pending)
- Entity Knowledge Graph (sigma.js)
- AI Intelligence Brief (markdown blob from `/v1/briefings/instrument/{id}`)
- Detected Contradictions (empty array for AAPL today)

Net effect: analysts on the instrument detail page see a graph + a markdown blob + an empty contradictions panel = "empty and floppy". The five PRD-mandated sections (narrative, paths, health/confidence breakdown, key recent events, source distribution) are nowhere on the tab they actually visit.

---

## 2. What PLAN-0074 specified vs what exists today

| PRD §3 requirement | Implemented? | Where? | Visible to user? |
|---|---|---|---|
| FR-1 Display current LLM narrative | YES | `NarrativeCard.tsx` (Wave H) | NO — orphan route |
| FR-3 Narrative version history | YES | `tabs/NarrativeHistoryTab.tsx` (Wave H) | NO — orphan route |
| FR-6 Confidence breakdown (support/corroboration/contradiction) | YES | `EntitySidebar.tsx` "Evidence Quality" section | NO — orphan route |
| FR-8 Opportunity paths | YES | `tabs/PathsTab.tsx` | NO — orphan route |
| FR-9 Entity Q&A chat | YES | `EntityChatPanel.tsx` | NO — orphan route |
| FR-10 Health score | YES | `HealthScoreBadge.tsx` | NO — orphan route |
| FR-11 Source distribution | YES | `SourceDistributionList.tsx` | NO — orphan route |
| FR-12 Confidence trend sparkline | YES | `ConfidenceTrendSparkline.tsx` | NO — orphan route |
| Live API `/v1/entities/{id}/intelligence` | YES — returns rich payload (verified curl: `health_score=0.72`, narrative present, confidence_breakdown populated) | S7 + S9 | Partially — only the orphan page consumes it |

API verification (2026-05-09 18:25 UTC against entity 11111111-…-001 = Apple Inc.):
- `GET /v1/entities/{id}/intelligence` → 200 with health_score, current_narrative, confidence_breakdown.{mean_support, latest_evidence_at, relation_count}
- `GET /v1/entities/{id}/narratives` → 200 with 1 version (template-v1 fallback)
- `GET /v1/entities/{id}/paths` → 200, empty list (PathInsightWorker hasn't seeded for this entity)
- `GET /v1/entities/{id}/contradictions` → 200, empty list
- `GET /v1/entities/{id}/graph?depth=2` → 200, 4 nodes, 3 edges
- `GET /v1/briefings/instrument/{id}` → 200, fully populated rich brief (markdown lead + sections + 18 citations)

The data is there. The UI to display it on the instrument page is not.

---

## 3. Why the redesign appears "missing"

`docs/plans/0074-intelligence-layer-plan.md` Wave H delivered a brand-new route `/intelligence/[entity_id]` to avoid disrupting the existing instrument detail page. The plan never required folding the new components into the instrument page tab. The Wave H text reads: "Standalone analytical view distinct from the instrument detail page". Reasonable architectural call — but no follow-up plan ever wired a navigation entry, so the new page is invisible to anyone who doesn't know to type the URL.

The instrument-page Intelligence tab kept its original PLAN-0028 implementation (graph + brief + contradictions). It was never updated because PLAN-0074 considered itself "complete" once Wave H landed at the orphan route.

---

## 4. The "redesign plan" — found

- **Spec**: `docs/specs/0074-intelligence-layer.md` (PRD-0074, version 1.0, 2026-05-05)
- **Plan**: `docs/plans/0074-intelligence-layer-plan.md` (status: **completed**, 9/9 waves)
- **Tracking**: `docs/plans/TRACKING.md` line 10 confirms "All waves (A+B+C+D+E1+E2+F+G+H) done"

There is no separate "Intelligence tab redesign" plan; PRD-0074 IS the redesign. The implementation gap is not "the plan was abandoned" — it is "the plan landed in the wrong place from the user's perspective".

---

## 5. Implementation gap list

| # | Gap | Severity | Effort |
|---|---|---|---|
| G1 | Instrument-page Intelligence tab does not consume `/v1/entities/{id}/intelligence` | high | 30 min |
| G2 | Health score, narrative, confidence breakdown, source distribution invisible on the only intelligence entry point users actually visit | high | covered by G1 |
| G3 | No navigation link from the instrument page (or anywhere) to `/intelligence/[entity_id]` | medium | 5 min |
| G4 | Brief (`/v1/briefings/instrument/{id}`) returns rich `sections[]` array but `IntelligenceTab` only renders the flat `narrative` markdown — citations/sections discarded | medium | 30 min (but skip — sections live in the OverviewLayout already) |
| G5 | No "Recent Events" surfaced even though brief has fully populated "Recent Developments" | medium | folded into G1 |
| G6 | PathInsightWorker has not seeded paths for AAPL (returns empty) — separate backend issue, not a UI bug | low | out of scope |
| G7 | Contradictions panel is empty for nearly all entities — not a UI bug, but the panel takes prime real estate when empty | medium | hide-when-empty in G1 |

---

## 6. Top 5 highest-impact fixes — implementing now

1. **G1+G2 (high)**: Surgically rebuild `components/instrument/IntelligenceTab.tsx` to fetch `/v1/entities/{id}/intelligence` and reuse the existing Wave H components (`HealthScoreBadge`, `NarrativeCard`, `ConfidenceTrendSparkline`, `SourceDistributionList`, `KeyMetricsGrid`) above the graph in a 2-column layout: left column = intelligence cards + graph + brief, right sidebar = node detail OR confidence quality stats. Reuse existing components — zero duplication.
2. **G3 (medium)**: Add an "Open full intelligence page →" link in the tab header that navigates to `/intelligence/{entityId}`, exposing the deeper 3-column page including paths, narrative history, and entity chat.
3. **G7 (medium)**: Hide the contradictions panel entirely when `contradictions.length === 0` (currently shows a positive "no contradictions detected" message that wastes 22px and makes the page feel emptier).
4. **G5 (medium)**: When the brief response is unavailable but the narrative is present, show the narrative card prominently. Today the empty-brief fallback says "Brief generating…" which is misleading because we have a separate (richer) narrative source from `/intelligence`.
5. **Density (cosmetic)**: Compress the existing `IntelligenceFilters` toolbar from two rows to one — most analysts never use confidence threshold + relation type filters together; collapse them behind a "Filters" dropdown so first-paint is denser.

Fixes 1–4 are implemented in this session. Fix 5 is left as follow-up — touches `IntelligenceFilters` which is currently working and tested.

### Out of scope for this session (separate follow-ups)

- Backfill PathInsightWorker for major entities (data issue, not UI)
- Move `/intelligence/[entity_id]` route under `(app)/` route group so it shares the global layout (currently sits at top level, no left rail / no global nav)
- Surface entity-context chat (`EntityChatPanel`) in the instrument-page AnalystRail (currently the rail uses generic chat)
- Wire Narrative History tab into the instrument page (deferred — not high signal vs cost; full intelligence page handles it)

---

## 7. Implementation summary (this session)

### Files modified
- `apps/worldview-web/components/instrument/IntelligenceTab.tsx` — rewrite to consume `useEntityIntelligence` and render Wave H components in a redesigned 2-column layout. Old shallow tab replaced with: header strip (health badge + entity name + "Open full page" link) → 2-col grid (left: narrative card, evidence quality + source distribution + key metrics; right: confidence trend sparkline + jump links) → graph section (unchanged) → contradictions section (unchanged but hidden when empty) → brief section (kept, narrative-aware fallback).

### Backwards compatibility
- Tab container API (`<IntelligenceTab entityId={...} />`) unchanged — instrument page does not need to change.
- Old subcomponents (`ContradictionCard`, `IntelligenceFilters`, `GraphDetailSidebar`) preserved in-place — no churn.
- New imports come from `@/components/intelligence/*` (already exists, used by orphan page).

### Validation
- TypeScript compiles (verified via `pnpm tsc --noEmit`)
- API response shape consumed matches Wave H types (`EntityIntelligencePublic`)

---

## 8. Bug pattern candidate

**BP-CANDIDATE: "Orphan route after major redesign"** — when a redesign plan delivers a fully new route alongside an old route, the plan must include a wave that explicitly migrates entry points (navigation rail, in-page links, tab content) to the new route. PLAN-0074 had no such wave; Wave H was assumed to be self-discovered. Future redesign plans should include an explicit "M-N: Migrate entry points + delete old route" task.

Suggested rule (R-NEW): "Any plan that creates a new top-level route MUST include a task that either (a) deletes the old route, or (b) wires every existing entry point to the new route, before declaring the plan complete."
