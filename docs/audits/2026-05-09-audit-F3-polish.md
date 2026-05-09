# PLAN-0087 Wave B — Audit F3: Frontend polish

> **Agent**: F3 (visual / UX cross-cutting)
> **VA**: VA-5 (Frontend critical paths, cross-cutting)
> **Scope**: `apps/worldview-web/` (read-only static analysis)
> **Date**: 2026-05-09
> **Method**: ripgrep over `components/`, `app/`, `features/`, `hooks/`, `lib/`, `contexts/`. No runtime probing.

The bar is "indistinguishable from Bloomberg." This audit only flags violations of the Terminal Dark canon defined in `docs/ui/DESIGN_SYSTEM.md` (v2.3, 2026-04-23) and density rules from PLAN-0071 Phase 6/6.5.

---

## 1. Off-palette violations

### 1A. Retired Bloomberg-Dark / Midnight-Pro hex codes still rendered live

`docs/ui/DESIGN_SYSTEM.md:9` explicitly forbids the prior palette: `#0A0E14`, `#E8A317`, `#E0DDD4`, `#6B7585`, `#111820`, `#1A2030`, `#243040`. Everything below renders at runtime (these are not just stale comments — the values are passed to `style={...}` or used as constants):

| File:line | Hex | Token it should be |
|-----------|-----|--------------------|
| `apps/worldview-web/components/screener/HeatCell.tsx:60` | `backgroundColor: "#1A2030"` | `bg-muted` (#18181B) |
| `apps/worldview-web/components/screener/HeatCell.tsx:60` | `color: "#6B7585"` | `text-muted-foreground` (#71717A) |
| `apps/worldview-web/components/brokerage/ConnectedBrokeragesList.tsx:234` | `color: "#0EA5E9"` | `text-primary` (#FFD60A) — the old Midnight-Pro primary |
| `apps/worldview-web/components/brokerage/ConnectedBrokeragesList.tsx:234` | `borderColor: "rgba(14,165,233,0.4)"` | `border-primary/40` |
| `apps/worldview-web/components/brokerage/ConnectedBrokeragesList.tsx:314` | `color: "#0EA5E9"` | `text-primary` |
| `apps/worldview-web/components/instrument/OHLCVChart.tsx:571` | `color: "#0EA5E9"` (MA200 line) | re-justify; the file's own comment says "sky-500" but #0EA5E9 was the retired Midnight-Pro primary, not sky |
| `apps/worldview-web/components/instrument/EntityGraph.tsx:57` | `const NODE_DEFAULT_COLOR = "#6B7585"` | `--muted-foreground` (#71717A) |
| `apps/worldview-web/components/instrument/EntityGraph.tsx:442` | `color: "#1A2030", labelColor: "#1A2030"` (dimmed nodes) | `--card` (#111113) or `--muted` (#18181B) |
| `apps/worldview-web/components/instrument/EntityGraph.tsx:695` | `style={{ background: "#0A0E14" }}` | `--background` (#09090B) |
| `apps/worldview-web/components/instrument/EntityGraph.tsx:711` | `labelColor: { color: "#6B7585" }` | `--muted-foreground` (#71717A) |
| `apps/worldview-web/components/instrument/EntityGraph.tsx:724` | `style={{ background: "#0A0E14" }}` | `--background` (#09090B) |
| `apps/worldview-web/components/instrument/EntityGraphPanel.tsx:73` | `fill: "#0A1A20"` (company) | non-token green-tinted; should be `--card` or document as graph-fill |
| `apps/worldview-web/components/instrument/EntityGraphPanel.tsx:74` | `fill: "#0D2921"` (person) | non-token; same |
| `apps/worldview-web/components/instrument/EntityGraphPanel.tsx:75` | `fill: "#2A1E06"` (event) | non-token |
| `apps/worldview-web/components/instrument/EntityGraphPanel.tsx:76` | `fill: "#1A1A2E"` (topic) | non-token |
| `apps/worldview-web/components/instrument/EntityGraphPanel.tsx:77` | `fill: "#111820", stroke: "#6B7585"` (default) | retired Bloomberg-Dark |
| `apps/worldview-web/components/instrument/EntityGraphPanel.tsx:286` | `stroke={isHighlighted ? "#6B7585" : "#1A2030"}` | retired |
| `apps/worldview-web/components/instrument/EntityGraphPanel.tsx:366` | `fill={isHovered ? "#E0DDD4" : "#6B7585"}` | retired |
| `apps/worldview-web/lib/entity-types.ts:182` | `FALLBACK.color = "#6B7585"` | retired (consumed by `EntityGraph.tsx:289`) |

**Surfaces affected**: A4 (`/instruments/{symbol}` Overview tab — EntityGraphPanel & EntityGraph render here), A8 (Screener — HeatCell on score column), A9 (Portfolio brokerages — ConnectedBrokeragesList).

### 1B. Tailwind shorthand colors outside the design tokens (live in production)

These ARE rendered (consumer paths verified):

| File:line | Class | Notes |
|-----------|-------|-------|
| `apps/worldview-web/lib/alias-types.ts:54,59,64,69,74,79,84` | `text-amber-300/400 bg-amber-300/10`, `text-zinc-300`, `text-sky-400`, `text-cyan-400`, `text-emerald-400`, `text-violet-400` | Consumed by `components/entity/AliasPill.tsx:85` (`token.className`) — renders on the entity sidebar |
| `apps/worldview-web/components/instrument/IntelligenceTab.tsx:114` | `bg-purple-500/15 text-purple-400 border-purple-500/30` (person badge) | Live on Intelligence tab |
| `apps/worldview-web/components/instrument/IntelligenceTab.tsx:115` | `bg-orange-500/15 text-orange-400 border-orange-500/30` (macro_event) | Live |
| `apps/worldview-web/components/instrument/ChartToolbar.tsx:210` | `text-sky-500` ("MA**200**") | Inline emphasis on toolbar label |
| `apps/worldview-web/features/chat/components/ActionConfirmModal.tsx:139` | `text-orange-400 border-orange-400/40 bg-orange-400/10` | Action-confirm modal warning state — should use `text-warning` (`#F59E0B`) |
| `apps/worldview-web/features/dashboard/components/BriefEntityPill.tsx:108` | `text-blue-400 hover:bg-blue-400/10` | Inline brief entity pill — blue is not in palette |
| `apps/worldview-web/features/dashboard/components/BriefDiffPanel.tsx:65,74` | `text-green-400/70`, `text-green-400` | Should be `text-positive` (#26A69A) |
| `apps/worldview-web/features/dashboard/components/BulletFeedback.tsx:85,86` | `text-green-400`, `hover:text-green-400` | Should be `text-positive` |
| `apps/worldview-web/features/dashboard/components/BulletFeedback.tsx:105,106` | `text-red-400`, `hover:text-red-400` | Should be `text-negative` (#EF5350 / #FF3B5C per token note) |
| `apps/worldview-web/features/dashboard/components/BriefRating.tsx:81,82,87` | `text-amber-400`, `hover:text-amber-400` | Star rating; should use `text-primary` (#FFD60A) for "selected/filled" — Bloomberg yellow IS the brand selected colour |
| `apps/worldview-web/features/dashboard/components/BriefDiffBadge.tsx:89` | `bg-amber-500/10 text-amber-400 hover:bg-amber-500/20` | Should be `text-warning bg-warning/10` |
| `apps/worldview-web/features/chat/components/ToolCallIndicator.tsx:110` | `text-green-500` (success check) | Should be `text-positive` |

### 1C. `lib/entity-types.ts` taxonomic palette

`lib/entity-types.ts:78–177` defines an entity-type colour map (`color: "#6366F1"`, `text-indigo-400`, `text-violet-400`, `text-purple-400`, `text-cyan-400`, `text-emerald-400`, `text-rose-400`, `text-red-400`, `text-sky-400`, `text-teal-400`, `text-amber-400/500`, `text-pink-400`, `text-slate-400`). The hex `color` values are consumed by `EntityGraph.tsx:289` for graph node fills. The `badgeClass` field is **not currently consumed anywhere** in the codebase (verified: `grep -rn 'badgeClass'` returns only the definitions and the type alias). Recommend either deleting `badgeClass` or reconciling with palette before a future consumer ships.

The `color:` field is consumed and renders in the entity graph (Surface A4). These values function as a deliberate categorical palette analogous to industry-standard graph-vis colour ramps; flagging here so the QA owner can decide whether the brand prohibits non-token tints inside the graph canvas. Treating this as **info** unless the QA owner says otherwise.

### 1D. Status page, login, landing — non-token colours

Lower priority (none on the Phase-A walk-through, but they ARE on demo path A0/A10):

| File:line | Class |
|-----------|-------|
| `apps/worldview-web/app/(public)/status/page.tsx:74,76,78,102,140,169,171,172` | `text-amber-500`, `text-red-500`, `text-zinc-500`, `bg-green-500/80 bg-red-500/80`, `bg-amber-950/50 border-amber-500/40`, `bg-red-950/50 border-red-500/40`, `bg-blue-950/50 border-blue-500/40` |
| `apps/worldview-web/app/(public)/status/components.ts:93,95,97,99,101` | `bg-green-500`, `bg-amber-500`, `bg-red-500`, `bg-zinc-500` (×2) |
| `apps/worldview-web/app/login/page.tsx:291` | `border-amber-500/50 text-amber-500 hover:bg-amber-500/10` (Dev Login button) |

---

## 2. Wrong-radius violations

`--radius` is `0.125rem` (2px). All radii must use `rounded-[2px]` (or bare `rounded` / `rounded-sm`, which resolve to the token). `rounded-md`/`-lg`/`-xl`/`-2xl` are forbidden except for `rounded-full` on dots, pills and avatars.

| File:line | Class |
|-----------|-------|
| `apps/worldview-web/app/error.tsx:96` | `rounded-md bg-primary px-5 py-2 ...` (recovery CTA on global error page) |
| `apps/worldview-web/app/not-found.tsx:63` | `rounded-md bg-primary px-5 py-2 ...` (404 recovery CTA) |
| `apps/worldview-web/app/login/page.tsx:264` | `rounded-md border border-destructive/50 ...` (login error banner — Phase A0) |
| `apps/worldview-web/features/dashboard/components/BriefDiffPanel.tsx:43` | `rounded-md border border-border bg-card p-3 ... shadow-md` (brief diff popover) |

`rounded-full` usage was checked — all instances are dots / pills / avatars / spinners / step-number badges, all legitimate. No violation there.

`rounded-sm` (e.g. `components/ui/dialog.tsx:59`) resolves to `calc(var(--radius) - 2px) = 0px` and is acceptable shadcn convention.

---

## 3. Tabular-nums missing on numeric output

The design rule (`DESIGN_SYSTEM.md:180–182`): **every** number rendered to the user MUST be in `font-mono tabular-nums`. Mixed mono/sans within a column is forbidden.

| File:line | What renders | Issue |
|-----------|--------------|-------|
| `apps/worldview-web/components/instrument/EntityGraph.tsx:493` | `Strength: {tooltip.weight.toFixed(2)}` (graph-edge tooltip) | Parent `<p className="mt-0.5 text-[10px] text-muted-foreground">` has no `tabular-nums` / `font-mono`. Hover tooltip shows `0.78`/`0.82`/`0.81` jittering as cursor moves. |
| `apps/worldview-web/app/(public)/status/page.tsx:140` | `{parseFloat(monitor.custom_uptime_ratio).toFixed(2)}% uptime (30d)` | Parent `<p className="text-[10px] tracking-wide ...">` — no `tabular-nums`. Status surface, lower priority (A0). |

**Note**: every hot demo-path numeric component I sampled (Holdings, Screener columns, KPI strips, FundamentalsTab, IntelligenceTab metrics, AnalystRail, CompactInstrumentHeader, CrosshairHUD, MarketHeatmap, AiSignals, KeyMetricsGrid, EvidenceTab, SessionStatsStrip, PreMarketMoversWidget, PortfolioKPIStrip) DOES have `font-mono tabular-nums`. The two findings above are the only unambiguous gaps in user-facing numeric output.

---

## 4. Density violations (PLAN-0071 Phase 6/6.5)

The Phase-6.5 sprint delivered: sidebar `h-9`→`h-7` (DONE — `CollapsibleSidebar.tsx:238`), ArticleRow `py-1 px-2` (DONE — `ArticleCard.tsx:120`), TopBar `h-8` (DONE — `TopBar.tsx:160`).

Remaining `h-9` rows are **legitimate** sticky sub-headers (per-page top bar inside the surface, not the navrail):

| File:line | Element | Verdict |
|-----------|---------|---------|
| `apps/worldview-web/app/(app)/screener/page.tsx:288` | `flex h-9 shrink-0 items-center border-b border-border` | Page-level sub-header. Acceptable per PRD-0031 §panel-header-height: TopBar at h-8, surface sub-headers at h-9 (24-row data underneath). |
| `apps/worldview-web/app/(app)/alerts/page.tsx:243` | `TabsList shrink-0 h-9 ...` | Tab strip — same justification. |
| `apps/worldview-web/app/(app)/instruments/page.tsx:134,159` | `flex h-9 shrink-0 items-center border-b border-border px-3` (×2) | Sub-headers, OK. |
| `apps/worldview-web/app/(app)/portfolio/page.tsx:217,335` | `flex h-9 items-center justify-between` and `TabsList shrink-0 h-9 ...` | Sub-header + tabs, OK. |
| `apps/worldview-web/features/portfolio/components/TransactionsTab.tsx:66` | `flex h-9 items-center gap-1.5 px-3` | Sub-header, OK. |
| `apps/worldview-web/features/portfolio/components/PortfolioPageHeader.tsx:78` | `flex h-9 shrink-0 items-center border-b border-border px-3 gap-3 bg-card` | Sub-header, OK. |

These `h-9` cases are NOT density violations.

### Genuinely loose padding

| File:line | Class | Concern |
|-----------|-------|---------|
| `apps/worldview-web/app/(app)/watchlists/page.tsx:99,116` | `flex flex-col items-start gap-2 p-4` (loading + error states) | `p-4` on what becomes a small inline state inside the watchlist sub-page. Could be `p-2` for terminal density. |
| `apps/worldview-web/app/(app)/watchlists/[id]/page.tsx:123,141` | `p-4 text-[11px]` and `flex flex-col items-start gap-2 p-4` | Same pattern. |
| `apps/worldview-web/app/(app)/news/page.tsx:163` | `flex flex-col items-start gap-2 p-4` | News page error state padding. |
| `apps/worldview-web/app/admin/feedback/page.tsx:163` | `mb-4 grid grid-cols-2 gap-3 ... p-4 sm:grid-cols-5` | Admin filter card — admin route, low-priority. |
| `apps/worldview-web/app/(app)/chat/page.tsx:704,777` | `flex flex-1 flex-col items-center justify-center gap-3 bg-background p-4` (empty state); `flex flex-col gap-3 p-4` (error/loading wrapper) | Empty / error states inside chat — `p-4` reads as consumer-app padding next to dense terminal panels. |
| `apps/worldview-web/components/shell/FlashOverlay.tsx:150` | `<div className="p-4">` | Flash overlay body — visible on alerts (Phase A surface). `p-4` is loose for an alert toast. |

---

## 5. Empty-state offenders

| File:line | Current copy | Issue |
|-----------|--------------|-------|
| `apps/worldview-web/features/dashboard/components/BriefEntityPill.tsx:130` | `{loading ? "Loading..." : ...}` | Three-dot ASCII; everywhere else uses ellipsis `…`. Inconsistent. |
| `apps/worldview-web/app/(app)/settings/beta-program/page.tsx:155` | `<div className="p-8 text-sm text-muted-foreground">Loading…</div>` | Plain "Loading…" with `p-8` — should be a `Skeleton` matching the page layout (per `components/ui/skeleton.tsx:6` doctrine: "Bloomberg-style 'loading…' indicators. Skeletons provide visual structure"). |
| `apps/worldview-web/app/admin/feedback/page.tsx:358` | `<div className="p-3 text-[11px] font-mono text-muted-foreground">Loading…</div>` | Admin route — same skeleton issue, lower priority. |
| `apps/worldview-web/app/(app)/chat/page.tsx:868` | `Context: {entityTicker ?? (looksLikeUuid ? "Loading…" : entityIdFromUrl)}` | Inline "Loading…" string in the chat header context badge — acceptable but verify it doesn't persist >1s during normal flow. |

**`—` placeholder usage** is correct — verified ~40 call sites all use the em dash for missing-data, matching the HeatCell null state and Bloomberg convention. Not a defect.

No raw `null` / `undefined` / `NaN` leaks into JSX (verified).

---

## 6. Component-library policy violations

CLAUDE.md says shadcn/ui only. `docs/ui/DESIGN_SYSTEM.md:18` repeats it: "shadcn/ui only — Radix UI primitives + Tailwind CSS; no other component library."

| File:line | Import | Verdict |
|-----------|--------|---------|
| `apps/worldview-web/components/ui/ag-grid/AgGridBase.tsx:8,17` | `from "ag-grid-react"`, `from "ag-grid-community"` | **NOT documented in DESIGN_SYSTEM.md**; consumed by `screener/ag-screener-columns.tsx`, `portfolio/ag-holdings-columns.tsx`, `portfolio/SemanticHoldingsTable.tsx`, `app/(app)/screener/page.tsx`, `app/providers.tsx`. AG Grid is a heavy non-shadcn data grid library shipped to production. Either policy-update DESIGN_SYSTEM.md to whitelist it (preferred — AG Grid is the right primitive for institutional data grids) or strip it. |
| `apps/worldview-web/components/portfolio/TransactionsTable.tsx:36` | `from "react-window"` | Virtualization helper, not a component lib. Acceptable but undocumented. |
| `apps/worldview-web/components/instrument/OHLCVChart.tsx:72` etc. | `from "lightweight-charts"` | TradingView charting; non-shadcn but acceptable as a *charting* library (DESIGN_SYSTEM never claims to cover charting). Documented in PLAN-0050. |
| `apps/worldview-web/components/instrument/EntityGraph.tsx` | sigma.js / cytoscape (graph viz) | Same — viz, not UI lib. ADR-F-08 / ADR-F-16. |
| `app/providers.tsx:20`, `components/ui/context-menu.tsx:38`, others | `from "sonner"` | shadcn-recommended toast primitive. Acceptable. |

All Radix imports are scoped inside `components/ui/*` (correct shadcn pattern). No competing UI library (antd / chakra / mui / mantine / nextui / react-bootstrap) found.

**Recommendation**: explicitly document AG Grid as the institutional data-grid primitive in DESIGN_SYSTEM.md §5 and section 14 (or remove it).

---

## 7. pnpm version-pinning violations

Memory rule: pnpm exact versions only — no `^`/`~`.

| File:line | Specifier |
|-----------|-----------|
| `apps/worldview-web/package.json:122` | `"openapi-typescript": "^7.13.0"` (devDependency) |

That is the **only** non-pinned entry — all 100+ other dependencies use exact versions. Single-line fix.

---

## Defect rows (YAML)

```yaml
- id: D-F3-001
  va: VA-5
  surface: A4   # Instrument Overview (EntityGraph rendered here)
  severity: HF-10
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. Open `/instruments/AAPL` (Overview tab)
    2. Hover any non-center node in the entity graph
    3. Inspect the dimmed sibling nodes — they receive `color: "#1A2030"` (retired Bloomberg-Dark `--muted`)
    4. Repeat on `/screener` — score column null cells render `bg #1A2030 / text #6B7585`
  evidence:
    - "components/instrument/EntityGraph.tsx:57,442,695,711,724"
    - "components/instrument/EntityGraphPanel.tsx:73-77,286,366"
    - "components/screener/HeatCell.tsx:60"
    - "components/brokerage/ConnectedBrokeragesList.tsx:234,314"
    - "components/instrument/OHLCVChart.tsx:571"
    - "lib/entity-types.ts:182"
  root_cause: |
    Inline `style={...}` and JS constants still carry the retired
    Bloomberg-Dark / Midnight-Pro palette (#1A2030, #6B7585, #0A0E14,
    #111820, #E0DDD4, #0EA5E9). The Terminal-Dark migration converted
    Tailwind tokens but missed inline-style and constant-defined hex.
  fix_decision: fix-now
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-002
  va: VA-5
  surface: A4   # Intelligence tab + entity sidebar (AliasPill, IntelligenceTab badges)
  severity: HF-10
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. Open `/instruments/AAPL/intelligence` (or any entity sidebar)
    2. Look at alias pills — they render `text-amber-300/400`, `text-sky-400`,
       `text-cyan-400`, `text-emerald-400`, `text-violet-400`, `text-zinc-300`
       — none are tokens.
    3. Same for entity-type badges in IntelligenceTab (`bg-purple-500/15`
       for person, `bg-orange-500/15` for macro_event).
  evidence:
    - "lib/alias-types.ts:54,59,64,69,74,79,84"
    - "components/instrument/IntelligenceTab.tsx:114,115"
    - "components/instrument/ChartToolbar.tsx:210"
    - "features/chat/components/ActionConfirmModal.tsx:139"
    - "features/dashboard/components/BriefEntityPill.tsx:108"
    - "features/dashboard/components/BriefDiffPanel.tsx:65,74"
    - "features/dashboard/components/BulletFeedback.tsx:85,86,105,106"
    - "features/dashboard/components/BriefRating.tsx:81,82,87"
    - "features/dashboard/components/BriefDiffBadge.tsx:89"
    - "features/chat/components/ToolCallIndicator.tsx:110"
  root_cause: |
    Tailwind shorthand colours (`text-amber-400`, `text-green-400`,
    `text-red-400`, `text-blue-400`, `text-emerald-400`, `text-orange-400`,
    `text-sky-400`, `text-cyan-400`, `text-violet-400`, `text-zinc-300`,
    `text-purple-400`, `text-pink-400`, `text-slate-400`) bypass the
    Terminal-Dark tokens (`text-positive`, `text-negative`, `text-warning`,
    `text-primary`, `text-muted-foreground`). The "WHY ..." comments above
    each violation acknowledge the choice but conflict with the canonical
    palette.
  fix_decision: fix-now
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-003
  va: VA-5
  surface: A0   # global error / 404 / login
  severity: HF-10
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. Trigger a route error → `app/error.tsx` recovery CTA renders `rounded-md`
    2. Hit a 404 → `app/not-found.tsx` recovery CTA renders `rounded-md`
    3. Open `/login` → wrong-credentials banner renders `rounded-md`
    4. Open Brief Diff popover from Morning Brief → renders `rounded-md`
  evidence:
    - "app/error.tsx:96"
    - "app/not-found.tsx:63"
    - "app/login/page.tsx:264"
    - "features/dashboard/components/BriefDiffPanel.tsx:43"
  root_cause: |
    Four hand-authored buttons / banners / popovers were never migrated
    to `rounded-[2px]` after `--radius` dropped from 0.375rem (6px) to
    0.125rem (2px). They render with 6px radius and look out of place
    next to the rest of the terminal UI.
  fix_decision: fix-now
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-004
  va: VA-5
  surface: A4
  severity: SF-1
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. Open any instrument with a populated entity graph
    2. Hover an edge — tooltip shows `Strength: 0.78`
    3. Hover a different edge — `0.82`. Watch the digits — they are NOT
       tabular-nums; the second digit jitters horizontally as you sweep.
  evidence:
    - "components/instrument/EntityGraph.tsx:493"
  root_cause: |
    The tooltip `<p className="mt-0.5 text-[10px] text-muted-foreground">`
    has no `font-mono tabular-nums`. Per DESIGN_SYSTEM.md:180 every
    user-facing number must be tabular.
  fix_decision: fix-now
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-005
  va: VA-5
  surface: A0   # public status page
  severity: SF-1
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. Open `/status`
    2. View any monitor card — uptime renders e.g. `99.97% uptime (30d)`
    3. Compare across cards — last digits jitter (no tabular-nums)
  evidence:
    - "app/(public)/status/page.tsx:140"
    - "app/(public)/status/page.tsx:74,76,78,102,169,171,172"
    - "app/(public)/status/components.ts:93,95,97,99,101"
  root_cause: |
    Status page predates the Terminal-Dark token migration. Uses
    `text-amber-500`, `text-red-500`, `text-zinc-500`, `bg-green-500`,
    `bg-amber-500/40`, `bg-red-500/80`, `bg-blue-500/40` shorthand
    classes; uptime numbers are not tabular-nums.
  fix_decision: fix-now
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-006
  va: VA-5
  surface: A4, A8, A6   # watchlists, news, chat empty/error states
  severity: SF-2
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. Open `/watchlists` while data is loading — `p-4` empty/loading box
    2. Open `/news` while loading — same `p-4` box
    3. Open `/chat` while waiting — `p-4` empty / loading wrapper
    4. Trigger an alert — `FlashOverlay` body has `p-4`
  evidence:
    - "app/(app)/watchlists/page.tsx:99,116"
    - "app/(app)/watchlists/[id]/page.tsx:123,141"
    - "app/(app)/news/page.tsx:163"
    - "app/(app)/chat/page.tsx:704,777"
    - "components/shell/FlashOverlay.tsx:150"
  root_cause: |
    PLAN-0071 Phase 6.5 density sweep didn't reach loading/empty/error
    state wrappers. `p-4` (16px) reads as consumer-app padding next to
    the surrounding terminal panels at `p-2` (8px) / `p-3` (12px).
  fix_decision: fix-now
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-007
  va: VA-5
  surface: A2   # morning brief
  severity: SF-2
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. Open dashboard with brief loaded
    2. Click an entity pill, then immediately the "Create Alert" affordance
    3. Loading copy says "Loading..." (three dots, ASCII)
    4. Compare to every other loading state on the page — they use "Loading…"
       (HORIZONTAL ELLIPSIS, U+2026)
  evidence:
    - "features/dashboard/components/BriefEntityPill.tsx:130"
  root_cause: |
    Single inconsistent string. The codebase otherwise uniformly uses
    "Loading…". `Loading...` reads more amateur next to the typographic
    ellipsis.
  fix_decision: fix-now
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-008
  va: VA-5
  surface: A9   # settings → beta-program
  severity: SF-3
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. Open `/settings/beta-program` while data loads
    2. See `<div className="p-8 text-sm text-muted-foreground">Loading…</div>`
       — bare text on huge padding instead of a Skeleton matching the page
       layout
  evidence:
    - "app/(app)/settings/beta-program/page.tsx:155"
    - "app/admin/feedback/page.tsx:358 (admin route, lower priority)"
  root_cause: |
    Loading state is a plain text node, not a Skeleton. `components/ui/skeleton.tsx:6`
    prescribes static (no animate-pulse) skeletons that mimic page structure.
  fix_decision: fix-now
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-009
  va: VA-5
  surface: A0  # cross-cutting policy
  severity: SF-3
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. `grep -rn "ag-grid" apps/worldview-web/components apps/worldview-web/app`
       → AgGridReact is consumed in screener and portfolio pages
    2. `grep -n "ag-grid" docs/ui/DESIGN_SYSTEM.md` → no mention
    3. CLAUDE.md and DESIGN_SYSTEM.md §1 say "shadcn/ui only"
  evidence:
    - "components/ui/ag-grid/AgGridBase.tsx:8,17"
    - "components/screener/ag-screener-columns.tsx:24"
    - "components/portfolio/ag-holdings-columns.tsx:22"
    - "components/portfolio/SemanticHoldingsTable.tsx:53"
    - "app/(app)/screener/page.tsx:45"
    - "app/providers.tsx:34"
  root_cause: |
    AG Grid was added (likely under PLAN-0059/F screener uplift) without
    a corresponding ADR or DESIGN_SYSTEM.md update. Either it should be
    documented as the institutional data-grid primitive (preferred) or
    replaced with a shadcn-compatible alternative.
  fix_decision: defer    # this is a docs / policy gap, not a runtime defect
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-010
  va: VA-5
  surface: A0  # build / dependency hygiene
  severity: SF-3
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. `grep -nE '"(\^|~)' apps/worldview-web/package.json`
    2. → `"openapi-typescript": "^7.13.0"`
  evidence:
    - "apps/worldview-web/package.json:122"
  root_cause: |
    Single non-pinned devDependency. Memory rule: pnpm exact versions only.
  fix_decision: fix-now   # 1-line edit
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""

- id: D-F3-011
  va: VA-5
  surface: A4
  severity: info
  status: open
  agent: F3
  found_at: 2026-05-09T10:18Z
  reproduce: |
    1. `grep -rn 'badgeClass' apps/worldview-web` — defined in
       `lib/entity-types.ts:47-184` but consumed nowhere
  evidence:
    - "lib/entity-types.ts:47–184"
  root_cause: |
    `badgeClass` was added during PLAN-0057 with the intent of being
    consumed by some future entity-badge component. The consumer never
    landed. The class strings carry off-palette colours (text-indigo-400,
    text-violet-400, ..., text-pink-400, text-slate-400) that would
    render off-brand if a consumer ever wires them.
  fix_decision: defer  # fix when a real consumer is needed
  fix_commit: ""
  validation_evidence: ""
  closed_at: ""
```

---

## Summary

| Section | Findings |
|---------|----------|
| 1A — Retired-palette hex (live) | 19 lines across 6 files |
| 1B — Off-palette tailwind shorthand (live) | 22 lines across 13 files |
| 1C — Entity taxonomic palette (live in graph) | 1 file, ~25 colours (info, decide policy) |
| 1D — Status / login non-token | ~14 lines in 3 files |
| 2 — Wrong radius | 4 sites |
| 3 — Tabular-nums missing | 2 sites |
| 4 — Density (loose padding) | 6 sites in 5 files |
| 5 — Empty-state copy | 4 sites |
| 6 — Component-library policy | AG Grid undocumented (consumed in 6 files) |
| 7 — pnpm pinning | 1 specifier |

**Severity counts**:
| Severity | Count |
|----------|-------|
| HF-10 | 3 (D-F3-001, -002, -003) |
| SF-1 | 2 (D-F3-004, -005) |
| SF-2 | 2 (D-F3-006, -007) |
| SF-3 | 3 (D-F3-008, -009, -010) |
| info | 1 (D-F3-011) |
| **Total** | **11** |

**Estimated fix effort**: D-F3-001/002/003/010 are large find-and-replace passes (1–2h each, mechanical). D-F3-004/005/007 are 1-line fixes. D-F3-006 is a 6-line padding sweep. D-F3-008 is a small Skeleton component swap. D-F3-009 is a docs decision. D-F3-011 is non-blocking. Total ≈ 6–8h to close all `fix-now` rows.
