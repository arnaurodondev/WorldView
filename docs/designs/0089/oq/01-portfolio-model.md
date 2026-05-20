# Cluster 1 — Portfolio Model (PRD-0089 Open Questions)

> **Status**: design discovery — feeds the master PRD-0089.
> **Author**: agent-portfolio-model
> **Date**: 2026-05-19
> **Scope**: 20 open questions from `02-dashboard.md`, `03-portfolio-overview.md`,
> `04-portfolio-detail.md` that all hinge on a single architectural decision:
> **what is "the portfolio" the user sees by default?**
> **Anchor**: user said *"I believe we should be displaying the total portfolio
> (all positions)"* — i.e. a household-aggregated view across all sub-portfolios,
> with the option to drill into a single one.

---

## 1. Summary of the cluster

### 1.1 The headline finding

**The aggregated household view is already built.** PLAN-0046 (W3/W4, shipped)
introduced a `PortfolioKind.ROOT` enum and a per-user auto-provisioned ROOT
portfolio that, when read through the existing use cases, transparently:

- Aggregates holdings via `HoldingRepository.list_by_portfolio_ids_aggregated_enriched()`
  (qty-summed, qty-weighted average cost per instrument).
- Unions transactions across sub-portfolios newest-first via
  `TransactionRepository.list_by_portfolio_ids()`.
- Fans out exposure across sub-portfolios via `GetExposureUseCase` ROOT branch.
- Snapshots a daily ROOT row by **summing** non-root snapshot rows for the same
  owner (Phase 2 of `PortfolioSnapshotWorker._aggregate_root_portfolios`).
- Surfaces in the frontend with ROOT-first sort
  (`apps/worldview-web/features/portfolio/hooks/usePortfolioData.ts:185-203`),
  a "root" chip in `PortfolioPageHeader.tsx:128`, and a typed
  `kind?: "manual" | "brokerage" | "root"` on the API DTO
  (`types/api.ts:796`).

What's missing is **product polish on top of the existing rails**:

1. The dashboard widgets (`PortfolioSummary`, the proposed `TopOfPortfolio`) do
   not explicitly steer the user toward the ROOT view — they pick whichever
   portfolio is first by listing order (today: ROOT-first, but the UX is silent
   on that).
2. KPI/widget copy still implies a single account ("Day P&L", "Cash Balance"),
   not an aggregated one.
3. No backend fan-out exists yet for the **derived** read endpoints proposed
   in `03-`/`04-`: `/top-movers`, `/twr`, `/attribution`, `/risk-metrics` need
   the same ROOT branch wired in.
4. Multi-currency, target weights, and per-broker tax-lot reconciliation are
   v1 deferrals — flagged below.

### 1.2 User preference anchor vs the recommendation

The user's stated preference ("display the total portfolio, all positions")
matches the ROOT-portfolio default exactly. We endorse it and recommend the
canonical pattern:

- **Default view = ROOT** ("All Accounts (USD)") — the page boots into the
  household-aggregated view on every entry, dashboard or portfolio page.
- **Selector** in the page header (and dashboard widget header) lets the user
  drill into any sub-portfolio (Manual / Demo / Live broker / Paper).
- **Persisted selection** in `localStorage` (`worldview.activePortfolioId`)
  scoped per user — but cleared whenever the selected portfolio_id no longer
  exists in `/portfolios` (broker disconnects, demo reset).
- **No fallback to a fake "first sub-portfolio"** — if the user has only a
  Demo portfolio, the ROOT view still works (it just aggregates one
  sub-portfolio), so it is always the safest default.

This decision propagates and resolves 9 of the 20 OQs directly (see §5).

### 1.3 The OQs in scope, by source

| Source doc | OQ # | Topic | Hinges on aggregated view? |
|------------|------|-------|----------------------------|
| `02-dashboard.md` | 1 | Default portfolio for Top-of-Portfolio | yes — directly |
| `02-dashboard.md` | 2 | No-brokerage state (demo vs CTA) | yes — interacts |
| `02-dashboard.md` | 3 | Day P&L during pre-market | partly — semantics of "day" change |
| `02-dashboard.md` | 5 | Mobile collapse for KPI strip | no — pure responsive UI |
| `02-dashboard.md` | 7 | Brief border style | no — orthogonal |
| `03-portfolio-overview.md` | 1 | Top contributors/detractors endpoint | yes — needs ROOT fan-out |
| `03-portfolio-overview.md` | 2 | Risk metrics computation source | yes — same fan-out |
| `03-portfolio-overview.md` | 3 | Currency exposure beyond top-2 | yes — household = multi-currency by nature |
| `03-portfolio-overview.md` | 5 | Benchmark choice (SPY only vs user-selectable) | partly — multi-currency forces benchmark choice |
| `03-portfolio-overview.md` | 6 | Performance chart height | no |
| `03-portfolio-overview.md` | 7 | Sparkline rendering performance | no |
| `03-portfolio-overview.md` | 8 | Period-return chip duplication | no |
| `03-portfolio-overview.md` | 9 | Empty state copy | yes — interacts with no-brokerage |
| `04-portfolio-detail.md` | 1 | Benchmark selection | yes — same as 03 OQ5 |
| `04-portfolio-detail.md` | 2 | Excess-return colouring | no |
| `04-portfolio-detail.md` | 3 | Holding contribution chart series | no |
| `04-portfolio-detail.md` | 4 | Custom period picker | no |
| `04-portfolio-detail.md` | 5 | Running balance accuracy | partly — ROOT cross-account fx |
| `04-portfolio-detail.md` | 6 | Attribution time aggregation | yes — ROOT changes the math |
| `04-portfolio-detail.md` | 7 | Empty-brokerage CSV import scope | no |
| `04-portfolio-detail.md` | 8 | Slide-over behaviour at < lg | no |

Cluster spans **20 OQs**; ~10 are sensitive to the aggregated-view decision.

---

## 2. Per-OQ deep dive

Each section follows the same structure: alternatives → pros/cons → recommendation.
Recommendations are summarised in §5.

### 2.1 `02-dashboard.md` OQ 1 — Which portfolio does Top-of-Portfolio default to?

**Current code (`PortfolioSummary.tsx`, `usePortfolioData.ts`)**: picks the first
portfolio in the response. Because the ROOT-first sort in
`usePortfolioData.ts:185-193` is already in place, the de-facto default is
"ROOT" — but the dashboard widget bypasses `usePortfolioData` and re-fetches
without the sort, so it sometimes lands on a non-root portfolio.

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. ROOT (household) default | Reuse `usePortfolioData` selector logic in the dashboard widget; default is the ROOT portfolio. User can switch via `[ROOT · Manual · Live ▾]` dropdown in the widget header. | Matches user preference verbatim. Reuses already-shipped backend. Single source of truth — same as `/portfolio` page. | Requires the dashboard widget to consume the same hook (small refactor). |
| B. Last-selected (localStorage) default | Persist last opened portfolio id; default to ROOT only if no preference. | Respects user habit. | Cross-device drift — desktop says ROOT, phone says Demo, confusing. Dead-end if the stored id is stale. |
| C. Live brokerage > Demo > ROOT | Prefer the user's "real money" account, fall through. | Surfaces the most-valuable book on top. | Ignores the explicit user preference. Adds a brittle heuristic the user can't override without reading docs. |
| D. Sticky URL query param `?portfolio=…` | Default = ROOT, persistence via URL. | Deep-linkable; shareable. | User can't bookmark dashboard with their preferred portfolio without manual URL surgery. |

**Recommendation: A + D**. ROOT is the default. Selection is persisted to
**URL** (`?portfolio=<id>` on `/portfolio`; not on `/dashboard`) and to
**localStorage** (`worldview.activePortfolioId`) as a fallback for the
dashboard widget. localStorage takes effect only if the id still exists in
the `/portfolios` response — otherwise we fall back to ROOT. Same hook
(`usePortfolioData`) used by both surfaces.

### 2.2 `02-dashboard.md` OQ 2 — No-brokerage state (demo data vs CTA)

**Today**: `PortfolioSummary.tsx` shows fake demo data when no portfolio is
connected. ROOT changes this — a brand-new user has **exactly one** sub-portfolio
(the seeded Demo) the moment they sign up, so the ROOT view is never empty.
The state "no portfolios at all" is unreachable on production
(`EnsureRootPortfolioUseCase` provisions on first login).

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Always real (ROOT/Demo) | Show the seeded Demo via ROOT aggregation; never show "fake" demo numbers. | One code path. Real-looking data drives engagement. Connect-broker CTA appears as a secondary banner. | New user sees Demo numbers that may overstate real wealth (mitigation: label "Demo Account" prominently). |
| B. CTA-only when ZERO sub-portfolios | Render `BrokerageEmptyState` with `Connect brokerage` / `Add manual portfolio` CTAs. Hide all KPI cells. | Unambiguous "do something" prompt. | Dashboard's "Top of Portfolio" widget becomes empty — defeats the user's stated goal of always seeing positions. |
| C. Hybrid — CTA banner + Demo aggregation | ROOT aggregation runs in background; topbar shows `[Connect a real brokerage →]` banner if zero brokerage connections. | Best of both — engagement + clear next step. | Marginally more chrome. |

**Recommendation: C**. ROOT view is always populated (the Demo is the
floor); a single-line banner above the KPI strip says
"Demo data — connect a brokerage to track real positions" when
`brokerage_connections.length === 0`. Demo Portfolio is clearly tagged with
a `DEMO` chip in the selector dropdown. Removes the entire "demo data in
widget vs CTA" dichotomy.

### 2.3 `02-dashboard.md` OQ 3 — Day P&L during pre-market

The semantics of "today" change between US sessions:

| Time (ET) | "Day" baseline | UX consequence |
|-----------|----------------|----------------|
| 04:00–09:30 | Prior regular-session close | Day P&L reflects after-hours + overnight; matches IBKR Mosaic. |
| 09:30–16:00 | Today's regular open (T-day close) | Standard Bloomberg/Finviz behaviour. |
| 16:00–20:00 | Today's regular close | Day P&L freezes; after-hours move shown as "After-Hrs Δ". |

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Always prior-close baseline | Match S9 `/quotes/batch` semantics — `day_change` is prior close → last trade (regular + after-hrs combined). Label "since prev close". | Single number; what the backend already computes. | Misleading during regular hours when user reads it as intraday only. |
| B. Session-aware (regular-only) | During RTH, day_change uses today's open. Pre/post markets get a separate "After-Hrs" row. | Most precise. | Two numbers to display; eats more KPI strip width; needs S3 OHLCV intraday open which isn't in `/quotes/batch`. |
| C. Prior-close + hover legend | A — but every Day P&L cell has a tooltip explaining the baseline. | One number, no chrome cost. | Doesn't fix the regular-hours confusion entirely. |
| D. Adaptive label only | Display "Day P&L (since prev close)" pre-market and "Day P&L (intraday)" during/after RTH — same number, just relabel. | Cheap. Reduces confusion. | Requires the frontend to know session state — adds a `useMarketSession()` hook. |

**Recommendation: D for v1, B for v2**. Ship adaptive label + tooltip in
v1 (no backend change). File a follow-up to add S9 `/quotes/batch?session=intraday`
return field to enable session-aware breakdown. For the **aggregated ROOT view**,
the Day P&L is the **weighted sum** of per-position day deltas — see §4.4.

### 2.4 `02-dashboard.md` OQ 5 — Mobile collapse for KPI strip

The proposed dashboard `TopOfPortfolio` (R3) is a 12-col strip that doesn't
collapse cleanly below `lg` (1024px).

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Two-row stack | KPI strip → full-width row 1; positions table → full-width row 2; sparkline → row 3. | Each block keeps its information. | Widget height doubles on mobile. |
| B. Hide table on `< md` | KPI strip only; positions table behind a "View positions" link. | Saves vertical space. | Defeats the user's stated goal (always show positions). |
| C. Carousel/swipe | Three pages: KPIs / positions / sparkline; swipe. | Native-feeling on phone. | Hidden affordance; non-power users miss the table. |

**Recommendation: A**. The user's anchor is "always show positions".
Mobile users get a taller dashboard, but every datum remains in view.
Breakpoint: `< lg` (1024px) collapses to single column.

### 2.5 `02-dashboard.md` OQ 7 — Brief border style

Pure visual; no portfolio implication.

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Left-rail border | `border-l-[3px] border-l-primary`, no other borders. Bloomberg amber-rail look. | Authentic terminal aesthetic; removes 6 px of chrome around the brief. | Looks "loud" on first impression. |
| B. Box border | `border border-primary/60` (current). | Familiar card look. | Eats real estate; the yellow border becomes the dashboard's loudest pixel. |
| C. No accent | Plain `border border-border/40`. | Removes the visual hierarchy; brief looks like every other widget. | User loses "this is the AI synthesis" affordance. |

**Recommendation: A**. Matches the established Bloomberg-inspired
language already used in `_INDEX.md` shared tokens.

### 2.6 `03-portfolio-overview.md` OQ 1 — Top contributors/detractors endpoint

**Today**: derived client-side from `holdings × quotes`. Period-aware
attribution (1M / YTD) needs historical position weights that the client
cannot reconstruct.

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. New S1 endpoint `/portfolios/{id}/top-movers?period=…` | Backend computes from `portfolio_snapshots` + per-instrument value-history. Returns top-4 + bottom-4. | Period-aware; canonical authority. Auto-handles ROOT via `list_non_root_active_ids_by_owner`. | New endpoint + tests + migration to attribution series storage. |
| B. Client-side derivation, 1D only | Current behaviour; period buttons disabled with tooltip "1D only". | Zero backend work. | Hard ceiling on usefulness. |
| C. Add `?include=movers` to `/value-history` | Piggyback the existing endpoint. | One round trip. | Couples two concerns. |

**Recommendation: B for v1, A for v1.1**. The Movers strip ships
client-side with 1D-only support, with the "1M/YTD" pills disabled and
tooltipped ("coming soon — backend support pending"). File the new endpoint
as PRD-0089's first follow-up backend task. The endpoint MUST honour the
ROOT branch (sub-portfolio fan-out, then collapse per-instrument).

### 2.7 `03-portfolio-overview.md` OQ 2 — Risk metrics computation source

`/portfolios/{id}/risk-metrics` already returns sharpe, sortino, beta_vs_spy,
volatility_annualized, drawdown_max, drawdown_current. Today it's only wired
to non-ROOT portfolios.

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Backend ROOT branch — sum snapshots | `GetRiskMetricsUseCase` reads ROOT snapshot rows (already aggregated by `PortfolioSnapshotWorker` Phase 2). Sharpe/Sortino/Vol are computed on the ROOT value-history series — canonical. | Reuses existing snapshot rows; zero new tables. Numbers are deterministic. | Beta-vs-SPY for ROOT requires a benchmark series — fine, we have S3 SPY OHLCV. |
| B. Frontend client-side compute | Sum sub-portfolio value-history series, then compute. | No backend change. | Two surfaces compute the same number — drift risk. R28 violation if widely used. |
| C. Hide risk metrics on ROOT | Show on per-portfolio only. | No work. | Defeats the user's "all positions" expectation; risk-adjusted return is *the* number a household view exists to surface. |

**Recommendation: A**. The ROOT branch is one extra `if portfolio.kind == ROOT`
in `GetRiskMetricsUseCase`. Worth the 30-minute backend change to keep the
risk numbers authoritative. The frontend `RiskMetricsStrip` works unchanged.

### 2.8 `03-portfolio-overview.md` OQ 3 — Currency exposure beyond top-2

Today's `ExposureCurrencyStrip` shows top-2 currencies inline. A household
view is naturally multi-currency once the user adds an IBKR EUR account.

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Inline top-3 + `+N more` popover | Show 3 currencies in the strip; click `+N` opens a 4-cell popover. | Bounded chrome. Always shows the dominant currency. | Popover hides data. |
| B. Inline all (truncate if >5) | Use available horizontal real estate; auto-shrink font when >5. | All data visible. | Strip becomes unreadable at 6+ currencies. |
| C. Currency tab in Analytics | Move detail to `/portfolio/analytics`; overview shows top-2 only. | Cleanest overview. | User has to leave the page to see USD vs EUR weighting. |

**Recommendation: A**. Top-3 inline (USD, then 2nd, then 3rd), then
`+N more` chip. Popover lists each currency with weight + base-USD value.
ROOT amplifies this need: a household with USD/EUR/GBP accounts gets the
right snapshot.

### 2.9 `03-portfolio-overview.md` OQ 5 — Benchmark choice (SPY only vs user-selectable)

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. SPY-only | Hard-coded. Matches what S1 `risk-metrics` returns today. | Simple; no UI for benchmark management. | Doesn't fit EUR/GBP books; doesn't fit bond-heavy books. |
| B. Dropdown of {SPY, QQQ, IWM, EFA, AGG, 60/40, custom ticker} | Persisted per portfolio (or globally per user). | Flexible; matches IBKR Portfolio Analyst. | Adds 1 backend field on Portfolio entity + 1 dropdown UI + benchmark series fetch (we already proxy S3). |
| C. Auto-pick by dominant currency | USD → SPY, EUR → IEUR/STOXX600, multi → 60/40. | Sensible default without UI. | Hides the choice; users assume their number is vs SPY when it isn't. |

**Recommendation: B with default SPY**. New nullable field on Portfolio:
`benchmark_ticker` (string, default NULL → frontend reads as SPY). User
selects from a curated list of 8 benchmarks; "custom ticker" is v2. ROOT
portfolio benchmark is set independently from sub-portfolios (it's the
"household benchmark"). Migration cost: 1 Alembic migration (add column,
default NULL), 1 use case update (`UpdatePortfolioUseCase`), 1
`/portfolios/{id}` PATCH endpoint extension.

### 2.10 `03-portfolio-overview.md` OQ 6 — Performance chart height

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. 120 px (current proposal) | Compromise — between Bloomberg's 180 and Finviz's 0. | Fits in the strip stack. | Tight for benchmark overlay readability. |
| B. 180 px (Bloomberg-style) | Matches PORT inline chart. | More room for benchmark + drawdown overlay. | Pushes positions table further down the fold. |
| C. Collapsible (default 120, expand to 240) | Toggle button on the chart's header. | Best of both. | Adds complexity. |

**Recommendation: C**. 120 px default + a `▾` toggle to expand to 240 px,
persisted to localStorage `worldview.perfChartHeight`. User can choose.

### 2.11 `03-portfolio-overview.md` OQ 7 — Sparkline rendering performance

60 px SVG × ~30 rows × 14 points = 420 small DOM nodes. AG Grid
`cellRenderer` renders incrementally.

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Inline SVG `<path>` per row | Single `path d="…"` element per cell; 14 lineTo commands. | Best CPU; lowest DOM count. | Renders only on row enter (AG Grid). |
| B. Canvas-based renderer | One canvas per cell. | Lowest paint cost. | Loses CSS-class theming. |
| C. CSS-only (mini bars) | No path, just 14 colored divs. | Trivial. | Looks like a heatmap not a sparkline. |

**Recommendation: A**. Single `path`. Bench on a 100-position book during
implementation. Already proposed in `03-`.

### 2.12 `03-portfolio-overview.md` OQ 8 — Period-return chip duplication

The "+4.8 %" chip in the page header duplicates the Day P&L cell in the
KPI strip when the chip's period is `1D`.

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Lock chip to chart period | Chip mirrors the chart's selected period. `1D` chart → chip duplicates KPI; `YTD` chart → chip is distinct. | Aligns two surfaces. | Still duplicates at 1D. |
| B. Hide chip on 1D | When period == 1D, hide the chip. | Removes duplication. | The chip appears/disappears — disorienting. |
| C. Drop the chip | Period info already in the chart legend + KPI cells. | One less surface. | Loses the "period return" anchor. |

**Recommendation: A**. Lock chip to chart period; tolerate the 1D
duplication (it's still the most-referenced number).

### 2.13 `03-portfolio-overview.md` OQ 9 — Empty state copy

Interacts with §2.2. Two real scenarios:

| Scenario | UI |
|----------|----|
| Zero brokerage connections, Demo only | ROOT shows Demo aggregation; topbar banner: "Demo data — [Connect a real brokerage]". |
| Zero positions in a *single* sub-portfolio (user switched off ROOT to e.g. Manual portfolio with no holdings) | Inline empty card inside the table: "No positions in this portfolio. [Add position] · [Switch to All Accounts]". |
| Sub-portfolio with positions all qty=0 (closed-out book) | Existing `allZeroQty` handling preserved. |

**Recommendation**: ROOT-default makes "no holdings anywhere" effectively
impossible. The empty state we need is the **sub-portfolio empty** case;
the copy includes a "Switch to All Accounts" CTA that flips back to ROOT.

### 2.14 `04-portfolio-detail.md` OQ 1 — Benchmark selection

Same answer as §2.9. **One dropdown sourced from the same per-portfolio
field**; the Analytics tab's `[Benchmark ▾]` reads from the same
`portfolios.benchmark_ticker`.

### 2.15 `04-portfolio-detail.md` OQ 2 — Excess-return colouring

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Colour by sign | Green if excess > 0, red if < 0. Bloomberg PORT does this. | Fast scan. | Conflates "absolute return" green with "vs-benchmark" green; users may misread. |
| B. Neutral (no colour) | Always `text-foreground`. IBKR does this. | Avoids confusion. | Loses the at-a-glance "am I beating SPY?" signal. |
| C. Distinct colour (e.g. amber for outperformance, muted for underperformance) | Uses `text-warning` for +excess. | Differentiates from absolute return. | Yet another colour vocabulary to learn. |

**Recommendation: A with a tooltip**. Colour by sign — `text-positive` /
`text-negative`. Tooltip on the column header: "Coloured by sign of excess
return vs SPY". The visual hierarchy stays familiar (green = good).

### 2.16 `04-portfolio-detail.md` OQ 3 — Holding contribution chart series

The mini-chart in the slide-over panel can show one of three series:

| Option | Series | Use case |
|--------|--------|----------|
| A | Position price (TradingView-style) | Pure price action — but the user can see this on the instrument page already. |
| B | Position market value (Bloomberg PORT-style) | qty × price over time — shows the *position's* value. |
| C | Contribution-to-portfolio (IBKR-style) | (weight × period_return) cumulative — answers "how much did this holding add to my book?" |

**Recommendation: C**. The slide-over's value-add over the instrument page
is exactly the *portfolio-relative* contribution. Approved in `04-`§10.3.

### 2.17 `04-portfolio-detail.md` OQ 4 — Custom period picker

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Native `<input type="date">` pair | Two date inputs; minimal chrome. Same pattern as the ledger filter. | Zero new dependencies. | Limited keyboard/range UX. |
| B. shadcn `Calendar` popover | Two-month grid range picker. | Polished. | New component dependency. |

**Recommendation: A**. Keep the dependency surface small; the user
audience is finance-pro and used to date typing.

### 2.18 `04-portfolio-detail.md` OQ 5 — Running balance accuracy

A per-row cash balance requires either:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Backend field with `?include=running_balance` | Authoritative; honours FX and corporate actions. | Right answer. | New backend feature; expensive query on long history. |
| B. Client-side reconstruction | `Total` cumulative — ignores FX, corporate actions, fees. | Cheap. | Inaccurate on multi-currency or post-split rows. |
| C. Drop the column | Don't show running balance. | No misinformation. | User loses a useful audit aid. |

**Recommendation: B with a tooltip**. Ship the column with a
clear tooltip ("Approximate — excludes FX revaluation and corporate
actions"). File a follow-up for backend support. ROOT case: running balance
is computed over the merged tx stream (already sorted by `executed_at`).

### 2.19 `04-portfolio-detail.md` OQ 6 — Attribution time aggregation

When a holding is sold mid-period:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. TWR with cash-flow weighting | Weight by capital deployed during the holding period. | Canonical; matches industry. | Math is non-trivial; requires backend. |
| B. Buy-and-hold simple return | Period return on the position assuming it was held the full period. | Easy. | Misleading if sold partway. |
| C. Daily reweighting | Recompute weights every day; sum daily contributions. | Most accurate. | Heavy compute on long histories. |

**Recommendation: C deferred to backend `/attribution` endpoint; v1 ships
A as a client-side approximation**. For v1, the Attribution table is
labelled "Simple period attribution (assumes constant weight)". The new
endpoint replaces it without a UI change.

### 2.20 `04-portfolio-detail.md` OQ 7 — Empty-brokerage CSV import scope

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Remove the `[Import CSV]` CTA for v1 | Empty state shows only `[Connect brokerage]` + `[Add manual position]`. | Honest scope. | Loses a real user need. |
| B. Implement a basic CSV importer | One-shot bulk transaction load. | Useful. | Out of v1 PRD scope; needs file schema + S1 endpoint. |
| C. Beta-flag the CTA | Render but disable; hover tooltip "Coming soon". | Hints at roadmap. | Disabled CTAs are clutter. |

**Recommendation: A**. Drop the CTA from v1. File a separate ticket
"CSV importer for transactions" — scoped to a future PRD.

### 2.21 `04-portfolio-detail.md` OQ 8 — Slide-over behaviour at `< lg`

**Alternatives**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Full-screen modal `< lg` | Slide-over takes the full viewport; close button stays in the corner. | Native-feeling on tablet; matches mobile expectations. | Loses table context. |
| B. Replace with a "View detail" link row | No panel; opens a dedicated route `/portfolio/{id}/holdings/{iid}`. | Simpler interaction model. | Diverges from the desktop pattern. |
| C. Bottom-sheet drawer `< md` | Slides up from the bottom on phones. | Best mobile pattern. | Custom component; adds CSS. |

**Recommendation: A**. Full-screen modal at `< lg`. The portfolio detail
page isn't a heavy phone target; A is the simplest correct pattern.

---

## 3. The big architectural decision — aggregated household view

### 3.1 What "aggregated household view" means here

The term comes from financial planning (Wealthfront, Fidelity, Schwab):
a single composite view that rolls up every account a user owns into one
"household" book. We use the term loosely — most worldview users have one
or two sub-portfolios, not the multi-account-trust-IRA-401k complexity of
a wealth-management UI.

For worldview, household = the **ROOT portfolio**:
- One per user.
- Auto-provisioned on first login (`EnsureRootPortfolioUseCase`).
- Reads aggregate across the user's non-root active portfolios (Manual /
  Brokerage / Demo / Paper).
- Writes (record transaction) are not allowed on ROOT — they fail in
  `RecordTransactionUseCase` line 132 (`if portfolio.kind == PortfolioKind.ROOT`).
- Snapshot worker writes a daily ROOT row by summing same-date sub-portfolio
  snapshots.

### 3.2 Competitor practice table

| Platform | Default view | Aggregated view supported? | Switch granularity | Notes |
|----------|--------------|---------------------------|---------------------|-------|
| **Bloomberg PORT** | Single portfolio (one `<Equity> PORT <GO>` runs at a time) | No native aggregation; AIM/Wealth-Manager add-on handles consolidation | Per-portfolio (one selected at a time) | Bloomberg's primary audience = institutional PMs with one mandate; consolidation is a separate workflow. |
| **Interactive Brokers — TWS Account Window** | Single account default; "Linked Accounts → Show Combined" toggle adds composite | YES — explicit consolidated view at the account level | Account dropdown + Combined toggle | The reference pattern for our ROOT default. |
| **Interactive Brokers — Portfolio Analyst** | Composite by default for users with multiple linked accounts | YES | Same Combined toggle | Analyst tab promotes consolidation. |
| **Schwab StreetSmart Edge** | "Linked Accounts" → multi-account dropdown with "All Accounts" entry | YES — "All Accounts" is a first-class option | Account dropdown with "All Accounts" | Closest analogue to our ROOT pattern. |
| **Fidelity Active Trader Pro** | Per-account default; "Multi-Account Selector" surfaces composite | YES — "Combined Accounts" view | Multi-select | Fidelity's "Household" terminology is on web.fidelity.com, not ATP. |
| **Wealthfront / Betterment** | Aggregated household by default (entire net worth) | YES — it's the only view | Account drilldown via clicks | The opposite extreme — aggregation is the *only* mode. |
| **Public.com / Robinhood** | Single account (no multi-account support) | NO | n/a | Retail-only model. |
| **TradingView Paper Trading** | Per-portfolio | NO native composite (workaround: third-party watchlist) | n/a | Trading-focused, not wealth-tracking. |
| **Koyfin Dashboard** | Per-portfolio | NO composite; users build a separate "watchlist" | n/a | Dashboard is one portfolio at a time. |

**Conclusion**: the platforms that match our target user (IBKR, Schwab,
Fidelity) all support a composite view as a first-class selector entry —
typically labelled "All Accounts" or "Combined Accounts". This is exactly
the ROOT pattern worldview has already shipped. None of them aggregate
silently — there is always a dropdown that lets the user switch granularity.

### 3.3 Long-term architectural implications

We assess these against the **already-shipped** ROOT pattern, since the
question is no longer "should we?" but "what gaps remain?".

#### 3.3.1 Domain — already done

| Concern | Status |
|---------|--------|
| Portfolio kind enum | `PortfolioKind.ROOT / MANUAL / BROKERAGE` in `enums.py:46` |
| One-root-per-user enforcement | Partial unique index `(owner_id) WHERE kind='root'` |
| Auto-provisioning | `EnsureRootPortfolioUseCase` called on first login (`provision_user.py`) |
| Holdings aggregation | `list_by_portfolio_ids_aggregated_enriched` — qty sum, qty-weighted avg cost |
| Transactions union | `list_by_portfolio_ids` — newest-first union |
| Exposure fan-out | `GetExposureUseCase` ROOT branch |
| Daily snapshot aggregation | `PortfolioSnapshotWorker._aggregate_root_portfolios` (Phase 2) |
| Write guard | `RecordTransactionUseCase` rejects writes to ROOT |
| Frontend awareness | `usePortfolioData` ROOT-first sort + `activeIsRoot` flag |
| API DTO | `kind?: "manual" | "brokerage" | "root"` |

#### 3.3.2 Currency normalisation — partly done

The `Money` value object (`value_objects.py:18-50`) explicitly raises on
currency mismatch. Today every portfolio is assumed USD. ROOT aggregation
sums quantities (currency-agnostic) and qty-weighted average costs (in
each sub-portfolio's currency — *which is wrong if currencies mix*).

**Gap**: when a user has a USD IBKR and an EUR IBKR account:
- `holdings.average_cost` is stored in the sub-portfolio's currency.
- ROOT aggregation sums in the wrong unit.

**Fix path** (deferred from v1):
1. Add `currency` field on `Holding` (already on Transaction; add to
   Holding read DTO).
2. Convert to a canonical currency (default USD) at aggregation time using
   `S5 FxRate` (already exists for transactions).
3. Surface a `currency_mix` field on the ROOT read response so the UI can
   show "USD 92 % · EUR 8 %" honestly.

**v1 scope**: assume USD-only — flag a backlog issue if a user adds a
non-USD sub-portfolio. Banner: "Mixed-currency aggregation is approximate;
non-USD positions converted at last close."

#### 3.3.3 Tax-lot rollup — out of scope for ROOT

FIFO lots are tracked per (portfolio_id, instrument_id) via
`GetHoldingLotsUseCase`. ROOT aggregation **does not** roll lots up.

**Why**: tax-lot semantics are per-account by IRS rule. A user holding
100 AAPL in IBKR Taxable and 50 AAPL in IBKR IRA has *two* lot sets — never
one. Combining them would produce a wrong cost basis for tax reporting.

**Recommendation**: ROOT view shows aggregate qty + qty-weighted avg cost
(already does), but the Holding Detail slide-over for a ROOT-aggregated
position must show **lots grouped by sub-portfolio**, with a header
"Lots are scoped to the account that opened them". One section per
sub-portfolio; never a single FIFO list.

#### 3.3.4 Performance — TWR with multi-account cash flows

A household with two accounts has different cash-flow histories per
account. TWR must:
- Time-weight returns within each sub-portfolio.
- Then dollar-weight (or value-weight) at the ROOT level.

The naive approach (`(end_value - start_value) / start_value`) breaks
when an account is funded mid-period.

**Today's snapshot aggregator** (`_aggregate_root_portfolios`) sums
end-of-day values — so ROOT TWR computed from its snapshot series is
**already** dollar-weighted, since deposits add to value the same day they
clear. This is the correct method for a household view. Document the math
in the eventual `/portfolios/{id}/twr` endpoint.

#### 3.3.5 Multi-tenancy — verified safe

`list_non_root_active_ids_by_owner(owner_id, tenant_id)` filters by
**both** owner_id AND tenant_id. RULES.md §9 (no cross-service DB access)
is honoured — every read is via the portfolio service. Manual audit of
`GetHoldingsUseCase` / `GetExposureUseCase` / `ListTransactionsUseCase`:
all three call the tenant-scoped variant. No leak found.

**Reinforcement test (proposed)**: an integration test that creates two
users in two tenants with the same instrument, aggregates one, asserts
the other's holding is NOT in the response.

#### 3.3.6 Frontend query strategy

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. One key per portfolio (current) | `qk.portfolios.holdings(portfolioId)` — ROOT is just another id. | Trivial. Already shipped. | When the user switches portfolio, every dependent query refetches. |
| B. One new key `qk.portfolios.aggregated()` | Dedicated query that always returns ROOT. | Stable cache across portfolio switches for the dashboard. | Diverges from the per-portfolio path on the `/portfolio` page. |
| C. Hybrid — A for the page, A+staleTime extension for ROOT on dashboard | `qk.portfolios.holdings(rootId)` with longer staleTime (5 min) on the dashboard than on the page (30 s). | Same cache, different freshness. | Slightly complex. |

**Recommendation: A**. ROOT id is stable per user (auto-provisioned),
so `qk.portfolios.holdings(rootId)` lives across navigation. No new key
needed.

### 3.4 Aggregated view contract (proposed endpoint shape)

The user asked specifically: "what's the exact shape if we go this
direction?". Since the rails already exist, the right shape is
**use the existing `/portfolios/{id}` endpoint with the ROOT id**,
NOT a new `/v1/portfolios/aggregated` endpoint. Adding `/aggregated`
would create two paths for the same data.

If a discovery alias is desired for the frontend:

```http
GET /v1/portfolios/aggregated
→ 302 Location: /v1/portfolios/{root_portfolio_id}
```

Or — cleaner — a new helper endpoint that returns just the id:

```http
GET /v1/portfolios/root
→ 200 { "portfolio_id": "<uuid>", "kind": "root" }
```

So the frontend can:

```ts
const { portfolio_id: rootId } = await gateway.getRootPortfolio();
const root = useQuery(qk.portfolios.holdings(rootId));
```

#### 3.4.1 Existing field schema (no change needed)

All endpoints below already accept the ROOT id and route through the
ROOT branch. Schemas are unchanged from the per-portfolio response —
which is the entire point: **the ROOT view is a portfolio, not a
side-feature**.

| Endpoint | Response | ROOT-aware? |
|----------|----------|-------------|
| `GET /v1/portfolios/{id}` | `Portfolio` (id, name, kind, owner_id, base_currency, created_at) | yes — `kind="root"` |
| `GET /v1/portfolios/{id}/holdings` | `Holding[]` (instrument_id, ticker, name, quantity, average_cost) | yes — collapsed by instrument |
| `GET /v1/portfolios/{id}/exposure` | `{ invested, cash, gross_exposure_pct, net_exposure_pct, leverage, prices_stale, prices_as_of }` | yes — summed |
| `GET /v1/portfolios/{id}/value-history?period=…` | `{ points: [{date, value, cash}] }` | yes — reads ROOT snapshots |
| `GET /v1/portfolios/{id}/transactions` | `{ items: EnrichedTransaction[], total }` | yes — UNION newest-first |
| `GET /v1/portfolios/{id}/risk-metrics` | `{ sharpe, sortino, vol, drawdown_max, beta, data_quality }` | **NO — gap (§2.7)** |
| `GET /v1/portfolios/{id}/realized-pnl` | `{ total, st, lt, per_instrument }` | yes — sums sub-portfolio lots |
| `GET /v1/portfolios/{id}/concentration` | `{ hhi, top_n, weights }` | yes — recomputed on aggregated holdings |
| `GET /v1/portfolios/{id}/performance` | `{ calmar, win_rate, drawdown_current }` | yes — reads ROOT snapshots |
| `GET /v1/portfolios/{id}/top-movers?period=…` | (proposed §2.6) | new — must implement ROOT branch |
| `GET /v1/portfolios/{id}/twr?period=…&benchmark=…` | (proposed §2.19) | new — must implement ROOT branch |
| `GET /v1/portfolios/{id}/attribution?period=…` | (proposed §2.19) | new — must implement ROOT branch |

#### 3.4.2 How holdings from different sub-portfolios merge

(Verified in `list_by_portfolio_ids_aggregated_enriched` docstring.)

For instrument_id = NVDA across portfolios A and B:

```
A: 100 NVDA @ $400 avg
B:  50 NVDA @ $450 avg

ROOT row for NVDA:
  quantity = 100 + 50 = 150
  average_cost = (100*400 + 50*450) / 150 = $416.67
  portfolio_id = A.portfolio_id (first one seen; aggregated rows are read-only)
  id = synthesized (never persisted)
```

**Caveat**: if A is USD and B is EUR, the average_cost is mathematically
wrong because $400 and €450 are summed as if same unit. **This is the
v1 currency caveat** (§3.3.2). For v1 we document the limitation; v1.1
adds FX normalisation.

#### 3.4.3 How transactions are reconstructed for analytics

ROOT transactions = UNION of sub-portfolio transactions, sorted by
`executed_at DESC`. **No deduplication** — each original tx row is
preserved. The user sees an account column (proposed `04-` Class +
Brokerage column) telling them which sub-portfolio each row came from.

For realised P&L (FIFO), the use case iterates sub-portfolio tx histories
**independently** then sums the per-sub-portfolio realised totals. This
keeps tax-lot ordering deterministic per account (§3.3.3).

#### 3.4.4 What is "Day P&L" for an aggregated view

**Definition**: sum of per-position day deltas in base currency, where
`day_delta = quantity × (last_price - prev_close_price)`.

This is a **weighted sum** (every position contributes its raw $ delta),
not an unweighted average. Matches Bloomberg PORT (`DTD P&L` column total)
and IBKR Mosaic (account `Day P&L` field).

For ROOT: same formula run over the **aggregated** holdings table:

```python
day_pnl_root = sum(
    h.quantity * (quote[h.instrument_id].last - quote[h.instrument_id].prev_close)
    for h in aggregated_holdings
)
day_pnl_pct_root = day_pnl_root / nlv_at_prev_close
```

Currency caveat applies; v1 ships USD-only.

---

## 4. Cross-OQ implications matrix

The aggregated-view decision forces or constrains several other choices:

| Constraint trigger | Affected OQ | Implication |
|--------------------|-------------|-------------|
| ROOT must aggregate snapshots correctly | 03-OQ2 (risk metrics), 03-OQ1 (top movers), 04-OQ6 (attribution) | All three need a ROOT branch in the corresponding use case — not just a frontend tweak. |
| Multi-currency in households | 03-OQ3 (currency exposure), 03-OQ5 / 04-OQ1 (benchmark) | Currency exposure becomes a first-class strip; benchmark needs to be dominant-currency-aware (long-term) or user-selectable (short-term). |
| ROOT default rules out "fake demo" pattern | 02-OQ2 (no-brokerage state), 03-OQ9 (empty state copy) | Demo data is delivered through real ROOT aggregation of the seeded Demo sub-portfolio. Empty state is only for sub-portfolio drill-downs. |
| ROOT view is multi-account by definition | 02-OQ3 (Day P&L pre-market), 04-OQ5 (running balance) | Day P&L formula must be a weighted sum, not an average. Running balance must be a merged stream across accounts; or scoped to a single sub-portfolio when the user drills in. |
| ROOT lots vary by sub-portfolio | 04-OQ3 (holding contribution chart series) | Lots panel groups by sub-portfolio. Contribution chart still works (it's contribution-to-portfolio at the ROOT level). |
| ROOT can't accept writes | All write-related flows | Add-position dialog from ROOT prompts the user "Which sub-portfolio?" with a dropdown. RecordTransaction guard already throws. |
| ROOT is the default | 02-OQ1 (default portfolio), 02-OQ5 (mobile collapse), 03-OQ6 (chart height), 03-OQ8 (period chip duplication) | Layout decisions assume ROOT is the page-load state. |

---

## 5. Recommended decisions (clean list)

| # | OQ | Decision | Rationale | Migration cost |
|---|----|----------|-----------|----------------|
| 1 | 02-OQ1 | **Default = ROOT**; persist non-ROOT selection in localStorage + URL `?portfolio=…` | Matches user anchor; uses already-shipped backend; consistent across dashboard widget + portfolio page. | None backend; ~50 LOC frontend hook unification. |
| 2 | 02-OQ2 | **ROOT always populated**; topbar banner "Demo — connect a brokerage" when 0 brokerage connections | Removes demo/CTA dichotomy. ROOT view always has the seeded Demo. | None backend; 1 banner component (~30 LOC). |
| 3 | 02-OQ3 | **Adaptive label** ("since prev close" pre-market, "intraday" RTH); same number | Cheap; reduces confusion. Future-flag for session-aware backend split. | None v1; ~20 LOC hook + tooltip. |
| 4 | 02-OQ5 | **Two-row stack `< lg`**: KPI strip → positions table → sparkline | Preserves user's "always show positions" requirement on phone. | None backend; ~40 LOC CSS in `TopOfPortfolio`. |
| 5 | 02-OQ7 | **Left-rail border** (3px `border-l-primary`) | Bloomberg authentic; removes 6px of yellow chrome. | None backend; 1-line CSS in `MorningBriefCard`. |
| 6 | 03-OQ1 | **Client-side derivation for v1, 1D-only**; backlog new `/top-movers?period=…` endpoint w/ ROOT branch | Ship overview now; perfect attribution later. | v1: 0 backend. v1.1: ~200 LOC backend + tests. |
| 7 | 03-OQ2 | **Add ROOT branch to `GetRiskMetricsUseCase`** so risk-metrics works on ROOT | One-line `if kind == ROOT` — cheap and removes a major hole. | ~40 LOC backend + 2 tests. |
| 8 | 03-OQ3 | **Top-3 inline + `+N more` popover** | Bounded chrome; honest about household currency mix. | ~100 LOC frontend; no backend (already computable). |
| 9 | 03-OQ5 & 04-OQ1 | **User-selectable benchmark**, default SPY; new nullable `portfolios.benchmark_ticker` column | Future-proofs non-US books. Persisted per portfolio (ROOT and sub each have one). | 1 Alembic migration; ~100 LOC `UpdatePortfolioUseCase`; ~60 LOC dropdown + S3 series proxy. |
| 10 | 03-OQ6 | **Collapsible perf chart**: 120 px default, expandable to 240 px (localStorage) | Best of both heights. | ~60 LOC `PerformanceChartPanel`. |
| 11 | 03-OQ7 | **Single SVG `<path>` per sparkline**; bench on 100-position book | Lowest DOM cost. Already proposed. | None new (part of `03-` impl). |
| 12 | 03-OQ8 | **Chip locked to chart period** | Aligns two surfaces; tolerates 1D duplication. | ~20 LOC frontend state lift. |
| 13 | 03-OQ9 | **No "all-empty" state** (ROOT always populated); sub-portfolio empty state offers "Switch to All Accounts" | Eliminates the trickiest empty state. | ~30 LOC empty-state component. |
| 14 | 04-OQ2 | **Colour excess by sign** with header tooltip | Familiar visual hierarchy. | None backend; 1 column-config update. |
| 15 | 04-OQ3 | **Contribution-to-portfolio** series in mini-chart | The only series that adds value over the instrument page. | None new (part of `04-` impl). |
| 16 | 04-OQ4 | **Native `<input type="date">` pair** | Minimal dependencies; matches existing ledger filter. | None new (part of `04-` impl). |
| 17 | 04-OQ5 | **Client-side running balance with tooltip caveat**; backlog backend support | Ship the column now; right answer later. | None v1; backlog new tx field. |
| 18 | 04-OQ6 | **v1 = simple period attribution** (constant-weight); v1.1 = backend `/attribution` endpoint | Honest about approximation; v1.1 fixes silently. | v1: ~80 LOC frontend; v1.1: ~300 LOC backend + tests. |
| 19 | 04-OQ7 | **Drop `[Import CSV]` CTA** for v1; separate PRD for the importer | Honest scope. | None — remove a button. |
| 20 | 04-OQ8 | **Full-screen modal on `< lg`** | Simplest correct mobile pattern. | ~40 LOC responsive handling. |

---

## 6. Backend additions required (consolidated)

In rough order of leverage / cost ratio:

### v1 (must ship with PRD-0089)

1. **`GetRiskMetricsUseCase` ROOT branch** (~40 LOC + 2 tests)
   - Add `if portfolio.kind == ROOT:` block; read ROOT snapshot series
     (already produced by `_aggregate_root_portfolios`).
2. **`GET /v1/portfolios/root`** (or `?include=root_id` on `/portfolios`)
   - Optional convenience endpoint; frontend can also filter
     `GET /portfolios → kind=="root"` itself. (Discuss with user.)
3. **`portfolios.benchmark_ticker TEXT NULL`** Alembic migration
   - New nullable column; default NULL → frontend reads as "SPY".
   - Extend `PATCH /v1/portfolios/{id}` to accept the field.
   - Wire benchmark series fetch through S9 → S3 (already proxied).
4. **`GetExposureUseCase` currency-mix output field** (~50 LOC)
   - Add `currency_breakdown: list[{currency, weight, value_usd}]` to the
     exposure response — needed for the `+N more` currency popover.
   - For now, all assumed USD; field exists for forward-compat.

### v1.1 (next wave after PRD-0089 ships)

5. **`GET /v1/portfolios/{id}/top-movers?period=…&limit=…`**
   - Period-aware top contributors/detractors backed by snapshot history.
   - Must implement ROOT fan-out (read sub-portfolio snapshot series, sum
     contributions per instrument over the window).
6. **`GET /v1/portfolios/{id}/twr?period=…&benchmark=…`**
   - Canonical TWR replacing client-side compute.
   - ROOT branch reads ROOT snapshot series directly.
7. **`GET /v1/portfolios/{id}/attribution?period=…&dimension=holding|sector|asset_class`**
   - Backs the Analytics tab attribution table.
   - ROOT branch fans out then collapses per-instrument.

### v2 (longer horizon)

8. **Currency normalisation in `list_by_portfolio_ids_aggregated_enriched`**
   - Convert `quantity * average_cost` to a canonical currency at SQL time
     using `FxRate.latest_for(currency, target_currency=USD)` join.
   - Required before launching non-USD brokerage accounts.
9. **Running balance field on transactions response** (`?include=running_balance`)
   - Backend reconstructs from snapshots + corporate actions; replaces
     the client-side caveat.
10. **Session-aware Day P&L** in `/v1/quotes/batch` (intraday open field).
11. **Custom benchmark ticker** (extends OQ5/04-OQ1 — instead of a curated
    list, let users type any ticker; backend validates it exists in S3).

---

## 7. Open follow-up questions for the user

Resolved-by-design above; the remaining items truly need your input:

1. **Naming of the ROOT portfolio in the UI.** The backend calls it "Root".
   The frontend currently shows it as the user's default-named portfolio
   (e.g. "My Portfolio"). Proposed display name: **"All Accounts (USD)"** —
   or, when only one sub-portfolio exists, hide it from the selector and
   only show the sub-portfolio. **Confirm naming preference**:
   - "All Accounts"
   - "Total Portfolio"
   - "Household"
   - "Combined"
   - Other?

2. **ROOT-id discovery.** Do you want:
   - (a) a dedicated `GET /v1/portfolios/root` endpoint, or
   - (b) the frontend filters `kind === "root"` on the existing
     `GET /v1/portfolios` response?
   (b) is what's effectively shipped today; (a) is cleaner.

3. **Benchmark scope for v1.** §2.9 proposes a curated list:
   `{SPY, QQQ, IWM, EFA, AGG, 60/40}`. Confirm or adjust. Should we
   include `BTC-USD`? Or scope to equity-only benchmarks?

4. **Currency policy.** v1 assumes USD-only. If you want non-USD
   support in v1, that bumps backend cost up significantly (FX adapter
   + Holdings.currency join + aggregation rewrite). Recommend v1 = USD-only
   with a UI banner if any sub-portfolio is non-USD. Confirm.

5. **Demo data tagging.** When ROOT aggregates only the Demo sub-portfolio
   (zero brokerage connections), should we display the dashboard widget in
   a slightly muted "DEMO" colour band, or treat it as the same as real
   data? Recommend muted band (`bg-warning/10` on the widget) until the
   user connects a real brokerage.

6. **Mobile design priority.** The cluster has 1 OQ on mobile collapse
   (02-OQ5) and 1 on slide-over (04-OQ8). The hedge-fund-PM persona is
   primarily desktop. Confirm mobile is "must-work, not must-shine".

7. **ROOT exposure currency mix output field.** OQ3 proposes a
   `currency_breakdown` field on the exposure response. Do you want the
   field shipped in v1 (empty/USD-only) or wait until non-USD support
   actually exists?

---

**End of `01-portfolio-model.md`.**

**Sources cited**:
- `docs/designs/0089/02-dashboard.md`
- `docs/designs/0089/03-portfolio-overview.md`
- `docs/designs/0089/04-portfolio-detail.md`
- `services/portfolio/src/portfolio/domain/enums.py`
- `services/portfolio/src/portfolio/application/ports/repositories.py`
- `services/portfolio/src/portfolio/application/use_cases/read_models.py`
- `services/portfolio/src/portfolio/application/use_cases/get_exposure.py`
- `services/portfolio/src/portfolio/application/use_cases/ensure_root_portfolio.py`
- `services/portfolio/src/portfolio/workers/portfolio_snapshot_worker.py`
- `apps/worldview-web/features/portfolio/hooks/usePortfolioData.ts`
- `apps/worldview-web/features/portfolio/components/PortfolioPageHeader.tsx`
- `apps/worldview-web/types/api.ts`
- Bloomberg PORT — `<Equity> PORT <Go>` (Bloomberg Help Desk reference)
- Interactive Brokers TWS Account Window — `https://www.interactivebrokers.com/en/trading/trader-workstation.php`
- Schwab StreetSmart Edge multi-account — `https://www.schwab.com/trading/platforms/streetsmart-edge`
- Fidelity Active Trader Pro — `https://www.fidelity.com/trading/advanced-trading-tools/active-trader-pro`
- Wealthfront household — `https://www.wealthfront.com/`
