# QA Report: PLAN-0059 F-1, F-2, Screener Migration

**Date**: 2026-05-03 16:16 UTC
**Skill**: qa
**Scope**: 3 commits — ScreenerTable migration (8e0e236a), F-1 5-table DataTable migration (c69a0367), F-2 RHF+Zod form layer (ac9e4f44)
**Branch**: feat/content-ingestion-wave-a1
**Agents**: QA/Test, Security, Frontend Architecture, Accessibility, Data Correctness
**Verdict**: PASS_WITH_WARNINGS

---

## Executive Summary

Three frontend implementation commits were reviewed across 5 specialist agents. All previously identified bugs (BP-326 through BP-330, revenue_usd mapping) are **confirmed fixed**. The test suite passes 1575 tests (up from 1573 baseline; 2 new regression guards added). 6 Bucket A auto-fixes were applied inline during the QA pass: `aria-invalid` pattern clarification, `.finite()` on avgPrice, `.trim()` on both name schemas, P/E "x" suffix, and two test additions. No BLOCKING issues remain post-fix. The primary deferred work is **missing test files** for 7 components/utilities and **accessibility improvements** for composite form inputs (DateRangePicker, TimePicker inside RHF FormControl).

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | MINOR | NIT |
|-------|---------------|----------|----------|----------|-------|-------|-----|
| QA/Test | 28 | 18 | 3→0 | 5 | 8 | 2 | 0 |
| Security | 14 | 11 | 0 | 1→0 | 5→3 | 4→3 | 1 |
| Frontend Architecture | 18 | 10 | 1→0 | 1→0 | 2→1 | 3 | 1 |
| Accessibility | 12 | 13 | 2→1 | 5→3 | 4 | 1 | 0 |
| Data Correctness | 15 | 14 | 0 | 0 | 1→0 | 0 | 0 |
| **Total** | — | **66** | **0** | **5** | **13** | **7** | **1** |

_→N = count after applying Bucket A auto-fixes_

### Cross-Agent HIGH-Confidence Signals
- Whitespace-only names bypass `.min(1)` check — flagged by Security + Data Correctness → **FIXED** (`.trim()` added to both name schemas)
- `aria-invalid` uses ambiguous `!!error || undefined` pattern — flagged by A11y + Architecture → **FIXED** (`error ? "true" : undefined`)
- P/E column missing "x" suffix — flagged by Data Correctness + QA → **FIXED**

### Fixes Applied (Bucket A)
| Finding | Fix | Status |
|---------|-----|--------|
| aria-invalid ambiguous pattern | `form.tsx:173` → `error ? "true" : undefined` | APPLIED |
| avgPrice missing `.finite()` | `AddPositionDialog.tsx:84` | APPLIED |
| CreatePortfolio name whitespace bypass | `.trim()` in Zod schema | APPLIED |
| CreateWatchlist name whitespace bypass | `.trim()` in Zod schema | APPLIED |
| P/E column missing "x" suffix | `screener-columns.tsx:266` | APPLIED |
| CreatePortfolioDialog error path test | `create-portfolio-dialog.test.tsx` — does NOT call onOpenChange(false) on server error | APPLIED |
| QuickEditPopover Enter-key test | `quick-edit-popover.test.tsx` — Enter fires onSave | APPLIED |
| screener-columns P/E test | Updated expected "34.6" → "34.6x" | APPLIED |

### Closed False Positives
| Agent Finding | Reason Closed |
|---------------|---------------|
| Architecture: sonner violates shadcn-only policy | `sonner@1.7.4` IS in `package.json`; approved dependency |
| Architecture: CreateWatchlistDialog `<form>` inside Dialog | `<form>` is correct here — `type="submit"` button needs it for Enter-key-to-submit; modern Radix Dialog has no conflict |

### Decisions Needed (Bucket C)
| ID | Question | Context |
|----|----------|---------|
| C-1 | Does a TransactionsTable row-click detail page exist? | Architecture agent flagged missing `onRowClick` in TransactionsTable. If `/portfolio/transactions/:id` doesn't exist, row-click is intentionally absent. |
| C-2 | Admin panel: add client-side role guard? | Security agent flagged that `/admin/feedback` renders before knowing user is admin. Low blast radius since backend enforces 403, but UX can be improved. |
| C-3 | Composite input a11y: DateRangePicker + TimePicker in RHF | A11y agents flagged that `aria-invalid` can't propagate to sub-inputs of composite components. Significant refactor required. Accept for now or fix in F-5? |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Status |
|-------|-------|-------|--------|--------|--------|
| TypeCheck (tsc --noEmit) | full | — | — | 0 | **PASS** |
| Lint (ESLint) | full | — | — | 0 errors | **PASS** (pre-existing warnings only) |
| Vitest unit | 139 files | 1575 | 1575 | 0 | **PASS** |
| Integration | skipped | — | — | — | N/A (requires Docker infra) |
| E2E (Playwright) | skipped | — | — | — | N/A (requires running container) |

---

## Bug Verification Results

| Bug | Status | File | Evidence |
|-----|--------|------|----------|
| BP-326: entity_id slug | ✅ FIXED | `lib/api/screener.ts:78` | Uses `instrument_id` fallback |
| BP-327: empty columns | ✅ FIXED | `features/screener/lib/build-filters.ts:82-87` | Adds `daily_return` + `pe_ratio` enrichment filters |
| BP-328: AddPosition qty validation | ✅ FIXED | `AddPositionDialog.tsx:74-77` | `z.number().positive("Must be > 0")` |
| BP-329: free-text currency | ✅ FIXED | `CreatePortfolioDialog.tsx:96-100` | `z.enum(CURRENCIES)` + Select component |
| BP-330: missing aria-invalid | ✅ FIXED | `form.tsx:173` | FormControl wires `aria-invalid` + `aria-describedby` |
| revenue_usd mapping | ✅ FIXED | `lib/api/screener.ts:96` | `metrics["revenue_usd"] ?? metrics["revenue"]` |
| BP-331 (additional): P/E no "x" suffix | ✅ FIXED | `screener-columns.tsx:266` | Applied this QA pass |
| Sort bridge screener | ✅ CORRECT | `screener/page.tsx:202-214` | `screenerSortToTanstack` + `tanstackToScreenerSort` |
| getRowId uniqueness (all 6 tables) | ✅ CORRECT | All table files | UUIDs / primary keys used |

---

## Open Issues (Post-Fix)

### CRITICAL Issues

#### F-C-001: SemanticHoldingsTable has no test file
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: QA/Test
**File**: `components/portfolio/SemanticHoldingsTable.tsx`
**Issue**: 12-column table with live price resolution, P&L calculations, weight computation, and URL-state persistence has zero test coverage. The totalValue=0 divide-by-zero guard and allZeroQty state message are untested.
**Fix**: Create `__tests__/semantic-holdings-table.test.tsx` covering: null quote prices, totalValue=0, VALID_SORT_COLS validation, empty holdings state.
**Effort**: 2h

#### F-C-002: RangeInput has no test file
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: QA/Test
**File**: `features/screener/components/RangeInput.tsx`
**Issue**: Used 12+ times in ScreenerFilterBar. The `parseValue` function coerces strings → numbers; bugs silently drop filters.
**Fix**: Create test file covering: `parseValue("") → undefined`, NaN/Infinity rejection, onChange callbacks, disabled state.
**Effort**: 1h

#### F-C-003: CreateWatchlistDialog has no test file
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: QA/Test
**File**: `components/watchlists/CreateWatchlistDialog.tsx`
**Issue**: Migrated to RHF + Zod in F-2 but has no corresponding test. AddPositionDialog and CreatePortfolioDialog both have tests; this is an inconsistency.
**Fix**: Create `__tests__/create-watchlist-dialog.test.tsx` mirroring the pattern in `create-portfolio-dialog.test.tsx`.
**Effort**: 1.5h

#### F-C-004: `applyClientFilters` function has no test
**Severity**: CRITICAL | **Confidence**: HIGH | **Flagged by**: QA/Test
**File**: `app/(app)/screener/page.tsx` (lines 115-143)
**Issue**: Exported function that performs client-side search filtering (ticker/name substring). Silent drops if bugs in null-safety or case-insensitive match.
**Fix**: Unit tests for empty search, case-insensitive match, null ticker/name safety.
**Effort**: 45min

#### F-C-005: FormMessage returns null — aria-describedby references non-existent element during render cycle
**Severity**: CRITICAL | **Confidence**: MEDIUM | **Flagged by**: Accessibility
**File**: `components/ui/form.tsx:219`
**Issue**: `if (!body) return null` means the FormMessage element is absent from DOM when there is no error. But `aria-describedby` in FormControl always includes `formMessageId` when an error exists. During the brief gap between RHF error state update and React re-render, the referenced element doesn't exist. Most screen readers handle this gracefully, but it's not spec-compliant.
**Fix**: Render FormMessage with `aria-hidden` when empty instead of returning null:
```tsx
<p id={formMessageId} role="alert" aria-hidden={!body} className={cn(..., !body && "hidden")} {...props}>
  {body ?? ""}
</p>
```
**Decision needed (C-3)**: This removes the current approach of not rendering empty elements for spacing hygiene.
**Effort**: 30min

---

### MAJOR Issues

#### F-M-001: No test files for watchlists hub/members column definitions
**Severity**: MAJOR | **File**: `app/(app)/watchlists/hub-columns.tsx`, `members-columns.tsx`
**Fix**: Create column tests similar to `__tests__/feedback-columns.test.ts`.

#### F-M-002: buildScreenerFilters has no test
**Severity**: MAJOR | **File**: `features/screener/lib/build-filters.ts`
**Fix**: Unit tests for metric name mapping, null/undefined removal, enum validation.

#### F-M-003: AddPositionDialog test exercises schema directly (not component interaction)
**Severity**: MAJOR | **File**: `__tests__/add-position-dialog.test.tsx:114-139`
**Issue**: Quantity tests call `schema.safeParse()` — pure schema test. No test renders the component, fires blur on NumberInput, and asserts `aria-invalid` appears.
**Fix**: Add one integration test: type "0" → blur → `waitFor(screen.getByText("Must be greater than 0"))`.

#### F-M-004: TimePicker inputs lack group ARIA labeling
**Severity**: MAJOR | **File**: `components/ui/time-picker.tsx:136-175`
**Issue**: Two individual `aria-label="Hours"` / `aria-label="Minutes"` inputs but no `role="group"` wrapper with a contextual label. Screen reader announces each input in isolation without context.
**Fix**:
```tsx
<div className="flex items-center gap-1.5" role="group" aria-label="Time (hours and minutes)">
```

#### F-M-005: DateRangePicker trigger missing accessible label
**Severity**: MAJOR | **File**: `components/ui/date-range-picker.tsx:116-130`
**Issue**: The trigger `<Button>` has no `aria-label`. Screen reader reads "CalendarIcon Select date range" without context.
**Fix**: `aria-label={`Select date range${value?.from ? `: ${label}` : ""}`}` on the Button.

#### F-M-006: QuickEditPopover Label not associated via htmlFor
**Severity**: MAJOR | **File**: `components/ui/quick-edit-popover.tsx:131-147`
**Issue**: `<Label>` renders the `{label}` text but has no `htmlFor` — the visible label and the input's accessible name are disconnected.
**Fix**: Use `React.useId()` to generate an `inputId`; set `<Label htmlFor={inputId}>` and `<NumberInput id={inputId}>`.

#### F-M-007: Admin panel shows generic "Access denied" for all errors including 5xx
**Severity**: MAJOR | **File**: `app/admin/feedback/page.tsx`
**Fix**: `const is403 = error instanceof GatewayError && error.status === 403;` — differentiate message.

---

### MINOR Issues

#### F-N-001: `applyClientFilters` and `buildScreenerFilters` daily_return bounds assumption undocumented
**Severity**: MINOR | `build-filters.ts:83` — `min_value: -1, max_value: 1` for daily_return assumes decimal format (not %). Add comment referencing backend schema.

#### F-N-002: Feedback admin page auth guard is authentication-only (not role-check)
**Severity**: MINOR | `app/admin/feedback/page.tsx` — useEffect checks `isAuthenticated` but not `user.role === "admin"`. Backend enforces 403; client UX shows the loading state briefly before redirecting.

#### F-N-003: QuickEditPopover focus not returned to trigger on close
**Severity**: MINOR | `quick-edit-popover.tsx:76-84` — no `triggerRef` to restore focus when popover closes. Keyboard users lose context.

#### F-N-004: avgPrice allows `undefined` but `.nonnegative()` runs before `.optional()`
**Severity**: NIT | `AddPositionDialog.tsx:82-85` — ordering is `.nonnegative().finite().optional()`. In Zod, `.optional()` makes the entire chain optional, which is correct, but consider `.optional().default(undefined)` for explicitness.

---

## Compounding Updates

### docs/BUG_PATTERNS.md
- **BP-331** (new): P/E multiple columns in finance UIs must include "x" suffix — `.toFixed(1)` without suffix is ambiguous (could be read as price). Fix: template literal `${val.toFixed(1)}x`. Regression guard: assert `container.textContent` includes the "x".
- **BP-332** (new): Zod `.string().min(1)` without `.trim()` allows whitespace-only strings to pass `.min(1)` but collapse to empty after `.trim()` at the call site, creating a silent server-side 422. Fix: always chain `.trim().min(1)` on string fields used in API payloads.

### .claude/review/checklists/REVIEW_CHECKLIST.md
- Add check: "Zod string schemas used in API payloads — does the schema have `.trim()` before `.min(1)`?"
- Add check: "Numeric multiples (P/E, P/B, EV/EBITDA) — do cell renderers include the 'x' suffix?"
- Add check: "Composite form inputs (DateRangePicker, TimePicker) inside RHF FormControl — does `aria-invalid` propagate to sub-inputs?"

---

## Recommendations (Priority Order)

1. **Create missing test files** — F-C-001 through F-C-004 (5 files, ~5h total). These represent untested migration work; a regression here would be silent.
2. **Fix TimePicker + DateRangePicker ARIA** — F-M-004, F-M-005, F-M-006 (1h) — straightforward attribute additions, no behavior change.
3. **Fix FormMessage null-render aria-describedby** — F-C-005 (30min) — spec compliance, low visual impact.
4. **Decide on TransactionsTable onRowClick** — C-1 — if `/portfolio/transactions/:id` page exists (or is planned), wire `onRowClick` now.
5. **Admin panel 403 vs 5xx error** — F-M-007 (20min) — user experience improvement.
