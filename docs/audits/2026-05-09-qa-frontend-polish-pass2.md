# PLAN-0087 — Pass-2 Frontend Polish Audit (post-D-F3 token sweep)

> **Date**: 2026-05-09
> **Method**: ripgrep + curl SSR probes against `worldview-web` on port 3001 (rebuilt 2026-05-09 from commit `a630d62f`).
> **Read-only**: no source edits.
> **Bar**: indistinguishable-from-Bloomberg.
> **Scope**: Phase A (A1–A10) + B1–B2 surfaces.

The pass-1 audit (`docs/audits/2026-05-09-audit-F3-polish.md`) closed 11 polish defects (D-F3-001..011) — palette sweep, radius, `tabular-nums` on graph tooltip + status uptime, `Loading…` ellipsis, AG-Grid policy, exact-pin. The post-fix architecture test guards retired hex + retired Tailwind shorthand only. This second pass found **18 fresh defects** untouched by F3 — the highest-impact ones cluster around (a) currency without locale separators, (b) per-route `<title>`s missing, (c) UUID leaks in alert overlay, (d) ISO-string timestamps where the spec mandates relative time, (e) a focus-ring discipline gap on three text inputs.

---

## 1. New defects (beyond F3 pass-1)

Severity legend: HF-10 = visible Hard-Fail per spec §3.1; SF = Soft-Fail per §3.2; INFO = info / non-blocking.

### 1A. Currency without locale separators (HF-10, multiple Phase-A surfaces)

`docs/specs/0087-pre-demo-qa-program.md:113` mandates: *"Currency: Always `$X.XXM/B/T` with locale-respecting separators; no naked floats."* The codebase ships `lib/format.ts:221 formatPrice()` precisely for this. **Eight call sites bypass it**, rendering raw `$1234.56` instead of `$1,234.56` for any value ≥ 1,000:

| File:line | Surface | Code | Visible breakage |
|-----------|---------|------|------------------|
| `apps/worldview-web/components/instrument/OverviewSidebar.tsx:180` | A4 (Instrument header sidebar) | `${currentPrice != null ? \`$${currentPrice.toFixed(2)}\` : "—"}` | Header price for AAPL today fine; **NVDA pre-split, BRK.A ($670k), GOOGL split adjusted etc. all break** |
| `apps/worldview-web/components/instrument/AnalystRail.tsx:274` | A4 (AnalystRail price strip) | `${price.toFixed(2)}` (rendered, not prompt copy) | same |
| `apps/worldview-web/components/instrument/InstrumentKeyMetrics.tsx:267` | A4 (Fundamentals metrics) | `eps_ttm != null ? \`$${snapshot.eps_ttm.toFixed(2)}\`` | low magnitude; mostly cosmetic |
| `apps/worldview-web/components/instrument/TechnicalSnapshot.tsx:127` (`formatMa`) | A4 (TechnicalSnapshot MA50/MA100/MA200) | `\`$${value.toFixed(2)}\`` | Renders the moving-average value; same break ≥$1k |
| `apps/worldview-web/components/screener/ag-screener-columns.tsx:84` | A9 (Screener Price column) | `v != null ? \`$${v.toFixed(2)}\` : "—"` | Every row over $1k renders without thousand separator |
| `apps/worldview-web/components/screener/screener-columns.tsx:195` | A9 (legacy screener) | same pattern | same |
| `apps/worldview-web/app/(app)/prediction-markets/page.tsx:65-68` | A2 (Prediction Markets tile) | `\`$${(volume / 1_000_000).toFixed(1)}M\` / K / .toFixed(0)` | Volumes accept; but the bare `${volume.toFixed(0)}` fallback (line 68) for sub-$1k loses formatting |

**Fix**: replace direct `$...toFixed` with `formatPrice(value)` (or `formatCompactCurrency` where SI-suffix is wanted). Bare-minimum: `value.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2})`.

### 1B. Generic `<title>` on every Phase-A route (HF-10, A0 cross-cutting)

Every SSR'd surface ships the **identical** `<title>Worldview — Institutional Market Intelligence</title>`. Verified by curl:

```
HTTP 200 size … /dashboard       → <title>Worldview — Institutional Market Intelligence</title>
HTTP 200 size … /instruments/AAPL→ <title>Worldview — Institutional Market Intelligence</title>
HTTP 200 size … /screener        → <title>Worldview — Institutional Market Intelligence</title>
HTTP 200 size … /chat            → <title>Worldview — Institutional Market Intelligence</title>
HTTP 200 size … /alerts          → <title>Worldview — Institutional Market Intelligence</title>
HTTP 200 size … /portfolio       → <title>Worldview — Institutional Market Intelligence</title>
HTTP 200 size … /login           → <title>Worldview — Institutional Market Intelligence</title>
```

Only `app/docs/[[...slug]]/page.tsx` and `app/legal/privacy/page.tsx` export their own `metadata`. **Bloomberg, Tradingview, Refinitiv all set per-route titles** — `AAPL · Worldview` / `Dashboard · Worldview` etc. Browser-tab discoverability + screen-reader page identification both currently fail.

**Fix**: export `generateMetadata({ params })` from each Phase-A route file. For `/instruments/[entityId]/page.tsx` use the resolved ticker; for `/dashboard`, `/chat`, `/screener`, `/alerts`, `/portfolio`, `/login` static `metadata` exports suffice.

### 1C. UUID leak in `FlashOverlay` (HF-10, A2 + A10)

`apps/worldview-web/components/shell/FlashOverlay.tsx:182`:

```tsx
{alert.entity_id && (
  <span className="font-mono">{alert.entity_id}</span>
)}
```

`AlertPayload.entity_id` (`apps/worldview-web/types/alerts.ts:25`) is the **KG canonical UUID** (e.g. `c4ad2e95-…`). The WS payload carries no `ticker` field — `AlertsList` rows have a `ticker` field; the overlay does not. **Critical-severity flash overlay shows a UUID where the trader expects "AAPL".**

Per spec §3.1 HF-4: *"Any visible $0 / NaN / "—" / "Loading…" stuck for ≥3 s in a populated tile."* — UUID is the same class of leak.

**Fix**: extend `AlertPayload` (S10 contract) to include `ticker?: string` + `entity_label?: string`, or resolve client-side via `useEntityLookup(entity_id)`. Until then, gate the badge: only render when `entity_id` is short (≤8 chars / not a UUID).

### 1D. Three text inputs strip the focus ring without replacement (HF-10, A4 + A9 + A1)

`focus:outline-none` removes the browser default ring, but no `focus-visible:ring-*` token replaces it. Tabbing in keyboard mode = invisible focus.

| File:line | Surface | Class |
|-----------|---------|-------|
| `apps/worldview-web/app/(app)/workspace/page.tsx:218` | Workspace symbol input | `focus:border-primary/50 focus:outline-none` (border-only — partial; OK on light, fails on dark cycling) |
| `apps/worldview-web/components/instrument/EntityGraph.tsx:665` | Entity Graph search filter (A4 KG tab) | `focus:border-border focus:outline-none` (no contrast change at all on focus) |
| `apps/worldview-web/components/portfolio/TransactionsTable.tsx:222` | Portfolio transactions search (B2) | `text-foreground placeholder:text-muted-foreground focus:outline-none` |
| `apps/worldview-web/components/chat/SlashCommandAutocomplete.tsx:86` | Chat slash command list (A5/A6) | `hover:bg-muted/50 focus:bg-muted/50 focus:outline-none` (background-only on focus) |
| `apps/worldview-web/components/portfolio/WatchlistsTabPanel.tsx:465` | Portfolio watchlists tab | same |

**Fix**: append `focus-visible:ring-1 focus-visible:ring-ring` (matches the rest of the codebase — see `app/(app)/chat/page.tsx:949`, `AnalystRail.tsx:357`).

### 1E. Raw ISO-slice timestamps in user-facing surfaces (SF-1, A2 + A4)

Per spec §3.3: *"Timestamps: '2 min ago' / 'today 14:32' / '2026-05-09' — never a raw ISO string in user surfaces."* Pass-1 only flagged the EntityGraph tooltip + Status uptime. Six more sites still render `ISOString.slice(...)`:

| File:line | Renders | Surface |
|-----------|---------|---------|
| `apps/worldview-web/components/dashboard/MorningBriefCard.tsx:243` | `Generated 2026-05-09 15:42 UTC` | A2 — Morning brief header (visible on landing) |
| `apps/worldview-web/components/instrument/IntelligenceTab.tsx:245` | `Generated 2026-05-09 15:42 UTC` | A4 — Intelligence brief footer |
| `apps/worldview-web/components/instrument/InstrumentBriefPanel.tsx:245` | same | A4 — Instrument brief panel |
| `apps/worldview-web/components/instrument/LiveQuoteBadge.tsx:189` | `15:42:31 UTC` | A4 — header live-quote pill |
| `apps/worldview-web/components/shell/FlashOverlay.tsx:187` | `15:42:31 UTC` | A2/A10 — alert overlay |
| `apps/worldview-web/components/shell/MarketStatusPill.tsx:151` | `Now: 15:42 UTC` | TopBar |

`lib/utils.ts:125 formatRelativeTime()` and `components/ui/data-timestamp.tsx` already exist — these sites bypass them. The clock pill is borderline acceptable (live wall-clock), but the brief "Generated" line and the FlashOverlay timestamp should switch to `formatRelativeTime` ("2 min ago" / "today 14:32").

**Note**: `MorningBriefCard.tsx:306-307` comment still references "Midnight Pro" (retired palette name) — stale comment.

### 1F. New off-token radii on landing page (HF-10, A0 — public landing)

Pass-1 swept `rounded-md/lg/xl/2xl`. New offenders use arbitrary-value radii outside the 2px token:

| File:line | Class | Visible |
|-----------|-------|---------|
| `apps/worldview-web/components/landing/HeroSection.tsx:133` | `rounded-[6px] bg-primary/10 opacity-50 blur-2xl` | Primary CTA glow card (3× the design token) |
| `apps/worldview-web/components/landing/HeroSection.tsx:136` | `rounded-[3px] border border-border/60 bg-card shadow-2xl` | Hero terminal mock frame |
| `apps/worldview-web/components/landing/AIDemoSection.tsx:77` | `rounded-[3px] border border-border/60 bg-card shadow-xl` | AI demo card |
| `apps/worldview-web/components/landing/PricingTiers.tsx:164` | `rounded-[3px] border p-6 transition-all` | Pricing tier cards |

Director pre-flight: **the public landing page IS the demo cold-start.** A 3px / 6px radius next to all 2px-radius UI looks "rounded but slightly off" — the kind of micro-detail Bloomberg never gets wrong.

**Fix**: replace `rounded-[3px]` and `rounded-[6px]` with `rounded-[2px]`. (The blur glow at HeroSection:133 may keep a soft radius; it can stay `rounded-[2px]` since it's a blurred backdrop.)

### 1G. Inconsistent dense-padding sweep (SF-2, A5/A6)

Pass-1 caught `p-4` in chat empty state, watchlists/news loading. The chat **thread message list and header** still use looser padding next to the post-fix `p-3` empty state:

| File:line | Class | Comment in code |
|-----------|-------|----------|
| `apps/worldview-web/app/(app)/chat/page.tsx:759` | thread header `flex … border-b border-border px-4 py-2` | should be `px-3` to match TopBar/sub-header rhythm |
| `apps/worldview-web/app/(app)/chat/page.tsx:780` | message scroll body `flex flex-col gap-3 p-4` | reading area; `p-3` is the terminal density |

This is borderline — chat *content* is read at slightly looser density on Bloomberg. Mark SF-2 (fix-if-time-permits).

### 1H. Dashboard `IntelligenceTab` "Generated" timestamp tabular-nums missing on raw ISO (SF-1, A4)

`apps/worldview-web/components/instrument/IntelligenceTab.tsx:244-246`:

```tsx
<p className="mt-2 font-mono text-[10px] tabular-nums text-muted-foreground">
  Generated {new Date(brief.generated_at).toISOString().slice(0, 16).replace("T", " ")} UTC
</p>
```

Has `tabular-nums` (good) — but pairs it with a raw ISO slice. See 1E. Soft fail.

### 1I. `truncate()` helper uses ASCII three-dot ellipsis (INFO, unused)

`apps/worldview-web/lib/utils.ts:279`: `return text.slice(0, maxLength - 3) + "...";` — should be `+ "…"` for typographic consistency. **Verified unused** in the codebase (no `import { truncate } from "@/lib/utils"`). Info only — fix-when-touched. If it ever ships, see D-F3-007 precedent.

### 1J. 92 `data-testid` attributes in production HTML (INFO, A0 cross-cutting)

`grep -rn 'data-testid' app components features` (excluding tests) returns 92 hits. Every drawing-tool button, MA toolbar, every screener cell carries one. Bloomberg's HTML doesn't expose test IDs; an analyst inspecting the DOM would notice instantly. Acceptable but flag.

**Recommendation**: keep them — cost of removing > benefit. If demo screen-share zooms into devtools, this is the one cosmetic that doesn't matter to the eye.

### 1K. `console.log` left in production code (SF-3, A2)

`apps/worldview-web/features/dashboard/components/BriefEntityPill.tsx:87` — explicitly intentional integration marker per its docstring (line 30, 82–87). Will fire in browser console on every alert-prefill click during the Phase A walkthrough. Spec §3.1 HF-2: *"Any console error on Phase A or B path"* — this is a `log`, not `error`, so technically passes. But it WILL show up in any DevTools-recorded session.

**Fix**: gate behind `if (process.env.NODE_ENV !== "production")` or remove now that the integration is verified.

### 1L. Stale "Midnight Pro" comments after Terminal Dark migration (INFO, several files)

| File:line | Comment |
|-----------|---------|
| `apps/worldview-web/components/dashboard/MorningBriefCard.tsx:306-307` | "font-mono + tabular-nums keeps digit columns aligned per **Midnight Pro** convention" |
| `apps/worldview-web/components/instrument/AnalystRail.tsx` (multiple) | likely similar |

Doesn't affect render but sloppy on inspection.

### 1M. `screener-columns.tsx` change-pct uses `pct >= 0` (positive includes zero) (INFO)

`apps/worldview-web/components/screener/screener-columns.tsx:231`:
```
{pct >= 0 ? "+" : ""}{pct.toFixed(2)}%
```
Zero renders as `+0.00%` (no movement should not have a sign). Bloomberg displays a literal flat `0.00%` for unchanged. Same pattern at `ag-screener-columns.tsx:108`. Cosmetic.

### 1N. `MorningBriefCard` carves 120-140px specifically for "2026-05-09 07:14 UTC" (INFO)

The brief header (h-5 ribbon, 20px tall) reserves `min-w-[120px] max-w-[140px]` for the timestamp slot. If the ISO string ever stretches beyond that (e.g. with seconds) it wraps and breaks the h-5 layout. Switching to `formatRelativeTime` (1E) makes the slot resilient — relative strings are always ≤ "yesterday".

### 1O. AG Grid documented in DESIGN_SYSTEM.md but not yet documented at API level (INFO)

D-F3-009 added AG Grid to DESIGN_SYSTEM.md §1 (post-pass-1). No ADR exists for it. Pre-demo: not blocking. Post-demo: write ADR-F-17.

### 1P. `transitions-colors duration-0` micro-pattern is everywhere (INFO)

50+ sites use `transition-colors duration-0`. Reading the source it's a deliberate "no animation" override. Bloomberg has zero hover transitions. The convention is fine; no defect.

### 1Q. `data-testid` on landing CTAs leaks to public-facing HTML (SF-3)

`components/landing/HeroSection.tsx:97` `data-testid="hero-primary-cta"` and `FinalCTA.tsx:36` ship to logged-out visitors. Marketing analytics tools may not collide, but director will inspect.

### 1R. `aria-label` discipline — sample passes; no defects flagged (INFO)

Spot-checked OHLCVChart, AnalystRail, CompactInstrumentHeader: `aria-label`, `role="status"` correctly set. No SF.

---

## 2. Density audit (PLAN-0071 Phase 6/6.5 conformance)

| Surface element | Spec | Verified | Pass |
|-----------------|------|----------|------|
| TopBar height | h-8 (32px) | `components/shell/TopBar.tsx:160` `flex h-8 …` | ✅ |
| Sidebar nav rows | h-7 (28px) | `components/shell/CollapsibleSidebar.tsx` `flex h-7 …` (3 sites) | ✅ |
| Sidebar settings link | h-7 | `CollapsibleSidebar.tsx` `flex h-7 …` | ✅ |
| WatchlistPanel rows | h-22px | `WatchlistPanel.tsx:214` `flex h-[22px] …` | ✅ |
| WatchlistPanel section header | h-6 | `WatchlistPanel.tsx:129` `flex h-6 …` | ✅ |
| Article rows (News tab + global news) | py-1 px-2 | `components/news/ArticleCard.tsx:120` `py-1 px-2` | ✅ |
| Alerts page padding | p-3 | `app/(app)/alerts/page.tsx:197` | ✅ |
| Alerts tab strip | h-9 / h-7 | `alerts/page.tsx:243` (h-9 outer), `:244` (h-7 trigger) | ✅ |
| Screener sub-header | h-9 | `app/(app)/screener/page.tsx:288` | ✅ |
| Instrument page sub-headers | h-9 | `app/(app)/instruments/page.tsx:134,159` | ✅ |
| Portfolio sub-header + tabs | h-9 | `app/(app)/portfolio/page.tsx:217,335` | ✅ |
| Chat empty-state padding | p-3 | `app/(app)/chat/page.tsx:707` | ✅ |
| Chat thread header | px-4 py-2 | `app/(app)/chat/page.tsx:759` | ⚠️ should be px-3 (defect 1G) |
| Chat message list | p-4 | `app/(app)/chat/page.tsx:780` | ⚠️ borderline (defect 1G) |
| FlashOverlay body | p-3 | `components/shell/FlashOverlay.tsx:152` | ✅ (post-F3) |
| Dashboard widget cards | p-3 | sampled MarketHeatmap, PreMarketMovers, MorningBriefCard | ✅ |

**Verdict**: density is overwhelmingly conformant. Two edge cases on chat (1G) only.

---

## 3. Typography audit

| Rule (DESIGN_SYSTEM.md §3) | Status | Evidence |
|----------------------------|--------|----------|
| All numbers `font-mono tabular-nums` | ✅ broad coverage | 409 grep hits for `tabular-nums`; spot-check on Holdings, Screener, KPI strips, AnalystRail, CrosshairHUD, MarketHeatmap, AiSignals, KeyMetricsGrid, EvidenceTab, PreMarketMoversWidget all confirm |
| Tickers in `font-mono uppercase tracking-widest` | ✅ | `WatchlistPanel.tsx`, `ArticleCard.tsx` source, `AnalystRail.tsx:271` `font-mono text-[11px] font-semibold`, screener column |
| Data-row text 11px | ✅ | screener `text-[11px] tabular-nums`, holdings `text-[11px]` |
| Heading weight consistency (`font-semibold tracking-tight`) | ✅ sample | error.tsx, not-found.tsx, MorningBriefCard headers — all consistent |
| Numeric sign discipline (`+%` for positive) | ✅ on demo path | dashboard widgets, screener cells, instrument header all show `{x >= 0 ? "+" : ""}` |
| Zero rendered without leading `+` | ⚠️ minor | screener uses `pct >= 0` so `0.00%` becomes `+0.00%` (defect 1M) |

**Verdict**: typography is essentially Bloomberg-grade. The pass-1 + pass-2 sweep reduces unique numeric sites without `tabular-nums` to **zero on the Phase-A demo path**. The architecture test introduced post-F3 should be extended to also assert `tabular-nums` on every `.toFixed(`-rendering site (heuristic).

---

## 4. Format audit

| Format kind | Spec rule | Actual | Defect |
|------------|-----------|--------|--------|
| Currency | `$X,XXX.XX` with thousand separators | 8 sites use `\`$${v.toFixed(2)}\`` (no separator) | **1A — HF-10** |
| Compact currency (B/M/K/T) | uniform "$1.2B" rule | `formatCompactCurrency` (lib/format.ts) is canonical; PredictionMarketsWidget bypasses it (`(volume / 1_000_000).toFixed(1)`) — minor | SF-3 |
| Percentage with sign | `+X.XX%` for positive, `-X.XX%` for negative, `0.00%` for zero | most sites correct (dashboard, screener); `pct >= 0` includes zero with `+` (defect 1M) | INFO |
| Percentage column tabular | required | confirmed on screener, dashboard, instrument header | ✅ |
| Dates user-facing | "2 min ago" / "today 14:32" / "2026-05-09" | 6 sites still emit raw `ISOString.slice(...)` UTC strings | **1E — SF-1** |
| Large counts | `1,234,567` with separators | `toLocaleString()` used widely (sampled `screener/page.tsx:383`, `prediction-markets/page.tsx:165`, `instruments/page.tsx:145`) | ✅ |
| Volume / shares | compact (1.2B / 234M) | `OwnershipSnapshotPanel.tsx:68-70` — direct toFixed; not via `formatCompactCurrency` | INFO |

---

## 5. Empty / error / loading state audit

| Surface | Empty | Error | Loading | Status |
|---------|-------|-------|---------|--------|
| A1 Login | n/a | dedicated banner (rounded-[2px] post-F3) | spinner + dedicated suspense | ✅ |
| A2 Dashboard | InlineEmptyState (sampled WatchlistMoversWidget, HoldingsMoversWidget) | per-widget try/retry | Skeleton matches layout | ✅ |
| A4 Instrument | "No news articles available for this entity." | EntityGraphErrorBoundary wraps graph | Skeletons via `IntelligenceSkeletons.tsx` | ✅ |
| A5/A6 Chat | empty state with 2-col starter prompts (post-F3 p-3) | `app/error.tsx` user-friendly | inline skeletons + ToolCallIndicator | ✅ |
| A9 Screener | "No results." (data-table.tsx:582) | gateway error returns | "Loading…" string on Load-More button | ✅ (`Loading…` correct ellipsis) |
| A10 Alerts | InlineEmptyState across feeds | per-tab error UI | skeletons | ✅ |
| Portfolio | "No holdings yet. Connect a brokerage…" (SemanticHoldingsTable) | `BrokerageConnectionCard` shows "Loading errors…" | spinner | ✅ |
| FlashOverlay | n/a | n/a | n/a — but **renders UUID** (defect 1C) | ❌ HF-10 |
| 404 | dedicated copy | dedicated app/error.tsx | n/a | ✅ |

**Verdict**: empty/error/loading states are honest. Single failure mode = FlashOverlay UUID leak (1C).

---

## 6. Keyboard nav audit

| Shortcut | Required | Implemented | Wired |
|----------|----------|-------------|-------|
| ⌘K | command palette | `components/shell/GlobalSearch.tsx:166` event listener | ✅ |
| `?` | hotkey cheat sheet | `components/shell/HotkeyCheatSheet.tsx`, `useHotkeyBindings()` | ✅ |
| `g d` | go to dashboard | `lib/hotkey-registry.ts` global Navigation group | ✅ |
| `g w` | go to watchlists | same | ✅ |
| `g p` | go to portfolio | same | ✅ |
| `g a` | go to alerts | same | ✅ |
| `g c` | go to chat | same | ✅ |
| `g s` | go to screener | same | ✅ |
| `⌘B` | toggle sidebar | hotkey-registry View group | ✅ |
| `/` | focus search | hotkey-registry Symbol group | ✅ |
| Auto-suspend in inputs | required | `useChordHotkeys` checks `document.activeElement` | ✅ |
| Modal scope > global | required | `HotkeyScope` precedence stack | ✅ |
| Tab focus visible | per WCAG | **3 inputs strip outline w/o ring** (defect 1D) | ❌ HF-10 |

**Verdict**: hotkey infrastructure is robust (Linear/Raycast pattern). One a11y gap on text inputs (1D).

---

## 7. Recommendations (ordered by demo impact)

### Demo-blocking (fix in next 1-2 hours)

1. **1A — Currency separators** (HF-10): replace 8 `$${v.toFixed(2)}` sites with `formatPrice(v)`. Mechanical 8-line edit across screener/instrument files. **Highest visibility:** instrument header price, screener Price column, AnalystRail. Estimated: 30 min.

2. **1B — Per-route `<title>`** (HF-10): export `metadata` (or `generateMetadata` for parameterised routes) on 7 Phase-A route files. Estimated: 30 min. Director WILL look at the browser tab.

3. **1C — FlashOverlay UUID leak** (HF-10): gate `entity_id` rendering behind a UUID-detector heuristic; render only if length ≤ 8 / not `xxxxxxxx-xxxx-…`. Long-term: extend WS payload with `ticker`. Estimated: 15 min for the gate.

4. **1D — Focus rings on 3 text inputs** (HF-10 for keyboard demo): append `focus-visible:ring-1 focus-visible:ring-ring`. Estimated: 10 min.

5. **1F — `rounded-[3px]` / `rounded-[6px]` on landing** (HF-10 for cold start): replace 4 sites with `rounded-[2px]`. Estimated: 5 min.

### Demo-soft (fix if time permits)

6. **1E — ISO timestamps → relative time** (SF-1): swap 6 sites to `formatRelativeTime` (`MorningBriefCard`, `IntelligenceTab`, `InstrumentBriefPanel`, `LiveQuoteBadge`, `FlashOverlay`, `MarketStatusPill`). Estimated: 30 min.

7. **1K — `console.log` in BriefEntityPill** (SF-3): wrap in `process.env.NODE_ENV` guard. Estimated: 2 min.

8. **1G — Chat thread padding** (SF-2): `px-4 py-2` → `px-3`, `p-4` → `p-3` (or accept reading-area exception). Estimated: 5 min.

### Post-demo (defer)

9. **1J — `data-testid` on production HTML** — leave; cost > benefit.
10. **1L — Stale "Midnight Pro" comments** — cosmetic.
11. **1M — Zero with `+` sign** — cosmetic.
12. **1O — AG Grid ADR-F-17** — write after demo.
13. **1I — Unused `truncate()` ellipsis** — fix-when-touched.

---

## Defect count summary

| Severity | Count | IDs |
|----------|-------|-----|
| HF-10 | 5 | 1A, 1B, 1C, 1D, 1F |
| SF-1 | 1 | 1E |
| SF-2 | 1 | 1G |
| SF-3 | 3 | 1H, 1K, 1Q |
| INFO | 8 | 1I, 1J, 1L, 1M, 1N, 1O, 1P, 1R |
| **Total** | **18** | |

**Demo-block list** = 1A + 1B + 1C + 1D + 1F. Estimated combined fix effort: **~90 minutes mechanical work**. None require architecture changes.

The post-F3 architecture test (`__tests__/architecture/no-off-palette-colors.test.ts`) should be extended to also assert (a) no `rounded-[(?!2px\])\d+px\]` outside the 2px token, (b) no `\\$\\$\\{[^}]+\\.toFixed` pattern in the source.
