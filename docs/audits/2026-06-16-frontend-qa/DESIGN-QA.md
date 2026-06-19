# Frontend Design / Layout QA — Bloomberg-Grade Assessment

- **Date:** 2026-06-18
- **Method:** Visual analysis of 41 full-viewport screenshots (1920×1080 and 1440×900) captured against the deployed production container (`apps/worldview-web`, Next.js 15). Regions cropped + upscaled (Pillow) to read dense data.
- **Reference:** `docs/ui/DESIGN_SYSTEM.md` — target is the dense, dark, finance-grade **"Terminal Dark"** Bloomberg-class aesthetic (#09090B bg, IBM Plex Sans/Mono, Bloomberg yellow #FFD60A primary, teal #26A69A positive / red #EF5350 negative, 22px data rows, 2px radius).
- **Scope:** DESIGN/LAYOUT only. Data-degradation issues (empty graph, 0 catalysts, NL 503) are documented in `FUNCTIONAL-QA.md`; this report only flags them where they create a *visual/layout* problem (e.g. unresolved skeletons, dead columns). **No code was changed.**
- **Severity:** HIGH = breaks the premium-terminal feel or is a visible defect; MED = noticeable polish gap; LOW = nice-to-have refinement.

> **Overall verdict:** The product is already *clearly* in the right aesthetic lane — IBM Plex Mono numbers, teal/red semantics, yellow accent, dense grouped grids, sharp 2px corners, grouped column headers. The **Screener, Portfolio holdings table, Financials grid, and Quote sidebar are genuinely terminal-grade.** What holds it back from feeling Bloomberg-premium are five recurring problems: (1) **empty/dead trend-sparkline columns** everywhere, (2) **huge wasted whitespace** on the right of most grids and on list pages (Watchlists, Alerts, News), (3) **unresolved skeletons** that read as "broken" rather than "loading", (4) **color-semantics overload** — green/red applied to non-directional values (P/E, news counts, ownership %, prediction YES/NO), and (5) **monotonous low-information rows** (Alerts especially). Fixing those would close most of the gap to Bloomberg.

---

## Per-Page Findings

### 1. SCREENER (focus area)

The screener is the strongest surface and is close to terminal-grade. Evidence: `1920-screener-01-default.png`, `02a/02b/02c`, `03`, `04`, `05a/05b` (+ 1440 equivalents).

**What's already excellent:** grouped column-header bands (FUNDAMENTALS / RATIOS / PERFORMANCE / OWNERSHIP / INTELLIGENCE) with yellow group separators; mono tabular numbers; `—` null sentinels used correctly (not 0/blank); CHG% heat cells (green/red tinted backgrounds); preset chip rail with active-yellow state; a polished filter drawer with range sliders + min/max inputs + collapsible groups + pinned APPLY/RESET; a clean column-settings popover with drag-reorder and PINNED Ticker/Name; 52W range mini-bars with position markers. Responsive: at 1440 the full column set and groups survive with no overflow/break.

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| S-1 | **HIGH** | **The "TREND (30d)" sparkline column is empty on every row** — renders as a dotted grey placeholder line, never a sparkline. It is **checked ON by default** in the column popover, so the default grid ships a dead column. A dead column on first paint is the single biggest "this looks broken" signal on the flagship page. | `01-default` right side (all rows dotted); `02c`; popover `02a` shows "Trend (30d)" checked. | Either (a) make the sparkline actually render (batch `POST /v1/quotes/bars/batch`, per §6.5e) before shipping it on by default, or (b) **default Trend OFF** until data is wired. Never ship an empty default column. Empty-state should be a faint flat baseline, not a dotted "loading" line that never resolves. |
| S-2 | **HIGH** | **Large dead whitespace on the right of the default grid.** With the default column set, the grid stops at ~TREND and leaves ~35–40% of the viewport black. Bloomberg fills width. | `01-default` (whole right third empty). | Default to a richer column set (the L3/L4/L5 columns the FUNCTIONAL audit confirmed work — 1M/3M RTN, Analyst Tgt, Inst Own%, Brief Score), OR add a right-side summary/detail rail (selected-row mini-profile, sector distribution of the result set, applied-filter recap). Empty black canvas next to a data grid is the most "unfinished" look in the app. |
| S-3 | MED | **NEWS 7D and BRIEF SCORE rendered in positive-green regardless of value** (e.g. `336`, `65`, `16`, `0.84` all teal-green). Green = "up/bullish" in the rest of the app; a neutral count colored green miscommunicates. | `01-default`, `02c` INTELLIGENCE columns. | Render counts/scores in `text-foreground` (neutral). If you want emphasis, use a single accent (yellow) for the *highest* values or a subtle heat ramp keyed to percentile — but do not reuse the bull/bear green. |
| S-4 | MED | **BETA colored yellow at high values** (2.20, 1.80, 1.66 in amber; 1.09/1.24 neutral). Yellow is the brand/primary/active color; using it as a "high beta" heat signal collides with active-state yellow and reads ambiguously. | `01-default` left grid, `02c`. | Use a dedicated heat token (e.g. warning-amber is already a semantic token, but it's near-identical to primary). Better: keep beta neutral and reserve color for directional/return columns only. |
| S-5 | MED | **Two columns both truncate to "ANALYST …"** when the Analyst group is on — indistinguishable headers (Analyst Target vs Analyst Upside). | `02c` header row. | Use distinct short labels: `TGT $` and `UPSIDE %`. The popover already calls them "Analyst Tgt" / "Analyst Upside" — mirror those, don't truncate both to the group word. |
| S-6 | MED | **Empty-state inconsistency on Live Catalysts.** The styled "SCREENER 0 MATCH / Adjust filters and apply" empty state was expected, but the screenshot shows AG Grid's **generic built-in "No Rows To Show"** centered in the grid body (header bands still visible above it). Two different empty-state treatments = inconsistent. | `04-live-catalysts` ("No Rows To Show"). | Supply a custom `noRowsOverlayComponent` matching the design-system EmptyState (§6.6): icon + "No instruments match this screen" + a "Clear filters" affordance. Never let AG Grid's default chrome show through. |
| S-7 | LOW | **NL-search error is bare red text** under the input ("…couldn't translate that screen — NL screener not configured (missing API key)") with no icon, border, or container — looks like a console error, not a designed state. | `05b-nl-result`. | Wrap in the shadcn `Alert` (destructive variant) or an inline pill with an `AlertTriangle` icon, per §6.7. (Backend 503 is a config issue — FUNCTIONAL-QA — but the *presentation* is a design gap.) |
| S-8 | LOW | **CHG% shows `-0.00%`** for flat rows (AAPL). A signed zero reads as a defect. | `01-default`, `05b` (Apple `-0.09%`/`-0.00%`). | Normalize `-0.00` → `0.00` (or `—`/`flat`) and render flat values in neutral color, not red. |
| S-9 | LOW | **52W RANGE bars are visually truncated** — the bar track is cut off before the right column edge, so the high-end marker can sit at/over the boundary. | `02c`, `01-default` right. | Give the 52W column a fixed comfortable width and inset the track with a few px of padding so low/high markers never touch the cell border. |

---

### 2. DASHBOARD

Evidence: `1920-dashboard.png`, `1440-dashboard.png`. The dashboard is impressively dense (Market Clock, Breadth, Sector Performance heat tiles, Portfolio, Top Positions, Prediction Markets, News Momentum, Economic + Earnings calendars). This is the most Bloomberg-like page when populated.

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| D-1 | **HIGH** | **Three top panels are stuck on skeletons that never resolve:** MORNING BRIEFING (grey bars inside a yellow-bordered frame), MARKET SNAPSHOT ("loading…" grey bars), and NEWS MOMENTUM (1920 pass). A page whose hero row is three loading blocks reads as broken on first impression. | `1920-dashboard` top band; `d_brief` crop (skeleton bars + "changes/Discuss/Read more"); MARKET SNAPSHOT "loading…". | These are data/timing issues (FUNCTIONAL) but the *design* fix is: skeletons must time out to an EmptyState/ErrorCard with retry (§6.1) rather than spinning forever. Per §6.2 skeletons are static — but a static skeleton that never resolves is worse than an explicit "Briefing unavailable — Retry". Add a max-wait → empty/error transition. |
| D-2 | MED | **Crypto/long tickers wrap to two lines in the Gainers/Top-Positions lists** ("AAVE-USD", "FIL-USD", "USD-…") breaking the fixed row rhythm and creating ragged rows. | `d_tr` crop (GAINERS), `1920-dashboard`. | Truncate symbol with ellipsis + tooltip, or reserve a wider symbol column; never let a symbol wrap inside a fixed-height data row. |
| D-3 | MED | **NEWS MOMENTUM shows implausible magnitudes** ("+1100%", "+1700%") rendered as green deltas. Even if real, an unformatted four-digit percent reads as a formatting bug and dominates the eye. | `d1440` NEWS MOMENTUM column. | Cap/abbreviate extreme values (`>999% → "999%+"`), or switch the metric to a bounded score; ensure the column has a clear unit header. |
| D-4 | LOW | Top Positions and similar widgets carry the same **empty dotted sparkline placeholder** as the screener (S-1). | `d_tl` TOP POSITIONS. | Same fix as S-1 — render or hide. |
| D-5 | LOW | Sector Performance heat tiles are good, but the **3×8-ish tile grid + the 1D/1W/1M toggle** sit a touch loose; tiles could be 1px tighter to match the calendar density below. | `d_tr` SECTOR PERFORMANCE. | Minor: reduce tile gap to `gap-px`/`gap-0.5` for true Finviz density. |

---

### 3. PORTFOLIO

Evidence: `1920-portfolio.png`, `1440-portfolio.png`. KPI strip, allocation donut, Market/Sector exposure, TWR-vs-SPY, and a genuinely excellent holdings table (real green/red sparklines, heat-tinted LAST/MKT VALUE cells, mono numbers, day/unreal P&L coloring).

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| P-1 | **HIGH** | **Two holdings rows visually overlap / collide** — "Netflix Inc." and "Tesla Inc." text superimpose ("Vetsflxn Inc.", "$6$618.24" double-drawn), and the row heights look inconsistent there. This is a real rendering defect, not data. | `p_hold` crop (rows 4–6). | Investigate the holdings table row virtualization/row-height (likely a duplicate/zero-height row or a sparkline canvas overflowing its row box). Enforce a fixed `--data-row-height` and `overflow-hidden` per cell. HIGH because overlapping text is the most obviously "broken" thing in the whole audit. |
| P-2 | MED | **SECTOR column is `—` for every holding** while the SECTOR EXPOSURE panel above clearly knows each holding's sector. Inconsistent — the table looks data-broken next to a working panel. | `p_hold` SECTOR col; `p_top` SECTOR EXPOSURE has values. | Wire the per-row sector from the same source the exposure panel uses. (Data gap, but the *visual* inconsistency is the design problem.) |
| P-3 | MED | **PERFORMANCE — TWR vs SPY shows `—` for every benchmark cell** ("SPY —" at 1D/1W/1M/3M). The panel renders a comparison with no comparison. | `p_top` PERFORMANCE panel. | If benchmark is unavailable, collapse to a single TWR column with an EmptyState note ("Benchmark unavailable") rather than a column of dashes that implies missing data per-row. |
| P-4 | LOW | KPI strip mixes `$0.00` (CASH, BUYING PWR), `—` (REALIZED P&L), and `+100.00%` (NET, B-ADJ). `+100.00%` for a fully-invested book is technically right but visually noisy; `$0.00` vs `—` inconsistency between "real zero" and "no data". | `p_top` KPI strip. | Standardize: true zero = `0.00`, unknown = `—`. Consider hiding NET/B-ADJ when they're trivially 100%. |

---

### 4. INSTRUMENT — QUOTE tab

Evidence: `1920-instrument-AAPL-quote.png`, `q_side` crop. **Terminal-grade.** Candlestick + volume chart (TradingView), drawing palette, dense right-side STATISTICS sidebar (VALUATION / PROFITABILITY / LEVERAGE & YIELD / 52-WEEK RANGE / OWNERSHIP) with grouped yellow-accent headers, mono numbers, semantic colors, 52W slider. Header quote row is excellent.

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| Q-1 | MED | **Color-semantics overload in the stats sidebar:** P/E `35.47` and FWD P/E `32.79` are colored (red/amber) as if "expensive = bad/bearish"; EPS TTM `8.26` green. Valuation multiples are not directional — reusing bull/bear red/green on them dilutes the meaning of red/green for actual price/return changes. | `q_side` VALUATION block. | Reserve teal/red strictly for directional values (price change, returns, P&L). Render multiples in `text-foreground`; if you want valuation context, use a separate subtle "cheap/rich vs sector" indicator, not the P&L palette. |
| Q-2 | LOW | Header micro-stats show `B×A —×—` (bid/ask empty) and `VOL 6K` (implausibly low). Cosmetically these read as data holes in an otherwise crisp header. | `1920-...-intelligence` header crop (same header). | If bid/ask unavailable, drop the `B×A` chip rather than showing `—×—`; sanity-format volume. |

---

### 5. INSTRUMENT — FINANCIALS tab

Evidence: `1920-instrument-AAPL-financials.png`, `f_grid`, `f_band`. Strong dense grid: top metric strip + grouped sections (VALUATION / PROFITABILITY / GROWTH / BALANCE SHEET / CASH FLOW / DIVIDENDS / OWNERSHIP / TECHNICALS) each with a yellow accent bar.

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| F-1 | **HIGH** | **An unresolved skeleton band sits below TECHNICALS** — a header skeleton bar + ~6 full-width grey skeleton rows that never load (likely a peers/earnings sub-panel). It's a large grey slab mid-page that reads as broken. | `f_band` crop (skeleton rows after TECHNICALS). | Same as D-1: skeleton must transition to EmptyState/Error after a timeout. If the sub-panel has no data for this deployment, render the empty state, not perpetual skeleton. |
| F-2 | MED | **Same P/E-colored-red valuation issue as Q-1** in the top metric strip (P/E `35.47x` red, FWD P/E `32.79x` amber). | `f_grid` top strip. | Same fix as Q-1 — neutral color for non-directional multiples. |
| F-3 | LOW | **Ownership/insider percentages carry `+` signs** (e.g. `% INSTIT +65.35%`, `% INSIDERS +1.64%`) implying a positive *change* when they're absolute levels. | `f_band` OWNERSHIP. | Drop the `+` prefix on absolute ratios; reserve `+/-` for deltas. |

---

### 6. INSTRUMENT — INTELLIGENCE tab

Evidence: `1920-instrument-AAPL-intelligence.png` (rendered at full clarity). **DEGRADED & visually the emptiest page in the app.**

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| I-1 | **HIGH** | **~75% of the page is empty black.** DOSSIER rail = skeleton; central entity-graph canvas = empty ("Select a node or edge to inspect"); NEWS rail = blank; EVENTS rail = skeleton; INSPECTOR = empty. The DEPTH slider + TYPE filter sit above a void. Even accounting for the data gap (FUNCTIONAL: graph empty for AAPL), the layout has no graceful degraded state. | `1920-...-intelligence` (full). | (a) When the graph has no data, the canvas should show a designed EmptyState ("No relationship graph available for AAPL yet"), not a bare prompt over black. (b) Skeleton rails must resolve to empty/error states. (c) Consider collapsing the three rails when empty so the page doesn't feel like an abandoned dashboard. |
| I-2 | LOW | The NEWS rail TONE/POS/NEU/NEG header and EVENTS header render even with no content beneath — empty section chrome. | `1920-...-intelligence` right rail. | Hide section headers when their body is empty, or pair with the EmptyState. |

---

### 7. WATCHLISTS

Evidence: `1920-watchlists.png` (full clarity). **Worst space-utilization page in the app.**

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| W-1 | **HIGH** | **A 3-row table floating in ~95% empty black viewport.** NAME / MEMBERS / UPDATED / CREATED with three rows and nothing else — the antithesis of a dense terminal. | `1920-watchlists` (full). | Redesign as a card grid (each watchlist a card with a mini constituent preview: top 3–5 symbols + live quotes + a member sparkline/heat strip), OR a master-detail layout (list left, selected watchlist's holdings table right). Reuse the working sidebar watchlist component (which *does* show AAPL/MSFT/GOOGL with live quotes) inline. |
| W-2 | MED | **MEMBERS = `0` for all three lists** while the sidebar simultaneously shows live members — visibly contradictory. | `1920-watchlists` MEMBERS col + sidebar. | Data fix (FUNCTIONAL `member_count:0`), but visually it makes the page look broken; the redesign in W-1 (showing actual constituents) would also mask/fix the perception. |
| W-3 | LOW | The **TopBar IndexTicker is blank** (skeleton bars) on this load — a resolution race, but it leaves the top chrome looking unfinished. | `1920-watchlists` TopBar. | Index strip should hold its last value or a designed placeholder, not collapse to empty skeleton cells (§6.2 pre-allocates 22×60 cells — confirm that's firing). |

---

### 8. ALERTS

Evidence: `1920-alerts.png`, `al_top` crop. Good chrome (tabs Active/Snoozed/Acknowledged/History, severity filter row with keyboard hints, ACK/ACK ALL), but the list itself is the most monotonous surface.

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| A-1 | **HIGH** | **30 visually identical rows:** every row is `TICKER · GRAPH_CHANGE · MEDIUM signal · …large empty gap… · Nm ago · [ACK ▾]`. No description, no differentiating detail, and a huge horizontal dead zone between "MEDIUM signal" and the timestamp. The eye cannot scan or prioritize. | `al_top` crop; `1920-alerts` full (rows fill the page identically). | Add a one-line alert *body/summary* in the dead horizontal space (what changed — e.g. "5 new edges to NVDA, AMD" — the sidebar ALARMS panel already shows this kind of detail!). Color/iconify the severity dot per level. Group/sort so CRITICAL/HIGH stand out. This single change would transform Alerts from a placeholder list into a usable feed. |
| A-2 | MED | Severity color isn't carried strongly — all rows read the same muted tone despite a `MEDIUM` label. | `al_top`. | Use `SeverityBadge` (design system has it) with the LOW/MED/HIGH/CRITICAL palette, and a left severity stripe per row. |
| A-3 | LOW | The left severity dot is present but tiny and same-color across rows. | `al_top` left edge. | Map dot color to severity token. |

---

### 9. NEWS

Evidence: `1920-news.png`, `n_list`, `n_right`. Dense, clean headline feed with sentiment chips (BULLISH/BEARISH/NEUTRAL with arrows) — good.

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| N-1 | MED | **Every row's relevance badge reads `84`** — identical across all rows. Even if data, a constant badge looks like a hardcoded placeholder and adds no information. | `n_right` crop ("84" on every row). | If scores don't vary, hide the badge; otherwise verify the score wiring. A varying `RelevanceBadge` (the design system has a 0–100 gradient component) would add real scan value. |
| N-2 | MED | **Wide empty middle band** in each news row between the headline and the right-side (source / 84 / time / link) cluster. | `n_list` + `n_right` (gap between). | Pull the metadata cluster left (tighter row), or fill the gap with the ticker chips / an impact sparkline (`ImpactSparkline` exists) so the row earns its width. |
| N-3 | LOW | Source badges are inconsistent (`EODHD` vs `EODHD_TI`) and styled as muted pills — fine, but the variant naming leaks an internal source id. | `n_right`. | Normalize source labels to human names. |

---

### 10. PREDICTION MARKETS

Evidence: `1920-prediction-markets.png`, `pm_list`. Dense table (QUESTION / YES% / 7D / NO% / BID-ASK / CLOSES).

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| PM-1 | MED | **YES% colored red, NO% colored green** (e.g. "Bitcoin $150k … YES 1% red / NO 99% green"). This reuses the bull/bear palette for a non-directional YES/NO probability, which is semantically wrong and confusing (low YES looks "bad/red"). | `pm_list`. | Color by *probability magnitude* (a single neutral or a confidence ramp), or color YES/NO with a distinct, non-P&L pair (e.g. blue/grey). Don't make a 1% probability look like a loss. |
| PM-2 | MED | **7D column is empty/flat** (dotted) on all rows — same dead-sparkline pattern as S-1/D-4. | `pm_list` 7D col. | Render or hide. |
| PM-3 | LOW | Repetitive content (a wall of "… win the 2026 FIFA World Cup?") makes the page look like seed data; not a design defect per se but worth category grouping. | `1920-prediction-markets`. | Group by category (already have ALL/POLITICS/SPORTS/CRYPTO tabs) and/or de-duplicate the question stem ("2026 FIFA World Cup —" as a group header, country as the row). |

---

### 11. CHAT

Evidence: `1920-chat.png`, `ch_mid`. Empty-state is reasonable: centered "Analyst Intelligence" + 4 suggested prompts + yellow "New conversation" CTA; left thread rail with history; right context panel.

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| C-1 | LOW | The center empty-state floats in a very large black canvas; the right context panel is also empty ("Context appears as you chat"). Acceptable, but on a wide monitor it feels sparse. | `ch_mid`, `1920-chat`. | Consider seeding the empty state with a couple of recent-thread cards or portfolio-aware prompt suggestions to fill the space and improve discoverability. |
| C-2 | LOW | Suggested-prompt chips are mono-text in thin outlines — fine, but slightly low-contrast against the black. | `ch_mid`. | Nudge chip border/hover contrast for affordance. |

---

### 12. LOGIN / INDICES

- **Login** (`00-login-page.png`): clean, on-brand; the "Dev Login (no Zitadel)" affordance is appropriate. No design issues.
- **`/indices` bare path** (`1920-indices.png`): renders the app 404 — not a regression (no such route; harness probe). 404 page is clean. No action.

---

## Cross-Cutting / Global Observations

1. **Dead sparkline columns are systemic** (Screener TREND, Dashboard Top Positions, Prediction Markets 7D). They are the most repeated "broken" signal. Global rule: a trend/sparkline column must either render data or not exist — never ship a dotted placeholder as the resting state.
2. **Skeletons that never resolve** (Dashboard Morning Briefing / Market Snapshot / News Momentum, Financials peers band, Intelligence rails, instrument-tab rails). The design system (§6.1/§6.2) mandates the loading→error/empty transition; it isn't firing. Add a max-wait fallback everywhere a skeleton is used.
3. **Color-semantics overload.** Teal/red must mean *direction* (price/return/P&L). Today they also color P/E, FWD P/E, news counts, brief scores, ownership %, and prediction YES/NO. Reclaim red/green for direction only; use neutral/foreground for levels and a distinct ramp for "heat".
4. **Whitespace on the right of grids/lists.** Screener default, Alerts, News, Watchlists all leave large right-side voids. Bloomberg fills width with either more columns or a contextual detail rail. This is the biggest single lever for "feels denser/more premium".
5. **Number-formatting hygiene:** `-0.00%`, `+100.00%`, `+65.35%` (level with a sign), constant `84` relevance, `1100%/1700%` momentum. Tighten formatters: neutralize signed zero, drop `+` on absolute levels, cap extreme magnitudes.
6. **The good news — consistency is largely there:** IBM Plex Mono tabular numbers, `—` null sentinels, grouped headers with yellow separators, 2px corners, heat cells, the filter drawer, the column popover, the Quote/Financials sidebars, and the Portfolio holdings table are all genuinely terminal-grade and should be the template the weaker pages (Watchlists, Alerts) are rebuilt against.
7. **Cookie-consent banner** overlays the bottom ~2 rows of every grid (and the yellow logo arc bleeds behind it). Minor, but on a data terminal it obscures live rows; ensure it's dismissible-once and doesn't cover grid content (or push content up by its height).
8. **Responsive (1920 vs 1440):** No breakage found. The screener keeps all column groups, the dashboard panels reflow, holdings/financials hold. The right-side whitespace shrinks slightly at 1440 (good) but the dead columns/skeletons persist identically. Responsiveness is *not* a problem; density and empty-state handling are.

---

## Top 10 Design Improvements to Feel Bloomberg-Grade

> Ordered by impact-to-effort. Each maps to findings above.

### Global (apply across the app)

1. **Kill every dead sparkline column** — render the trend data (batch bars endpoint) or remove the column from defaults. No dotted placeholders at rest. *(S-1, D-4, PM-2 — HIGH)*
2. **Give skeletons a timeout → EmptyState/ErrorCard transition** so no panel spins forever. A page should never show three perpetual loading blocks. *(D-1, F-1, I-1 — HIGH)*
3. **Reclaim teal/red for direction only.** Recolor P/E, news counts, brief scores, ownership %, and prediction YES/NO to neutral or a distinct heat ramp. This is the highest-signal *cheap* polish — it makes the green/red you *do* show actually mean something. *(S-3, Q-1, F-2, PM-1 — MED, high perceived quality gain)*
4. **Fix number formatting globally:** neutralize `-0.00`, drop `+` on absolute levels (`% INSTIT`), cap extreme percents, and stop rendering constant placeholder scores (`84`). *(S-8, P-4, F-3, N-1, D-3)*
5. **Fill right-side whitespace with a contextual detail rail or richer default columns** on the grid/list pages (Screener, Alerts, News). Bloomberg never leaves a data grid next to a black void. *(S-2, A-1, N-2 — HIGH)*

### Screener-specific (the focus area)

6. **Ship a richer default column set** (the L3/L4/L5 columns are confirmed working: 1M/3M RTN, Analyst Tgt, Inst Own%, Brief Score) so the default grid fills width and shows the platform's intelligence edge immediately — instead of stopping at an empty TREND column. *(S-2)*
7. **Custom no-rows overlay** matching the design-system EmptyState (icon + message + "Clear filters") so Live Catalysts / empty screens never show AG Grid's generic "No Rows To Show". *(S-6)*
8. **Disambiguate the two "ANALYST …" headers** → `TGT $` / `UPSIDE %`, and inset the 52W range track so markers never touch cell edges. *(S-5, S-9)*

### High-value page rebuilds

9. **Rebuild Watchlists from a 3-row table into a constituent-preview card grid (or master-detail).** It's currently 95% empty black — the least terminal-like page in the app. Reuse the working sidebar watchlist component inline. *(W-1 — HIGH)*
10. **Make Alerts rows informative:** add the one-line "what changed" summary (the sidebar ALARMS panel already has this content) into the dead horizontal gap, apply `SeverityBadge` + a left severity stripe, and sort by severity. Turns 30 identical placeholder rows into a real signal feed. *(A-1, A-2 — HIGH)*

---

## Appendix — Evidence Index

| Finding group | Primary screenshots |
|---|---|
| Screener | `1920/1440-screener-01-default`, `02a` (popover), `02c` (all columns), `03` (filters), `04` (catalysts empty), `05b` (NL error) |
| Dashboard | `1920/1440-dashboard` |
| Portfolio | `1920/1440-portfolio` (holdings overlap in rows 4–6) |
| Instrument | `1920-instrument-AAPL-quote` / `-financials` / `-intelligence` |
| Watchlists | `1920-watchlists` |
| Alerts | `1920-alerts` |
| News | `1920-news` |
| Prediction Markets | `1920-prediction-markets` |
| Chat | `1920-chat` |
| Login / 404 | `00-login-page`, `1920-indices` |

*Read-only audit. No source files were modified.*
