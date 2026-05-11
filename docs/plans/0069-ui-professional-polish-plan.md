---
id: PLAN-0069
title: "UI Professional Polish — Bloomberg-Grade Terminal Hardening"
status: complete
created: 2026-05-03
updated: 2026-05-03
waves_done: 4
waves_total: 4
prd: N/A (investigation-driven)
---

# PLAN-0069 — UI Professional Polish: Bloomberg-Grade Terminal Hardening

> **Purpose**: Address all UI quality issues discovered in the 2026-05-03 comprehensive Bloomberg-grade terminal audit.
> Two rounds of investigation were conducted: Round 1 (instrument UI deep-dive + platform-wide background sweep) and Round 2 (additional surfaces: workspace, chat, settings, portfolio sub-components, screener detail).
> Every fix in this plan must meet the Bloomberg/Refinitiv Eikon bar — users have these tools in muscle memory.

---

## Context

### Audit Findings Summary

| Category | Count | Source |
|----------|-------|--------|
| Critical (single-class fixes) | 7 | Round 1 instrument + platform |
| High (structural layout fixes) | 11 | Round 1 instrument + platform |
| Medium (density / alignment) | 6 | Round 1 instrument |
| Feature gaps (missing signal wiring) | 3 | Round 1 instrument |
| Additional findings | TBD | Round 2 investigation (subagents) |

### Finance Client Mandate (Must Be Re-Read Before Every Wave)
- 11px data text, 10px labels
- h-[22px] rows, h-7 (28px) headers
- tabular-nums on ALL numbers
- strokeWidth={1.5} on ALL icons
- No hover:underline, no rounded-lg/xl on data surfaces
- No animate-pulse on data skeletons (use static skeleton bars)
- bg-background everywhere (not bg-card to avoid seam artifacts)

---

## Pre-flight: Codebase State Verification

All findings verified against actual source files on 2026-05-03.

| Finding | File | Line | Current State | Fix Required |
|---------|------|------|---------------|--------------|
| IC-001 | `components/instrument/AnalystConsensusStrip.tsx` | 70-88 | Equal-bar green/muted/red with "—" counts | Replace with "Analyst consensus loading…" pending state text |
| IC-002 | `app/(app)/instruments/[entityId]/page.tsx` | 277,280,281,282 | 4× `text-xs` on TabsTriggers | `text-[11px]` |
| IC-003 | `components/instrument/FundamentalsTab.tsx` | 389 | ⚠ Unicode character in JSX | Lucide `AlertTriangle` icon |
| IC-004 | `components/instrument/IntelligenceTab.tsx` | 65 | `rounded-full border-2 animate-spin` div | `<RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />` |
| IH-001 | `app/(app)/instruments/[entityId]/page.tsx` | 275 | TabsList `px-4` | `px-2` |
| IH-002 | `components/instrument/InstrumentAISubheader.tsx` | 177 | `h-9` collapsed state | `h-7` |
| IH-003 | `app/(app)/instruments/[entityId]/page.tsx` | 212 | `hover:underline` + `→` Unicode on not-found | Remove underline; replace `→` with Lucide `ArrowRight h-3 w-3` |
| IH-004 | `components/instrument/SessionStatsStrip.tsx` | 122 | `bg-card` | `bg-background` |
| IH-005 | `components/instrument/TechnicalSnapshot.tsx` | — | No price-relative MA coloring | Add `currentPrice` prop; color 50DMA/200DMA green/red/muted |
| IH-006 | `components/instrument/OverviewLayout.tsx` | 307-326 | Native `<select>` in SparklinePanel | shadcn `Select` with `h-6 text-[11px]` |
| IH-007 | `components/instrument/OverviewLayout.tsx` | 283,300 | EntityGraph `h-[280px]`; Sparklines `height={48}` | `h-[400px]`; `height={68}` |
| IH-008 | `components/instrument/FundamentalsTab.tsx` | 412 | `lg:grid-cols-3` | Remove (keep `md:grid-cols-2`) |
| IM-001 | `components/instrument/OverviewLayout.tsx` | 307 | SparklinePanel label hardcoded "TREND" | Dynamic label from metric name |
| IM-002 | `components/instrument/FundamentalsTab.tsx` | ~350 | MetricRow uses `py-1 items-baseline` | Normalize to `h-[22px] items-center` |
| IM-003 | `components/instrument/OverviewLayout.tsx` | ~200 | Bottom grid no min-height | `min-h-[320px]` on graph+sparkline container |
| A-001 | `app/(app)/alerts/page.tsx` | 199 | `text-lg` section header | `text-[11px] uppercase tracking-[0.08em] text-muted-foreground` |
| A-003 | `app/(app)/alerts/page.tsx` | 413, 518 | `h-8 w-8` icons in empty/error states | `h-4 w-4 strokeWidth={1.5}` |
| A-004 | `app/(app)/alerts/page.tsx` | 398, 503 | `text-sm` error text | `text-[11px]` |
| MB-001 | `components/dashboard/MorningBriefCard.tsx` | 81 | `animate-pulse` skeleton | Static skeleton (no animation) |
| MB-004 | `components/dashboard/MorningBriefCard.tsx` | — | `hover:underline` on brief links | Remove |
| D-002 | `app/(app)/dashboard/page.tsx` | — | Inconsistent grid cell border opacity | Unify to `border-border/40` |
| A-006 | `app/(app)/alerts/page.tsx` | — | Tab trigger icon sizing | `h-3 w-3 strokeWidth={1.5}` on all tab icons |
| P-003 | `features/portfolio/components/*.tsx` | — | Tab trigger sizing inconsistent | `text-[11px]` on all tab triggers |
| MB-003 | `components/dashboard/MorningBriefCard.tsx` | — | Hardcoded 152px timestamp column width | `min-w-[120px] max-w-[140px]` fluid |

---

## Wave A — Critical Single-Class Fixes

**Goal**: Apply all IC-* and A-00* critical fixes — isolated text/class changes that cannot cause regressions.
**Depends on**: none
**Estimated effort**: 45–75 minutes
**Architecture layer**: frontend components

### Pre-read (agent must read before starting)
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx`
- `apps/worldview-web/components/instrument/AnalystConsensusStrip.tsx`
- `apps/worldview-web/components/instrument/FundamentalsTab.tsx`
- `apps/worldview-web/components/instrument/IntelligenceTab.tsx`
- `apps/worldview-web/app/(app)/alerts/page.tsx`
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`

### Tasks

#### T-A-1-01: Fix tab trigger font sizes on Instrument page and Alerts page

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (lines ~275–285)
- `apps/worldview-web/app/(app)/alerts/page.tsx` (line ~199 + tab triggers)

**What to build**:
Instrument page has 4 TabsTrigger elements using `text-xs` (12px) — must be `text-[11px]`. TabsList uses `px-4` — must be `px-2`. Alerts page has a section header using `text-lg` that must be `text-[11px] uppercase tracking-[0.08em] text-muted-foreground`. All tab trigger icons in alerts must be `h-3 w-3 strokeWidth={1.5}`.

**Acceptance criteria**:
- [ ] All 4 Instrument TabsTrigger elements use `text-[11px]` (not `text-xs`)
- [ ] Instrument TabsList uses `px-2` (not `px-4`)
- [ ] Alerts section header font is `text-[11px] uppercase tracking-[0.08em] text-muted-foreground`
- [ ] All tab trigger icon sizing consistent `h-3 w-3 strokeWidth={1.5}`
- [ ] `pnpm --filter worldview-web lint && pnpm --filter worldview-web typecheck` pass

---

#### T-A-1-02: Replace Unicode symbols with Lucide icons

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/FundamentalsTab.tsx` (line ~389)
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (line ~212)

**What to build**:
FundamentalsTab has a coverage banner using `⚠` Unicode character. Replace with `<AlertTriangle className="h-3 w-3 text-yellow-500 shrink-0" strokeWidth={1.5} />`. The not-found state in page.tsx uses `→` Unicode arrow — replace with `<ArrowRight className="h-3 w-3" strokeWidth={1.5} />` and remove `hover:underline`.

**Logic & Behavior**:
- Import `AlertTriangle, ArrowRight` from `lucide-react`
- The `⚠` currently appears inside a `<span>` — replace the span content with the icon component
- The `→` appears in an anchor/link element — wrap with flex + gap, replace character with icon

**Acceptance criteria**:
- [ ] No Unicode code points above U+25FF in any TSX file (use `grep -r "[⚠✓→←]" apps/worldview-web` to verify)
- [ ] FundamentalsTab coverage banner uses AlertTriangle icon
- [ ] Not-found back link uses ArrowRight icon, no hover:underline
- [ ] lint + typecheck pass

---

#### T-A-1-03: Fix IntelligenceTab spinner to terminal standard

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/IntelligenceTab.tsx` (line ~65)

**What to build**:
The loading spinner uses a `div` with `rounded-full border-2 border-t-primary animate-spin h-8 w-8` — this is a consumer fintech pattern, not terminal style. Replace with `<RefreshCw className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />`.

**Acceptance criteria**:
- [ ] No `rounded-full border-2 animate-spin` div in IntelligenceTab
- [ ] Uses Lucide RefreshCw with `h-4 w-4 animate-spin text-muted-foreground strokeWidth={1.5}`
- [ ] lint + typecheck pass

---

#### T-A-1-04: Fix AnalystConsensusStrip broken placeholder

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/AnalystConsensusStrip.tsx` (lines ~70–88)

**What to build**:
The current placeholder renders three equal-width flex-1 green/muted/red bars with "—" counts — this looks like a broken chart. Replace with a simple pending state: a single row with `<span className="text-[11px] text-muted-foreground">Analyst consensus data unavailable</span>`. Preserve the actual data-loaded rendering path; only the no-data/zero-analyst-count branch needs changing.

**Logic & Behavior**:
- Read the component to understand when the empty bars render (likely when `analysts === 0` or data is null)
- Replace that branch with a clean text fallback row matching instrument row height `h-[22px]`
- Do NOT change the fully-loaded data rendering

**Acceptance criteria**:
- [ ] Zero-analyst state shows a single text row, not broken bars
- [ ] Data-loaded state unchanged
- [ ] lint + typecheck pass

---

#### T-A-1-05: Fix alerts page error/empty state icon sizing + text

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/app/(app)/alerts/page.tsx` (lines ~398, 413, 503, 518)

**What to build**:
Error and empty states in alerts page have `h-8 w-8` icons (too large for a terminal) and `text-sm` body text. Fix: `h-4 w-4 strokeWidth={1.5}` on all icons in these states; `text-[11px]` on all error/empty state body text.

**Acceptance criteria**:
- [ ] No `h-8 w-8` on icons in error/empty states in alerts page
- [ ] No `text-sm` on error/empty body text in alerts page
- [ ] lint + typecheck pass

---

#### T-A-1-06: Fix MorningBriefCard animate-pulse and hover:underline

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx` (lines ~75–90)

**What to build**:
MorningBriefCard skeleton uses `animate-pulse` — terminal skeletons are static. Brief links have `hover:underline` — terminals don't use underline affordances. Fix both.

**Acceptance criteria**:
- [ ] No `animate-pulse` in MorningBriefCard
- [ ] No `hover:underline` on brief content links in MorningBriefCard
- [ ] lint + typecheck pass

---

### Validation Gate
- [ ] `pnpm --filter worldview-web lint` passes
- [ ] `pnpm --filter worldview-web typecheck` passes
- [ ] `pnpm --filter worldview-web test` passes (no regressions)
- [ ] `pnpm --filter worldview-web build` passes

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/alerts-*.test.tsx` (if exists) | Icon size assertions may snapshot-match `h-8 w-8` | Update assertions to `h-4 w-4` |
| `__tests__/morning-brief-*.test.tsx` (if exists) | Skeleton class assertions may include `animate-pulse` | Remove from expected class strings |

### Regression Guardrails
- **BP-357**: Never introduce Unicode code points above U+25FF — verify with grep after IC-003/IH-003 fixes
- **BP-182**: Do not add `hover:underline` to terminal links — this wave removes it

---

## Wave B — Layout and Density Polish

**Goal**: Fix structural layout issues — SessionStatsStrip seam, tab sizing, AI subheader height, native select replacement, FundamentalsTab grid, MA coloring.
**Depends on**: Wave A (IC-003 imports Lucide — Wave B may reuse same imports)
**Estimated effort**: 90–150 minutes
**Architecture layer**: frontend components

### Pre-read (agent must read before starting)
- `apps/worldview-web/components/instrument/SessionStatsStrip.tsx`
- `apps/worldview-web/components/instrument/InstrumentAISubheader.tsx`
- `apps/worldview-web/components/instrument/OverviewLayout.tsx`
- `apps/worldview-web/components/instrument/FundamentalsTab.tsx`
- `apps/worldview-web/components/instrument/TechnicalSnapshot.tsx`
- `apps/worldview-web/app/(app)/dashboard/page.tsx`
- `apps/worldview-web/features/portfolio/components/` (scan for tab trigger inconsistencies)

### Tasks

#### T-B-2-01: Fix SessionStatsStrip bg-card seam

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/SessionStatsStrip.tsx` (line ~122)

**What to build**:
SessionStatsStrip uses `bg-card` which creates a visible seam below the OHLCV chart. Change to `bg-background` to match the chart background.

**Acceptance criteria**:
- [ ] `bg-card` replaced with `bg-background` in the outermost container
- [ ] lint + typecheck pass

---

#### T-B-2-02: Fix InstrumentAISubheader collapsed height

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/InstrumentAISubheader.tsx` (line ~177)

**What to build**:
Collapsed subheader uses `h-9` (36px) — non-standard for terminal rows. Change to `h-7` (28px). Verify the collapsed trigger button still renders properly at this height.

**Acceptance criteria**:
- [ ] Collapsed state uses `h-7` (not `h-9`)
- [ ] Expanded state height unchanged
- [ ] lint + typecheck pass

---

#### T-B-2-03: Replace native select with shadcn Select in SparklinePanel

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/OverviewLayout.tsx` (lines ~307–326)

**What to build**:
SparklinePanel uses a native `<select>` element for metric selection — this renders with OS-default styling (completely wrong for a terminal). Replace with shadcn `<Select>` using `h-6 text-[11px]` sizing. Also fix the label to be dynamic based on the selected metric (currently hardcoded "TREND").

**Entities / Components**:
- Import `Select, SelectContent, SelectItem, SelectTrigger, SelectValue` from `@/components/ui/select`
- Use `className="h-6 text-[11px]"` on `SelectTrigger`
- Map metric name to a readable label: `{ close: 'PRICE', volume: 'VOLUME', rsi: 'RSI', macd: 'MACD', returns: 'RETURN' }` (or whatever the actual metric options are — read the component first)

**Acceptance criteria**:
- [ ] No native `<select>` element in OverviewLayout
- [ ] shadcn Select renders with `h-6 text-[11px]` on trigger
- [ ] SparklinePanel label is dynamic (not hardcoded "TREND")
- [ ] lint + typecheck pass

---

#### T-B-2-04: Fix FundamentalsTab grid and MetricRow height

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/FundamentalsTab.tsx` (lines ~350, ~412)

**What to build**:
Two issues: (1) The sections grid uses `lg:grid-cols-3` which creates an empty cell with 8 sections — change to just `md:grid-cols-2`. (2) MetricRow uses `py-1 items-baseline` — normalize to `h-[22px] items-center` for consistent row height.

**Logic & Behavior**:
- Search for all MetricRow usages and ensure the row container div uses `h-[22px]` (not `py-*`)
- If MetricRow is a component, update the component's root element; if it's inline JSX, update each occurrence
- Remove `lg:grid-cols-3` from the sections grid

**Acceptance criteria**:
- [ ] No `lg:grid-cols-3` in FundamentalsTab
- [ ] All MetricRow containers use `h-[22px]` row height
- [ ] lint + typecheck pass

---

#### T-B-2-05: Add EntityGraph min-height and fix Sparkline heights

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/OverviewLayout.tsx` (lines ~283, ~300)

**What to build**:
EntityGraph container is `h-[280px]` — too small for useful graph visualization. Change to `h-[400px]`. Sparkline chart elements use `height={48}` — too compressed. Change to `height={68}`. Also add `min-h-[320px]` to the bottom grid container (graph + sparklines) to prevent empty panels.

**Acceptance criteria**:
- [ ] EntityGraph container uses `h-[400px]`
- [ ] Sparkline height prop is `68` (not `48`)
- [ ] Bottom grid container has `min-h-[320px]`
- [ ] lint + typecheck pass

---

#### T-B-2-06: Add price-relative MA coloring to TechnicalSnapshot

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/TechnicalSnapshot.tsx`
- `apps/worldview-web/components/instrument/FundamentalsTab.tsx` (line ~760 — where TechnicalSnapshot is instantiated)

**What to build**:
TechnicalSnapshot displays 50DMA and 200DMA values but does not color-code them relative to current price. A terminal trader reads this in <1 second: if price > MA, it's a bullish signal (green); if price < MA, bearish (red); if within 0.5%, neutral (muted).

**Logic & Behavior**:
1. Add `currentPrice?: number` prop to TechnicalSnapshot
2. For 50DMA and 200DMA value spans, compute:
   ```
   if !currentPrice || !maValue → text-muted-foreground
   if currentPrice > maValue * 1.005 → text-[#26A69A] (bull green)
   if currentPrice < maValue * 0.995 → text-[#EF5350] (bear red)
   else → text-muted-foreground (within 0.5%)
   ```
3. In FundamentalsTab, pass `currentPrice={instrument.price ?? instrument.last_price}` (or equivalent — read the component to find the right field)
4. Add a WHY comment on the coloring logic

**Acceptance criteria**:
- [ ] TechnicalSnapshot accepts `currentPrice` prop
- [ ] 50DMA/200DMA values colored bull/bear/neutral relative to currentPrice
- [ ] FundamentalsTab passes currentPrice
- [ ] lint + typecheck pass

---

#### T-B-2-07: Fix dashboard grid border consistency and portfolio tab sizing

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/app/(app)/dashboard/page.tsx`
- `apps/worldview-web/features/portfolio/components/` (tab trigger files)

**What to build**:
Dashboard grid cells have inconsistent border opacities — some use `border-border`, others `border-border/40`, others `border-border/60`. Unify to `border-border/40`. Portfolio tab triggers have inconsistent `text-sm` vs `text-xs` — normalize to `text-[11px]`.

**Acceptance criteria**:
- [ ] All dashboard grid cell borders use `border-border/40` (verify with grep)
- [ ] All portfolio tab triggers use `text-[11px]`
- [ ] lint + typecheck pass

---

#### T-B-2-08: Fix MorningBriefCard timestamp column width

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`

**What to build**:
Timestamp column in brief articles has a hardcoded 152px width. This is too rigid — on narrow breakpoints it clips the content, and on wide viewports it wastes space. Change to `min-w-[120px] max-w-[140px]` (fluid within a range).

**Acceptance criteria**:
- [ ] No hardcoded `w-[152px]` on timestamp column
- [ ] Uses `min-w-[120px] max-w-[140px]`
- [ ] lint + typecheck pass

---

### Validation Gate
- [ ] `pnpm --filter worldview-web lint` passes
- [ ] `pnpm --filter worldview-web typecheck` passes
- [ ] `pnpm --filter worldview-web test` passes
- [ ] `pnpm --filter worldview-web build` passes

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/technical-snapshot*.test.tsx` (if exists) | New `currentPrice` prop | Add prop to test renders |
| `__tests__/overview-layout*.test.tsx` (if exists) | Native select replaced with shadcn | Update query from `getByRole("combobox")` or similar |

### Regression Guardrails
- **BP-182**: Only use shadcn primitives — the native select replacement must use shadcn Select, not custom HTML
- **BP-357**: No new Unicode introduced

---

## Wave C — Feature Gap Wiring (Signal Indicators)

**Goal**: Wire up missing signal features — next earnings date in header, price vs MA signal chip, and display real analyst count when available.
**Depends on**: Wave B (TechnicalSnapshot currentPrice prop from T-B-2-06)
**Estimated effort**: 2–3 hours
**Architecture layer**: frontend components + gateway client

### Pre-read (agent must read before starting)
- `apps/worldview-web/components/instrument/CompactInstrumentHeader.tsx` (if exists) or equivalent header component
- `apps/worldview-web/components/instrument/OverviewLayout.tsx`
- `apps/worldview-web/lib/gateway.ts` — check if earnings date endpoint exists
- `apps/worldview-web/components/instrument/AnalystConsensusStrip.tsx`
- `docs/services/api-gateway.md` — verify available S9 endpoints

### Tasks

#### T-C-3-01: Add next earnings date to instrument header

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- Header component for the instrument detail page (find by reading page.tsx)
- `apps/worldview-web/lib/gateway.ts` (if `getEarningsCalendar` missing)

**What to build**:
Professional terminals always show next earnings date in the instrument header. If `getEarningsCalendar` exists in gateway, use it. The earnings date should appear as a compact chip in the second row of the instrument header: `NEXT ERN  MM/DD` in `text-[10px] text-muted-foreground font-mono`. If the earnings endpoint does not exist in S9, add a `TODO` comment and render nothing (never mock data).

**Logic & Behavior**:
1. Check `lib/gateway.ts` for `getEarningsCalendar` method
2. Check `docs/services/api-gateway.md` for the earnings endpoint path
3. If endpoint exists: use `useQuery` with `['earnings', entityId]` key; render nearest future date
4. Format: `new Date(date).toLocaleDateString('en-US', { month: '2-digit', day: '2-digit' })` → `MM/DD`
5. Show as `NEXT ERN  ${formattedDate}` with a `Calendar` Lucide icon `h-3 w-3`

**Acceptance criteria**:
- [ ] If S9 earnings endpoint exists: next earnings date renders in instrument header
- [ ] If endpoint does not exist: nothing renders (no placeholder, no TODO visible to user)
- [ ] Date format is MM/DD, font is mono, text is 10px
- [ ] lint + typecheck pass

---

#### T-C-3-02: Add price vs MA signal chip to OverviewSidebarMetrics

**Type**: impl
**depends_on**: T-B-2-06
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/OverviewLayout.tsx` (sidebar metrics section)

**What to build**:
Add a "MA Signal" chip to the sidebar metrics section. This is a single-row indicator:
- If `currentPrice > sma50 > sma200`: `BULLISH (price above both MAs)` in green
- If `currentPrice < sma50 && sma50 < sma200`: `BEARISH (price below both MAs)` in red
- Otherwise: `NEUTRAL` in muted

Render as a compact badge: `<span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded-sm bg-[color]/10 text-[color]">LABEL</span>`

**Acceptance criteria**:
- [ ] MA Signal chip renders in sidebar when price + MA data are available
- [ ] Correct color logic (bull/bear/neutral)
- [ ] Renders nothing when data unavailable (no empty badge)
- [ ] lint + typecheck pass

---

#### T-C-3-03: Wire analyst consensus real data

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/instrument/AnalystConsensusStrip.tsx`
- `apps/worldview-web/lib/gateway.ts`

**What to build**:
Check if S9 has an analyst consensus endpoint. If yes, wire it. If not, check `docs/services/api-gateway.md`. This component should show: Buy/Hold/Sell counts from real data when available. If no endpoint exists, the T-A-1-04 fix (pending state text) is sufficient for now — document this as requiring backend work.

**Logic & Behavior**:
1. Search `docs/services/api-gateway.md` for analyst/consensus endpoints
2. If found: add `getAnalystConsensus(entityId)` to gateway.ts; replace pending state with `useQuery` data
3. If not found: leave T-A-1-04 fix in place; add code comment `// TODO: wire when S9 /api/v1/instruments/{id}/consensus route available`

**Acceptance criteria**:
- [ ] If S9 endpoint exists: real data displayed
- [ ] If no endpoint: pending state (from Wave A) preserved, TODO comment added
- [ ] lint + typecheck pass

---

### Validation Gate
- [ ] `pnpm --filter worldview-web lint` passes
- [ ] `pnpm --filter worldview-web typecheck` passes
- [ ] `pnpm --filter worldview-web test` passes
- [ ] `pnpm --filter worldview-web build` passes

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Any test using `AnalystConsensusStrip` | Data-wiring changes render shape | Update test mocks to return analyst data |

### Regression Guardrails
- **BP-182**: Never call backend services directly — all data via gateway.ts → S9
- Check `docs/services/api-gateway.md` before adding any new gateway method — route must exist

---

## Wave D — Round 2 Investigation Findings

**Goal**: Implement fixes discovered by the Round 2 background investigation subagents covering: workspace surface, chat surface, settings page, and additional portfolio sub-components.
**Depends on**: Wave A (baseline fixes applied)
**Estimated effort**: TBD based on Round 2 findings
**Architecture layer**: frontend components (various surfaces)

> **NOTE**: This wave's tasks will be populated after Round 2 investigation subagents complete. The plan file will be updated with specific task entries. The wave is reserved here to prevent plan ID conflicts.

### Surfaces covered by Round 2 investigation
1. **Workspace page** — panel headers, chart toolbar, symbol picker, layout controls
2. **Chat / RAG surface** — message bubbles, code blocks, citation chips, input bar
3. **Settings page** — form fields, section headers, toggle sizing
4. **Portfolio sub-components** — `CashManagementCard`, `SemanticHoldingsTable`, `RealizedPnLChart`, `PortfolioAnalyticsPanel`
5. **Screener detail** — column headers, filter chips, sort indicators, pagination controls
6. **Morning brief full page** — if separate from dashboard card
7. **Prediction markets page** — typography, category pills, table density

### Round 2 Findings Summary

| ID | File | Line | Severity | Issue |
|----|------|------|----------|-------|
| UI-001 | `components/ui/skeleton.tsx` | 24 | CRITICAL | `animate-pulse` on ALL skeletons — affects every loading state |
| UI-002 | `components/instrument/IntelligenceTab.tsx` | 65 | CRITICAL | CSS spinner div (already duplicates IC-004 — verify if Wave A fixed it) |
| UI-003 | `components/ui/tabs.tsx` | 44 | HIGH | `text-xs` default on TabsTrigger — 12px on every tab in app |
| UI-004 | `components/ui/card.tsx` | 71 | HIGH | `text-sm` on CardTitle default — explains all settings/portfolio CardTitle violations |
| UI-005 | `components/ui/data-table/data-table.tsx` | 533,538,543 | HIGH | Sort chevrons missing `strokeWidth={1.5}` |
| UI-006 | `components/ui/data-table/data-table.tsx` | 416,465,475 | HIGH | Copy/Download icons missing `strokeWidth={1.5}` |
| GLOBAL | Entire `apps/worldview-web` | — | HIGH | `strokeWidth={1.5}` systematically absent from ALL Lucide icons |
| WS-001 | `components/workspace/WorkspaceGrid.tsx` | 160 | CRITICAL | `text-xl` on close button |
| WS-002 | `components/workspace/WorkspaceChatWidget.tsx` | — | CRITICAL | `animate-pulse` on cursor character |
| WS-003 | `components/workspace/WorkspacePortfolioPanel.tsx` | 65,95 | CRITICAL | `hover:underline` on links |
| WS-004 | `components/workspace/SymbolLinkColorPicker.tsx` | — | CRITICAL | `rounded-full` on interactive control |
| WS-005 | `components/chat/SlashCommandCard.tsx` | 116 | HIGH | `animate-pulse` on skeleton divs |
| WS-006 | `components/chat/SlashCommandCard.tsx` | 163,165,224,227,235,251 | HIGH | Text sizes 12–15px on data content |
| WS-007 | `components/chat/SlashCommandCard.tsx` | 445 | HIGH | `hover:underline` on ScreenerCard link |
| WS-008 | `components/chat/SlashCommandAutocomplete.tsx` | 85 | HIGH | `text-[12px]` on command list items |
| WS-009 | `app/(app)/chat/page.tsx` | 661 | HIGH | `text-[12px]` on starter question buttons |
| WS-010 | `features/chat/components/MessageBubble.tsx` | 60-62 | MEDIUM | `animate-bounce` on typing indicator dots |
| WS-011 | `features/chat/components/SlashTurnBlock.tsx` | 27-28 | MEDIUM | `text-sm` applied twice (parent + child = 14px effective) |
| CH-001 | `app/(app)/chat/page.tsx` | 451 | CRITICAL | MessageSquare icon missing `strokeWidth={1.5}` |
| CH-002 | `app/(app)/chat/page.tsx` | 450,468 | CRITICAL | Plus icons missing `strokeWidth={1.5}` |
| CH-008 | `components/chat/SlashCommandCard.tsx` | 159,217,286,348,397,442 | HIGH | 6 card icons missing `strokeWidth={1.5}` |
| SP-001 | `app/(app)/alerts/page.tsx` | 199 | CRITICAL | `text-lg` — already in Wave A T-A-1-01 |
| SP-002 | `app/(app)/alerts/page.tsx` | 398,414 | HIGH | `text-sm` on error messages — already in Wave A T-A-1-05 |
| SP-003 | `app/(app)/alerts/page.tsx` | 401,510 | HIGH | `hover:underline` on retry links |
| SP-004 | `app/(app)/news/page.tsx` | 269 | HIGH | `text-[12px]` on article titles |
| ST-001..010 | `app/(app)/settings/_components/tabs.tsx` | 89,104,148,208,248,280 | CRITICAL | `text-sm` CardTitles (root cause: UI-004 card.tsx fix cascades to these) |
| ST-013 | `app/(app)/settings/layout.tsx` | 86 | HIGH | Nav icons missing `strokeWidth={1.5}` |
| PO-001 | `features/portfolio/components/PortfolioPageHeader.tsx` | 79 | CRITICAL | `font-sans` on portfolio header |
| PO-006 | `features/portfolio/components/AddPositionDialog.tsx` | 173 | CRITICAL | `text-[13px]` on DialogTitle |
| PO-007 | `features/portfolio/components/CreatePortfolioDialog.tsx` | 165 | CRITICAL | `text-[13px]` on DialogTitle |
| PO-008 | `features/portfolio/components/DeletePortfolioDialog.tsx` | 65 | CRITICAL | Default heading size on DialogTitle |
| PO-011 | `features/portfolio/components/AddPositionDialog.tsx` | 201 | HIGH | `text-[12px]` on input text |
| PO-012 | `features/portfolio/components/CreatePortfolioDialog.tsx` | 195 | HIGH | `text-[12px]` on input text |
| SC-005..016 | `components/screener/` | various | HIGH | 12 screener icons missing `strokeWidth={1.5}` (covered by global fix) |
| SC-019 | `components/screener/SavedScreensDialog.tsx` | 128 | HIGH | `text-[12px]` on dialog title |
| UI-007 | `app/(app)/alerts/page.tsx` | 242,246,250 | HIGH | Tab icons missing `strokeWidth={1.5}` (covered by global) |
| UI-008 | `app/(app)/watchlists/page.tsx` | 74,175,186 | HIGH | 3 icons missing `strokeWidth={1.5}` (covered by global) |

### Tasks

#### T-D-4-01: Fix shared primitive root causes (skeleton, tabs, card)

**Type**: impl
**depends_on**: none
**blocks**: T-D-4-02
**Target files**:
- `apps/worldview-web/components/ui/skeleton.tsx`
- `apps/worldview-web/components/ui/tabs.tsx`
- `apps/worldview-web/components/ui/card.tsx`

**What to build**:
Three shared primitives have wrong defaults that cascade to every consumer. Fix each at the primitive level — it's more reliable than patching each callsite.

**skeleton.tsx**: Remove `animate-pulse` from the base class. Bloomberg terminal skeletons are static bars. The custom `skeleton-pulse` keyframe can remain in the CSS (for intentional opt-in use) but must not be the default. Replace `animate-pulse` with no animation.

**tabs.tsx**: TabsTrigger's base className includes `text-xs` (12px). Change to `text-[11px]`. This immediately fixes all TabsTrigger instances across the app.

**card.tsx**: CardTitle uses `text-sm` (12px). Change to `text-[11px]`. This immediately fixes all 10+ settings section headers, all dashboard widget titles, and all portfolio card headers.

**WHY fix primitives not callsites**: There are 100+ skeleton instances, 30+ CardTitle instances, and 40+ TabsTrigger instances. Patching callsites creates drift; fixing the primitive enforces the standard at the root.

**Logic & Behavior**:
- Read each file before editing to understand the full class composition
- For skeleton.tsx: the class composition is likely `cn("animate-pulse rounded-md bg-muted", className)` → remove `animate-pulse`
- For tabs.tsx: search for `text-xs` in the TabsTrigger `cva` variants or base className → change to `text-[11px]`
- For card.tsx: search for CardTitle's className (usually inside a `cn()` call with `text-sm`) → change to `text-[11px]`
- Do NOT change any other styles — minimum viable diff only

**Downstream test impact**:
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| Any test asserting `animate-pulse` on skeletons | Class removed from primitive | Update assertion to not expect `animate-pulse` |
| Any test asserting `text-xs` on TabsTrigger | Class changed to `text-[11px]` | Update assertion |
| Any test asserting `text-sm` on CardTitle | Class changed to `text-[11px]` | Update assertion |

**Acceptance criteria**:
- [ ] `skeleton.tsx` has no `animate-pulse` in its default class
- [ ] `tabs.tsx` TabsTrigger uses `text-[11px]` (not `text-xs`)
- [ ] `card.tsx` CardTitle uses `text-[11px]` (not `text-sm`)
- [ ] `pnpm --filter worldview-web test` passes (fix broken snapshot/class assertions)
- [ ] `pnpm --filter worldview-web lint && pnpm --filter worldview-web typecheck` pass

---

#### T-D-4-02: Global Lucide icon strokeWidth={1.5} pass

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**: All `*.tsx` files in `apps/worldview-web` containing Lucide icon imports

**What to build**:
Every Lucide icon in the codebase is missing `strokeWidth={1.5}`. The default Lucide stroke is 2px — too heavy for a data-dense terminal. This must be fixed globally.

**Strategy**: Two options — (A) grep-based targeted fix per file, or (B) set a global default. **Option B is preferred** if Lucide supports it. Check if `apps/worldview-web/components/ui/` has a wrapper or if `lucide-react` supports a global config. If not, do a targeted fix on the highest-impact files:

Priority order for manual patching:
1. `components/ui/data-table/data-table.tsx` (ChevronUp, ChevronDown, ChevronsUpDown, Copy, Download)
2. `components/chat/SlashCommandCard.tsx` (TrendingUp, Briefcase, Newspaper, ListChecks, AlertCircle, Search)
3. `app/(app)/chat/page.tsx` (MessageSquare, Plus, Search, Download, Send)
4. `components/screener/` (ChevronDown, Settings2, Check, RotateCcw, GripVertical, Save, FolderOpen, Trash2, Download, FileText, FileSpreadsheet, FileImage)
5. `app/(app)/settings/layout.tsx` (nav icons)
6. `features/portfolio/components/PortfolioPageHeader.tsx` (ChevronDown, Plus, Trash2)
7. `app/(app)/alerts/page.tsx` (BellRing, Newspaper, TrendingUp)
8. `app/(app)/watchlists/page.tsx` (Eye, ListChecks, Plus)
9. `app/(app)/settings/beta-program/page.tsx` (Beaker, Loader2)

**WHY manual per-file (not regex sed)**: A regex substitution like `s/<(\w+) className/< $1 strokeWidth={1.5} className/g` would break icons that already have `strokeWidth={1.5}` (duplicating it) and icons inside complex JSX expressions. Manual per-file review is safer.

**If Lucide global config is available**: Check if `lucide-react` v0.4+ supports `<LucideProvider strokeWidth={1.5}>` — if yes, wrap `app/layout.tsx` and skip per-file patching.

**Acceptance criteria**:
- [ ] All icons in the listed files have explicit `strokeWidth={1.5}`
- [ ] No duplicated strokeWidth on icons that already had it
- [ ] `pnpm --filter worldview-web lint && pnpm --filter worldview-web typecheck` pass

---

#### T-D-4-03: Fix workspace surface violations

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/workspace/WorkspaceGrid.tsx` (line ~160)
- `apps/worldview-web/components/workspace/WorkspaceChatWidget.tsx`
- `apps/worldview-web/components/workspace/WorkspacePortfolioPanel.tsx` (lines ~65, ~95)
- `apps/worldview-web/components/workspace/WorkspaceWatchlistWidget.tsx` (line ~95)
- `apps/worldview-web/components/workspace/SymbolLinkColorPicker.tsx`

**What to build**:
Five workspace violations:
1. **WS-001** `WorkspaceGrid.tsx:160`: `text-xl` on close button → remove (icon is already sized)
2. **WS-002** `WorkspaceChatWidget.tsx`: `animate-pulse` on cursor character `▋` → keep the cursor character but remove `animate-pulse` (or use `animate-[blink_1s_step-end_infinite]` with a `@keyframes blink { 50% { opacity: 0 } }` — but only if a CSS keyframe is already defined; otherwise just static)
3. **WS-003** `WorkspacePortfolioPanel.tsx` and `WorkspaceWatchlistWidget.tsx`: `hover:underline` on links → remove
4. **WS-004** `SymbolLinkColorPicker.tsx`: `rounded-full` on the interactive color dot → `rounded-[2px]`

**Acceptance criteria**:
- [ ] No `text-xl` on workspace close button
- [ ] No `animate-pulse` on chat cursor
- [ ] No `hover:underline` in workspace portfolio/watchlist panels
- [ ] Color picker dot uses `rounded-[2px]` not `rounded-full`
- [ ] lint + typecheck pass

---

#### T-D-4-04: Fix chat surface text sizing and animations

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/components/chat/SlashCommandCard.tsx`
- `apps/worldview-web/components/chat/SlashCommandAutocomplete.tsx`
- `apps/worldview-web/app/(app)/chat/page.tsx`
- `apps/worldview-web/features/chat/components/MessageBubble.tsx`
- `apps/worldview-web/features/chat/components/SlashTurnBlock.tsx`

**What to build**:
Six chat surface violations:
1. **SlashCommandCard animate-pulse skeleton** (line ~116): remove `animate-pulse` (T-D-4-01 primitive fix may already handle this if using shadcn Skeleton — verify)
2. **SlashCommandCard text sizes** (lines 163,165,224,227,235,251): `text-[15px]` and `text-[14px]` on price/card content → `text-[11px]`; `text-[12px]` on labels → `text-[11px]`
3. **SlashCommandCard hover:underline** (line 445): remove from ScreenerCard link
4. **SlashCommandAutocomplete text** (line ~85): `text-[12px]` → `text-[11px]`; arg specs → `text-[10px]`
5. **chat/page.tsx starter questions** (line ~661): `text-[12px]` → `text-[11px]`
6. **MessageBubble animate-bounce** (lines 60-62): typing indicator dots — remove animate-bounce; replace with static `...` text or single `<RefreshCw className="h-3 w-3 animate-spin" strokeWidth={1.5} />`
7. **SlashTurnBlock text-sm** (lines 27-28): parent + child both have `text-sm` causing 14px effective size → parent `text-[11px]`, remove child `text-sm`

**Acceptance criteria**:
- [ ] No text size above `text-[11px]` on data content in chat/slash command components
- [ ] No `animate-pulse` in SlashCommandCard skeleton (unless using shadcn Skeleton which was fixed in T-D-4-01)
- [ ] No `hover:underline` on chat links
- [ ] No `animate-bounce` on typing indicator
- [ ] lint + typecheck pass

---

#### T-D-4-05: Fix portfolio dialogs and header font

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/features/portfolio/components/PortfolioPageHeader.tsx`
- `apps/worldview-web/features/portfolio/components/AddPositionDialog.tsx`
- `apps/worldview-web/features/portfolio/components/CreatePortfolioDialog.tsx`
- `apps/worldview-web/features/portfolio/components/DeletePortfolioDialog.tsx`

**What to build**:
Five portfolio violations:
1. **PO-001** `PortfolioPageHeader.tsx:79`: `font-sans` on portfolio header → `font-mono`
2. **PO-006** `AddPositionDialog.tsx:173`: `text-[13px]` on DialogTitle → `text-[11px] font-mono uppercase tracking-[0.08em]`
3. **PO-007** `CreatePortfolioDialog.tsx:165`: `text-[13px]` on DialogTitle → `text-[11px] font-mono uppercase tracking-[0.08em]`
4. **PO-008** `DeletePortfolioDialog.tsx:65`: unformatted DialogTitle → add `className="text-[11px] font-mono uppercase tracking-[0.08em]"`
5. **PO-011/012** Input text `text-[12px]` in both dialogs → `text-[11px]`

**Acceptance criteria**:
- [ ] All portfolio DialogTitles use `text-[11px] font-mono uppercase tracking-[0.08em]`
- [ ] Portfolio page header uses `font-mono`
- [ ] Dialog input text uses `text-[11px]`
- [ ] lint + typecheck pass

---

#### T-D-4-06: Fix secondary page text sizing and hover:underline

**Type**: impl
**depends_on**: none
**blocks**: none
**Target files**:
- `apps/worldview-web/app/(app)/news/page.tsx` (line ~269)
- `apps/worldview-web/app/(app)/alerts/page.tsx` (lines ~401, ~510)
- `apps/worldview-web/components/screener/SavedScreensDialog.tsx` (line ~128)

**What to build**:
Three secondary page violations (some may overlap with Wave A fixes):
1. **SP-003** `alerts/page.tsx:401,510`: `hover:underline` on retry links → remove
2. **SP-004** `news/page.tsx:269`: `text-[12px]` on article titles → `text-[11px]`
3. **SC-019** `SavedScreensDialog.tsx:128`: `text-[12px]` on dialog title → `text-[11px]`

Note: SP-001/SP-002 are already covered by Wave A tasks T-A-1-01 and T-A-1-05.

**Acceptance criteria**:
- [ ] No `hover:underline` on retry/action links in alerts page
- [ ] News page article titles use `text-[11px]`
- [ ] Screener SavedScreensDialog title uses `text-[11px]`
- [ ] lint + typecheck pass

---

### Validation Gate
- [ ] `pnpm --filter worldview-web lint` passes
- [ ] `pnpm --filter worldview-web typecheck` passes
- [ ] `pnpm --filter worldview-web test` passes (fix any snapshot/class assertions broken by T-D-4-01)
- [ ] `pnpm --filter worldview-web build` passes

### Break Impact
| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/*.test.tsx` files asserting `animate-pulse` | skeleton.tsx primitive change removes class | Remove `animate-pulse` from expected class strings |
| `__tests__/*.test.tsx` files asserting `text-xs` on tabs | tabs.tsx change to `text-[11px]` | Update assertions |
| `__tests__/*.test.tsx` files asserting `text-sm` on CardTitle | card.tsx change to `text-[11px]` | Update assertions |
| `__tests__/workspace-chart-widget.test.tsx` | WorkspaceGrid close button class change | Verify test does not assert `text-xl` |

### Regression Guardrails
- **BP-357**: No new Unicode above U+25FF introduced
- **BP-358**: skeleton.tsx must not have `animate-pulse` after T-D-4-01 — verify with `grep animate-pulse apps/worldview-web/components/ui/skeleton.tsx`
- **R19** (Never delete tests): When tests break due to class changes, fix the assertion — do not delete the test
- Verify T-D-4-01 primitive fixes cascade correctly by running `pnpm test` after each change and checking that skeleton tests no longer expect `animate-pulse`

---

## Risk Assessment

- **Critical path**: Wave A (no deps) → Wave B → Wave C → Wave D
- **Highest risk**: T-B-2-06 (TechnicalSnapshot prop threading — touches 2 files and requires reading current prop interface carefully); T-D-4-01 (shared primitive changes may break test assertions in bulk)
- **Rollback strategy**: Each wave is a set of isolated CSS/component changes — revert is a single git revert per wave commit
- **Testing gaps**: No existing Vitest coverage for visual styling assertions; manual visual check required for MA coloring logic; T-D-4-01 primitive changes will break tests asserting old class names — fix assertions, do not skip tests

---

## Compounding Updates

### New Bug Patterns from this investigation
- **BP-357** (added to `docs/bug-patterns/frontend.md`): Unicode emoji characters (⚠ ✓ →) render as colorful glyphs on Windows/Linux — use Lucide icons for all iconography
- **BP-358** (added to `docs/bug-patterns/frontend.md`): shadcn Skeleton primitive defaults to `animate-pulse` — cascades to every loading state; Bloomberg terminals use static skeleton bars

### HIGH_RISK_PATTERNS Update
- Flag `animate-pulse` in skeleton components — terminal UIs must be static
- Flag native `<select>` elements — always shadcn Select in terminal
- Flag `rounded-full border-2 animate-spin` (consumer spinner pattern)
- Flag any Lucide icon without explicit `strokeWidth={1.5}` — system-wide enforcement needed
