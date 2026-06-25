# Momentum Widget — Unit Inconsistency Root-Cause Report

**Date**: 2026-06-19
**Component**: `apps/worldview-web/components/dashboard/ai-signals/NewsMomentumRow.tsx`
**Severity**: P0 display bug (user-visible inconsistency; one unit convention throughout the widget)
**Status**: Root cause identified; fix recommendation ready for `/fix-bug`

---

## Symptom

Some tickers in the NEWS MOMENTUM widget display their change as an **absolute integer**
(e.g. `+11`) while others display a **percentage** (e.g. `↑200%`). The formatting varies
row-by-row within the same render.

---

## Data Flow (full trace)

```
nlp-pipeline DB (entity_mentions)
  → GetTrendingEntitiesUseCase: computes delta, delta_pct
  → GET /api/v1/news/trending-entities (S6)
  → S9 _to_momentum_row(): passes count, prior_count, delta, delta_pct through unchanged
  → GET /v1/signals/ai
  → AiSignalsWidget.tsx: passes item to NewsMomentumRow
  → NewsMomentumRow calls trendMeta(item)
  → trendMeta renders trend.label
```

All fields (`count`, `prior_count`, `delta`, `delta_pct`) arrive correctly on every row.
The backend sends uniform, well-typed data. There is **no data-layer inconsistency**.

---

## Root Cause

**Location**: `apps/worldview-web/components/dashboard/ai-signals/news-meta.ts`, line 41

**The `trendMeta` function contains an intentional conditional branch that switches units
based on whether `prior_count === 0`:**

```typescript
// news-meta.ts lines 39-43
if (delta > 0) {
  // New coverage (no prior baseline) reads better as "+N new" than a giant %.
  const label = prior === 0 ? `+${delta}` : `↑${Math.round(pct)}%`;
  return { arrow: "↑", text: "text-positive", label, word: "rising" };
}
```

When `prior_count === 0` (the entity had **zero** articles in the prior window), the label
is formatted as `+{delta}` — an **absolute integer** (the article count delta).

When `prior_count > 0`, the label is formatted as `↑{Math.round(pct)}%` — a **percentage**.

### Concrete trigger

This is common in practice because:
- The backend `delta_pct` formula floors the denominator at 1: `100 * delta / max(prior_count, 1)`
- A brand-new entity with `prior_count=0` and `count=11` yields `delta=11`, `delta_pct=1100.0`
- `trendMeta` sees `prior === 0`, so it renders `+11` instead of `↑1100%`
- An established entity with `prior_count=5` and `count=10` yields `delta_pct=100`, renders `↑100%`

So on any given render, entities with no prior coverage show absolute counts while those
with established prior baselines show percentages — producing the mixed display.

### Why the code was written this way

The comment says: `"New coverage (no prior baseline) reads better as '+N new' than a giant %."`.

This is a legitimate editorial position for the tooltip (`trendTitle`), but it is wrong for
the **column label** because:
1. The column is a fixed-width `w-[44px]` slot — the unit change (number vs %) visually
   disrupts alignment row-to-row.
2. Users scan a momentum ranking expecting a uniform axis; mixing units makes inter-row
   comparison impossible.
3. The percentage IS informative even for prior=0 cases if we cap the display (e.g. `new`
   or `↑999%+` rather than the raw 1100%).

### The falling-delta branch is consistent (no bug there)

```typescript
// line 45
if (delta < 0) {
  return { arrow: "↓", text: "text-negative", label: `↓${Math.abs(Math.round(pct))}%`, word: "falling" };
}
```
The negative branch always shows a percentage regardless of prior_count. Only the positive
branch has the conditional unit switch.

---

## Evidence from tests (static)

The test at `ai-signals-widget.test.tsx` line 111-119 **explicitly pins the inconsistent behavior**:

```typescript
it("shows '+N' for new coverage when the prior window was empty", async () => {
  // Prior=0 → prefer the honest "+5" reading over a giant "↑500%".
  expect(await screen.findByText("+5")).toBeInTheDocument();
});
```

This test was written to assert the current (buggy) behavior. It will need updating as part
of the fix.

---

## Fix Recommendation (P0)

**Unit convention**: use **percentage** throughout — it is the financial convention for
momentum/movers (consistent with the rest of the dashboard: TopMovers, PreMarketMovers,
HoldingsMovers all show `%`). The percentage is already computed by the backend on every row.

**Approach A — preferred**: Replace the special-cased `prior === 0` branch with a capped
percentage. When prior_count is 0, the % is large but meaningful; cap it at 999 and add a
`+` indicator for the "all new" case to still communicate the qualitative idea:

```typescript
// news-meta.ts trendMeta, delta > 0 branch — PROPOSED
if (delta > 0) {
  const displayPct = Math.min(Math.round(pct), 999);
  const label = prior === 0 ? `↑${displayPct}%+` : `↑${displayPct}%`;
  return { arrow: "↑", text: "text-positive", label, word: "rising" };
}
```

The `%+` suffix for the new-coverage case preserves the editorial intent (signals "this is
a floor, actual surge is unbounded") without switching units. Alternatively, just use the
uncapped percentage if the backend already floors the denominator cleanly.

**Approach B — minimal**: Remove the conditional entirely; always use percentage:

```typescript
if (delta > 0) {
  const label = `↑${Math.round(pct)}%`;
  return { arrow: "↑", text: "text-positive", label, word: "rising" };
}
```

This is the smallest change. The tooltip (`trendTitle`) already explains the raw counts
(`"5 articles in the last 24H, vs 0 in the prior 24H"`), so the user can always recover
the absolute meaning. Recommended if the widget's `w-[44px]` column needs predictable
alignment (it does — `↑1100%` at 7 chars overflows vs `+5` at 2 chars; cap is needed).

**Approach B with cap (recommended)**:

```typescript
if (delta > 0) {
  const label = `↑${Math.min(Math.round(pct), 999)}%`;
  return { arrow: "↑", text: "text-positive", label, word: "rising" };
}
```

**Files to change**:
1. `apps/worldview-web/components/dashboard/ai-signals/news-meta.ts` — line 41, `trendMeta`
2. `apps/worldview-web/components/dashboard/ai-signals/__tests__/ai-signals-widget.test.tsx`
   — update the `shows '+N' for new coverage` test to assert `↑500%` (or `↑500%` capped)

**No backend changes needed.** The backend already provides `delta_pct` correctly for all rows
including `prior_count=0` cases.

---

## Files Involved

| File | Role |
|------|------|
| `apps/worldview-web/components/dashboard/ai-signals/news-meta.ts:39-48` | Bug location — `trendMeta` conditional |
| `apps/worldview-web/components/dashboard/ai-signals/NewsMomentumRow.tsx:84-88` | Renders `trend.label` |
| `apps/worldview-web/components/dashboard/ai-signals/__tests__/ai-signals-widget.test.tsx:111-119` | Test pins the buggy behavior |
| `apps/worldview-web/components/dashboard/AiSignalsWidget.tsx` | Widget orchestrator — no bug here |
| `services/api-gateway/src/api_gateway/routes/signals.py` | S9 proxy — no bug here |
| `services/nlp-pipeline/src/nlp_pipeline/application/use_cases/trending_entities.py:121-125` | Computes `delta_pct` correctly |
