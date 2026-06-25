# Alerts UI Investigation — Alert-Creation Frontend (2026-06-20)

**Scope:** Frontend alert-CREATION experience in `apps/worldview-web`. Maps the current
creation UI + flow, the submit contract, gaps for 5 new alert types, and a concrete
proposed UX + component plan. **Read-only / docs-only** — no source changes were made.

**Working tree:** `/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability/apps/worldview-web`

**Sibling agents** cover the backend alert engine + signal sources. Wherever this report
asserts a payload shape, it is flagged as **[BACKEND-CONFIRM]** — the rule schema must be
agreed with the backend investigation.

---

## 1. Headline finding (read this first)

**Alert *rules* (the "tell me when X happens" definitions) have NO backend.** They are
written to and read from `localStorage` only. There is a `_localOnly: true` tag on every
rule and a documented gap (`docs/audits/2026-04-29-alert-rule-crud-gap.md`). The planned
backend contract is stubbed but not shipped:

```
GET    /v1/alerts/rules
POST   /v1/alerts/rules
PATCH  /v1/alerts/rules/{id}
DELETE /v1/alerts/rules/{id}
```
(source: `lib/alerts/rules.ts` header, lines 11–21)

By contrast, **fired alerts** (the events) DO have a real S10/S9 API:
`/v1/alerts/pending`, `/v1/alerts/{id}/acknowledge`, `/v1/alerts/{id}/snooze`,
`/v1/alerts/history` (source: `lib/api/alerts.ts`).

**Implication for the 5 new types:** building them is *primarily a backend + contract*
effort. The frontend rule builder is a thin localStorage form today; the 5 new types need
(a) a real rule schema, (b) a real CRUD endpoint, and (c) a redesigned creation UX. This
report designs (c) and proposes the (a) schema for the backend to confirm.

---

## 2. Current alert-creation UI (file refs)

All alert components live in `components/alerts/`:

| File | Role |
|------|------|
| `AlertRuleBuilder.tsx` | **Legacy** quick-add dialog ("+ Create Rule"). Create-only. Writes straight to localStorage. |
| `RuleManagerDialog.tsx` | **Primary** CRUD surface ("⚙ Rules"). Two tabs: List + Edit. Create/edit/pause/delete. Uses `lib/alerts/rules.ts`. |
| `lib/alerts/rules.ts` | The localStorage CRUD layer. Defines the `AlertRule` type + `STORAGE_KEY="worldview-alert-rules"`. |
| `lib/alerts/format.ts` | Rule formatting helpers. |
| `NotificationPreferencesDialog.tsx` | Quiet hours + severity floor (notification delivery prefs, not rule conditions). |
| `AlertDetailSheet.tsx` | Read panel for a *fired* alert; has a "Set alert rule" suggested-action that opens `RuleManagerDialog` pre-filled with the alert's ticker. |
| `AddToWatchlistDialog.tsx` | Minimal watchlist picker reused as a suggested action. |
| `AlertsList.tsx`, `AlertHistoryTab.tsx`, `SeverityBadge.tsx` | Display of fired alerts (not creation). |

### 2.1 The current form (both builders are near-identical)

Fields rendered (`RuleManagerDialog.tsx` Edit tab, lines 330–437):

- **Name** — free text, optional; defaults to `${TypeLabel} • ${entity} • ${condition}` via `defaultRuleName()`.
- **Rule type** — native `<select>`, exactly **4 options**:
  `price_threshold | volume_spike | news_signal | portfolio_risk`.
- **Entity / ticker** — a **plain free-text `<input>`** (`placeholder="e.g. AAPL"`).
  **Not** a search/autocomplete. The comment says "backend will resolve to entity_id".
- **Condition** — a **single free-text `<input>`**. Placeholder changes per type
  (`CONDITION_PLACEHOLDER`, lines 50–55): e.g. `"e.g. price > 150"`, `"e.g. volume > 2x 30d avg"`,
  `"e.g. keyword: earnings"`, `"e.g. drawdown > 5%"`.
- **Toggles** — Enabled, In-app, Email (checkboxes).

**Validation:** the only check is `condition.trim()` non-empty (save button disabled
otherwise). There is **no** structured validation of the condition string — it is opaque
free text. The entity field is never validated or resolved to an `entity_id`.

### 2.2 What the UI submits today

`handleSave()` (RuleManagerDialog lines 157–187) builds:

```ts
{
  name: string,                 // or defaultRuleName(...)
  type: "price_threshold" | "volume_spike" | "news_signal" | "portfolio_risk",
  entitySearch: string,         // free text, NOT an entity_id
  condition: string,            // free text expression, opaque
  enabled: boolean,
  notifyInApp: boolean,
  notifyEmail: boolean,
}
```
…and calls `createAlertRule()` / `updateAlertRule()` in `lib/alerts/rules.ts`, which
**only writes to localStorage** (no network). There is no `rule_type → structured
condition params` mapping at all — `condition` is a single human string.

> **There is no current "submit contract" to a backend for rule creation.** The fired-alert
> API (`lib/api/alerts.ts`) is read/ack/snooze only.

---

## 3. Entry points & flow

**The only entry points to alert creation are on the `/alerts` page** (`app/(app)/alerts/page.tsx`):

- Page header (lines 347–369): `NotificationPreferencesDialog`, `⚙ Rules (N)` →
  `RuleManagerDialog`, and `+ Create Rule` → `AlertRuleBuilder`.
- Secondary, contextual: `AlertDetailSheet` "Set alert rule" suggested action
  (lines 313–324) opens `RuleManagerDialog` with `prefillEntity={alert.ticker}`.

**Notable gaps in entry points:**

- **No "Set alert" / "Create alert" on the Instrument Detail page** (`components/instrument/*`).
  Grep for `AlertRuleBuilder|RuleManagerDialog|Create Rule|Set Alert` hits only the alerts
  page + alerts components. A trader viewing AAPL cannot create a price/fundamental alert
  from the instrument view — a major missing entry point for the new types.
- **No entry from the watchlist** (e.g. "alert me on any of these").
- **No entry from the KG graph / PathBetween panel** (relevant for the node-connection type).

**Flow today:** `/alerts` → click `+ Create Rule` or `⚙ Rules` → dialog opens → pick type
from 4-item dropdown → type entity text → type condition text → Save → row appears in
localStorage list (badged "local only"). No preview, no confirmation, no backtest.

---

## 4. Gap analysis for the 5 new alert types

Current type enum is fixed at 4 values in **three** places that must change:
`AlertRuleBuilder.tsx` (line 43, 57–62, 169–173), `RuleManagerDialog.tsx`
(lines 50–70), and `lib/alerts/rules.ts` (lines 39, 96–104, 75). The "condition" is a
single free-text string everywhere — there is **no per-type structured editor**.

| # | New type | What exists | What's missing (UI) |
|---|----------|-------------|---------------------|
| 1 | **Stock price crosses X** | Closest is `price_threshold` (free text "price > 150") | Structured editor: **operator** (above/below/crosses) + **price level** number input + **entity picker**. Currently entity is free text and value is parsed from a string. |
| 2 | **News count ≥ N (over window)** | `news_signal` (free text "keyword: earnings") | **count** number input + **time window** select (1h/24h/7d) + optional entity scope + optional keyword/topic. None exist. |
| 3 | **News momentum increase** | none | **momentum delta** input (e.g. ≥ +Δ vs prior window) + window select + entity scope. Needs a "momentum" concept the UI has no widget for. **[BACKEND-CONFIRM]** the momentum metric definition. |
| 4 | **Connection between two KG nodes** | none in creation UI. `PathBetweenPanel.tsx` already does a **two-entity picker** + pairwise path query (read-only). | A **two-entity picker** in the rule form (reuse PathBetweenPanel's `EntityPicker` pattern) + condition = "alert when a path appears / weirdness ≥ X / hops ≤ N". **[BACKEND-CONFIRM]** what "connection appears" means as a trigger. |
| 5 | **Fundamental metric crosses Y** | none. Screener (`ScreenerFilterBar.tsx`) has a **metric catalogue** (P/E, P/B, P/S, Div Yield, ROE, margins, Rev YoY, Earnings YoY, D/E, Current Ratio) usable as the metric picker source. | **metric picker** (dropdown from screener catalogue) + **operator** + **value** + **entity picker**. None exist in alerts. |

**Cross-cutting gaps:**
- **No entity/instrument picker in the rule form.** Entity is free text today. Reusable
  pickers exist elsewhere (see §5) and must be wired in.
- **No type-aware form.** One free-text condition box for all types.
- **No preview / "would have fired N times" backtest.** **[BACKEND-CONFIRM]** feasibility.
- **No natural-language summary** of the assembled rule.
- **No real persistence** — must move off localStorage to the planned `/v1/alerts/rules` CRUD.

---

## 5. Reusable components (find-and-reuse before building new)

| Need | Reuse this | Path |
|------|-----------|------|
| Instrument picker (ticker → instrument_id) | `TickerPicker` (Popover + cmdk Command + `searchInstruments`) | `components/workspace/TickerPicker.tsx` |
| Entity picker returning **real KG entity_id** | `EntityPicker` inside `PathBetweenPanel` (debounced `searchFundamentals` → `entity_id`) | `components/intelligence/PathBetweenPanel.tsx` (lines 54–162) |
| Two-node connection picker + path result | `PathBetweenPanel` (whole panel) for type 4 preview | `components/intelligence/PathBetweenPanel.tsx` |
| Fundamental metric catalogue | Screener filter metrics (P/E, ROE, margins, …) | `components/screener/ScreenerFilterBar.tsx`, `features/screener/lib/filter-state.ts` |
| Search APIs | `searchInstruments`, `searchFundamentals` (entity_id-enriched), `resolveTickersBatch` | `lib/api/search.ts` |
| shadcn primitives | `command.tsx`, `popover.tsx`, `select.tsx`, `form.tsx`, `multi-combobox.tsx`, `dialog.tsx`, `tabs.tsx` | `components/ui/` |
| Debounce | `useDebounce(value, 300)` | `hooks/useDebounce.ts` |

**Key reuse note:** `searchInstruments` sets `entity_id = instrument_id` (S3 has no KG link).
For types that need a true KG `entity_id` (4 = node connection; arguably 2/3 news-by-entity),
use **`searchFundamentals`** (enriches via company-overview) as `EntityPicker` already does.
For pure price/fundamental alerts an `instrument_id` is sufficient. **[BACKEND-CONFIRM]**
which id each rule type keys on (instrument_id vs entity_id).

**New components needed:** a shared `<EntityPicker>` primitive (extract from PathBetweenPanel —
its header explicitly invites this), a `<MetricPicker>` (wrap screener metric list), and the
per-type condition editors (below).

---

## 6. Proposed UX (finance-grade, per `docs/ui/DESIGN_SYSTEM.md`)

### 6.1 Shape: **type-first wizard inside the existing Dialog**, not a single mega-form

Rationale: 5 types with disjoint condition shapes make a unified form noisy and error-prone.
A two-step wizard keeps each step dense and Bloomberg-like (Midnight Pro, 2px radius,
`text-[11px]`, uppercase `tracking-[0.08em]` labels — matching the existing dialogs).

- **Step 1 — Pick type.** Replace the 4-item `<select>` with a compact grid of 5 type cards
  (icon + label + one-line "fires when…" description). Keyboard-navigable.
- **Step 2 — Condition editor** (type-specific) + entity scope + a live **natural-language
  summary** line + notify toggles. Back/Next/Save footer.

Keep it in the current `Dialog` (the codebase notes `Sheet` exists too — either is fine; Dialog
is already the alerts convention). Reuse `Tabs` is unnecessary; a `step` state is simpler.

### 6.2 Per-type condition editors (rule_type → form mapping)

> All payloads below are **[BACKEND-CONFIRM]** proposals. The frontend currently sends one
> free-text `condition`; the new schema should be a structured `condition` object keyed by
> `rule_type`.

**1. `price_cross`** — InstrumentPicker (TickerPicker) + operator `Select`
(`above | below | crosses`) + numeric price `Input`.
`condition: { instrument_id, operator, price }`

**2. `news_volume`** — optional EntityPicker scope + numeric `count` + window `Select`
(`1h|6h|24h|7d`) + optional keyword `Input`.
`condition: { entity_id?, count, window, keyword? }`

**3. `news_momentum`** — EntityPicker scope + `delta` numeric (e.g. "+50%") + comparison
window `Select` + baseline window. (Mirror the dashboard's "news momentum" concept — sibling
backend agent owns the exact metric.)
`condition: { entity_id?, delta_pct, window, baseline_window }` **[BACKEND-CONFIRM]**

**4. `kg_connection`** — **two** EntityPickers (Source/Target, reuse PathBetweenPanel pattern)
+ trigger select (`path_appears | weirdness_gte | hops_lte`) + threshold + maxHops.
Inline preview can mount `PathBetweenPanel`'s query to show the *current* connection state.
`condition: { source_entity_id, target_entity_id, trigger, threshold?, max_hops }` **[BACKEND-CONFIRM]**

**5. `fundamental_cross`** — InstrumentPicker + MetricPicker (screener catalogue) + operator
`Select` + numeric value + optional unit hint.
`condition: { instrument_id, metric_key, operator, value }` (metric_key MUST match the
backend extractor names — see `docs/audits/2026-04-29-screener-metric-gap.md`) **[BACKEND-CONFIRM]**

### 6.3 "Make it easy" affordances

- **Sensible defaults per type** (e.g. price_cross defaults operator=`above`, window=`24h`
  for news, maxHops=3 for connection — matching PathBetweenPanel).
- **Natural-language summary** rendered live from the structured condition, e.g.
  *"Alert me when AAPL price crosses above $150"* / *"…when ≥5 articles mention NVDA in 24h"* /
  *"…when a connection appears between Apple and Anthropic within 3 hops"*. Replaces today's
  opaque `defaultRuleName()` string-concat with a real, per-type formatter (extend
  `lib/alerts/format.ts`).
- **Inline backtest preview** — "this would have fired N times in the last 30d" — **highly
  desirable but [BACKEND-CONFIRM]**: requires a dry-run/preview endpoint. If the backend can't
  offer it cheaply, ship without it in v1.
- **Entity validation** — replacing free text with a picker eliminates the silent
  "unresolvable ticker" failure class that the current free-text entity field permits.
- **New entry points** — add a "＋ Alert" affordance on the Instrument Detail header (price +
  fundamental + news types) and on the PathBetween/graph panel (connection type), each opening
  the wizard pre-scoped to that entity (mirrors the existing `prefillEntity` mechanism in
  `RuleManagerDialog`).

### 6.4 Component plan summary

**Reuse:** `TickerPicker`, `EntityPicker` (extract→share), `PathBetweenPanel` (type-4 preview),
screener metric list, `searchInstruments`/`searchFundamentals`, all `components/ui/*` primitives.

**New:**
- `AlertWizard.tsx` (type grid + step controller) — replaces/absorbs `AlertRuleBuilder` and the
  Edit tab of `RuleManagerDialog`.
- `condition-editors/` — one component per type (`PriceCrossEditor`, `NewsVolumeEditor`,
  `NewsMomentumEditor`, `KgConnectionEditor`, `FundamentalCrossEditor`).
- `EntityPicker.tsx` (shared, extracted from PathBetweenPanel).
- `MetricPicker.tsx` (wraps screener catalogue).
- `lib/alerts/format.ts` extension: per-type NL summary.
- `lib/api/alertRules.ts` (new) — swap the localStorage CRUD in `lib/alerts/rules.ts` for the
  real `/v1/alerts/rules` endpoints once the backend ships (one-file swap, as the existing
  header anticipates).

---

## 7. Backend coordination checklist (flag to sibling agents)

1. **Confirm the rule schema:** `rule_type` enum values + the structured `condition` object per
   type (§6.2). The frontend currently sends a single free-text `condition` — this MUST change.
2. **Ship `/v1/alerts/rules` CRUD** (GET/POST/PATCH/DELETE) — the frontend localStorage layer is
   designed to swap to it.
3. **Confirm id keying** per type: `instrument_id` vs KG `entity_id` (price/fundamental likely
   instrument_id; connection needs entity_id; news likely entity_id).
4. **Confirm the news-momentum metric definition** (delta vs baseline window).
5. **Confirm kg_connection trigger semantics** (path appears / weirdness threshold / hop limit).
6. **Confirm fundamental metric_key vocabulary** (must match extractor names; cite the screener
   metric-gap audit).
7. **Preview/backtest endpoint** ("would have fired N times / 30d") — confirm feasibility; gates
   the §6.3 backtest affordance.

---

## 8. Key file references

- `components/alerts/AlertRuleBuilder.tsx` — legacy create dialog (localStorage).
- `components/alerts/RuleManagerDialog.tsx` — primary CRUD dialog (localStorage).
- `lib/alerts/rules.ts` — localStorage CRUD + `AlertRule` type + planned backend contract.
- `lib/api/alerts.ts` — fired-alert API (pending/ack/snooze/history) — *no rule creation*.
- `app/(app)/alerts/page.tsx` — the only creation entry points.
- `components/alerts/AlertDetailSheet.tsx` — "Set alert rule" suggested action (prefill).
- `components/workspace/TickerPicker.tsx` — reusable instrument picker (Popover+cmdk).
- `components/intelligence/PathBetweenPanel.tsx` — reusable EntityPicker + two-node path UI.
- `components/screener/ScreenerFilterBar.tsx` — fundamental metric catalogue.
- `lib/api/search.ts` — `searchInstruments` / `searchFundamentals` (entity_id-enriched).
- `docs/audits/2026-04-29-alert-rule-crud-gap.md` — existing record of the CRUD gap.
- `docs/audits/2026-04-29-screener-metric-gap.md` — fundamental metric naming source of truth.
