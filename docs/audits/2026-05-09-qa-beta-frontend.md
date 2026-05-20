# Frontend Bug-hunt + Polish — Beta-Readiness Audit

**Date**: 2026-05-09
**Agent**: Frontend Bug-hunt + Polish specialist (PLAN-0087 / `/qa` beta-readiness)
**Scope**: `apps/worldview-web/` — chart auto-scroll bug investigation + density/polish + real-analyst usage bugs
**Method**: Static source analysis (read OHLCVChart.tsx in full + neighbours), endpoint smoke against running stack, SSR HTML inspection on `localhost:3001`, ripgrep across `app/` `components/` `features/` for bug-pattern signatures.
**Container state**: `worldview-web` on `:3001` returns SSR HTTP 200 in 28ms; S9 gateway on `:8000` healthy; dev-login JWT issued OK.
**Read-only**: zero source edits.

---

## Executive summary

Two serious chart bugs survive (one regression of a pre-existing fix, one structural). One demo-killing data-shape mismatch where `OHLCVChart` silently shows a blank 280px box when the API returns zero bars (which is the case for the seeded AAPL `01900000-0000-7000-8000-000000001001` for several timeframes). Per-route `<title>` is partially fixed but emits truncated UUID instead of resolved ticker. No onboarding/welcome flow exists. Polish remaining is mostly typography density (text-sm → text-xs candidates) and minor padding sweeps already enumerated by pass-1/pass-2 — no new structural surprises.

**Demo-blocking count**: 4 hard-fails (CHART-001, CHART-002, UX-001, UX-002).
**Estimated combined fix effort**: ~3 hours mechanical edits.

---

## 1. Chart bugs (top priority — `OHLCVChart.tsx` + helpers)

The chart implementation lives in
`apps/worldview-web/components/instrument/OHLCVChart.tsx`
(1282 lines, **35 hook call-sites**, 14 `useRef`-held series handles, dynamic `import("lightweight-charts")`).
Sibling components: `CrosshairHUD.tsx`, `ChartToolbar.tsx`, `DrawingPalette.tsx`, `DrawingCanvas.tsx`, `VolumeProfileOverlay.tsx`.

### CHART-001 — Empty-bars renders a silent blank 280px chart (HF-4)

**Severity**: HARD-FAIL (HF-4 per PRD-0087 §3.1: "$0 / NaN / — / Loading… stuck for ≥3 s in a populated tile").

**Live evidence**:
```
$ curl -sS -H "auth: …" "http://localhost:8000/v1/ohlcv/01900000-0000-7000-8000-000000001001?timeframe=1d"
200 with bars[] populated (post-transform)

$ curl -sS -H "auth: …" "http://localhost:8000/v1/ohlcv/01900000-0000-7000-8000-000000001001?timeframe=5m"
{ "items": [], "total": 0 }   → bars[].length === 0 after gateway transform

$ curl -sS -H "auth: …" "http://localhost:8000/v1/ohlcv/01900000-0000-7000-8000-000000001001?timeframe=1w"
{ "items": [], "total": 0 }   → bars[].length === 0
```

**File:line**: `apps/worldview-web/components/instrument/OHLCVChart.tsx:1260-1266`

```tsx
{/* ── Skeleton loading overlay ───────────────────────────────────── */}
{isLoading && !data && (
  <Skeleton
    className="pointer-events-none absolute inset-0 w-full"
    style={{ height: CHART_HEIGHT }}
  />
)}
```

There is no fallback for `data && data.bars.length === 0`. The data-update effect at line 775-898 returns early on `!data?.bars` but **does NOT return early on `data.bars.length === 0`** — it calls `setSeriesData(seriesRef.current, [])` and the chart renders an empty 280×N px black canvas with grid lines and no candles. PRD A4 quality bar demands ≥30 bars; user picks 5M or 1W timeframe → blank chart.

Even worse: the page-bundle endpoint returns `ohlcv.bars: 0` for AAPL (`/v1/instruments/01900000-0000-7000-8000-000000001001/page-bundle | jq '.ohlcv'`) → if `OHLCVChart` is being passed `initialBars=[]` from the bundle path through `OverviewLayout`, the placeholder runs with zero bars on first paint, then the standalone `/v1/ohlcv` query hopefully fills in. Worth verifying.

**Fix**:
```tsx
{!isLoading && data && data.bars.length === 0 && (
  <div
    className="flex items-center justify-center rounded-[2px] border border-border bg-card"
    style={{ height: CHART_HEIGHT }}
  >
    <p className="text-[11px] text-muted-foreground">No price data for this timeframe</p>
  </div>
)}
```

Place between the skeleton overlay and the chart container, OR gate the entire chart-canvas div on `data.bars.length > 0`.

### CHART-002 — Compare-overlay never removes its priceScale / leaks pane on instrument switch (potential)

**Severity**: SOFT-FAIL (SF-2) — only fires when an analyst uses `+CMP`.

**File:line**: `apps/worldview-web/components/instrument/OHLCVChart.tsx:365-409` (the `useEffect` that adds compare series).

The cleanup at lines 746-771 only nulls the ref. It does NOT call `chart.removeSeries(compareSeriesRef.current)` before nulling. On instrument navigation, the entire chart is destroyed (`chart?.remove()` at line 748), which is fine. BUT the data-update effect at line 365 is keyed on `[compareData]`; if the user types two different compare tickers in rapid succession AND the second `searchInstruments` resolves before the first OHLCV query, the first compareData arrives later, calls `removeSeries(compareSeriesRef.current)` — but at that moment the ref might already point at the second series. Result: removes the wrong series. Not visible at demo unless analyst spams `+CMP`. Defer.

### CHART-003 — Auto-scroll-into-past bug — STATUS = FIXED, no regression detected

**History (memory cite)**: PLAN-0053 T-A-1-01 fixed an "infinite past-scroll" bug caused by an unstable `placeholderData` reference creating a render loop. The fix was `useMemo` on the placeholder, plus a `hasScrolledToRealTime` ref guard plus `pendingScrollToRealTime` ref to handle the race when initialBars arrives before chart init.

**Verification**:
- `memoizedPlaceholder` at line 438-448 stabilises the placeholder via `useMemo([initialBars, timeframe, instrumentId])` ✓
- `hasScrolledToRealTime` ref at line 280 prevents repeat scrolls ✓
- Reset on `[instrumentId, timeframe]` change at line 299-302 ✓
- Data-effect at line 880 uses `scrollToRealTime()` (NOT `fitContent()`) — fitContent was the original bug (zoomed out to 1985 first bar) ✓
- `pendingScrollToRealTime` at line 285 handles the race when placeholderData beats initChart resolution ✓

**Assessment**: the original bug is well-defended. **Two latent hazards remain**:

1. The data-effect dependency `[data?.bars]` (line 898) — `data?.bars` is a new array reference whenever React Query refetches (every staleTime=60s), even if the bar data is identical. The effect re-runs every 60s, calls `setSeriesData(...)` which is fine (idempotent), and the `hasScrolledToRealTime` guard correctly prevents re-scroll. **No bug, but expensive**: the effect re-computes ALL 11 indicators (RSI, MACD, BB, ATR, STOCH, OBV, VWAP, VolMA, VolProfile) on every refetch, calling `setSeriesData` 14 times per cycle. CPU cost is small (≤500 bars × O(n)) but on a slow laptop during the demo this is ~10ms hiccup every minute. Optional optimisation: dep on `data?.bars?.length` + `data?.bars?.[data.bars.length-1]?.timestamp` as a fingerprint.

2. The `compareData` effect at line 365 also has unstable dep `[compareData]` — same pattern. Less impact (only fires when compare is active).

### CHART-004 — `compareData!` non-null assertion can NPE if React Query returns undefined mid-flight (low)

**File:line**: `apps/worldview-web/components/instrument/OHLCVChart.tsx:395` `const bars = compareData!.bars;`

Inside the async `addCompareSeries` closure, `compareData` is captured at effect-enter. If TanStack Query invalidates between the closure being scheduled and executing (await import → next tick), `compareData!` is technically unsafe. The wrapping `if (!compareData?.bars?.length || !chartRef.current) return;` at line 366 guards this, but the assertion at 395 is a code smell — replace with `compareData.bars` (already guarded). Defer.

### CHART-005 — Hardcoded indicator hex colors bypass the design tokens (HF-10 polish)

Already enumerated by F1-walkthrough audit (see `docs/audits/2026-05-09-audit-F1-walkthrough.md` §4). Lines 567 (#0EA5E9 sky-500 MA200), 651 (#10B981 emerald ATR), 678 (#38BDF8 sky-400 OBV), 699 (#84CC16 lime VolMA20), 689/710 (#EC4899 pink VWAP), 600/606 (#A78BFA purple-400 MACD), 623/636 (#6366F1 indigo BB). These are universal indicator-color conventions, but PRD-0087 §3.1 HF-10 forbids "off-palette colors". Recommendation: keep them — these are chart-internal indicators that traders expect by convention; document as an explicit DESIGN_SYSTEM exception ("indicator series colors follow TradingView convention"). Do NOT change before demo.

---

## 2. Real-analyst use bugs (UX-*)

### UX-001 — Per-route `<title>` shows raw entity_id instead of resolved ticker (HF-10)

**Severity**: HARD-FAIL (HF-10 — visible "off-brand" defect in browser tab).

**Live evidence**:
```
$ curl -sS http://localhost:3001/instruments/11111111-0001-7000-8000-000000000001 \
    | grep -o '<title>[^<]*</title>'
<title>11111111… | Worldview | Worldview</title>
```

The instrument page emits a `generateMetadata` that puts the URL slug verbatim into the title, then truncates with ellipsis. Result: the browser tab shows `11111111… | Worldview | Worldview` — UUID leak (HF-10 — same severity class as the FlashOverlay UUID leak from pass-2) AND duplicate "Worldview | Worldview" suffix.

The pass-2 audit recommended `generateMetadata({params})` → resolve the ticker server-side and emit `AAPL · Worldview`. Either it was implemented half-way (UUID slug fed straight into `title:` without resolution) or wasn't implemented at all and the static template just got the slug appended.

**File**: search for `generateMetadata` in `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (or sibling `layout.tsx` / `head.tsx`). If absent, add one that calls `getCompanyOverview(entityId)` server-side and returns `{ title: \`${ticker} · Worldview\` }`. Cache this in a unstable_cache wrapper to avoid hammering S9 on every navigation.

### UX-002 — `OHLCVChart` shows blank 280px box when API returns 0 bars

See CHART-001. Same defect from a UX angle: the analyst clicks "5M" timeframe on AAPL and sees a totally blank chart with no message. They'll think the platform is broken.

### UX-003 — page-bundle returns `overview.quote: null` and `ohlcv.bars: 0` for the seeded AAPL

This is a backend defect (already filed as D-F1-007 in F1 walkthrough audit) but it's the user's most-visible breakage on the instrument page. The frontend renders `—` for price/Δ/marketCap/PE in the header (`CompactInstrumentHeader.tsx:263-265`) because `overview?.quote?.price` is null in the bundle even though the standalone `/v1/quotes` endpoint returns the data correctly. Front-end mitigation while backend lands the fix: have the instrument page issue a fallback `getQuote(instrumentId)` query when `bundle.overview.quote === null` and merge into the header — single conditional `useQuery` with `enabled: bundle && !bundle.overview?.quote`. Not strictly a frontend bug, but a 5-minute frontend mitigation for a several-hour backend fix.

### UX-004 — No onboarding / welcome screen exists

**Verification**:
```
$ find apps/worldview-web/app/onboarding apps/worldview-web/app/welcome apps/worldview-web/components/onboarding
(nothing)
```

There is no first-run flow. New users land directly on `/dashboard` after dev-login or Zitadel callback. PRD-0087 §2.3 explicitly excludes onboarding from the demo path — but a hedge-fund director who logs in for the first time and lands on a half-populated dashboard with empty alerts / empty prediction markets / placeholder morning brief will NOT have a guided experience. Defer to post-demo (out of scope per §1.3 "no new features").

### UX-005 — `<html lang="en" class="dark">` set permanently with `suppressHydrationWarning` is the right pattern (PASS)

`apps/worldview-web/app/layout.tsx:137-139` correctly uses `suppressHydrationWarning` on `<html>` to swallow the legitimate dark-class mismatch. No FOUC because the class is applied server-side in the SSR HTML payload (verified: `<html lang="en" class="dark __variable_c8daab __variable_46fe82">` in the served HTML). PASS.

### UX-006 — `MarketStatusPill.tsx:150` uses `suppressHydrationWarning` on a tabular-num timestamp

`<p suppressHydrationWarning>` indicates a client-only timestamp. Acceptable workaround. INFO.

### UX-007 — Loading-state coverage on the dashboard (PASS)

Each widget has its own skeleton via TanStack Query. Verified InlineEmptyState + Skeleton use across `MorningBriefCard.tsx`, `TopMovers.tsx`, `EconomicCalendar.tsx`, `RecentAlerts.tsx`, etc. PASS.

### UX-008 — Unguarded `console.log` in `BriefEntityPill.tsx:87` (SF-3)

Already flagged by pass-2 audit (defect 1K). `console.log("[BriefEntityPill] Alert prefill data for drawer:", prefill)` on every alert-prefill click. Will fire in DevTools-recorded sessions. Wrap in `if (process.env.NODE_ENV !== "production")`.

### UX-009 — `ShareWorkspaceDialog.tsx:112` `console.warn("Clipboard write failed; user can manually copy the URL.")` (SF-3)

Falls in the demo-day class only if the director clicks Share-Workspace, which is unlikely. Defer.

### UX-010 — `OIDC callback warn` at `app/callback/page.tsx:109` (INFO)

`console.warn("OIDC callback error:", safeError)` — only fires on failed OIDC, demo uses dev-login. INFO.

---

## 3. Polish enhancement audit — typography density + spacing

User's exact request: "letter size reduced, space between components reduced". Candidate edits below; **do not apply without confirming with user** — these are taste-driven trims, not bugs.

### 3.1 `text-sm` → `text-xs` candidates on the dashboard

| File:line | Current | Suggestion | Rationale |
|-----------|---------|-----------|-----------|
| `components/dashboard/TopBets.tsx:59` | `text-sm text-muted-foreground` | `text-xs text-muted-foreground` | Sub-label / footnote — text-xs (12px) is the Bloomberg standard; text-sm (14px) drifts toward "marketing landing page" |
| `components/dashboard/TopBets.tsx:69` | `text-sm text-muted-foreground` | `text-xs` | Empty-state copy |
| `components/dashboard/AiSignals.tsx:61` | `text-sm text-muted-foreground` | `text-xs` | Empty-state |
| `components/dashboard/TopMovers.tsx:83` | `text-sm text-muted-foreground` | `text-xs` | Empty-state |
| `components/dashboard/TopMovers.tsx:126` | `text-sm text-muted-foreground` | `text-xs` | "No data available" |
| `components/dashboard/EconomicCalendar.tsx:78` | `text-sm text-muted-foreground` | `text-xs` | Empty-state |
| `components/dashboard/PortfolioSummary.tsx:333` | `text-sm` (delta line) | keep | Already justified in surrounding comment as the visual hierarchy second-tier |

### 3.2 `text-sm` in instrument page (20 occurrences)

`grep text-sm apps/worldview-web/components/instrument/*.tsx | wc -l` = 20. Most are tab labels, panel sub-headers, and chart-internal labels. Spot-check candidates for trimming:
- `IntelligenceTab.tsx` — sub-headers in narrative panel could go to `text-xs` to match the rest of the terminal density
- `FundamentalsTab.tsx` — section labels likely already `text-xs` (verified pass-2 polish)
- `AnalystRail.tsx` — pill text already `text-[11px]`; OK

### 3.3 Spacing — `gap-*` and `p-*` candidates

Pass-2 audit (defect 1G) flagged chat thread header `px-4 py-2` → `px-3` and message body `p-4` → `p-3`. Re-confirmed.

`IntelligenceTab.tsx`:
| File:line | Current | Suggestion |
|-----------|---------|-----------|
| `components/instrument/IntelligenceTab.tsx` (line found via grep "p-3 space-y-4") | `flex-1 overflow-y-auto p-3 space-y-4` | `space-y-3` (12px) instead of `space-y-4` (16px) — tighter vertical rhythm, matches the surrounding 12px gap-3 grid |
| `components/instrument/EntityGraph.tsx` (similar line) | same pattern | same |
| `components/instrument/IntelligenceTab.tsx` "gap-4 h-[22px]" line | `gap-4` between severity filter pills | `gap-2` — 16px gap on 22px-tall pills is loose |

`Dashboard `:
- `app/(app)/dashboard/page.tsx:112` uses `gap-3 ... p-3` — already at the spec (Wave E gap-3 = 12px). Don't tighten further; the gap-3 is the panel-seam aesthetic.
- `MorningBriefCard.tsx:399` — large compound class with `[&_h2]:mt-2`. The 8px h2 top-margin is fine; the `[&_p]:mb-1` (4px paragraph margin) is at the floor.

### 3.4 Inline-value typography

I did NOT find any new tabular-nums gaps beyond pass-2 audit (which closed FundamentalsTab as the last offender). Sample-checked AnalystRail, EntityGraph tooltip, KeyMetricsGrid, EvidenceTab — all `font-mono tabular-nums`.

---

## 4. §D verifications (specific things you asked me to check)

| Item | Status | Evidence |
|------|--------|----------|
| Settings page (theme toggle, brokerage, alert prefs) | EXISTS | `app/(app)/settings/{layout,page,preferences,security,appearance,integrations,profile,beta-program,data,notifications}/page.tsx` — full multi-tab settings |
| User onboarding / welcome flow | **MISSING** (UX-004) — no `/onboarding`, `/welcome`, `components/onboarding/` |
| Brokerage connect flow visual feedback | EXISTS — `components/portfolio/BrokerageConnectionCard.tsx` + portfolio/connect route (referenced in PRD-0087 §2.2 B1) |
| Chat history pagination | LIKELY MISSING — grep for `loadMore\|hasMore\|cursor` in `app/(app)/chat` + `features/chat` returned no infinite-scroll or "Load older" affordance. `GET /v1/threads` returns all threads in one shot with no offset/limit param visible in the chat-page query. With 5+ pre-existing threads in the dev DB, this is fine; with hundreds it would scroll forever. Demo-acceptable |
| Brief diff viewer | EXISTS — `features/dashboard/components/BriefDiffPanel.tsx`, `BriefDiffBadge.tsx`, `__tests__/brief-diff-badge.test.tsx` |
| Feedback widget (👍/👎) | EXISTS — `components/feedback/{FeedbackButton,FeedbackModal,MicroSurvey,NPSPrompt,NPSPromptHost,FeedbackDeepLinkHandler,ScreenshotCapture,ConsoleLogCapture}.tsx`. Full instrumented feedback with screenshot + console-log attach. Wire-up in app shell not verified |
| Alert deep-link from dashboard to detail sheet | EXISTS — `BriefEntityPill.tsx:87` console-logs the prefill, indicating wiring (the same line is the SF-3 unguarded log). Deep-link handler at `components/feedback/FeedbackDeepLinkHandler.tsx`. Not visually verified end-to-end |
| ⌘K, g+d, g+w, g+c, g+a, g+p chord hotkeys | EXISTS — pass-2 audit verified `lib/hotkey-registry.ts` has all 6 + `?` (cheat sheet) + ⌘B (sidebar) + `/` (focus search). No re-test needed |
| Tab focus visible | 3 inputs strip outline (pass-2 defect 1D) — Workspace, Entity-Graph filter, TransactionsTable search, SlashCommandAutocomplete, WatchlistsTabPanel — all need `focus-visible:ring-1 focus-visible:ring-ring` |
| Theme contrast (WCAG AA) | NOT MEASURED — visual contrast on `--foreground #E4E4E7` over `--background #09090B` is 17.5:1 (well above AAA 7:1). `--muted-foreground #71717A` over `--card #111113` is 3.9:1 (AA-large pass at 18px+; AA-normal fails at <18px). Several `text-[10px]` and `text-[11px]` `text-muted-foreground` spans in dense data rows are below the 18px threshold and read at ~3.9:1 — technically AA-normal-fail but standard for trading terminals. Bloomberg's terminal does the same. Not blocking |

---

## 5. Severity classification (F-NNN format)

| F-ID | Code | Severity | Surface | One-liner | Est. fix |
|------|------|----------|---------|-----------|----------|
| F-CHART-001 | HF-4 | HARD | A4 chart | `OHLCVChart` shows blank 280px box when `data.bars.length === 0` (5M, 1W timeframes for AAPL all return 0 bars) | 5 min — add empty-state JSX between skeleton and canvas |
| F-UX-001 | HF-10 | HARD | A4 page tab | Browser title shows truncated UUID `11111111… | Worldview | Worldview` instead of `AAPL · Worldview` | 30 min — add async `generateMetadata` that calls S9 to resolve ticker |
| F-UX-002 | HF-4 | HARD | A4 header | Page-bundle returns `overview.quote: null` → header price/Δ/marketCap render `—` | (backend bug; frontend mitigation: 10 min fallback `useQuery` for quote when bundle.quote is null) |
| F-CHART-005 | HF-10 | HARD-defer | A4 chart | 7 hardcoded indicator hex values bypass tokens — recommend keeping (universal convention) | document only |
| F-CHART-002 | SF-2 | SOFT | A4 chart | Compare-overlay rapid-toggle race could remove wrong series | defer |
| F-CHART-003 | SF-2 | SOFT | A4 chart | Data-effect re-runs every 60s recomputing 11 indicators (~10ms hiccup) | optional optimisation |
| F-UX-008 | SF-3 | SOFT | A2 brief | Unguarded `console.log` in BriefEntityPill on prefill click | 2 min — wrap in NODE_ENV check |
| F-UX-004 | INFO | DEFER | new-user flow | No onboarding/welcome screen | post-demo |
| F-UX-009 | INFO | DEFER | workspace | Unguarded `console.warn` on clipboard fail | trivial |
| F-DENSITY-001 | INFO | OPTIONAL | dashboard | 6 `text-sm text-muted-foreground` empty-state lines that could be `text-xs` | 5 min |
| F-DENSITY-002 | INFO | OPTIONAL | intelligence | `space-y-4` + `gap-4` in IntelligenceTab/EntityGraph could be `space-y-3` / `gap-2` | 5 min |
| F-DENSITY-003 | SF-2 | SOFT | chat | Pass-2 defect 1G — chat thread header `px-4 py-2` → `px-3`, message body `p-4` → `p-3` | 2 min — already known |

---

## 6. Recommended ordering

**Demo-blocking (next 60 min)**:
1. F-CHART-001 — empty-bars empty-state (5 min)
2. F-UX-001 — `generateMetadata` for instrument route (30 min)
3. F-UX-002 — fallback `getQuote` query when bundle.quote null (10 min) — until backend fixes the page-bundle composer

**Demo-soft (if time permits, 30 min)**:
4. F-DENSITY-003 — chat padding (2 min)
5. F-UX-008 — wrap console.log (2 min)
6. F-DENSITY-001 — 6× text-sm → text-xs (5 min, only if user confirms)

**Defer to post-demo**:
- F-CHART-002, F-CHART-003, F-CHART-004, F-CHART-005 (chart edge cases)
- F-UX-004 (onboarding flow)
- F-UX-009, F-UX-010 (low-value console logs)
- F-DENSITY-002 (intelligence padding — taste call)

---

## 7. Files inspected

Primary read in full:
- `apps/worldview-web/components/instrument/OHLCVChart.tsx` (1282 lines)
- `apps/worldview-web/components/instrument/CrosshairHUD.tsx` (145 lines)
- `apps/worldview-web/components/shell/FlashOverlay.tsx` (relevant section, 85-200)
- `apps/worldview-web/lib/api/instruments.ts` (relevant section, 60-180)
- `apps/worldview-web/app/(app)/instruments/[entityId]/page.tsx` (60-170)

Cross-cutting greps:
- console.log/warn/error guarded vs unguarded
- text-sm/p-4/gap-4 in dashboard + instrument
- onboarding/welcome routes
- subscribeCrosshairMove, setData, fitContent, scrollTo* in chart components
- aria-label, focus-visible, keyboard hotkeys

Live container probes (ran successfully):
- `POST /v1/auth/dev-login` — 200, JWT issued
- `GET /` SSR HTML on `:3001` — 200, 22585 bytes, 28ms; verified title bug
- `GET /v1/ohlcv/.../?timeframe={1d,5m,1w}` — confirmed 0-bars condition
- `GET /v1/instruments/.../page-bundle` — confirmed `overview.quote: null`, `ohlcv.bars: 0`

---

**End of audit.**
