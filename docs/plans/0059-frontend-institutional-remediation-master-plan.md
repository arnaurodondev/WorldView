# PLAN-0059 — Frontend Institutional Remediation (Master)

**Status:** in-progress · **Created:** 2026-04-30 · **Updated:** 2026-04-30 · **Source:** `docs/audits/2026-04-30-deep-remediation-master-report.md` (canonical) + `docs/audits/2026-04-29-qa-institutional-ui-audit-report.md` (findings index)
**Stakeholder:** BlackRock-grade institutional credibility
**Composite scope:** 96 confirmed fix items + 76 newly discovered (172 total) across 5 specialist domains: Codebase, Visualization, Components, Visual Design, Layout/IA

---

## Pre-flight

| Check | Result | Notes |
|-------|:-----:|-------|
| Source documents readable | PASS | Both audit reports present in `docs/audits/` |
| No unresolved BLOCKING open questions | PASS | Decisions locked in remediation report §9 |
| Cross-plan conflicts | PASS | PLAN-0053 (frontend-polish) is **complete**; PLAN-0057/0058 are backend-pipeline scope, no overlap |
| Source recency | PASS | Master report dated 2026-04-30 (today); no architecture drift since |
| RULES.md compliance | PASS | All proposed rules are *additions*, not violations of current rules |
| Plan ID reservation | PASS | `0059` is next free; appended to TRACKING.md in same commit |

This is a **frontend-domain master plan** with cross-cutting backend touchpoints (S9 WebSocket proxy, S2 quote republisher, S9 OpenAPI exposure, S9 page-bundle endpoints). Backend tasks are scoped here; backend implementation can fork into a sub-plan if desired.

---

## 1. Decomposition Strategy

The remediation work decomposes into **10 sub-plans** by execution boundary (each fits 1–2 Claude Code sessions). Sub-plans are sequenced by dependency and parallelizability.

### 1.1 Sub-plan index

| Sub-plan | Title | Wave (master) | Sessions | Critical path? | Parallel-safe with |
|----------|-------|:-----------:|:--------:|:-------------:|--------------------|
| **PLAN-0059-A** | Quick wins & foundations | W0 | 1 | YES — gates everything else | — |
| **PLAN-0059-B** | Workflow grammar (hotkeys, command palette, SymbolBar) | W1 Track A | 2 | YES — credibility lever | C |
| **PLAN-0059-C** | Contract spine (codegen, query-key factory, format module, storage) | W1 Track B | 2 | YES — gates A1+ refactors | B |
| **PLAN-0059-D** | Real-time tick stream + WS proxy | W2 Track A | 2 | YES — single largest demo gap | E |
| **PLAN-0059-E** | God-file decomposition | W2 Track B | 2 | NO — enables W3+ | D |
| **PLAN-0059-F** | Universal primitives (DataTable, Form layer, ContextMenu, Hotkey Manager) | W3 | 3 | YES — foundation for all tables/forms | — |
| **PLAN-0059-G** | Performance + bundle + CI gates | W4 | 1 | NO — polish | H |
| **PLAN-0059-H** | Multi-pane charts + Workspace v2 + multi-monitor | W5 | 2 | NO — power features | G |
| **PLAN-0059-I** | IA correctness + hardening (CSP, page bundles, settings reorg) | W6 | 1 | NO — polish | — |
| **PLAN-0059-J** | Differentiators (saved items, drag-drop, mobile, onboarding, B2B) | W7 | 3 | NO — long-tail | — |

### 1.2 Dependency graph

```
        ┌─────────────────────────────────────┐
        │  PLAN-0059-A — Quick wins (1 wk)    │  ← W0
        │  Closes silent CRITICAL findings    │
        └────────┬────────────────────────────┘
                 │
       ┌─────────┴─────────┐
       ▼                   ▼
┌───────────────┐   ┌───────────────┐
│ PLAN-0059-B   │   │ PLAN-0059-C   │
│ Workflow      │   │ Contract      │
│ grammar       │   │ spine         │  ← W1 (parallel)
│ (3 wks)       │   │ (3 wks)       │
└───────┬───────┘   └───────┬───────┘
        │                   │
        └─────────┬─────────┘
                  ▼
       ┌─────────────────────┐
       │  PLAN-0059-D        │
       │  Real-time + WS     │  ← W2 Track A (BE+FE, 2 wks)
       │  PLAN-0059-E        │  ← W2 Track B (FE, 2-3 wks)
       │  God-file decomp    │     parallel with D
       └─────────┬───────────┘
                 ▼
       ┌─────────────────────┐
       │  PLAN-0059-F        │
       │  Universal          │  ← W3 (3 wks)
       │  primitives         │
       │  DataTable + Forms  │
       └─────────┬───────────┘
                 ▼
       ┌────────┬────────────┐
       ▼        ▼            ▼
┌───────────┐ ┌───────────┐ ┌───────────┐
│ G — Perf  │ │ H — Charts │ │ I — IA    │
│ (W4 1wk)  │ │ + Workspace│ │ + harden  │  ← parallel after W3
│           │ │ v2 (W5 3wk)│ │ (W6 2wk)  │
└───────────┘ └───────────┘ └───────────┘
                 │
                 ▼
       ┌─────────────────────┐
       │ J — Differentiators │  ← W7 (4 wks; long-tail, can sprawl)
       └─────────────────────┘
```

### 1.3 Effort summary

| Sub-plan | Engineer-weeks (1 eng) | With 2 engineers in parallel |
|---------|:-----------------------:|:----------------------------:|
| A | 1 | 0.5 |
| B | 3 | 3 (single-track) |
| C | 3 | (parallel with B) |
| D | 2 | 2 (BE-bound) |
| E | 2-3 | (parallel with D) |
| F | 3 | 2 (split DataTable + Forms) |
| G | 2 | 1 |
| H | 3 | 2 |
| I | 2 | 1 |
| J | 4-6 | 3 |
| **Total** | **~25-30 weeks** | **~14-16 weeks calendar** |

**Minimum demo path:** A + B + D = 6 weeks calendar (2 engineers). Closes the four signals that disqualify a 90-second demo (frozen UI, dead hotkeys, broken contrast, no brand).

---

## 2. Codebase State Verification (Phase 1.3)

Verified by deep-investigation agents 2026-04-30 against current source. Frontend-only scope under `apps/worldview-web/`. Backend touchpoints called out in DELTAs.

| Reference | Type | Service | Actual Current State | Target State | Delta |
|-----------|------|---------|---------------------|--------------|:-----:|
| `lib/gateway.ts` | TS module | FE | 2,657 LOC; 100+ methods on one closure; hand-typed responses | Split into `lib/api/{auth,instruments,portfolios,watchlists,alerts,screener,chat,brokerage,markets}.ts` driven by `openapi-fetch`; each <350 LOC | DECOMPOSE |
| `types/api.ts` | TS module | FE | 1,401 LOC hand-typed; comments admit drift ("S3 returns `items` not `bars`") | `types/generated/api.ts` from `openapi-typescript`; `types/api.ts` <80 LOC re-export shim | CODEGEN |
| `app/(app)/portfolio/page.tsx` | route | FE | 1,739 LOC: 12 useQuery + 17 useState + 2 inline dialogs + 4-tab JSX | `features/portfolio/{components,hooks,queries,lib}/`; page <100 LOC | DECOMPOSE |
| `app/(app)/chat/page.tsx` | route | FE | 1,293 LOC; SSE inline + thread list + slash-cmd parsing + markdown export | `useChatStream(threadId)` hook; `<ThreadSidebar>`/`<ConversationView>`/`<MessageComposer>` split | DECOMPOSE |
| `components/screener/ScreenerFilterBar.tsx` | component | FE | 986 LOC; 4 useState; hand-rolled validation | RHF + Zod; per-section split | REWRITE |
| `components/dashboard/WatchlistMoversWidget.tsx` | component | FE | 800 LOC; data + ranking + render mixed | `useWatchlistMovers(period, sectorFilter)` hook; render split | DECOMPOSE |
| `components/instrument/OHLCVChart.tsx` | component | FE | 1,019 LOC; 14 useEffect for indicator visibility; lightweight-charts v4 stacking 7 oscillators on one canvas | INDICATOR_DEFS registry map; lightweight-charts v5 multi-pane | UPGRADE |
| `app/globals.css` (`.dark` block, line ~120) | CSS | FE | `--muted-foreground: 240 4% 46%` (live)<br>vs `:root` `55%` (dead) | `.dark` synced to `55%` | PATCH |
| `app/globals.css` `--positive` | CSS var | FE | `174 42% 40%` = `#26A69A` (TradingView teal) | `150 100% 41%` = `#00D26A` (institutional green) | REPLACE |
| `app/globals.css` `--negative` | CSS var | FE | `0 63% 62%` = `#EF5350` (Material Red 400) | `350 100% 62%` = `#FF3B5C` (urgent red) | REPLACE |
| `app/globals.css` `--destructive` | CSS var | FE | (aliased to `--negative`) | `0 84% 60%` = `#EF4444` (split from negative) | SPLIT |
| `app/globals.css` `--accent-ai` | CSS var | FE | (does not exist) | `268 90% 65%` = `#A855F7` (violet) | ADD |
| `lib/utils.ts:248-265` `heatCellColor()` | function | FE | Hardcoded blue-tinted hex from retired Bloomberg Dark palette | Derived from CSS variables via `hsl(var(--positive)/0.32)` etc. | REWRITE |
| `lib/utils.ts:43,63` formatters | function | FE | `formatPrice`/`formatPriceCompact` hardcode `currency:"USD"` | `formatPrice(v, {currency, locale})`; `lib/format.ts` | REWRITE |
| `lib/utils.ts:55,127,138` + 3 ad-hoc | functions | FE | 4 different B/M/T compaction implementations | Single `formatCompactCurrency` in `lib/format.ts` | CONSOLIDATE |
| `components/ui/button.tsx:54-58` | component | FE | `default: h-9 px-4 py-2`, `sm: h-8`, no xs | `density: compact|default|comfortable` cva variant; default `h-7 px-3 text-xs` | REWRITE |
| `components/ui/input.tsx:23` | component | FE | `h-9 px-3 text-sm` | density variant; default `h-7 px-2 text-[11px]` | REWRITE |
| `components/ui/dialog.tsx:46-47` | component | FE | `max-w-lg p-6 gap-4` | `p-4 gap-2 max-w-md` default + 3 sizes | REWRITE |
| `components/ui/tabs.tsx:29` | component | FE | `h-9 rounded-[2px] bg-muted p-1` (pill-on-muted) | Bare flex `h-7` + 1px primary underline on active | REWRITE |
| `package.json` | manifest | FE | Has `react-grid-layout`, `react-resizable`, `@radix-ui/react-toast` (zero imports); has `recharts` | Remove dead deps; `pnpm remove recharts`; add `sonner`, `react-hook-form`, `@hookform/resolvers`, `zod`, `@radix-ui/react-context-menu`, `@radix-ui/react-hover-card`, `react-day-picker`, `@dnd-kit/sortable`, `@dnd-kit/core`, `papaparse`, `nuqs`, `openapi-fetch`; devDeps: `openapi-typescript`, `@sentry/nextjs`, `depcheck`, `knip`, `bundlewatch`, `@lhci/cli`, `axe-core/playwright`, `style-dictionary` | DEPS |
| `app/layout.tsx:33` | component | FE | `IBM_Plex_Sans({weight:["300","400","500","600","700"]})` ships 5 weights | Drop `300`; ship `400/500/600/700` (mono: `400/500`) | TUNE |
| `next.config.ts:88` | config | FE | CSP `'unsafe-inline'` in script-src AND style-src | Nonce-based CSP via `middleware.ts` (Wave 6) | DEFER |
| `next.config.ts` | config | FE | No `experimental.reactCompiler`, no `optimizePackageImports`, no `compiler.removeConsole` | Enable all three | TUNE |
| `tsconfig.json` | config | FE | `strict: true` only; missing `noUncheckedIndexedAccess`, `noImplicitOverride`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`, `noFallthroughCasesInSwitch` | Stage 1 (W0): cheap flags. Stage 2 (W6): `noUncheckedIndexedAccess` (~300 errors expected) | STAGED |
| `.eslintrc.json` | config | FE | `@typescript-eslint/no-explicit-any: warn`; 21 `any` casts | Set to `error`; replace with `unknown` + narrowing | TIGHTEN |
| `public/` | assets | FE | EMPTY — no favicon, icon.svg, OG image, wordmark | Brand identity package (10 files) | ADD |
| `app/globals.css` | CSS | FE | No `@media (prefers-reduced-motion)`, `(forced-colors: active)`, `(prefers-contrast: more)`, `print` | Add all four blocks | ADD |
| `components/shell/Sidebar.tsx` | component | FE | Legacy 56px implementation; 267 LOC; 0 imports | DELETE; CI guard | REMOVE |
| `components/shell/StatusBar.tsx` | component | FE | Renders 6 chord hints with no listener wired | Read from registered hotkey-registry | REWRITE |
| `components/shell/UtcClock.tsx:44` | component | FE | `useState(() => formatUtcTime(new Date()))` — guaranteed hydration mismatch | Empty SSR; populate in `useEffect` | PATCH |
| `contexts/AlertStreamContext.tsx:160-163` | context | FE | Direct WS to S10:8010, JWT in URL | S9 WS proxy `/v1/alerts/stream`; JWT in `Sec-WebSocket-Protocol` subprotocol | REWIRE (BE+FE) |
| S9 `/v1/quotes/stream` | endpoint | S9 (BE) | does not exist | New WebSocket route fans out from Kafka `quotes.tick.v1` | CREATE (BE) |
| Kafka `quotes.tick.v1` | topic | infra | does not exist | New topic; S2 produces, S9 consumes | CREATE (BE) |
| S2 quote republisher | adapter | S2 (BE) | Alpaca WS ingested, persisted to DB only | Add Kafka producer fork after persist | EXTEND (BE) |
| S9 `/openapi.json` | endpoint | S9 (BE) | exposed (FastAPI default) | Verify NOT auth-gated; commit `infra/contracts/s9-openapi.yaml` snapshot | VERIFY (BE) |
| S9 `/v1/portfolios/{id}/page-bundle` | endpoint | S9 (BE) | does not exist | New endpoint composing 5–12 internal calls via `asyncio.gather` | CREATE (BE, W6) |
| S9 `/v1/instruments/search` enrichment | endpoint | S9 (BE) | returns flat `Instrument[]` | Add `{primary_listing, mic, isin, cusip, country_iso2}` fields | EXTEND (BE) |
| S5 `/v1/fx/rates` | endpoint | S5 or S2 (BE) | does not exist | Daily FX rates for multi-currency formatting | CREATE (BE) |
| S1 `/v1/users/me/profile` | endpoint | S1 (BE) | partial | Add `{defaultCurrency, defaultTimezone, density}` fields | EXTEND (BE) |
| S1 `/v1/users/me/onboarding-state` | endpoint | S1 (BE) | does not exist | Returns `{role, region, hasPortfolio, hasWatchlist}` for onboarding flow (W7) | CREATE (BE) |
| S9 `/v1/workspaces` | endpoint | S9 (BE) | does not exist | Workspace CRUD + share-token + version vector (W5) | CREATE (BE) |
| S9 `/v1/annotations` | endpoint | S9 (BE) | does not exist | Chart annotation cloud-sync (W7) | CREATE (BE) |

**Critical path:** every CODEGEN/REWRITE/REPLACE/DECOMPOSE row is on the dependency chain. ADD/PATCH rows are quick wins (Wave 0). BE rows fork into a backend sub-plan if a separate engineer takes them.

---

## 3. PLAN-0059-A — Quick Wins & Foundations (Wave 0)

**Goal:** Close all silent CRITICAL findings + remove dead deps + observability online + brand identity + a11y baseline.
**Depends on:** none. **Parallel-safe.** **Effort:** 1 calendar week (1 engineer).
**Architecture layer:** mixed (CSS / config / instrumentation).

### Wave A-1 — Token surgery + a11y CSS + brand (Day 1–2) ✅
**Status: DONE — 2026-04-30 · 850 tests pass · ruff/lint/typecheck clean**

**Architecture layer:** CSS / assets

#### T-A-1-01: Patch `.dark` block `--muted-foreground` drift

**Type:** schema (CSS var)
**depends_on:** none
**blocks:** [T-A-1-02, T-A-1-04]
**Target files:** `apps/worldview-web/app/globals.css` (line ~120)
**PRD reference:** F-VISUAL-NEW-M, master report §6.2 NEW-M

**What to build:** Sync `.dark` block to `:root` value `55%`. The WCAG fix shipped to `:root` was never propagated. Active class is `.dark`, so every `text-muted-foreground` site is sub-AA today (4.27:1).

**Logic & Behavior:**
- Edit `.dark { ... --muted-foreground: 240 4% 46%; ... }` to `--muted-foreground: 240 4% 55%`
- Verify contrast against `--background #09090B` rises from 4.27:1 to 5.42:1 (passes WCAG AA at body sizes)

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_muted_foreground_contrast_dark_theme` | `getComputedStyle(document.body).getPropertyValue('--muted-foreground')` resolves to HSL with L>=55% under `.dark` class; computed contrast against `#09090B` >= 4.5:1 | unit (Vitest + jsdom) |
| `test_muted_foreground_root_dark_parity` | Both `:root` and `.dark` blocks declare identical `--muted-foreground` value | unit (snapshot scan of globals.css) |

**Downstream test impact:** None — purely a CSS value change.

**Acceptance criteria:**
- [ ] `.dark { --muted-foreground }` resolves to `240 4% 55%`
- [ ] Contrast measurement: 5.42:1 minimum (verified via `tinycolor2` in test)
- [ ] Both tests pass

---

#### T-A-1-02: Replace `--positive`, `--negative`; split `--destructive`; add `--accent-ai`

**Type:** schema (CSS var)
**depends_on:** [T-A-1-01]
**blocks:** [T-A-1-03, T-A-1-04, T-A-2-01]
**Target files:** `apps/worldview-web/app/globals.css` (lines 81–83, 109–138 `.dark` block)
**PRD reference:** F-VISUAL-001/002, master report §6.3

**What to build:** Three CRITICAL color-token replacements + one new token. Single CSS change rebuilds the entire price-direction visual signal.

**Logic & Behavior:**
- `--positive: 174 42% 40%` (`#26A69A`) → `--positive: 150 100% 41%` (`#00D26A`)
- `--negative: 0 63% 62%` (`#EF5350`) → `--negative: 350 100% 62%` (`#FF3B5C`)
- `--destructive: 0 63% 62%` (aliased) → `--destructive: 0 84% 60%` (`#EF4444`) — distinct hue
- ADD `--accent-ai: 268 90% 65%` (`#A855F7`) for AI-feature accents
- ADD `--positive-fill: 145 100% 32%` and `--negative-fill: 350 80% 50%` (for badge backgrounds where text-only color is too thin)
- Apply same changes to **both** `:root` and `.dark` blocks (single source after Wave A-7 Style Dictionary)

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_positive_token_resolves_to_institutional_green` | `getComputedStyle` `--positive` resolves to `hsl(150 100% 41%)` under `.dark` | unit |
| `test_positive_contrast_aaa` | `#00D26A` contrast vs `#09090B` >= 7:1 (AAA) | unit |
| `test_negative_contrast_aa` | `#FF3B5C` contrast vs `#09090B` >= 4.5:1 (AA) | unit |
| `test_destructive_distinct_from_negative` | `--destructive` and `--negative` resolve to different hex values | unit |
| `test_accent_ai_present` | `--accent-ai` is defined and resolves to violet (`hsl(268 90% 65%)`) | unit |
| `test_color_blind_distinguishability_deuteranope` | Computed deuteranope-simulated luminance for `--positive` vs `--negative`: delta >= 80 | unit (Color algorithms via `culori`) |

**Downstream test impact:**
- `apps/worldview-web/__tests__/HeatCell.test.tsx` will need snapshot updates (different rendered hex)
- Visual regression in Storybook (Chromatic) for any component using `text-positive`/`text-negative`/`bg-positive/*` — expected updates

**Acceptance criteria:**
- [ ] Six color tests pass
- [ ] Visual smoke check: open `/dashboard` — green/red feel "Bloomberg-grade" (institutional green, not teal accent)
- [ ] No hardcoded `#26A69A` or `#EF5350` remain in CSS (grep test)

---

#### T-A-1-03: Rewrite `heatCellColor()` to derive from CSS tokens

**Type:** impl
**depends_on:** [T-A-1-02]
**blocks:** [T-A-1-04, T-D-2-01]
**Target files:** `apps/worldview-web/lib/utils.ts` (lines 244–266)
**PRD reference:** F-VISUAL-003, master report §6.2 F-003

**What to build:** Replace hardcoded blue-tinted retired-palette hex values (`#1A2030`, `#0A2E28`, etc. — explicitly forbidden by `globals.css:11`) with CSS-variable-derived 7-step diverging scale. Single source of truth for sector heatmap, screener heat cells.

**Entities / Components:**
- **`heatCellColor(changePct: number | null): { background: string; color: string }`**
  - Returns `{background: 'hsl(var(--positive)/0.32)', color: 'hsl(var(--positive))'}` for `>=3%`
  - 7 steps: `>=3 / >=1.5 / >=0.5 / >-0.5 (neutral) / >-1.5 / >-3 / <=-3`
  - Neutral cell: `bg = hsl(var(--surface-2))`, `color = hsl(var(--muted-foreground))`
  - Null returns same as neutral
- **`resolveCssColor(varName: string): string`** (NEW helper in `lib/format/color.ts`)
  - Reads `getComputedStyle(document.documentElement).getPropertyValue(varName)` once, caches
  - Returns hex (for lightweight-charts which needs literals)
  - Used when the color must be passed to a non-DOM consumer

**Logic & Behavior:**
- Pure function; no side effects
- Pulls live token values via CSS `hsl()` syntax — palette tweaks cascade automatically
- `resolveCssColor` cache invalidated on `class="dark"` mutation (uses `MutationObserver`)

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_heat_cell_strong_gain_uses_positive_token` | `heatCellColor(3.5)` returns `background` containing `var(--positive)` | unit |
| `test_heat_cell_strong_loss_uses_negative_token` | `heatCellColor(-3.5)` returns `background` containing `var(--negative)` | unit |
| `test_heat_cell_neutral_zero_hue` | `heatCellColor(0.1)` returns `background` containing `var(--surface-2)`, NOT a tinted color | unit |
| `test_heat_cell_null_neutral` | `heatCellColor(null)` returns identical to neutral case | unit |
| `test_heat_cell_no_legacy_hex_returns` | No return value contains `#1A2030`, `#0A2E28`, `#0A2420`, `#251218`, `#300E12`, `#3D0A0E` | unit (regex scan) |
| `test_heat_cell_threshold_boundaries` | Boundary inputs (3.0, 1.5, 0.5, -0.5, -1.5, -3.0) each select correct step | unit |
| `test_resolve_css_color_caches_on_first_call` | Second invocation does not call `getComputedStyle` (spy assertion) | unit |
| `test_resolve_css_color_invalidates_on_theme_change` | After class mutation, next call re-reads | unit |

**Downstream test impact:**
- `__tests__/MarketHeatmap.test.tsx` — snapshot will change (new hex values)
- `__tests__/SectorHeatmapWidget.test.tsx` — same
- `__tests__/HeatCell.test.tsx` — same
- All affected snapshots regenerated as part of this task

**Acceptance criteria:**
- [ ] All eight tests pass
- [ ] Grep for `#1A2030|#0A2E28|#0A2420|#0E201C|#251218|#300E12|#3D0A0E` in `apps/worldview-web/lib/` returns zero hits
- [ ] Sector heatmap visually harmonizes with page hue (no longer "stickers from a different app")

---

#### T-A-1-04: Replace hardcoded `text-amber-*`/`bg-amber-*` Tailwind defaults with semantic tokens

**Type:** impl
**depends_on:** [T-A-1-02]
**blocks:** none
**Target files:**
- `apps/worldview-web/components/shell/AskAiPanel.tsx`
- `apps/worldview-web/components/shell/AskAiButton.tsx`
- `apps/worldview-web/components/instrument/InstrumentBriefPanel.tsx`
- `apps/worldview-web/components/dashboard/MorningBriefCard.tsx`
- (plus 9 additional sites grep returns)

**PRD reference:** F-VISUAL-022, master report §6.2

**What to build:** 21 occurrences across 13 files use Tailwind defaults (`text-amber-400`, `bg-amber-500/20`) bypassing the token system. Replace with `text-[hsl(var(--accent-ai))]` and `bg-[hsl(var(--accent-ai)/0.18)]` for AI panels; `text-warning` for general amber semantics.

**Logic & Behavior:**
- AI-feature elements (AskAi, brief, copilot icons) → `--accent-ai` violet
- Severity-warning elements (medium-priority alerts) → existing `--warning` token
- Codemod `jscodeshift` transform automates all 21 sites
- ESLint rule `no-restricted-classnames` added to prevent regression: bans `text-amber-*`, `text-blue-*`, `text-yellow-*`, `text-green-*`, `text-red-*`, `bg-amber-*`, etc. outside `app/login` and `app/error` (allowlist).

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_no_tailwind_color_defaults_in_components` | Grep across `components/` finds zero hits for banned classes | unit (lint-style) |
| `test_ask_ai_panel_uses_accent_ai_token` | AskAiPanel renders with `text-[hsl(var(--accent-ai))]` (snapshot) | component |
| `test_eslint_blocks_text_amber_in_components` | ESLint config rejects `<div className="text-amber-400">` in a fixture file | unit (eslint test runner) |

**Downstream test impact:**
- All 13 component snapshot tests regenerated
- ESLint baseline updated

**Acceptance criteria:**
- [ ] Three tests pass
- [ ] Grep `text-amber-|bg-amber-|text-blue-|text-yellow-` in `components/` returns 0 hits (only allowed in `app/login` + `app/error`)
- [ ] AI panel visually distinct from primary yellow (violet vs yellow)

---

#### T-A-1-05: Replace blanket `disabled:opacity-50` with explicit disabled tokens

**Type:** impl
**depends_on:** [T-A-1-02]
**blocks:** none
**Target files:** all 388 sites; codemod-driven across `components/`
**PRD reference:** F-VISUAL-027

**What to build:** `disabled:opacity-50` halves contrast of every disabled element. With `text-foreground` (`#E4E4E7`) on `bg-background` (`#09090B`) at 15.94:1, `*0.5` yields `~3.5:1` (FAILS AA). For `text-muted-foreground` already at 5.42:1, `*0.5` yields `~2.7:1` (FAILS AA badly). Replace with explicit disabled tokens that desaturate, do not vanish.

**Logic & Behavior:**
- Add to `globals.css`:
  ```
  --disabled-foreground: 0 0% 46%   /* #757575 — 5.5:1 on background */
  --disabled-bg: 240 4% 11%          /* same as --muted */
  --disabled-border: 240 4% 20%
  ```
- Codemod replaces all `disabled:opacity-50` with `disabled:bg-[hsl(var(--disabled-bg))] disabled:text-[hsl(var(--disabled-foreground))] disabled:border-[hsl(var(--disabled-border))] disabled:cursor-not-allowed`
- Keep `disabled:cursor-not-allowed` as separate concern

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_disabled_button_contrast_passes_aa` | Disabled `<Button>` rendered: computed text contrast vs computed bg >= 4.5:1 | component |
| `test_disabled_input_does_not_use_opacity_50` | DOM doesn't carry `opacity: 0.5` style on disabled inputs | component |
| `test_codemod_replaces_all_opacity_50_disabled` | Grep across `components/` finds zero `disabled:opacity-50` | unit (lint-style) |

**Downstream test impact:**
- Snapshot regen for any disabled-state component test

**Acceptance criteria:**
- [ ] Disabled UI passes WCAG AA on contrast
- [ ] Three tests pass
- [ ] Visual regression: disabled Button still clearly different from enabled, but readable

---

#### T-A-1-06: Add accessibility-mode CSS (`prefers-reduced-motion`, `forced-colors`, `prefers-contrast`, print)

**Type:** schema (CSS)
**depends_on:** [T-A-1-02]
**blocks:** none
**Target files:** `apps/worldview-web/app/globals.css` (append four `@media` blocks)
**PRD reference:** F-VISUAL-NEW-B, master report §6.2 NEW-B

**What to build:** Four media-query blocks closing the audit's accessibility-coverage gap. For BlackRock enterprise accessibility committee compliance.

**Logic & Behavior:**

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
  .tick-flash { animation: none !important; }
}

@media (forced-colors: active) {
  :root {
    --background: Canvas; --foreground: CanvasText;
    --card: Canvas; --card-foreground: CanvasText;
    --border: CanvasText; --primary: Highlight;
    --primary-foreground: HighlightText;
    --positive: LinkText; --negative: Mark;
    --muted-foreground: GrayText;
  }
  [class*="opacity-"], [class*="/10"], [class*="/20"], [class*="/30"] { opacity: 1 !important; }
  *:focus-visible { outline: 2px solid CanvasText !important; }
}

@media (prefers-contrast: more) {
  :root {
    --foreground: 0 0% 100%;
    --muted-foreground: 0 0% 78%;
    --border: 0 0% 45%;
  }
}

@media print {
  :root {
    --background: 0 0% 100%; --foreground: 0 0% 0%;
    --card: 0 0% 100%; --border: 0 0% 60%;
    --muted-foreground: 0 0% 30%;
    --positive: 150 100% 25%; --negative: 0 80% 35%;
  }
  body { background: white !important; color: black !important; }
  .topbar, .sidebar, .statusbar, [data-print-hide] { display: none !important; }
  tr, .data-row { page-break-inside: avoid; }
}
```

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_reduced_motion_disables_transitions` | Setting `prefers-reduced-motion: reduce` clamps `transition-duration` to 0.01ms | unit (jsdom + matchMedia mock) |
| `test_forced_colors_redefines_tokens_to_system` | Under `forced-colors: active`, `--background` resolves to `Canvas` | unit |
| `test_print_uses_light_palette` | Under `@media print`, body bg is white | unit (CSS parsing) |
| `test_high_contrast_bumps_foreground` | `prefers-contrast: more` raises `--foreground` to `100%` lightness | unit |

**Downstream test impact:** None.

**Acceptance criteria:**
- [ ] Four blocks present in `globals.css`
- [ ] Four tests pass
- [ ] Manual verification (Mac System Settings > Reduce Motion / Increase Contrast — animations stop / colors brighten)

---

#### T-A-1-07: Add minimum brand identity package

**Type:** impl (assets)
**depends_on:** none
**blocks:** none
**Target files:**
- `apps/worldview-web/public/favicon.ico` (NEW)
- `apps/worldview-web/public/icon.svg` (NEW — 4×4 grid mark, dark/light media-query variants)
- `apps/worldview-web/public/icon-{16,32,180,192,512}.png` (NEW — multi-resolution)
- `apps/worldview-web/public/manifest.webmanifest` (NEW — PWA manifest, `theme_color: #FFD60A`)
- `apps/worldview-web/public/og-image.png` (NEW — 1200×630)
- `apps/worldview-web/public/og-image-square.png` (NEW — 1200×1200, Slack/Discord)
- `apps/worldview-web/public/twitter-card.png` (NEW — 1200×600)
- `apps/worldview-web/brand/{worldview-mark,worldview-wordmark,worldview-mark-mono}.svg` (NEW)
- `apps/worldview-web/app/layout.tsx` — `metadata` extended with `icons`, `openGraph`, `twitter`, `manifest`
- `apps/worldview-web/app/icon.svg` (Next.js convention — overrides `public/icon.svg`)

**PRD reference:** F-VISUAL-NEW-C, master report §6.2 NEW-C

**What to build:** Minimum identity that distinguishes Worldview from a Vercel template in browser bookmark, Slack share preview, print PDF, mobile home-screen save.

**Mark spec:** 16×16 grid, 4px cells with 1px gap, top-right cell filled `#FFD60A`, others filled `#27272A` on `#09090B` background. SVG with media-query light/dark variant. Renders correctly at favicon scale (16px).

**Wordmark spec:** IBM Plex Sans 600, lowercase `worldview` with `o` in `world` replaced by 1-em-square solid `#FFD60A`, vertically centered on x-height, `letter-spacing: -0.02em`. Smallest 18px (TopBar) — largest 96px (login).

**OG image:** 1200×630, `bg #09090B`, yellow wordmark centered, `text-h2` strapline below: `Institutional market intelligence`.

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_favicon_files_exist` | All 8 `public/*` files exist with correct dimensions | unit (FS check) |
| `test_metadata_includes_og_image` | `app/layout.tsx` `metadata.openGraph.images` array contains the OG path | unit |
| `test_manifest_theme_color_is_brand_yellow` | `manifest.webmanifest` `theme_color` is `#FFD60A` | unit (JSON parse) |
| `test_icon_svg_dark_light_aware` | `icon.svg` contains `prefers-color-scheme: light` media query | unit |

**Downstream test impact:**
- E2E test for `<head>` content updates expected
- Lighthouse PWA score improves (manifest discoverable)

**Acceptance criteria:**
- [ ] Bookmark Worldview in Chrome — favicon visible (4-cell grid with yellow accent)
- [ ] Share `localhost:3001` link in Slack — OG image preview renders
- [ ] Print `/dashboard` to PDF — header has wordmark logo
- [ ] Four tests pass

---

### Wave A-2 — Dependency hygiene + observability + ESLint (Day 3) ✅
**Status: DONE — 2026-04-30 · sonner mounted · dead deps removed · ESLint hardened (no-explicit-any: error) · tsconfig stage 1 (noImplicitOverride + noFallthroughCasesInSwitch) · UtcClock hydration fix · next.config tuned · legacy Sidebar deleted**

**Note:** T-A-2-03 (Sentry wiring) deferred to Wave A-3 — requires DSN env var setup; landing as a separate commit. The other 6 Wave A-2 tasks are complete.

**Architecture layer:** config / instrumentation

#### T-A-2-01: Drop dead deps; mount sonner Toaster

**Type:** config + impl
**depends_on:** [T-A-1-02]
**blocks:** [T-A-2-02]
**Target files:**
- `apps/worldview-web/package.json` — remove `react-grid-layout`, `react-resizable`, `@radix-ui/react-toast`; add `sonner`
- `apps/worldview-web/app/providers.tsx` — mount `<Toaster>`
- `apps/worldview-web/lib/toast.ts` (NEW) — re-export `sonner.toast` typed wrapper

**PRD reference:** F-CODE-010, F-COMP-NEW-TOAST-001, master report §3.2 / §5.9

**What to build:** Three dead deps shipping to lockfile (~80 KB gz). Toast provider doesn't exist. Replace with `sonner@1.5` — single provider, `toast.error()`/`toast.success()`/`toast.info()` import-anywhere API.

**Logic & Behavior:**
- `pnpm remove react-grid-layout react-resizable @radix-ui/react-toast`
- `pnpm add sonner@1.5`
- Mount `<Toaster position="bottom-right" richColors theme="dark" closeButton expand visibleToasts={5} toastOptions={{className: "font-mono text-[11px] tabular-nums"}} />` in `app/providers.tsx`
- `lib/toast.ts` re-exports with typed signature; centralizes default options
- Replace inline error strings (`{error && <p className="text-destructive">...</p>}`) with `toast.error(message)` — start with 3 highest-traffic sites; bulk replace in Wave 6

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_dead_deps_removed` | `package.json` does not contain `react-grid-layout`, `react-resizable`, `@radix-ui/react-toast` | unit (JSON scan) |
| `test_sonner_toaster_mounted_in_providers` | `app/providers.tsx` renders `<Toaster>` | component |
| `test_toast_error_renders_destructive_color` | `toast.error("oops")` renders an element with `bg-destructive` token-derived | component |

**Downstream test impact:** None (no current consumer of dead deps).

**Acceptance criteria:**
- [ ] `pnpm install` completes; lockfile shrinks
- [ ] `pnpm exec depcheck` reports 0 unused deps for the three removed
- [ ] Three tests pass
- [ ] Trigger an error in dev → sonner toast appears bottom-right

---

#### T-A-2-02: Add depcheck + knip + bundlewatch + eslint tightening to CI

**Type:** config
**depends_on:** [T-A-2-01]
**blocks:** none
**Target files:**
- `apps/worldview-web/package.json` — devDeps: `depcheck`, `knip`, `bundlewatch`, `lighthouse-ci`
- `apps/worldview-web/.eslintrc.json` — `@typescript-eslint/no-explicit-any: error` (was `warn`)
- `apps/worldview-web/bundlewatch.config.json` (NEW)
- `apps/worldview-web/.lighthouserc.json` (NEW)
- `.github/workflows/ci.yml` (root) — add three jobs

**PRD reference:** F-CODE-NEW-009, master report §3.3 / §10.6

**What to build:** Five CI gates that prevent regression:
1. `pnpm exec depcheck` fails on any unused dep
2. `pnpm exec knip` fails on any unused export
3. `pnpm exec bundlewatch` fails on >10% bundle regression per route
4. `pnpm exec lhci autorun` fails on LCP > 1.8s, CLS > 0.1, Perf < 90
5. ESLint `no-explicit-any` raised from `warn` to `error`; existing 21 sites replaced with `unknown` + narrowing

**Logic & Behavior:**
- `bundlewatch.config.json` budgets: `/dashboard < 220KB gz`, `/portfolio < 380KB gz`, `/screener < 280KB gz`, `/instruments/[id] < 320KB gz`
- LHCI thresholds in `.lighthouserc.json`
- For ESLint `any` migration: 21 sites replaced incrementally; if any case is genuinely impossible to type, suppress with `// eslint-disable-next-line` + comment explaining
- CI runs all five gates on every PR

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_eslint_rejects_explicit_any` | A fixture `: any` triggers lint error | unit |
| `test_existing_any_sites_replaced` | Grep finds 0 occurrences of `: any` or `as any` outside `// eslint-disable` annotations | unit |
| `test_depcheck_passes` | `pnpm exec depcheck` exits 0 | integration (CI gate) |
| `test_bundlewatch_budgets_enforced` | A deliberate +200KB chunk triggers bundlewatch failure (in fixture) | integration |

**Downstream test impact:**
- 21 files lose `any` casts — type checker may flag downstream issues; resolve as part of this task

**Acceptance criteria:**
- [ ] CI runs all 5 new gates green on this PR
- [ ] Four tests pass
- [ ] `pnpm exec knip` reports 0 unused exports

---

#### T-A-2-03: Sentry wiring (`@sentry/nextjs`)

**Type:** config + impl
**depends_on:** [T-A-2-01]
**blocks:** none
**Target files:**
- `apps/worldview-web/package.json` — add `@sentry/nextjs@^8`
- `apps/worldview-web/sentry.client.config.ts` (NEW)
- `apps/worldview-web/sentry.server.config.ts` (NEW)
- `apps/worldview-web/sentry.edge.config.ts` (NEW)
- `apps/worldview-web/next.config.ts` — wrap with `withSentryConfig`
- `apps/worldview-web/components/instrument/EntityGraphErrorBoundary.tsx` — replace stubbed comment with `Sentry.captureException`
- `apps/worldview-web/app/error.tsx` — `Sentry.captureException(error)` in `useEffect`
- `infra/secrets` — add `SENTRY_DSN` env var
- `apps/worldview-web/.env.example` — document `NEXT_PUBLIC_SENTRY_DSN`

**PRD reference:** F-CODE-NEW-010, master report §3.4

**What to build:** Frontend error monitoring online before any refactor lands. Tag every event with `tenant_id`, `user_id`, `route`, `panel_id`, `linkColor`. Replace all `console.error` with `Sentry.captureException`.

**Logic & Behavior:**
- `sentry.client.config.ts`: `Sentry.init({dsn, tracesSampleRate: 0.1, replaysSessionSampleRate: 0.0, replaysOnErrorSampleRate: 1.0})` — replays only on error to control cost
- Source-map upload via `next-sentry` build hook (auth via `SENTRY_AUTH_TOKEN`)
- `useUser()` hook calls `Sentry.setUser({id, email})` on auth state change
- Web Vitals reported to Sentry Performance via `reportWebVitals` in `app/layout.tsx`
- ErrorBoundary catches surfaced via `Sentry.withErrorBoundary` HOC (already partially used in `EntityGraphErrorBoundary`)

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_sentry_init_called_on_client` | `sentry.client.config.ts` calls `Sentry.init` | unit |
| `test_error_boundary_calls_capture_exception` | A thrown error in a child triggers `Sentry.captureException` (mock spy) | unit |
| `test_set_user_on_auth_change` | When auth context flips to authenticated, `Sentry.setUser` called with `{id, email}` | unit |
| `test_no_console_error_in_production_code` | Grep across `app/` and `components/` finds 0 `console.error` outside test files (replaced with `Sentry.captureException` or toast) | unit |
| `test_dsn_env_var_required_in_production` | Build fails if `NEXT_PUBLIC_SENTRY_DSN` not set in `NODE_ENV=production` | integration |

**Downstream test impact:**
- 38 sites with inline `error` strings to be addressed (incremental; this task does the 5 highest-traffic; rest in Wave 6)
- 12 `console.error` sites replaced

**Acceptance criteria:**
- [ ] Throw deliberate error in dev → appears in Sentry within 30s with sourcemap
- [ ] User context attached to events
- [ ] Five tests pass
- [ ] Source-map upload works in build pipeline

---

#### T-A-2-04: Fix `UtcClock` (and similar) hydration mismatch

**Type:** impl
**depends_on:** none
**blocks:** none
**Target files:**
- `apps/worldview-web/components/shell/UtcClock.tsx` (line 44)
- `apps/worldview-web/components/shell/MarketStatusPill.tsx` (similar pattern)
- `apps/worldview-web/components/ui/data-timestamp.tsx` (similar)
- Any other file with `useState(() => formatXxx(new Date()))` or `useState(() => Math.random())`

**PRD reference:** F-CODE-NEW-004, master report §3.4 NEW-004

**What to build:** Lazy initializer in `useState(() => browserApi())` runs **on the server** during SSR with the server's clock and **again on the client** during hydration with the client's clock — they will differ. `suppressHydrationWarning` papers over the warning but doesn't prevent the actual DOM-diff repaint cost.

**Logic & Behavior:**

```tsx
// before
const [time, setTime] = useState<string>(() => formatUtcTime(new Date()));

// after
const [time, setTime] = useState<string>("");          // empty string SSR + first hydration
useEffect(() => {
  setTime(formatUtcTime(new Date()));
  const id = setInterval(() => setTime(formatUtcTime(new Date())), 1000);
  return () => clearInterval(id);
}, []);
```

Alternative for components with no useful SSR content: `dynamic(() => import("./UtcClock"), { ssr: false })` from the parent.

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_utc_clock_renders_empty_on_server` | SSR render returns `<span></span>` (no clock value) | unit (Next.js SSR test) |
| `test_utc_clock_populates_on_mount` | After mount, `<span>` contains time matching `HH:MM:SS UTC` regex | component |
| `test_no_hydration_mismatch_warning` | Render via `next/router` with `suppressHydrationWarning={false}` — no warning emitted | integration |

**Downstream test impact:**
- Existing `UtcClock` snapshot test — server render snapshot will change

**Acceptance criteria:**
- [ ] Three tests pass
- [ ] DevTools console shows zero hydration mismatch warnings on `/dashboard` reload

---

#### T-A-2-05: Tune `next.config.ts` (React Compiler, optimizePackageImports, removeConsole)

**Type:** config
**depends_on:** none
**blocks:** none
**Target files:** `apps/worldview-web/next.config.ts`
**PRD reference:** F-CODE-NEW-014, master report §3.4 NEW-014

**What to build:**

```ts
const nextConfig: NextConfig = {
  // ... existing
  experimental: {
    reactCompiler: true,                                  // auto-memoization (React Forget)
    optimizePackageImports: ["lucide-react", "@radix-ui/react-icons", "@tanstack/react-query", "date-fns"],
  },
  compiler: {
    removeConsole: process.env.NODE_ENV === "production" ? { exclude: ["error", "warn"] } : false,
  },
  productionBrowserSourceMaps: true,                     // for Sentry
};
```

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_react_compiler_enabled` | `next.config.ts` exports `experimental.reactCompiler: true` | unit |
| `test_console_log_stripped_in_production_build` | Production build of a fixture `console.log("x")` returns chunk without that string | integration |
| `test_console_error_preserved` | Production build keeps `console.error` (excluded list) | integration |

**Downstream test impact:**
- Production bundle size shrinks (~5–8% from `optimizePackageImports`)
- React Profiler should show fewer manual `useMemo` needs (Compiler auto-memoizes)

**Acceptance criteria:**
- [ ] `next build` completes successfully with new flags
- [ ] Three tests pass
- [ ] Bundle analyzer shows reduction
- [ ] Production build does not include dev `console.log` strings

---

#### T-A-2-06: tsconfig stage 1 (cheap strict flags)

**Type:** config
**depends_on:** [T-A-2-02]
**blocks:** none
**Target files:** `apps/worldview-web/tsconfig.json`
**PRD reference:** F-CODE-NEW-001, master report §3.4

**What to build:** Enable inexpensive strict flags first; defer `noUncheckedIndexedAccess` to Wave 6 (~300 errors expected).

```json
{
  "compilerOptions": {
    "strict": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "verbatimModuleSyntax": true
  }
}
```

**Tests:** `pnpm typecheck` clean.

**Acceptance criteria:**
- [ ] Three new flags present
- [ ] `pnpm typecheck` exits 0

---

#### T-A-2-07: Delete legacy `Sidebar.tsx`; add CI guard

**Type:** impl + config
**depends_on:** none
**blocks:** none
**Target files:**
- DELETE `apps/worldview-web/components/shell/Sidebar.tsx` (267 LOC, zero imports)
- `apps/worldview-web/.eslintrc.json` — custom rule `worldview/no-orphan-shell-components`
- `apps/worldview-web/scripts/check-orphans.ts` (NEW) — uses `knip` to detect 0-import shell components

**PRD reference:** F-LAYOUT-002

**What to build:** Verified zero imports. Delete the file. Add a CI grep guard: any file under `components/shell/` with zero imports fails the build.

**Tests to write:**

| Test Name | What It Verifies | Type |
|-----------|-----------------|------|
| `test_legacy_sidebar_deleted` | `components/shell/Sidebar.tsx` does not exist | unit (FS) |
| `test_orphan_check_catches_zero_import_files` | A fixture orphan file fails `pnpm exec check-orphans` | integration |

**Acceptance criteria:**
- [ ] File deleted
- [ ] CI gate green
- [ ] Two tests pass

---

### Wave A-3 — Validation gate ✅
**Status: DONE — 2026-04-30 · all green**

Before W0 closes:
- [ ] All Wave A-1 + A-2 tests pass (~30 new tests)
- [ ] `pnpm typecheck` exits 0
- [ ] `pnpm exec ruff format` (no Python here, skip)
- [ ] `pnpm lint` exits 0
- [ ] `pnpm test` exits 0 with no regression
- [ ] Lighthouse CI green for `/dashboard` (LCP < 1.8s, CLS < 0.1, Perf >= 90)
- [ ] Sentry DSN set in `.env.local`; deliberate test error appears in Sentry dashboard
- [ ] Bookmark `localhost:3001` — favicon shows brand mark
- [ ] Visual smoke check: green/red on `/dashboard` and `/screener` reads "institutional" not "TradingView teal"
- [ ] No `console.error` in `components/` outside `// eslint-disable` (grep test)
- [ ] `pnpm exec depcheck` exits 0
- [ ] `pnpm exec knip` exits 0

### Wave A-4 — Break impact

| Broken File | Why It Breaks | Fix Required |
|-------------|--------------|-------------|
| `__tests__/HeatCell.test.tsx` | Color tokens changed | Regenerate snapshots |
| `__tests__/MarketHeatmap.test.tsx` | Same | Regenerate snapshots |
| `__tests__/SectorHeatmapWidget.test.tsx` | Same | Regenerate snapshots |
| `__tests__/UtcClock.test.tsx` | SSR render now empty | Update SSR snapshot |
| 13 component tests using `text-amber-*` | Class names changed via codemod | Regenerate snapshots |
| 21 files using `: any` | ESLint now `error` | Replace with `unknown` + narrow, or add `// eslint-disable` with reason comment |
| 12 files using `console.error` | Replaced with `Sentry.captureException` or `toast.error` | Update import + call site |
| Existing E2E tests asserting `<head>` | Metadata extended | Update assertions |

### Wave A-5 — Regression guardrails

- **BP-NEW-G** `:root` and `.dark` blocks drift silently → migrate to Style Dictionary in Wave 1, but monitor with grep gate.
- **BP-NEW-F** Lazy initializer hydration mismatch → covered by T-A-2-04; lint rule deferred (custom rule complex).
- **HR-NEW-3** Hardcoded hex in `lib/utils.ts` → covered by T-A-1-03 + grep gate.
- **HR-NEW-1** UI primitive default at consumer SaaS scale → deferred to Wave 3 (`<Button>`/`<Input>` density variants).
- **BP-009** (existing) "ENV var not set in production" → covered by T-A-2-03 build-time check.

---

## 4. PLAN-0059-B — Workflow Grammar (Wave 1, Track A) ✅ (B-1/B-2/B-3/B-5 partial)
**Status: B-1 + B-2 + B-3 + B-5 (mnemonics) DONE — 2026-04-30 · 934 tests pass · lint+typecheck clean**
**Deferred to follow-up:** B-3 command palette `>action` mode (needs Action Registry — its own scope), B-4 SymbolBar (needs S9 recents endpoint), B-6 idle/session/multi-tab.

**Goal:** Implement the keyboard-driven, command-driven, symbol-first interaction grammar that defines an institutional terminal. Closes the single most damaging signal of the audit ("dead StatusBar shortcuts").
**Depends on:** PLAN-0059-A complete.
**Effort:** 3 calendar weeks (1 engineer).
**Architecture layer:** mixed (hooks / context / shell components / routes)

### Wave structure (high-level — to be expanded by next `/plan` invocation)

- **B-1 (3d) Hotkey infrastructure:** `lib/hotkey-registry.ts`, `hooks/useChordHotkeys.ts`, `<HotkeyProvider>`, `<HotkeyScope>`, scope stack (modal/input/chart/table/global), 1.2s chord-reset window, suspends inside inputs.
- **B-2 (2d) Cheat sheet + StatusBar refactor:** `components/shell/HotkeyCheatSheet.tsx` (`?` overlay, auto-derived from registry), StatusBar reads from registry (impossible to advertise unwired chord).
- **B-3 (3d) Command palette superset:** Extend `GlobalSearch` to 3-mode parser (`>` actions / `?` help / `/` saved screens / `>>` AI mode), Action Registry `lib/command-actions.ts` with ~30 commands, ranking algorithm (recent-decay + fuzzy).
- **B-4 (2d) SymbolBar in StatusBar:** Persistent symbol input + 10 most-recent symbols pill row + active-link-color indicator + `Tab+function` Bloomberg pattern.
- **B-5 (3d) Bloomberg mnemonics on `/instruments/[id]`:** `D/G/F/N/H/R/E/O` → tab navigation when no input focused. Hooks per route via `<HotkeyScope page="/instruments/[id]" keys={...}/>`.
- **B-6 (2d) Session handling + URL state foundation:** Idle timeout/auto-lock (15min), session-expired graceful redirect with `?next=`, force-update banner via build-version mismatch, multi-tab sign-out via BroadcastChannel.

**Tests per wave:** ~10–15 each, totaling ~70 tests for the sub-plan.

### Critical tests to ensure
- `test_chord_g_d_navigates_to_dashboard`
- `test_chord_resets_after_1200ms`
- `test_chord_suspended_when_input_focused`
- `test_chord_suspended_when_modal_open`
- `test_cheat_sheet_lists_only_registered_chords` (impossible-promises test)
- `test_command_palette_action_mode_parses_>`
- `test_command_palette_help_mode_parses_?`
- `test_symbol_bar_pill_click_loads_instrument`
- `test_instrument_page_d_chord_jumps_to_overview_tab`
- `test_idle_timeout_locks_after_15min`
- `test_session_expired_redirects_with_next_param`
- `test_force_update_banner_when_version_mismatch`

---

## 5. PLAN-0059-C — Contract Spine (Wave 1, Track B) ✅ (C-2/C-3/C-4/C-5 partial)

**Status**: **PARTIAL DONE** — 2026-04-30 · 1,017 frontend tests pass · ruff/lint/typecheck clean

**Goal:** Establish typed, drift-free contracts between frontend and backend. Eliminate hand-typing, scattered query keys, recomputed gateway factories, and four parallel formatters.
**Depends on:** PLAN-0059-A complete.
**Parallel-safe with PLAN-0059-B.**
**Effort:** 3 calendar weeks.

### Wave structure (high-level)

- **C-1 (3d) OpenAPI codegen:** `openapi-typescript` + `openapi-fetch` adoption. `scripts/generate-api-types.ts` + CI drift gate. `types/generated/api.ts` committed; `types/api.ts` shrinks to <80 LOC re-export shim. **DEFERRED** to dedicated wave (requires backend OpenAPI ergonomics work + CI gate).
- **C-2 (2d) Query-key factory ✅:** `lib/query/keys.ts` hierarchical factory shipped (50+ keys across portfolios/watchlists/instruments/quotes/news/screener/alerts/chat/dashboard/workspace/search/feedback/user/brokerage). ESLint `no-restricted-syntax` rule registered as `warn` (153 legacy sites flagged for incremental migration; promote to `error` when migration completes).
- **C-3 (1d) `useApiClient()` provider ✅:** `lib/api-client.tsx` memoises `createGateway(token)` per token (===). `useAuthedQuery` wrapper auto-disables on missing token. Mounted in `app/providers.tsx` inside AuthProvider.
- **C-4 (1.5d) `useInterval` + `lib/storage/safe-storage.ts` ✅:** Abramov pattern shipped (`hooks/useInterval.ts`); 6 raw `setInterval` call sites identified, UtcClock migrated as proof-of-pattern. `lib/storage/safe-storage.ts` shipped with hand-rolled validator (zod-compatible interface; swap when zod added). Sidebar expanded/width localStorage migrated as proof-of-pattern. Zustand-persist DEFERRED to follow-up.
- **C-5 (1d) `lib/format.ts` consolidation ✅:** Canonical `lib/format.ts` shipped (`formatCompact`, `formatCompactCurrency`, `formatPrice`, `formatPercent`, `formatPercentUnsigned`, `formatBasisPoints`, `formatRatio`). Multi-currency: USD/EUR/GBP/JPY/CHF/CAD/AUD/CNY/HKD/KRW/BTC/ETH. `lib/utils.ts` formatters re-export from canonical module (zero call-site churn). `ScreenerTable.formatCap` and `InstrumentAskAiButton` mcap formatter migrated.
- **C-6 (2d) `nuqs` URL state:** Adopt on screener filters, portfolio tab, equity-curve period, transaction filter, active workspace. Document URL-state schema in `docs/ui/URL_STATE.md`. **DEFERRED** to dedicated wave (multi-feature touch).

### Critical tests
- `test_api_types_generated_from_openapi_drift_gate` — CI fails if generated file out of sync
- `test_query_key_factory_invalidation_cascades` — `qc.invalidateQueries({queryKey: qk.portfolio(id)})` invalidates all child keys
- `test_eslint_blocks_inline_queryKey` — fixture with `queryKey: ["foo"]` fails lint
- `test_use_api_client_memoizes_per_token` — same token returns same client instance (===)
- `test_use_interval_calls_latest_callback` — Abramov pattern: closure captures latest, not stale
- `test_safe_storage_zod_validates_on_read` — corrupted JSON returns `defaultValue`, not crashes
- `test_format_compact_currency_multi_currency` — EUR/GBP/JPY/BTC each render with correct symbol
- `test_format_basis_points` — returns `+23 bps` / `-12 bps`
- `test_url_state_screener_filter_round_trips` — set filter, reload page, filter restored

---

## 6. PLAN-0059-D — Real-Time + WS Proxy (Wave 2, Track A)

**Goal:** Close the single largest demo gap — WebSocket quote stream + per-cell tick flash. Replaces 15s polling.
**Depends on:** PLAN-0059-A complete; PLAN-0059-C C-1 (codegen).
**Parallel-safe with PLAN-0059-E.**
**Effort:** 2 calendar weeks (BE-bound).

### Wave structure

- **D-1 (3d, BE) S2 Kafka producer + Avro schema:** `quotes.tick.v1` Avro schema `{instrument_id, last, bid, ask, bid_size, ask_size, ts, exchange}`; S2 fork after Alpaca WS ingest persist → produce to Kafka.
- **D-2 (3d, BE) S9 WebSocket fanout route:** `/v1/quotes/stream` with subprotocol JWT auth (browser-compatible); subscribe/unsubscribe protocol; heartbeat 15s.
- **D-3 (1d, BE) S9 alerts WS proxy:** `/v1/alerts/stream` proxying to S10 internal; drops `NEXT_PUBLIC_WS_BASE_URL` env var; CSP `connect-src 'self'`.
- **D-4 (2d, FE) `QuoteStreamProvider` + `useQuoteStream(ids)` + `FlashBus`:** Single connection ref-counted; rAF backpressure; visibility-aware suspend.
- **D-5 (2d, FE) `useTickFlash` + cell rollout:** Apply to IndexTicker → LiveQuoteBadge → WatchlistPanel → ScreenerTable price/change → PortfolioSummary MTM → TopMovers → WorkspaceChartWidget last-bar.
- **D-6 (1d, FE) StatusBar connection-status dot:** 3px teal/amber/red dot; latency display.

### Critical tests
- `test_quotes_tick_avro_schema_forward_compatible` (contract test)
- `test_s2_produces_to_kafka_after_alpaca_tick` (integration)
- `test_s9_ws_subprotocol_jwt_auth_rejects_invalid` (integration)
- `test_use_quote_stream_subscribes_on_mount`
- `test_use_quote_stream_unsubscribes_on_unmount`
- `test_use_tick_flash_returns_up_on_increasing_value`
- `test_use_tick_flash_returns_down_on_decreasing`
- `test_use_tick_flash_returns_null_after_450ms`
- `test_use_tick_flash_respects_prefers_reduced_motion`
- `test_flash_bus_raf_batches_above_40_emits_per_second`
- `test_index_ticker_flashes_on_tick` (E2E via mock WS)
- `test_screener_row_flashes_on_quote_update` (E2E)
- `test_status_bar_dot_red_after_3_consecutive_ws_failures`

---

## 7. PLAN-0059-E — God-File Decomposition (Wave 2, Track B) ✅ (E-1 done · E-2 done · E-3 done · E-4 done · E-5 done)

**Status: E-1 DONE — 2026-05-02 · 1218 frontend tests pass · typecheck + lint clean · 15-endpoint live curl matrix verified**

**Status: E-2 partial DONE — 2026-05-02 · 1249 frontend tests pass (+31 new kpi unit tests) · typecheck + lint clean · /portfolio renders 200**

**Status: E-2-followup DONE — 2026-05-02 · 1293 frontend tests pass · typecheck + lint clean · build OK · `app/(app)/portfolio/page.tsx` 1,175 → 363 LOC (69% additional cut, 1,745 → 363 cumulative = 79% total reduction) · usePortfolioData orchestrator hook + 5 extracted components**

**Status: E-3 partial DONE — 2026-05-02 · 1286 frontend tests pass · typecheck + lint clean · /chat renders 200 · 6 chat sub-components extracted**

**Status: E-3-followup DONE — 2026-05-02 · 1293 frontend tests pass (+7 new useChatStream SSE-abort/[DONE]/error/slash/auto-thread tests) · typecheck + lint clean · build OK · `app/(app)/chat/page.tsx` 916 → 778 LOC (15% additional cut) · SSE/abort lifecycle now isolated in `features/chat/hooks/useChatStream.ts`**

**Status: E-4 DONE — 2026-05-02 · 1286 frontend tests pass (+18 new active-counts unit tests) · typecheck + lint clean · /screener renders 200**

**Status: E-5 DONE — 2026-05-02 · 1268 frontend tests pass (+19 new movers unit tests) · typecheck + lint clean**

**Goal:** Split `lib/gateway.ts` (2,657 LOC), `app/(app)/portfolio/page.tsx` (1,739), `app/(app)/chat/page.tsx` (1,293), `components/screener/ScreenerFilterBar.tsx` (986), `components/dashboard/WatchlistMoversWidget.tsx` (800).
**Depends on:** PLAN-0059-C complete (codegen + URL state).
**Parallel-safe with PLAN-0059-D.**
**Effort:** 2-3 calendar weeks.

### Waves

- **E-3 (4d) Chat page decomposition — partial ✅ 2026-05-02:** `app/(app)/chat/page.tsx` reduced from 1,332 LOC → 916 LOC (31% cut). Extracted 6 pure render sub-components + 2 helper modules under `apps/worldview-web/features/chat/`: `components/MessageBubble.tsx` (TypingIndicator + MessageBubble + StreamingBubble), `components/CitationList.tsx` (with `getCitationIcon` heuristic), `components/SlashTurnBlock.tsx`, `components/ThreadItem.tsx` (sidebar row with rename UX), `lib/types.ts` (StreamingMessage / SlashTurn / LogEntry), `lib/starters.ts` (PLACEHOLDER_THREAD_TITLE / STARTER_QUESTIONS / entityStarters). Validated: 1286/1286 vitest pass, typecheck + lint clean, dev-server compiles `/chat` → HTTP 200 in 1.9s. **NOT YET DONE in E-3** (deferred to E-3-followup): `useChatStream(threadId)` hook extraction (the SSE / abort / ref-state path is the highest regression risk in the chat surface — separate session) and `<ConversationView>` shell.

- **E-3-followup ✅ 2026-05-02 — useChatStream SSE/abort hook:** `app/(app)/chat/page.tsx` reduced from 916 → 778 LOC (15% additional cut, 138 LOC of inline SSE state lifted out). Extracted `features/chat/hooks/useChatStream.ts` (373 LOC) — encapsulates the entire send/stream/abort lifecycle: POST `/api/v1/chat/stream` + `response.body.getReader()` SSE parser, AbortController ref pattern, unmount cleanup, [DONE] sentinel handling, "[Response interrupted]" early-EOF suffix, AbortError swallow, slash-command short-circuit, `crypto.randomUUID()` thread auto-creation, `refetchThreads()` invalidation. Public surface: `{localMessages, setLocalMessages, streaming, chatError, setChatError, isStreaming, send, cancel, resetForThread}`. Page just wires inputs (auth token, active thread id, refetcher). Companion `features/chat/hooks/__tests__/useChatStream.test.tsx` adds **7 unit tests** covering the highest-risk paths: happy [DONE] path / mid-stream cancel / unmount-aborts-fetch / non-2xx → chatError / AbortError-from-fetch swallowed / slash command no-fetch / auto-thread-id creation. The "<ConversationView>` shell extraction stays deferred (orthogonal layout concern, no SSE risk). Validated: 1293/1293 vitest pass (+7 new), lint warnings only (queryKey migration), typecheck clean, `pnpm build` succeeds.

- **E-4 (3d) ScreenerFilterBar split ✅ 2026-05-02:** `components/screener/ScreenerFilterBar.tsx` reduced from 986 LOC → 693 LOC (30% cut). 5 extractions under `apps/worldview-web/features/screener/`: `lib/filter-state.ts` (FilterState + DEFAULT_FILTERS + GICS_SECTORS + CapTier + CAP_TIERS), `lib/active-counts.ts` (`isSet`, `rangeCount`, `countActiveFiltersByGroup`), `lib/__tests__/active-counts.test.ts` (**18 unit tests** covering NaN/Infinity/boolean-false edges, 0-bound treatment, section isolation, top-row exclusion), `components/Section.tsx` (collapsible §0.5 grid-rows wrapper), `components/RangeInput.tsx` (min/max number-pair). FilterState + DEFAULT_FILTERS re-exported from the bar so all existing call sites compile unchanged. Validated: 1286/1286 vitest pass (+18 new), typecheck + lint clean, `/screener` → HTTP 200 in 2.1s. The useReducer migration of the form-state remains for W3 (RHF + Zod).

- **E-5 (2d) WatchlistMoversWidget split ✅ 2026-05-02:** `components/dashboard/WatchlistMoversWidget.tsx` reduced from 800 LOC → 442 LOC (45% cut). 5 extractions under `apps/worldview-web/features/dashboard/`: `lib/movers.ts` (5 pure functions: `buildMoverRows` / `applySectorFilter` / `rankByAbsChangePct` / `splitGainersLosers` / `pickFirstWatchlistByCreatedAt`), `lib/__tests__/movers.test.ts` (**19 unit tests** pinning 1D-vs-1W/1M behaviour, <2-bar / first<=0 edge cases, "loading row stays visible" sector-filter rule, top-N partition rules, deterministic default-watchlist picker), `components/WatchlistMoverRow.tsx` (104 LOC inline → file), `components/WatchlistSummaryStrip.tsx` (73 LOC), `components/BiggestNewsRow.tsx` (30 LOC). Widget body now reads as 4 pure-function calls inside thin useMemo wrappers. Validated: 1268/1268 vitest pass (+19 new), typecheck + lint clean.

- **E-2 (5d) Portfolio page decomposition — partial ✅ 2026-05-02:** `app/(app)/portfolio/page.tsx` reduced from 1,745 LOC → 1,175 LOC (33% cut, 570 LOC removed). Three extractions landed under `apps/worldview-web/features/portfolio/`: (1) `lib/kpi.ts` — pure functions `computePortfolioKPI`, `computeAllocations`, `computeScopeHint`, `livePriceFor`, `formatStalenessAwarePrice` covered by **31 unit tests** in `lib/__tests__/kpi.test.ts` (F-202 top-loser-stays-null, B-2 delisted-instrument fallback, BP-265-aware `realizedPnl=null` while loading, divide-by-zero guards, sector-allocation parity with KPI total). (2) `components/CreatePortfolioDialog.tsx` — extracted dialog (was inline 184 LOC). (3) `components/AddPositionDialog.tsx` — extracted dialog (was inline 213 LOC). Page now imports these and replaces three inline useMemo blocks with calls to the pure functions. Validated: 1249/1249 vitest pass (+31 from E-2), typecheck clean, lint clean, dev-server compiles `/portfolio` to HTTP 200. **NOT YET DONE in E-2:** the 8-query `usePortfolioData` orchestrator hook (full hook extraction deferred — high risk to scramble queryKey/refetchInterval invariants) and the 600+ LOC of tab JSX split into per-tab components. The page is not yet the "<100 LOC orchestrator" the plan calls for; remaining work tracked as E-2-followup.

- **E-2-followup ✅ 2026-05-02 — usePortfolioData orchestrator + tab JSX split:** `app/(app)/portfolio/page.tsx` reduced from 1,175 → 363 LOC (69% additional cut, 812 LOC lifted; cumulative E-2 + followup = 1,745 → 363 = 79% total reduction). Six extractions landed under `apps/worldview-web/features/portfolio/`: (1) `hooks/usePortfolioData.ts` (456 LOC) — owns all 9 useQuery calls (portfolios, holdings, holdings-quotes, transactions, watchlists, watchlist-quotes, realized-PnL FIFO, performance, holdings-overviews) + ROOT-first sort + KPI/allocations/scopeHint useMemo blocks + the F-013 deletePortfolioMutation + the two cross-mutation invalidation callbacks (`handlePortfolioCreated`, `handlePositionAdded`). All queryKey shapes / staleTime / refetchInterval invariants preserved verbatim from the prior inline implementation. (2) `components/PortfolioPageHeader.tsx` (240 LOC) — page chrome with portfolio selector, ALL badge, position-count, Add Position / New Portfolio / Delete buttons + F-021 scope-hint sub-line. (3) `components/PerformanceStrip.tsx` (73 LOC) — period-return chip with `~` prefix when covered_pct < 0.99. (4) `components/HoldingsTab.tsx` (168 LOC) — Holdings tab body wrapping CashManagementCard, RealizedPnLChart, SemanticHoldingsTable, SectorAllocationPanel, RecentActivityFeed, DividendIncomeTimeline, PortfolioAnalyticsSection. (5) `components/TransactionsTab.tsx` (131 LOC) — collapsible Connected Brokerages section + TransactionsTable with reused holdingOverviews ticker enrichment. (6) `components/DeletePortfolioDialog.tsx` (102 LOC) — F-013 destructive-action confirmation with pending-state interlock. The page is now a thin orchestrator: useAuth + 4 dialog booleans + equity period state + `usePortfolioData()` + 6 child components. Validated: 1293/1293 vitest pass (no regressions; same count as E-3-followup since this wave is pure extraction), typecheck clean, lint warnings only (queryKey migration — same pre-existing signal as E-2 partial), `pnpm build` succeeds. The `<100 LOC orchestrator` plan target is not strictly hit (363 LOC) because the page still owns ~80 LOC of TabsList/TabsContent JSX that defines the page's tab routing — splitting those further would push the layout responsibility into a mostly-empty wrapper. Remaining 363 LOC = file header + imports + dialog state + loading/error skeletons + tab routing JSX, which is the irreducible orchestrator surface for this page.

- **E-1 (5d) Gateway split ✅ — 2026-05-02:** `lib/api/{_client,auth,instruments,knowledge-graph,news,screener,portfolios,watchlists,alerts,chat,prediction-markets,dashboard,brokerage,search,feedback}.ts`. `lib/gateway.ts` reduced from 2,906 LOC monolith → 103-LOC shim that imports each factory and merges them via spread, preserving the `createGateway`/`GatewayError`/`Gateway` surface. All ~91 import sites unchanged. Cross-domain `this.X()` calls (search→instruments, watchlists self-refs) use explicit `this:` interface types to avoid circular `ReturnType` traps. 15 modules avg 212 LOC; largest (`portfolios.ts` 667, `instruments.ts` 407) over the 350-LOC plan target — incremental further-split deferred (CI gate not added in this wave to avoid shipping a failing gate). E-2 will kill the shim. Validated end-to-end: 1218/1218 vitest pass, dev-login + 14 representative endpoint curls (auth/instruments/news/screener/portfolios/watchlists/alerts/chat/prediction-markets/dashboard/brokerage/feedback/knowledge-graph/search) all return expected status codes. 2× parallel QA agents (behavioral parity + type/import surface) returned clean.
- **E-2 (5d) Portfolio page decomposition:** `features/portfolio/{components,hooks,queries,lib}/`. `usePortfolioKPI(portfolioId)` hook + `lib/kpi.ts` pure functions + tests. Page <100 LOC orchestrator.
- **E-3 (4d) Chat page decomposition:** `useChatStream(threadId)` (or `@vercel/ai-sdk useChat`); `<ThreadSidebar>`, `<ConversationView>`, `<MessageComposer>`, `<CitationPanel>`. Slash command parsing → `lib/chat/parseSlashCommand.ts`.
- **E-4 (3d) ScreenerFilterBar split:** Per-section subcomponents + `useReducer` filter state (W3 will migrate to RHF+Zod).
- **E-5 (2d) WatchlistMoversWidget split:** `useWatchlistMovers(period, sectorFilter)` + render split.

### Critical tests
- `test_gateway_split_no_circular_imports`
- `test_lib_api_each_file_under_350_loc` (CI gate)
- `test_features_portfolio_page_under_100_loc`
- `test_use_chat_stream_handles_abort_on_unmount`
- `test_use_portfolio_kpi_returns_stable_reference`
- All existing portfolio + chat E2E tests pass after refactor (regression suite)

---

## 8. PLAN-0059-F — Universal Primitives (Wave 3)

**Goal:** Build the primitive layer that every feature consumes. Eliminates ~3,000 LOC of duplication and unlocks bulk-actions/freeze panes/sticky-footer/group-by/saved-views/copy-as-TSV/search-within everywhere at once.
**Depends on:** PLAN-0059-B (hotkeys), PLAN-0059-C (URL state, query keys), PLAN-0059-E (decomp complete).
**Effort:** 3 calendar weeks.

### Waves

- **F-1 (10d) Universal `<DataTable>`:** Full props interface from master report §5.2; replaces 7 tables; ships density variants, virtualization, frozen rows/cols, multi-sort stack, multi-select + bulk actions, inline edit, group-by + sticky footer totals, saved views, exporters (csv/tsv/xlsx/pdf), context menu, FlashBus integration.
- **F-2 (8d) Form layer:** RHF + Zod adoption; `<Form>`/`<FormField>` shell; `<NumberInput>` with TradingView shorthand; `<DateRangePicker>`; `<TimePicker tz>`; `<MultiCombobox>`; `<QuickEditPopover>`.
- **F-3 (2d) `<ContextMenu>` primitive + Action Registry:** 6 categories × 24+ actions; Bloomberg-mnemonic single-letter hotkeys.
- **F-4 (1.5d) Confirm/Undo Pattern Library:** Three-tier ladder T1/T2/T3; `<DestructiveButton>`.
- **F-5 (5d) Polish + a11y:** Skeleton variants, EmptyState consolidation, focus management, dialog stacking, sidesheet/popover rules, icon-button aria-label lint, density variants on Button/Input/Select/Tabs/Dialog primitives.

### Critical tests
- ~120 unit tests across DataTable, Form, ContextMenu, NumberInput, DateRangePicker, MultiCombobox, Skeleton, EmptyState
- ~20 integration tests verifying 7-table migration zero behavioral regression
- 5 E2E tests for bulk-actions on each table

---

## 9. PLAN-0059-G — Performance + Bundle (Wave 4)

**Goal:** Drop recharts; dynamic-import all heavy widgets; React 19 patterns; Server Components audit; CI performance budgets.
**Depends on:** PLAN-0059-F (primitive layer stable).
**Parallel-safe with PLAN-0059-H + I.**
**Effort:** 1 calendar week.

### Waves

- **G-1 (3d) Drop recharts:** Migrate `EquityCurveChart`, `RevenueTrendSparklines`, `EarningsHistoryChart` to `lightweight-charts` line series; `<Sparkline>` rollout to 7 panels.
- **G-2 (2d) Dynamic imports:** All dialogs, EntityGraph, WorkspaceGrid, KnowledgeGraph, MarkdownRenderer, ScreenerFilterBar, PDF/Excel exports — go from 1 to ~15+ dynamic imports.
- **G-3 (3d) React 19 patterns:** `React.memo` on row/cell leaves; `useDeferredValue` on filter inputs; `useTransition` on tab switches; stable callbacks.
- **G-4 (5d) Server Components audit:** Strip `"use client"` from 30-50 pure-render components.
- **G-5 (2d) Storybook 8 + Chromatic:** Top 25 primitives + 12 financial widgets cataloged.

### Critical tests
- React Profiler before/after on `/screener` filter input — render count drops 5–10×
- `pnpm exec bundlewatch` enforces budgets per route
- Lighthouse CI per route — LCP < 1.8s, CLS < 0.1

---

## 10. PLAN-0059-H — Multi-Pane Charts + Workspace v2 (Wave 5)

**Depends on:** PLAN-0059-F (universal primitives).
**Parallel-safe with G + I.**
**Effort:** 3 calendar weeks.

### Waves

- **H-1 (2d) lightweight-charts v5 upgrade:** API factory pattern rewrite (~14 series creation calls in OHLCVChart).
- **H-2 (3d) OHLCV power features:** Crosshair HUD, log scale, compare overlay, earnings/news/alert markers, range selector, EquityCurveChart Brush.
- **H-3 (1.5d) Squarified treemap:** `lib/treemap.ts` Bruls/Huijsen/van Wijk algorithm; collapses MarketHeatmap + SectorHeatmapWidget.
- **H-4 (2d) Knowledge Graph filters:** Filter pills, edge-strength slider, search input, layout switcher, drill-down side-panel.
- **H-5 (4d) Workspace v2:** Quad template + workspace SymbolBar + drag-tray Add Panel + chord splits.
- **H-6 (5d) Multi-monitor pop-out:** `Maximize2` + `Pop out` icon; `window.open` + BroadcastChannel sync; detached-window persistence.
- **H-7 (5d) Workspace S9 sync:** 3-tier (localStorage + S9 durable + share-link).

### Critical tests
- `test_oklcv_v5_pane_isolation` — RSI in pane 1 doesn't bleed into MACD pane 2
- `test_crosshair_hud_renders_ohlcv_at_hovered_bar`
- `test_log_scale_toggle_changes_axis`
- `test_compare_overlay_rebases_to_index_100`
- `test_squarified_treemap_aspect_ratio_within_2x` — Bruls property
- `test_workspace_quad_template_links_4_panels`
- `test_pop_out_panel_via_window_open`
- `test_broadcast_channel_syncs_symbol_change`
- `test_workspace_s9_conflict_409_resolution`

---

## 11. PLAN-0059-I — IA Correctness + Hardening (Wave 6)

**Depends on:** PLAN-0059-F.
**Parallel-safe with G + H.**
**Effort:** 2 calendar weeks.

### Waves

- **I-1 (3d) Promote `/watchlists` to real hub:** `/watchlists`, `/watchlists/[id]`, `/watchlists/[id]/edit`, `/watchlists/new`. Remove `/portfolio` watchlists tab.
- **I-2 (2d) Promote `/news` to feed:** `/news`, `/news/[id]`, `/news/feeds`. Replace 307 redirect.
- **I-3 (3d) Settings reorg to 11-route tree:** `/settings/{profile,preferences,appearance,notifications,shortcuts,data,security,integrations,api-keys,billing,feedback,danger}`.
- **I-4 (4d) User preferences (BE+FE):** Timezone selector, currency selector (with FX layer), density toggle, a11y settings panel — backed by S1 user profile extensions.
- **I-5 (5d) Page-bundle endpoints (BE+FE):** S9 `/v1/portfolios/{id}/page-bundle`, `/v1/instruments/{id}/page-bundle` — collapse 12-deep waterfalls.
- **I-6 (5d) Hardening:** `tsconfig` stage 2 (`noUncheckedIndexedAccess`); nonce-based CSP via `middleware.ts`; Suspense boundaries everywhere; idle timeout/auto-lock; print stylesheets; cookie consent.

### Critical tests
- `test_watchlists_hub_renders_at_root`
- `test_no_uncheckedIndexedAccess_compile_clean`
- `test_csp_nonce_per_request`
- `test_idle_timeout_locks_after_15min_inactive`
- `test_print_stylesheet_renders_light_palette`
- `test_page_bundle_endpoint_returns_in_one_round_trip` (integration)

---

## 12. PLAN-0059-J — Differentiators (Wave 7)

**Depends on:** PLAN-0059-F.
**Parallel-safe with all.**
**Effort:** 4-6 calendar weeks. **Long-tail.** Items can be cut.

### Waves (each independent)

- **J-1 (3d) Recent items / pins / saved-items / tags / search history**
- **J-2 (3d) Versioning of saved screens / saved layouts** (append-only with "View history" drawer)
- **J-3 (3d) Drag-drop between surfaces:** screener row → watchlist; chart annotation → research note (`@dnd-kit/core`)
- **J-4 (1d) Quick-add FAB pattern**
- **J-5 (3d) CSV bulk import wizard** (Upload → Preview/Map → Confirm; `papaparse`)
- **J-6 (3d) Trade ticket slide-in** (read-only preview MVP)
- **J-7 (4d) Visualizations:** underwater drawdown, rolling beta vs SPY, factor radar, Brinson-Fachler attribution
- **J-8 (1.5d) News sentiment overlay on price charts** (S6 `composite_score`)
- **J-9 (2d) Annotation cloud sync** (S9 `/v1/annotations`)
- **J-10 (5d) B2B foundations:** org switcher, audit log surface, role-gate, permissions
- **J-11 (4d) Onboarding flow + coachmark tour** (Driver.js)
- **J-12 (5d) Mobile/tablet pass:** responsive 1280/1024/768/480, long-press, pull-to-refresh

### Critical tests
- ~80 unit tests
- ~15 E2E tests covering each differentiator end-to-end

---

## 13. Cross-Cutting Concerns

### 13.1 Contract changes

- `quotes.tick.v1` Avro schema (NEW; D-1)
- S9 OpenAPI document (verify exposed; C-1)
- S9 `/v1/instruments/search` response shape extended (F-COMP-005; D-1 or earlier)
- S9 page-bundle endpoints (NEW; I-5)
- S9 `/v1/quotes/stream` WS protocol (NEW; D-2)
- S9 `/v1/alerts/stream` WS protocol (modified; D-3)
- S9 `/v1/workspaces` REST + share token (NEW; H-7)
- S9 `/v1/annotations` REST (NEW; J-9)
- S1 user profile extensions (defaultCurrency, defaultTimezone, density, role, region; I-4)
- S1 `/v1/users/me/onboarding-state` (NEW; J-11)
- S5 (or S2) `/v1/fx/rates` (NEW; C-5 multi-currency)

### 13.2 Migration needs (backend)

- S2 Kafka producer config: add `quotes.tick.v1` producer
- S9: register WebSocket routes in FastAPI
- Schema Registry: register `quotes.tick.v1` Avro schema
- S1 DB migration: add user profile columns (defaultCurrency, defaultTimezone, density)
- S9 DB migration: workspaces table, annotations table, share_tokens table

### 13.3 Event flow changes

- New: Alpaca WS → S2 → Kafka `quotes.tick.v1` → S9 → Frontend WS clients
- Modified: S10 alert events now flow via S9 proxy (CSP cleanup)

### 13.4 Configuration changes

- New env vars in `apps/worldview-web/.env.example`:
  - `NEXT_PUBLIC_SENTRY_DSN`
  - `SENTRY_AUTH_TOKEN` (build-only)
- Removed: `NEXT_PUBLIC_WS_BASE_URL` (after D-3)
- New backend env: `KAFKA_QUOTES_TICK_TOPIC`
- New `bundlewatch.config.json`, `.lighthouserc.json` in repo root

### 13.5 Documentation updates

- `docs/ui/DESIGN_SYSTEM.md` — major rewrite (14 sections per master report §10.3)
- `docs/ui/URL_STATE.md` — NEW (C-6)
- `docs/services/api-gateway.md` — new endpoints
- `docs/MASTER_PLAN.md` — note workflow grammar architecture
- `apps/worldview-web/README.md` — codegen workflow, hotkey reference, Sentry setup
- `RULES.md` — 10 new candidate rules from master report §10.4

---

## 14. Risk Assessment

### 14.1 Critical path

PLAN-0059-A (W0) gates everything. Then B/C run in parallel; D/E in parallel after B/C. F gates G/H/I. J is long-tail.

The single highest-leverage path: **A → B → D = 6 calendar weeks** (closes the four signals that disqualify a 90-second BlackRock demo).

### 14.2 Highest-risk waves

- **PLAN-0059-D (Real-time):** depends on backend; WS auth + reconnection + CSP changes. Mitigation: feature flag `NEXT_PUBLIC_QUOTE_STREAM=off` falls back to current polling paths.
- **PLAN-0059-E (Decomposition):** 387 sites in `createGateway`, 1,739-LOC portfolio page. Mitigation: keep `lib/gateway.ts` as re-export shim for one wave; behind feature flag at portfolio page; smoke-test at every step.
- **PLAN-0059-H multi-monitor:** subtle BroadcastChannel sync edge cases; window-state persistence. Mitigation: opt-in feature flag for first ship.
- **tsconfig stage 2 (`noUncheckedIndexedAccess`):** ~300 errors expected. Mitigation: scoped to single PR; not blocking.

### 14.3 Rollback strategy

- A: per-task; each is independently reversible.
- B: Hotkey infrastructure feature-flagged via `NEXT_PUBLIC_HOTKEYS=on`.
- C: Codegen reverts to hand-typed via dual exports during transition.
- D: WS opt-in feature flag.
- E: god-files retained as shims for one wave.
- F: DataTable migration table-by-table, not all-at-once.

### 14.4 Testing gaps

- Multi-monitor pop-out: hard to E2E-test (Playwright single-context). Mitigate with unit tests on `useDetachedPanel` + manual smoke checks.
- Real-time tick flash: need mock WebSocket harness for E2E. Build `tests/e2e/_helpers/mockWs.ts`.
- Color-blind simulation: automate via `culori` + Coblis algorithm in unit tests.

---

## 15. Estimated Total Test Coverage

| Wave | New tests | Cumulative |
|------|:---------:|:----------:|
| A (W0) | ~30 | 30 |
| B (W1A) | ~70 | 100 |
| C (W1B) | ~50 | 150 |
| D (W2A) | ~40 | 190 |
| E (W2B) | ~30 (regression) | 220 |
| F (W3) | ~140 | 360 |
| G (W4) | ~25 (mostly perf assertions) | 385 |
| H (W5) | ~60 | 445 |
| I (W6) | ~40 | 485 |
| J (W7) | ~95 | 580 |
| **Total** | **~580** | |

Plus existing 815 frontend Vitest + Playwright E2E suite — combined target **~1,400 tests** for full coverage of the 172 fix items.

---

## 16. Recommended Execution Order

1. **Week 1:** PLAN-0059-A — `/implement PLAN-0059-A Wave A-1` then Wave A-2 then A-3 validation
2. **Weeks 2–4:** PLAN-0059-B (Track A engineer) parallel with PLAN-0059-C (Track B engineer)
3. **Weeks 5–6:** PLAN-0059-D (full-stack engineer, has backend) parallel with PLAN-0059-E (frontend engineer)
4. **Weeks 7–9:** PLAN-0059-F (single engineer or split DataTable + Forms)
5. **Weeks 10–13:** PLAN-0059-G + H + I in parallel (3 engineers if available; 2 if not)
6. **Weeks 14+:** PLAN-0059-J long-tail; ship items independently

**Minimum BlackRock-demo path:** A + B + D = 6 calendar weeks (2 engineers).
**BlackRock-credible:** A + B + C + D + E + F = 12 calendar weeks (2 engineers).
**Production-grade:** Full plan = 16 calendar weeks (2 engineers).

---

## 17. Open Questions / Risks Requiring Decision

1. **i18n (F-CODE-NEW-013):** Pursue only if BlackRock APAC is real. If yes, add as PLAN-0059-K. If no, defer.
2. **Workspace marketplace (PLAN-0059-H stretch):** Build now or after demo? Recommend defer.
3. **Real-time backend ownership:** Does S2 add the Kafka producer, or is a new lightweight `quote-fanout` service preferable? Recommend extend S2 (smaller change).
4. **Style Dictionary (F-VISUAL-NEW-A):** Adopt now (Wave A) or defer (Wave 6)? Recommend defer — token surgery (T-A-1-02) closes the immediate WCAG/visual gaps; pipeline is structural improvement that can wait.
5. **Storybook 8 vs Ladle:** Both viable. Recommend Storybook 8 for Chromatic ecosystem.
6. **`@vercel/ai-sdk useChat` vs custom `useChatStream`:** Adopt SDK if S8's SSE is OpenAI-compatible (it is). Recommend adopt — saves 2d.

---

## 18. Compounding Updates

Per CLAUDE.md compounding rules, this plan triggers updates to:

- `docs/BUG_PATTERNS.md` — add 9 patterns (BP-NEW-A through BP-NEW-I per master report §10.1)
- `.claude/review/heuristics/HIGH_RISK_PATTERNS.md` — add 10 patterns per master report §10.2
- `.claude/review/checklists/REVIEW_CHECKLIST.md` — add 10 review checks per master report §10.5
- `RULES.md` — 10 candidate rules per master report §10.4
- `docs/ui/DESIGN_SYSTEM.md` — major rewrite (14 sections per master report §10.3)
- 13 CI gates per master report §10.6

These updates will be authored as part of each sub-plan's wave commits, not in a separate documentation pass.

---

## Next step

`/implement PLAN-0059-A Wave A-1`

This kicks off the 1-week Wave 0. After A-1 (token surgery + brand) ships, run `/qa --plan PLAN-0059-A` then proceed to A-2 (deps + observability + ESLint).

Subsequent `/plan` invocations should expand each of PLAN-0059-B through PLAN-0059-J into full task detail before their `/implement` sessions, using this master plan as the source.
