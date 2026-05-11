# DESIGN QA GATE — Bloomberg-Grade Terminal Standards

> **Purpose:** Pre-merge checklist enforcing terminal-grade information density,
> token correctness, accessibility, performance, and security.
> Run this checklist before every PR that touches `apps/worldview-web/`.
>
> **Reference:** `feremabraz/bloomberg-terminal` density patterns;
> `docs/ui/DESIGN_SYSTEM.md` for token catalogue.
>
> **Status tracking:** Every line item maps to a specific PLAN-0071 phase.
> Violations must be fixed (not suppressed) before merge.

---

## 1 — Token Enforcement

> Raw Tailwind color classes are banned by ESLint (`no-restricted-syntax` in `.eslintrc.json`).
> All color values must resolve through CSS variable tokens.

| Check | Rule | Verify |
|-------|------|--------|
| T-1-1 | No `text-gray-*`, `bg-gray-*`, `border-gray-*`, `text-zinc-*`, `text-slate-*` | `grep -r "text-gray\|bg-gray\|border-gray\|text-zinc\|text-slate" components/ app/` → zero matches |
| T-1-2 | No `text-amber-*` raw class; use `text-warning` (CSS var `--warning`) | `grep -r "text-amber" components/ app/` → zero matches |
| T-1-3 | No hardcoded hex colors in `className` or `style` props | No `#[0-9a-fA-F]{3,6}` in JSX className strings |
| T-1-4 | Sentiment colors use token class: `text-positive`, `text-negative`, `text-warning` | Search for raw `text-green-*`, `text-red-*` → zero matches |
| T-1-5 | ESLint rule is active and passing | `pnpm --filter worldview-web lint` exits 0 |
| T-1-6 | `hsl(var(--positive))` / `hsl(var(--negative))` used ONLY in dynamic `className` string interpolation (not in Tailwind `cn()` — use `text-positive` token instead) | Review any `hsl(var(--` in JSX attribute strings |

---

## 2 — Typography

> IBM Plex Mono for all data. `text-[11px]` for data rows. `tabular-nums` everywhere digits appear.

| Check | Rule | Verify |
|-------|------|--------|
| T-2-1 | All data row text uses `font-mono` (IBM Plex Mono loaded in `globals.css`) | Data tables, screener rows, sidebar items, news rows: `font-mono` present |
| T-2-2 | Data row font size: `text-[11px]` (body) or `text-[10px]` (label/meta) | No `text-sm` (14px) or `text-base` (16px) in widget data rows |
| T-2-3 | `tabular-nums` on every price, percentage, counter, timestamp | `grep -r "font-mono" components/` — every instance also has `tabular-nums` OR value is non-numeric |
| T-2-4 | Section/panel headers: `text-[10px] uppercase tracking-[0.08em] text-muted-foreground` | Nav section labels, widget titles match this pattern |
| T-2-5 | No `text-xs` (12px) in data cells; `text-xs` permitted only in badge/pill labels | Review any `text-xs` instances in data widgets |
| T-2-6 | Leading: `leading-snug` for title text; `leading-none` for single-line data rows | Confirm news `ArticleRow`, screener rows use `leading-none` |

---

## 3 — Spacing

> Bloomberg terminal density: 8px (p-2) inside data widgets, 4px (gap-1) between data rows.
> 16px (p-4) only in editorial / docs / landing pages.

| Check | Rule | Verify |
|-------|------|--------|
| T-3-1 | Data widget bodies: `p-2` max (no `p-4`, `p-6`, `p-8`) | `grep -r "p-4\|p-6\|p-8" components/dashboard/ components/instrument/` — review each hit; fix data widgets |
| T-3-2 | List/feed gaps: `gap-2` max between items (no `gap-4`, `gap-6`) | `grep -r "gap-4\|gap-6\|space-y-4\|space-y-6" components/dashboard/` → zero in data widgets |
| T-3-3 | Widget section headers: `px-2 py-1` (no `py-2`, `py-3`) | Section headers in `FundamentalsTab`, `PortfolioSummary`, etc. |
| T-3-4 | Editorial pages (`/docs`, `/landing`) may use `p-4`+ — do not reduce | These are intentionally larger for readability |
| T-3-5 | Collapsed sidebar: max `px-2.5` on nav items | `CollapsibleSidebar.tsx` nav items use `px-2.5` |
| T-3-6 | `ArticleCard` body: `py-1 px-2` — no `py-2` or higher | `components/news/ArticleCard.tsx` |

---

## 4 — Component Density

> Row height targets from bloomberg-terminal reference: 22px data rows, 28px nav rows, 32px top bar.

| Check | Rule | Verify |
|-------|------|--------|
| T-4-1 | Sidebar nav rows: `h-7` (28px) — no `h-9` (36px) | `CollapsibleSidebar.tsx` Link elements use `h-7` |
| T-4-2 | Sidebar icons: `h-[14px] w-[14px]` — no `h-[18px]` | `CollapsibleSidebar.tsx` Icon components |
| T-4-3 | Collapsed rail width: `40px` (COLLAPSED_WIDTH constant) — no `48px` | `CollapsibleSidebar.tsx` constant value |
| T-4-4 | TopBar height: `h-8` (32px) — no `h-9` (36px) | `TopBar.tsx` header element |
| T-4-5 | News `ArticleRow`: single-line layout, no second metadata `<div>` | `app/(app)/news/page.tsx` — no `ml-12 flex items-center` second row |
| T-4-6 | News `ArticleRow` padding: `py-1` — no `py-1.5` or `py-2` | `app/(app)/news/page.tsx` |
| T-4-7 | AG Grid row height: `rowHeight={22}` in `AgGridBase` | `components/ui/ag-grid/AgGridBase.tsx` |
| T-4-8 | `ArticleCard` summary: `line-clamp-1` (no `line-clamp-2`) | `components/news/ArticleCard.tsx` |
| T-4-9 | Holdings / screener data rows: `h-[22px]` | `SemanticHoldingsTable`, screener AG Grid |
| T-4-10 | `MetricRow` in `FundamentalsTab`: `h-[22px]` fixed height | `FundamentalsTab.tsx` MetricRow component |

---

## 5 — Accessibility

> WCAG 2.1 AA. All interactive elements keyboard-reachable. Focus rings visible.

| Check | Rule | Verify |
|-------|------|--------|
| T-5-1 | All `<button>` elements have `aria-label` when they contain only an icon | `grep -r "<button" components/ app/ | grep -v "aria-label"` — review hits |
| T-5-2 | All `<Link>` nav items have `aria-label` | Sidebar `Link` elements; confirmed in `collapsible-sidebar.test.tsx` |
| T-5-3 | `focus-visible:ring-1 focus-visible:ring-primary` on all interactive elements | Buttons, links, inputs — check via keyboard Tab navigation |
| T-5-4 | `aria-current="page"` on the active sidebar nav item | Confirmed in sidebar tests; verify in browser with screen reader |
| T-5-5 | Charts have `aria-label` on their container | `OHLCVChart`, `MarketHeatmap` treemap, sparklines |
| T-5-6 | Color-only information always has a text/icon equivalent | Positive/negative P&L has both color class AND `▲`/`▼` or `TrendingUp`/`TrendingDown` icon |
| T-5-7 | External links have `(opens in new tab)` in aria-label | `ArticleRow`, `ArticleCard` anchor elements |
| T-5-8 | Keyboard nav: Tab reaches all interactive sidebar items in collapsed mode | Manual test |
| T-5-9 | No `tabIndex={-1}` removing reachable elements | Grep for `tabIndex` usage in component files |

---

## 6 — Performance

> Production build must be clean. No layout shift on data load. No unnecessary re-renders.

| Check | Rule | Verify |
|-------|------|--------|
| T-6-1 | `pnpm --filter worldview-web build` exits 0 with no errors or warnings | Run before every PR |
| T-6-2 | No layout shift (CLS) when data loads: skeleton placeholder sizes match real content | Visual check: news list, dashboard widgets, portfolio table |
| T-6-3 | AG Grid bundle: `@ag-grid-community/react` ≤ 500KB gzipped | Check `.next/analyze/` if `ANALYZE=true pnpm build` |
| T-6-4 | No `useQuery` calls with `staleTime: 0` (defeats cache deduplication) | `grep -r "staleTime: 0" components/ app/` → review each hit |
| T-6-5 | Lists over 50 items use virtualization (react-virtual or AG Grid) | News list (50+), screener (500+), holdings (20+) |
| T-6-6 | `useMemo` / `useCallback` used where treemap/chart items are recomputed on every render | `MarketHeatmap` items array is memoized; confirm similar for other heavy computations |
| T-6-7 | No `useEffect` with empty deps `[]` that fires async calls — use `useQuery` | Grep for `useEffect` + `fetch` or `axios` |

---

## 7 — Security

> Frontend security baseline. No XSS vectors. No secrets in client code. S9-only API calls.

| Check | Rule | Verify |
|-------|------|--------|
| T-7-1 | No `dangerouslySetInnerHTML` in any component | `grep -r "dangerouslySetInnerHTML" components/ app/` → zero matches |
| T-7-2 | No access token in `localStorage`, `sessionStorage`, or cookies | Tokens live in React context (AuthContext) only — never in storage APIs |
| T-7-3 | All API calls go through `createGateway(accessToken)` (S9 proxy) — no direct backend URLs | `grep -r "localhost:800[0-9]\|:8001\|:8002\|:8003\|:8004\|:8005\|:8006\|:8007\|:8008" components/ app/` → zero matches |
| T-7-4 | External links use `safeExternalUrl()` (validates protocol, strips `javascript:`) | All `href` values from API data pass through `safeExternalUrl()` |
| T-7-5 | No hardcoded API keys, secrets, or credentials in any frontend file | `pnpm --filter worldview-web lint` + secret scan (`.claude/hooks/security_scan.py`) |
| T-7-6 | CSP nonce applied to all inline `<script>` and `<style>` tags | `middleware.ts` injects nonce; `_document.tsx` passes it through |
| T-7-7 | No `eval()` or `new Function()` usage | `grep -r "eval(\|new Function(" components/ app/ lib/` → zero matches |
| T-7-8 | `rel="noopener noreferrer"` on all `target="_blank"` links | `grep -r 'target="_blank"' components/ app/ | grep -v "noopener"` → zero matches |

---

## Checklist Quick-Run Script

Run from `apps/worldview-web/`:

```bash
# 1. Lint (token enforcement + ESLint rules)
pnpm lint

# 2. Type-check
pnpm typecheck

# 3. Unit tests
pnpm test --run

# 4. Production build
pnpm build

# 5. Token violations (manual grep)
echo "=== Token violations ==="
grep -rn "text-gray\|bg-gray\|text-zinc\|text-amber-\|text-red-\|text-green-" \
  components/ app/ --include="*.tsx" --include="*.ts" | grep -v "\.test\."

# 6. Padding violations in data widgets
echo "=== Widget padding audit ==="
grep -rn "p-4\|p-6\|gap-4\|gap-6\|space-y-4" \
  components/dashboard/ components/instrument/ --include="*.tsx"

# 7. External link security
echo "=== Unsafe external links ==="
grep -rn 'target="_blank"' components/ app/ --include="*.tsx" | grep -v "noopener"

# 8. Direct backend calls
echo "=== Direct service calls ==="
grep -rn "localhost:800[0-9]" components/ app/ lib/ --include="*.ts" --include="*.tsx"
```

All commands must exit without matches (or zero violations) before a PR is merged.

---

## Failing Checks: Escalation Path

1. **Token violation** → Fix in the same PR. ESLint blocks merge.
2. **Spacing violation** → Fix in the same PR. Document WHY if editorial exception needed.
3. **A11y violation** → Fix in the same PR. WCAG AA is non-negotiable.
4. **Performance regression** → Investigate bundle diff. Fix or document as known debt.
5. **Security violation** → BLOCK merge. Escalate immediately.

---

*Maintained by the Frontend Team. Update this file when new patterns are added to the design system.*
*PLAN-0071 Phase 1 P1-5.*
