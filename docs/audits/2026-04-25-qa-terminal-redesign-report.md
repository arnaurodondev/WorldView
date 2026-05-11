# QA Report: Terminal Redesign Gap Audit

**Date**: 2026-04-25
**Skill**: qa
**Scope**: terminal-redesign (Waves A/B/C vs plan in `docs/audits/qa-frontend-design.md`)
**Branch**: feat/content-ingestion-wave-a1
**Commits audited**: d0f1c8b (Wave A), e4cc2c0 (Wave B), 2923f94 (Wave C)
**Verdict**: NOT_COMPLETE
**Final decision**: NOT_READY

---

## 1. Executive Verdict

**PARTIAL**

The committed waves (A/B/C) executed the radius, padding, and empty-state sweep correctly across core surfaces. Many P0 items from the plan are done. However, the work is incomplete in material ways: TypeScript typecheck FAILS (5 errors), no screenshots or browser validation exist, two workspace panel types still render placeholder text instead of real widgets, the screener filter panel is not collapsible, SessionStatsStrip is not created, and the plan's entire Wave C (portfolio data density) and Wave D (workspace widgets + dashboard audit) were not committed.

Safe to merge: **NO**
Additional implementation required: **YES** (P0 and P1 gaps)
Highest-severity blockers: TypeCheck FAIL, missing browser validation, workspace placeholders

---

## 2. Evidence Summary

| Evidence type | Status |
|---|---|
| Commits inspected | d0f1c8b, e4cc2c0, 2923f94 |
| Files read | workspace/page, screener/page, portfolio/page, alerts/page, OHLCVChart, AlertsList, FundamentalsTab, MorningBriefCard, GlobalSearch, instrument/page, gateway.ts, types/api.ts |
| ESLint | PASS (0 warnings/errors) |
| TypeScript typecheck | **FAIL** (5 errors) |
| Vitest unit tests | PASS (315/315) |
| Browser validation | NOT DONE (no Playwright, no screenshots) |
| Seeded data validation | NOT DONE |
| Screenshots captured | NONE (`docs/screenshots/redesign/` does not exist) |
| Hard-rule scan | Zero remaining `rounded-lg`/`rounded-xl` violations in changed files; some padding variants remain in non-critical locations |

---

## 3. Requirement-by-Requirement Matrix

### Wave A requirements (T-A-1-01 through T-A-1-09)

| Requirement | Required by plan | Implemented | Evidence | Gap | Severity | Merge blocker | Next fix |
|---|---|---|---|---|---|---|---|
| T-A-1-01: InlineEmptyState + InlineErrorState + PanelHeader primitives | Yes | YES | Files exist in `components/data/` | None | — | No | — |
| T-A-1-02: ArticleCard `rounded-[2px]` | Yes | YES | Grep finds no `rounded-lg` in ArticleCard | None | — | No | — |
| T-A-1-03: AlertRow compact divide-y | Yes | YES | AlertsList.tsx uses h-8 py-1.5 compact rows, divide-y | None | — | No | — |
| T-A-1-04: Alerts page full-width, p-3 | Yes | YES | No `max-w-4xl` in alerts/page.tsx | None | — | No | — |
| T-A-1-05: Portfolio p-3, remove stub button | Yes | YES | p-6→p-3 done; disabled Add Position absent | None | — | No | — |
| T-A-1-06: Instrument header py-2, router.back(), news wrappers | Yes | YES | py-2 confirmed; router.back() at line 112; news wrappers removed | Minor: wrapper still `py-2` not `py-1` | MINOR | No | Change `px-3 py-2` to `px-3 py-1` |
| T-A-1-07: OHLCVChart height 360 | Yes | YES | `height: 360` at line 141; skeleton h-[360px] | None | — | No | — |
| T-A-1-08: FundamentalsTab gap-2 p-3 | Yes | YES | No `gap-6` or `p-4` violations found | None | — | No | — |
| T-A-1-09: GlobalSearch recent instruments + keyboard hint | Yes | YES | localStorage history + ↑↓ hint strip confirmed in code | None | — | No | — |

### Wave B requirements (T-B-2-01 through T-B-2-04)

| Requirement | Required by plan | Implemented | Evidence | Gap | Severity | Merge blocker | Next fix |
|---|---|---|---|---|---|---|---|
| T-B-2-01: Verify ScreenerResult type fields | Yes | YES | pe_ratio confirmed in COLUMNS; Sector added | beta, revenue_ttm not added | MAJOR | No | Verify backend availability; add if present |
| T-B-2-02: Remove Price col, add P/E + 2 more | Yes | PARTIAL | Price removed; Sector+P/E added = 7 cols | Plan requires ≥8 cols; Beta, Revenue not added | MAJOR | No | Add Beta + Revenue or document backend blocker |
| T-B-2-03: Screener filter collapse → top bar | Yes | NOT DONE | `aside w-64` left panel still present (line 384) | Filter panel is always visible, not collapsible | MAJOR | No | Replace aside with toggle + inline filter bar |
| T-B-2-04: SessionStatsStrip + instrument header data | Yes | NOT DONE | No `SessionStatsStrip.tsx` in `components/instrument/` | "Price Chart" h2 still in instrument page | MAJOR | No | Create SessionStatsStrip; add volume/open/hi/lo to header |

### Wave C requirements (T-C-3-01 through T-C-3-03) — Wave C commit only touched MarketHeatmap+FlashOverlay

| Requirement | Required by plan | Implemented | Evidence | Gap | Severity | Merge blocker | Next fix |
|---|---|---|---|---|---|---|---|
| T-C-3-01: Semantic `<table>` for holdings + realized P&L | Yes | NOT DONE | CSS grid div confirmed at lines 241/274; intentional deviation with justification | Missing semantic table (axe accessibility concern); missing Realized P&L KPI | MAJOR | No | Add realized P&L KPI; defer semantic table if justified |
| T-C-3-02: Sector allocation panel | Yes | NOT DONE | No SectorAllocationPanel in codebase | Missing feature | MAJOR | No | Implement per-holding fundamentals fan-out |
| T-C-3-03: Intelligence tab severity strip | Yes | NOT VERIFIED | IntelligenceTab.tsx not deeply inspected for this | Unknown | MINOR | No | Inspect IntelligenceTab.tsx |

### Wave D requirements (T-D-4-01 through T-D-4-04) — Not committed

| Requirement | Required by plan | Implemented | Evidence | Gap | Severity | Merge blocker | Next fix |
|---|---|---|---|---|---|---|---|
| T-D-4-01: WorkspaceScreenerWidget | Yes | NOT DONE | `WorkspacePlaceholder type="screener"` at line 492 | Screener panel shows "use the sidebar" instead of real data | CRITICAL | **YES** | Implement WorkspaceScreenerWidget |
| T-D-4-02: WorkspaceChatWidget | Yes | NOT DONE | `WorkspacePlaceholder type="chat"` at line 498 | Chat panel shows "use the sidebar" instead of real widget | CRITICAL | **YES** | Implement WorkspaceChatWidget |
| T-D-4-03: EmptyWorkspace compact | Yes | DONE | py-24 removed; now `py-4 text-xs` at line 735 | None | — | No | — |
| T-D-4-04: Dashboard widgets audit | Yes | PARTIAL | PortfolioSummary text-2xl fixed; MorningBriefCard no violations found; others not confirmed | MorningBriefCard has typecheck errors; RecentAlerts, WatchlistNews not confirmed | MAJOR | No | Fix typecheck; verify RecentAlerts/WatchlistNews |

### Wave E requirements (T-E-5-01 through T-E-5-05) — Not committed at all

| Requirement | Required by plan | Implemented | Evidence | Gap | Severity | Merge blocker | Next fix |
|---|---|---|---|---|---|---|---|
| T-E-5-01: Inspect/fix uninspected components | Yes | PARTIAL | Chat+Settings fixed in Wave A; IntelligenceTab/EntityGraphPanel not confirmed | EntityGraphPanel, TopBar, Sidebar not fully audited | MAJOR | No | Read and verify |
| T-E-5-02: Screenshot validation | Yes | NOT DONE | `docs/screenshots/redesign/` does not exist | Zero screenshots | CRITICAL | **YES** | Run Playwright, capture and commit screenshots |
| T-E-5-03: Accessibility check (axe-core) | Yes | NOT DONE | No axe-core tests exist | Portfolio holdings div-grid not tested | MAJOR | No | Run axe on portfolio/screener/alerts |
| T-E-5-04: Console error validation | Yes | NOT DONE | No Playwright script exists | Hardcoded `demoEntityId="entity-aapl"` may 404 | MAJOR | No | Add Playwright console-error test |
| T-E-5-05: Responsive checks | Yes | NOT DONE | No Playwright responsive tests | No evidence of 1280px/1440px/1920px testing | MINOR | No | Add viewport tests |

---

## 4. Page-by-Page Audit Matrix

| Page | Current status | Terminal-grade | Evidence | Remaining issues | Severity | Required fix |
|---|---|---|---|---|---|---|
| Dashboard | Mostly correct | PARTIAL | gap-px p-1 grid is correct; widgets not fully verified | MorningBriefCard typecheck errors; RecentAlerts unverified | MAJOR | Fix typecheck; verify RecentAlerts |
| Workspace | Compact empty states; partial panel support | NOT YET | WorkspacePlaceholder for screener+chat | 2/8 panel types show placeholder text, not data | CRITICAL | Implement WorkspaceScreenerWidget + WorkspaceChatWidget |
| Instrument overview | Header compact; chart 360px | YES | py-2 confirmed; router.back() confirmed; height:360 confirmed | Missing SessionStatsStrip; "Price Chart" h2 still present | MAJOR | Create SessionStatsStrip |
| Instrument fundamentals | gap-2 p-3 | YES | No violations found | None significant | — | — |
| Instrument news | Compact wrappers | PARTIAL | px-3 py-2 wrapper (was px-4 py-3) | py-2 should be py-1; no compact/card toggle | MINOR | Reduce to py-1; add list/card toggle |
| Instrument intelligence | Not verified | UNKNOWN | File not deeply audited | Severity strip not confirmed | MINOR | Inspect + verify |
| Instrument graph | Error state fixed | YES | EntityGraph.tsx error state compact confirmed (Wave B) | Unknown for full graph interaction | MINOR | Browser verify |
| Screener | Partial redesign | PARTIAL | 7 columns; no rounded-lg; p-3 filter | Left panel still visible (not collapsible); only 7 cols | MAJOR | Collapsible filter bar; add Beta/Revenue |
| Portfolio | Compact; no stub button | PARTIAL | p-3 confirmed; disabled btn removed; CSS grid retained | No sector allocation; no realized P&L; CSS grid not table | MAJOR | Sector panel + realized P&L |
| Alerts | Full-width; compact rows | YES | max-w-4xl removed; divide-y rows; no p-8 | None significant | — | — |
| Chat | Compact | YES | rounded fixes applied in Wave A | Unverified in browser | MINOR | Browser verify |
| Settings | Compact | YES | p-3 applied in Wave A | Unverified in browser | MINOR | Browser verify |
| Shell/TopBar | Not fully verified | UNKNOWN | IndexTicker gap-2 confirmed | TopBar height not measured | MINOR | Browser verify height ≤44px |

---

## 5. Hard-Rule Scan

### Remaining violations across all frontend files

| Pattern | File | Context | Valid exception | Severity | Fix |
|---|---|---|---|---|---|
| `py-2` article wrappers | `instruments/[entityId]/page.tsx:304` | `px-3 py-2` per article in news tab | No (plan requires `py-1`) | MINOR | Change to `py-1` |
| CSS grid holdings | `portfolio/page.tsx:241,274` | `grid-cols-[...]` div pattern | YES — comment documents responsive rationale | MINOR | Document explicitly or convert to table |
| Workspace placeholder text | `workspace/page.tsx:530` | `"use the sidebar for the full-page experience"` | Partial — compact text is correct style, but content should be real widget | CRITICAL | Replace with WorkspaceScreenerWidget/WorkspaceChatWidget |
| `demoEntityId = "entity-aapl"` | `workspace/page.tsx:446` | Hardcoded AAPL for chart/fundamentals panels | No — may 404 in real environments | MAJOR | Use top-mover entity or user preference |

### Zero violations confirmed

| Pattern | Result |
|---|---|
| `rounded-lg` in changed component files | NONE FOUND |
| `rounded-xl` anywhere | NONE FOUND |
| `max-w-4xl` in alerts page | NONE FOUND |
| `p-6` outer padding (portfolio, alerts, chat, settings) | NONE FOUND |
| `py-12` empty states | NONE FOUND |
| `py-24` empty states | NONE FOUND |
| Disabled production buttons | NONE FOUND |
| `coming soon` text | NONE FOUND |

---

## 6. Interaction Audit

| Interaction | Status | Evidence | Issue |
|---|---|---|---|
| Search → type → suggestions | DONE | GlobalSearch uses useQuery for search | Not browser-tested |
| Search → recent instruments when empty | DONE | localStorage RECENT_KEY confirmed | Not browser-tested |
| Search → keyboard hint | DONE | ↑↓ hint strip in code | Not browser-tested |
| Search → Enter/click navigates | DONE | `navigateTo()` calls `router.push()` | Not browser-tested |
| Instrument back nav | DONE | `router.back()` at line 112 | Not browser-tested |
| Chart timeframe buttons | UNVERIFIED | Code exists | Not browser-tested |
| Screener row click navigates | DONE | `onRowClick` pushes to router | Not browser-tested |
| Screener filter apply | DONE | `setAppliedFilters` | Not browser-tested |
| Screener filter collapse | **NOT DONE** | `aside w-64` left panel still present | — |
| Portfolio row click | DONE | `onRowClick` handler | Not browser-tested |
| Alert row click | DONE | `href` in AlertRow | Not browser-tested |
| Graph node click | UNVERIFIED | EntityGraphPanel not deeply audited | Not browser-tested |
| Workspace panel add/remove | DONE | Panel catalogue + selector bar | Not browser-tested |
| Workspace screener panel | **NOT DONE** | Shows "use the sidebar" | — |
| Workspace chat panel | **NOT DONE** | Shows "use the sidebar" | — |

---

## 7. Browser/Screenshot QA

**Status: COMPLETELY MISSING**

No browser validation was performed. No screenshots were captured. The `docs/screenshots/redesign/` directory does not exist. This violates:
- Wave A acceptance criteria (screenshots required for `/alerts` before/after, `/portfolio` before/after, etc.)
- Wave E T-E-5-02 (Playwright screenshot tests for all major routes)
- The QA audit spec requirement ("no screenshots = not READY_TO_MERGE")

**Substitute evidence assessment**: The 315 unit tests passing is not a substitute for browser validation. The unit tests mock all network calls and don't validate visual density, actual layout, or seeded-data scenarios.

**Key risks unvalidated**:
- `demoEntityId = "entity-aapl"` in workspace — may 404 if seed data uses a different entity ID
- Console errors on chart panel (OHLCVChart dynamic import mocking issues seen in Vitest stderr)
- GlobalSearch dropdown positioning and keyboard behavior
- Responsive layout at 1280px, 1440px, 1920px

---

## 8. Test Results

| Layer | Scope | Tests | Passed | Failed | Skipped | Status |
|---|---|---|---|---|---|---|
| ESLint | worldview-web | — | 0 errors | 0 | — | **PASS** |
| TypeScript (tsc --noEmit) | worldview-web | — | — | **5 errors** | — | **FAIL** |
| Vitest (unit) | worldview-web | 315 | 315 | 0 | 0 | **PASS** |
| Playwright (E2E) | worldview-web | N/A | N/A | N/A | N/A | **NOT RUN** |
| Backend unit tests | All services | Not run | — | — | — | **NOT RUN** |

### TypeScript error detail

```
components/dashboard/MorningBriefCard.tsx(118,58): error TS7006: Parameter 'text' implicitly has an 'any' type.
components/dashboard/MorningBriefCard.tsx(118,64): error TS7006: Parameter 'mention' implicitly has an 'any' type.
components/dashboard/MorningBriefCard.tsx(129,38): error TS7006: Parameter 'part' implicitly has an 'any' type.
components/dashboard/MorningBriefCard.tsx(129,44): error TS7006: Parameter 'i' implicitly has an 'any' type.
lib/gateway.ts(60,3): error TS2305: Module '"@/types/api"' has no exported member 'MorningBrief'.
```

**Root cause**: MorningBriefCard.tsx has reduce/replace callback parameters without explicit types. The `gateway.ts` error indicates either a working-tree/committed state mismatch (the committed gateway.ts may still import the removed `MorningBrief` type) or a type export missing from `types/api.ts`. The Wave A commit message claimed `pnpm typecheck ✓` — this claim is false for the current branch state.

---

## 9. Missing Implementation Backlog

### P0 — Blockers (prevent merge)

| ID | Issue | File | Required change | Acceptance criteria |
|---|---|---|---|---|
| P0-001 | TypeScript typecheck FAILS (5 errors) | `MorningBriefCard.tsx`, `lib/gateway.ts` | Add explicit types to reduce callbacks; fix MorningBrief import | `pnpm run typecheck` exits 0 |
| P0-002 | No screenshots or browser validation | `docs/screenshots/redesign/` | Run Playwright or manual browser test; capture screenshots for all major routes; commit to `docs/screenshots/redesign/` | Directory exists with ≥7 screenshots; no console errors |
| P0-003 | Workspace screener panel = placeholder | `workspace/page.tsx:492` | Implement `WorkspaceScreenerWidget` — calls `runScreener()` empty filters, renders top 10 in CompactTable | No "sidebar" placeholder text; table renders data |
| P0-004 | Workspace chat panel = placeholder | `workspace/page.tsx:498` | Implement `WorkspaceChatWidget` — minimal SSE chat input + 5-message history | No "sidebar" placeholder text; input renders |

### P1 — Required before merge

| ID | Issue | File | Required change | Acceptance criteria |
|---|---|---|---|---|
| P1-001 | Screener filter panel not collapsible | `screener/page.tsx:384` | Replace `aside w-64` with `showFilters` toggle + inline filter bar | No always-visible left panel; filter toggle works |
| P1-002 | SessionStatsStrip not created | `components/instrument/` | Create `SessionStatsStrip.tsx` with O/H/L/V/VWAP fields | Component renders; "Price Chart" h2 removed from instrument page |
| P1-003 | Screener only 7 columns | `screener/page.tsx:215-227` | Add Beta + Revenue TTM (verify S9 backend; document backend blocker if missing) | ≥8 columns or explicit blocker documented |
| P1-004 | Portfolio missing realized P&L | `portfolio/page.tsx` | Compute from transactions (client-side; no backend needed) | Realized P&L KPI tile visible |
| P1-005 | Portfolio missing sector allocation | `portfolio/page.tsx` | SectorAllocationPanel with per-holding fundamentals fan-out | Sector bars visible for portfolios with ≥2 holdings |

### P2 — Polish (recommended before merge)

| ID | Issue | File | Required change |
|---|---|---|---|
| P2-001 | Instrument news article wrapper `py-2` not `py-1` | `instruments/[entityId]/page.tsx:304` | Change `px-3 py-2` → `px-3 py-1` |
| P2-002 | Hardcoded `demoEntityId = "entity-aapl"` in workspace | `workspace/page.tsx:446` | Use top-mover entity or user config |
| P2-003 | IntelligenceTab severity strip not confirmed | `IntelligenceTab.tsx` | Inspect + add `HIGH n │ MEDIUM n │ LOW n` strip |
| P2-004 | RecentAlerts/WatchlistNews not verified | `dashboard/*.tsx` | Read files; confirm no card-style alert rows or large padding |
| P2-005 | TopBar height not validated | `shell/TopBar.tsx` | Verify ≤44px in browser |

### P3 — Later

| ID | Issue | File | Required change |
|---|---|---|---|
| P3-001 | Holdings CSS grid (not semantic `<table>`) | `portfolio/page.tsx` | Convert to shadcn Table if accessibility is required |
| P3-002 | No instrument tab keyboard shortcuts (1/2/3/4) | `instruments/[entityId]/page.tsx` | Add `useHotkeys` |
| P3-003 | No news compact/card toggle | `instruments/[entityId]/page.tsx` | Add list/card toggle with localStorage preference |
| P3-004 | Responsive checks not run | — | Playwright at 1280/1440/1920px |
| P3-005 | Axe accessibility tests not written | — | Run axe on portfolio holdings, screener, alerts |

---

## 10. Issue Deep Investigations

### Issue F-001: TypeScript Typecheck FAILS

**Severity**: CRITICAL
**Confidence**: HIGH
**File**: `apps/worldview-web/components/dashboard/MorningBriefCard.tsx:118,129`; `apps/worldview-web/lib/gateway.ts:60`

**Root Cause**:
- **What**: `tsc --noEmit` fails with 5 errors. In `MorningBriefCard.tsx`, the `.reduce()` and `.replace()` callback parameters (`text`, `mention`, `part`, `i`) have implicit `any` types. In `gateway.ts`, the import list references `MorningBrief` which no longer exists in `@/types/api`.
- **Why**: Wave A introduced the `contentWithLinks` reduce logic in MorningBriefCard.tsx (or modified existing code) without explicit parameter types. The gateway.ts `MorningBrief` import is a committed type name that was superseded by `BriefingResponse` — the committed code still has the old name.
- **When**: Every `pnpm run typecheck` invocation on the current branch.
- **History**: Wave A commit claimed `pnpm typecheck ✓` — this was either a false claim or typecheck passed on a slightly different state.

**Impact**:
- Immediate: Production TypeScript validation gate is broken
- CI/CD: Any CI pipeline that runs `tsc --noEmit` will fail
- Developer trust: Commit claims are inconsistent with actual state

**Solution**:

Option A — Fix inline:
1. `MorningBriefCard.tsx` lines 118,129: add explicit types to reduce/replace callbacks
   ```typescript
   const contentWithLinks = brief.entity_mentions.reduce((text: string, mention: EntityMention) => { ... })
   ```
2. `gateway.ts` line 60: ensure import is `BriefingResponse` not `MorningBrief` (working tree already has this fix — just needs committing)

Effort: Low | Risk: Low

**Recommended**: Option A — straightforward fix, then verify `pnpm run typecheck` exits 0.

---

### Issue F-002: Workspace Panels Still Show Placeholder Text

**Severity**: CRITICAL
**Confidence**: HIGH
**File**: `apps/worldview-web/app/(app)/workspace/page.tsx:492,498,523-535`

**Root Cause**:
- **What**: The `WorkspacePlaceholder` component renders for both `"screener"` and `"chat"` panel types. It now shows compact text ("use the sidebar for the full-page experience") rather than the previously-large centered block — which fixes the visual style violation — but still renders no actual content.
- **Why**: Wave B commit correctly removed the `py-12` centered icon block and replaced with compact inline text, but did not implement `WorkspaceScreenerWidget` or `WorkspaceChatWidget`. The plan required T-D-4-01 and T-D-4-02.
- **When**: Always — when a user opens a Screener or Chat panel in the workspace.

**Impact**:
- Visual: A panel that a user explicitly added shows "use the sidebar" — functionally useless
- Platform readiness: Per audit spec, "coming soon" workspace panels are explicitly listed as unacceptable
- The /qa rule states: "Do not return READY_TO_MERGE if workspace still has placeholders"

**Solution**:

Option A — Minimal screener widget (recommended):
- `WorkspaceScreenerWidget`: calls `runScreener()` with empty filters, limit 10; renders a CompactTable (Ticker, Name, Mkt Cap, Score, Change%). Row click navigates. No filter panel.
- `WorkspaceChatWidget`: renders a minimal chat input (h-8 textarea + send button) and last 5 messages in `text-xs`. SSE streaming reusing existing `gateway.chat` method.
- Replaces `WorkspacePlaceholder` in both switch cases.

Effort: Medium | Risk: Low

---

### Issue F-003: No Browser/Screenshot Validation

**Severity**: CRITICAL
**Confidence**: HIGH
**File**: N/A (process gap)

**Root Cause**:
The audit plan explicitly requires screenshots in `docs/screenshots/redesign/` (before/after for 8 routes) and Playwright validation of console errors. Wave E was never committed. The directory does not exist.

**Impact**:
- No evidence the UI actually renders correctly with seeded data
- No evidence the demoEntityId `"entity-aapl"` produces real content vs 404
- No evidence chart height is actually 360px in a real browser (only Skeleton height verified in tests)
- No evidence of zero console errors on instrument/workspace pages

**Solution**:
1. Run `make dev` + `make seed`
2. Open each route in browser; verify zero console errors
3. Capture screenshots with Playwright `page.screenshot()` or equivalent
4. Commit to `docs/screenshots/redesign/`

---

## 11. Supplementary Checks

| Check | Status | Notes |
|---|---|---|
| ESLint | PASS | 0 errors; security warning about ws:// (pre-existing, non-critical) |
| TypeScript | FAIL | 5 errors — see F-001 |
| Vitest unit | PASS | 315/315 tests |
| Service structure | NOT RUN | Scope is frontend-only |
| Avro schema validation | N/A | Frontend-only changes |
| Doc freshness | PARTIAL | docs/audits/qa-frontend-design.md is the source; plan tracking not updated yet |
| Security scan | N/A | Frontend style changes; no new endpoints or secrets |

---

## 12. TRACKING.md Update Required

After resolving blockers, update `docs/plans/TRACKING.md` to record this QA pass date against the terminal-redesign work (currently tracked under the worldview-web redesign entries).

---

## 13. Final Decision

**NOT_READY**

### Decision checklist

| Rule | Status |
|---|---|
| All major routes audited | **NO** — workspace screener/chat, IntelligenceTab, EntityGraphPanel, TopBar not browser-tested |
| Browser/screenshot validation performed | **NO** — directory missing |
| Workspace has no placeholders | **NO** — screener + chat panels still render placeholder text |
| Search navigation functional | Likely yes (code correct) but not browser-validated |
| Screener meets density requirement | **NO** — 7 columns (requires ≥8); filter not collapsible |
| Portfolio has table-first holdings | **PARTIAL** — CSS grid with documented justification; no sector/realized P&L |
| No console errors on core routes | **UNKNOWN** — not validated |
| No critical/major defects | **NO** — TypeCheck FAIL is critical; workspace placeholders are critical |

---

## 14. Next Steps (Priority Order)

1. **Fix TypeScript errors** (`pnpm run typecheck` must exit 0) — 30 min
2. **Fix workspace placeholders** — implement WorkspaceScreenerWidget + WorkspaceChatWidget — 2-4 hrs
3. **Run browser validation** — `make dev` + `make seed` + manual route walkthrough + screenshots — 1-2 hrs
4. **Fix screener filter collapse** — convert aside to toggle + inline bar — 1-2 hrs
5. **Create SessionStatsStrip** — new component + instrument page integration — 1 hr
6. **Add portfolio realized P&L** — client-side computation from existing transactions query — 1 hr
7. **Add portfolio sector allocation** — fan-out from holdings fundamentals — 2-3 hrs
8. **Document screener Beta/Revenue blocker** — check S9 response; either add fields or create tracking issue — 30 min

---

## 15. Compounding Updates

### New bug pattern identified

**BP-XXX**: Frontend commit claims typecheck pass (`pnpm typecheck ✓` in commit message) but working branch fails typecheck. Root cause: implicit-any parameters in `.reduce()` callbacks with complex generic types, and stale import names after type renames. Prevention: Run `pnpm run typecheck` immediately before writing commit message and include exit code in output.

### Recommendation for REVIEW_CHECKLIST.md

Add to frontend section:
- [ ] `pnpm run typecheck` exits 0 (not just `pnpm run lint`)
- [ ] `docs/screenshots/` directory updated with before/after for any UI-affecting change
- [ ] All workspace panel types have been opened in a real browser with seeded data

---

*Report generated 2026-04-25 by direct source inspection, commit analysis, and validation tool execution.*
*Agent: /qa terminal-redesign audit*
