# Worldview Frontend — UI/Design Competitive Roadmap

- **Date:** 2026-06-19
- **Author:** Design-strategy audit (read-only; no source/component changes)
- **Method:** Re-captured the live deployed frontend (`http://localhost:3001`, Dev Login, S9 gateway `:8000`) with Playwright at **1920×1080** *after* the 2026-06-18 design-fix round, then analysed the screenshots with vision against finance-terminal standards and the project design system (`docs/ui/DESIGN_SYSTEM.md`). Benchmarked against Bloomberg EQS, Koyfin, S&P Capital IQ and TIKR via web research (sources cited at the end).
- **Evidence:** `docs/audits/2026-06-19-ui-screenshots/` (19 PNGs) — capture script `apps/worldview-web/scripts/qa-capture-0619.mjs`.
- **Baseline:** prior audit `docs/audits/2026-06-16-frontend-qa/DESIGN-QA.md` (its "Top 10 to feel Bloomberg-grade" + per-page findings).
- **Target aesthetic:** "Terminal Dark" — `#09090B` bg, IBM Plex Sans/Mono, Bloomberg yellow `#FFD60A` primary, teal `#26A69A` positive / red `#EF5350` negative, 22px data rows, 2px radius.

> **Overall verdict.** The 2026-06-18 round closed most of the *"this looks broken"* defects and the product now reads as a genuine terminal on its flagship surfaces. **Dashboard, Screener, Portfolio, Quote, Financials, and the Intelligence graph are terminal-grade.** What remains is no longer a quality-of-finish problem on the strong pages — it is (1) a small set of *still-open* polish items (color-semantics on non-directional values, signed `+` on absolute levels, the bare NL error, the empty middle band in News rows), (2) **two weak pages that have not been touched — Watchlists (95% empty) and Alerts (30 identical low-information rows)**, and (3) the gap that actually separates Worldview from Bloomberg/Koyfin: **feature-UX depth** (saved/shareable state surfaced everywhere, peer-percentile conditional formatting, a discoverable ⌘K, cross-entity linking) and the chance to make the platform's **intelligence-native** content (contradictions, briefs, the graph) a first-class visual differentiator the incumbents structurally lack.

---

## 1. Current-State Assessment (post-2026-06-18) — what got fixed, what's still open

Cross-referenced against the prior audit's findings. Evidence files are in `docs/audits/2026-06-19-ui-screenshots/`.

### 1.1 RESOLVED since 2026-06-16 (verified in new screenshots)

| Prior ID | Finding | Status now | Evidence (2026-06-19) |
|---|---|---|---|
| S-1 | Dead dotted "TREND (30d)" column on every screener row | **FIXED** — TREND now renders real green/red sparklines per row | `screener-01-default.png`, `screener-02c-with-columns.png` |
| S-2 | ~35–40% dead black to the right of the default grid | **FIXED** — default + toggled column sets now fill the viewport width | `screener-01-default.png`, `screener-02c-with-columns.png` |
| S-6 | Live Catalysts showed AG-Grid generic "No Rows To Show" (0 matches) | **FIXED (data + state)** — preset now returns **7 real rows**; no generic overlay | `screener-04-live-catalysts.png` (rows after catalysts: 7) |
| D-1 | Dashboard hero row = 3 perpetual skeletons (Morning Briefing / Market Snapshot / News Momentum) | **FIXED** — all three populate (briefing text, `-$71,104.39` snapshot, momentum list) | `dashboard.png` |
| P-1 | Two holdings rows visually overlapped ("Vetsflxn Inc.", double-drawn `$`) | **FIXED** — Netflix/Tesla rows render cleanly with sparklines, fixed row height | `portfolio.png` |
| P-2 | SECTOR column `—` for every holding | **FIXED** — per-row sectors populate (Technology, Communication Services, …) | `portfolio.png` |
| I-1 | Intelligence tab ~75% empty black; graph never rendered | **FIXED** — graph renders at **depth=1** (AAPL hub + ~10 nodes); dossier/news/events rails populate | `instrument-AAPL-intelligence.png` |
| W-3 | TopBar IndexTicker collapsed to empty skeleton | **FIXED** — QQQ/IWM/DIA/VIX/TLT quotes render | `watchlists.png` (TopBar) |
| Q-1 (partial) | FWD P/E colored as if directional | **PARTIAL** — FWD P/E + P/EBITDA now neutral; **P/E still red** (see 1.2) | `instrument-AAPL-quote.png` sidebar |

**Net:** 8 of the prior 10 "Bloomberg-grade" items are materially addressed. The screener — explicitly the focus area — is now the strongest surface end-to-end, and it already ships **Saved Screens** and **Export** chrome (a real Bloomberg/Koyfin parity feature).

### 1.2 STILL OPEN (verified unchanged or only partially addressed)

| Prior ID | Finding | Status | Evidence |
|---|---|---|---|
| **W-1 / W-2** | **Watchlists page = a 3-row table floating in ~92% empty black; MEMBERS=`0` for all three lists** while the sidebar shows live AAPL/MSFT/GOOGL quotes | **OPEN — untouched.** This is now the single least-terminal page in the app. | `watchlists.png` |
| **A-1 / A-2** | **Alerts = ~30 visually identical rows** `TICKER · GRAPH_CHANGE · MEDIUM signal · …large dead gap… · time · ACK`; no "what changed" body; severity uniform | **OPEN — only severity-grouping ("MEDIUM (30)") added.** The dead horizontal zone and low information density remain. | `alerts.png`, crop `_crop_alerts_row.png` |
| **Q-1 / F-2** | Non-directional **valuation multiples still colored** (P/E `35.47` **red**); profitability levels (margins, ROE, ROA) **all green** in the stats sidebar | **PARTIAL** — bull/bear palette still applied to levels, diluting directional red/green | `instrument-AAPL-quote.png` sidebar |
| **S-3** | Intelligence counts/scores (NEWS 7d, BRIEF SCORE) rendered in positive-green regardless of value | **LIKELY OPEN** (counts still teal in the INTELLIGENCE group) | `screener-02c-with-columns.png` |
| **F-3** | Ownership %s carry a `+` sign on an absolute level (`INSIDER OWN +1.64%`, `% INSTIT +65.35%`) | **OPEN** — `+` still prefixes absolute ratios | `instrument-AAPL-quote.png` OWNERSHIP block |
| **S-7** | NL-search failure is **bare red text** ("Couldn't translate that screen — LLM service returned an error"), no icon/border/`Alert` container | **OPEN** (presentation gap; backend is also erroring — see note) | `screener-05b-nl-result.png`, crop `_crop_nl.png` |
| **N-2** | News rows have a wide empty middle band between headline and the right metadata cluster | **OPEN / partial** — rows are dense and sentiment chips vary, but the mid-row gap persists | `news.png`, crop `_crop_news_right.png` |
| **S-8 / P-4** | Number hygiene: signed-zero `-0.00%`, `+100.00%` KPIs | Not re-verified at zoom this pass; treat as **likely open** (cheap to sweep globally) | — |

**Capture caveats (transparency):**
- The **Command Palette (⌘K)** did not open under headless Playwright (`Meta+k`/`Control+k` keypress did not trigger it), so `command-palette.png` shows the dashboard. The palette *exists* and is well-specced (`DESIGN_SYSTEM.md` §6.15: Navigate / Recent Instruments / Instruments / Recent Conversations). Its *discoverability*, not its existence, is the roadmap item (§3).
- A background `502 POST /api/v1/screener/nl-translate` poll appears in every page's console log — it is the NL-translate backend being down (a config/service issue, not a per-page frontend defect). It surfaces visually only on the screener NL box (S-7).
- This pass captured **1920×1080 only** (per scope); the prior audit found no 1440 breakage and that is unlikely to have regressed.

---

## 2. Competitor Benchmark — what makes incumbents feel premium

Concrete, citable affordances the leaders ship, mapped to where Worldview stands.

| Premium affordance | Bloomberg EQS | Koyfin | Capital IQ / TIKR | Worldview today |
|---|---|---|---|---|
| **Saved / reusable screens** | "Saved Screens" recalls prior screening configs by name; "As of" date control | unlimited saved screeners on paid tiers | core to all | **Has it** — SAVED SCREENS in screener header. Extend the pattern app-wide (§3). |
| **Reusable column/table "views"** | EQS "Fields" picker per result set | **"My Views"** — independent column sets reused across watchlists & dashboards | configurable units/decimals/columns | Screener has a column-settings popover; **views are not reusable across surfaces** (watchlist/portfolio don't share a column model). |
| **Custom drag-and-drop dashboards** | launchpad | resizable/draggable widget dashboards (a headline differentiator) | dashboards | Worldview has a `/workspace` (drag-and-drop) — surface it more prominently. |
| **Peer / percentile context on metrics** | EQS example screens rank vs weighted peer-group averages | correlation analysis, peer comps | peer comps | **Missing** — metrics are absolute; no "cheap/rich vs sector" percentile cue (this is the upgrade path for the P/E-color problem, §3). |
| **Heatmaps & color-coded performance** | sector/market heatmaps | dashboard heatmaps, color-coded performance | — | Dashboard has sector heat tiles + heat cells. Strong. |
| **Command palette / keyboard-first nav** | terminal mnemonics (EQS, DES, GP) | — | — | **Has ⌘K + g-chords** — ahead of Koyfin/TIKR here; needs discoverability + on-grid actions (§3). |
| **Density modes** | terminal density is the default | view-level density | configurable decimals | Worldview ships a density toggle (cookie copy references it) — good. |
| **Premium polish: charting templates, sharing, downloads** | — | chart templates, sharing, chart/table downloads | interactive tables | Quote chart is TradingView-grade with a drawing palette; **sharing a screen/chart by URL is the gap.** |

**Reading of the field.** TIKR is repeatedly described as having "all the right data … [but] a frustratingly clunky UI"; Koyfin wins on *customization, portability and polish* (custom dashboards, My Views, mobile sync) rather than more data. The lesson for Worldview: it has **already cleared the data-density bar** that TIKR struggles with, and it already ships two things Koyfin/TIKR don't (a real ⌘K command palette and an LLM-native intelligence layer). The premium gap is now **reusable/shareable state + conditional-formatting context + finishing the two weak pages** — plus leaning into the intelligence layer as the thing none of the incumbents have.

---

## 3. Prioritized Roadmap

Each item: **surface · concrete change · impact (HIGH/MED/LOW) · effort (S/M/L) · type (Table-stakes | Differentiator)**.

### (a) Quick professional-polish wins (cheap, high perceived-quality return)

| # | Surface | Concrete change | Impact | Effort | Type |
|---|---|---|---|---|---|
| A1 | Global (Quote/Financials/Screener stats) | **Reclaim teal/red for direction only.** Render non-directional levels — P/E, FWD P/E, margins, ROE/ROA, ownership %, brief scores, news counts — in `text-foreground`. Reserve red/green strictly for price change / returns / P&L. | HIGH | S | Table-stakes |
| A2 | Global formatters | **Number hygiene sweep:** drop the `+` prefix on absolute levels (`INSIDER OWN 1.64%`), neutralize signed-zero (`-0.00%` → `0.00%` neutral), cap extreme percents (`>999% → 999%+`). One shared formatter util. | MED | S | Table-stakes |
| A3 | Screener NL box | **Wrap the NL failure in the design-system `Alert` (destructive)** with an `AlertTriangle` icon + border (§6.7) instead of bare red text. (Also fix the backend `502 nl-translate`.) | MED | S | Table-stakes |
| A4 | News feed | **Earn the row width:** pull the metadata cluster (source/score/time/link) left or fill the mid-row gap with ticker chips / an `ImpactSparkline` so each row uses its width. | MED | M | Table-stakes |
| A5 | Quote header | Drop empty `B×A —×—` chip when bid/ask is unavailable; sanity-format volume (the `VOL 6K` hole). | LOW | S | Table-stakes |
| A6 | Screener headers | Disambiguate the two "ANALYST …" headers → `TGT $` / `UPSIDE %`; inset the 52W-range track a few px so markers never touch the cell edge. | LOW | S | Table-stakes |
| A7 | Cookie banner | Ensure the consent banner is dismiss-once and never overlaps the bottom grid rows (it currently sits over the last ~2 rows on dense pages). | LOW | S | Table-stakes |

### (b) High-leverage feature-UX (closes the gap to Koyfin/Capital IQ)

| # | Surface | Concrete change | Impact | Effort | Type |
|---|---|---|---|---|---|
| B1 | **Watchlists (rebuild)** | Replace the 3-row table with a **constituent-preview card grid OR master-detail** (list left, selected list's holdings table right). Reuse the working sidebar watchlist component inline (it already shows live quotes). Fix MEMBERS=0. **This page is the worst-looking surface in the app today.** | HIGH | L | Table-stakes |
| B2 | **Alerts (rebuild rows)** | Put a one-line **"what changed" body** in the dead horizontal gap (the sidebar ALARMS panel already has this content: "META — graph update: 5 new edges…"). Apply `SeverityBadge` + a left severity stripe; sort/group CRITICAL→LOW. Turns 30 identical rows into a scannable feed. | HIGH | M | Table-stakes |
| B3 | Screener / tables | **Peer-percentile conditional formatting.** Add an opt-in heat ramp keyed to *percentile within the result set / sector* for valuation & quality columns. This is the *correct* fix for A1's P/E problem — context, not bull/bear color — and is a headline Bloomberg/Koyfin affordance. | HIGH | M | Differentiator |
| B4 | Global shell | **Make ⌘K discoverable** (the palette already exists): persistent `⌘K` hint chip in the TopBar, a first-run nudge, and ensure it lists Navigate + Recent Instruments + Conversations + **screen/page actions**. Worldview is already ahead of Koyfin/TIKR here — advertise it. | MED | S | Differentiator |
| B5 | Screener / Quote / Chart | **Shareable, URL-encoded state.** Make a screen / chart layout / instrument view shareable by URL (Koyfin sells "sharing + downloads"). Pairs with the existing Saved Screens. | MED | M | Table-stakes |
| B6 | Watchlist + Portfolio + Screener | **Reusable column "Views"** (Koyfin "My Views"): one column-model definition reused across the three table surfaces, persisted in localStorage. | MED | M | Differentiator |
| B7 | Global | **Cross-entity linking.** Every ticker / entity / sector chip (in News, Alerts, Holdings, the graph) becomes a click-through to the instrument page or a screener-prefiltered view. Bloomberg's "everything is a link" feel. | MED | M | Table-stakes |
| B8 | Tables | **Alert-on-screen / row actions.** Right-click or hover-row affordance to "Create alert from this row" / "Add to watchlist" / "Open in chat". Bloomberg-style on-grid actions. | MED | M | Differentiator |

### (c) Intelligence-native differentiators (what Bloomberg/Koyfin structurally lack)

| # | Surface | Concrete change | Impact | Effort | Type |
|---|---|---|---|---|---|
| C1 | Dashboard / Instrument / new "Signals" rail | **Surface contradictions as a first-class visual element.** The pipeline now flows real contradictions — render them as a dedicated card ("Conflicting signals on AAPL: analyst upgrades vs. negative supply-chain news") with the two sources side-by-side. No incumbent has this. | HIGH | M | **Differentiator** |
| C2 | Instrument Intelligence tab | Now that the graph renders at depth=1, **make the empty/degraded states designed** (EmptyState for tickers with no graph), and add **node→instrument cross-links** and an "explain this edge" → chat handoff. Lean into the graph as the signature surface. | MED | M | **Differentiator** |
| C3 | Morning Briefing (dashboard) | Promote the AI brief from a text block to a **structured, cited brief** (bulleted catalysts each linking to source article + affected ticker + impact window). Make the LLM layer *visibly* the product. | MED | M | **Differentiator** |
| C4 | Chat empty-state | Seed the large empty canvas with **portfolio-aware prompt cards** + recent-thread cards (discoverability + fills the void). | LOW | S | Differentiator |
| C5 | Across surfaces | Consistent **"Discuss in chat" affordance** on any data object (holding, alert, news item, screener row) → opens chat pre-seeded with that context. Ties the intelligence layer to every surface. | MED | M | **Differentiator** |

---

## 4. TOP 8 to do next (opinionated)

Ordered by impact-to-effort, biased toward closing the *visible* gap fast then pulling ahead on the differentiator.

1. **A1 — Reclaim teal/red for direction only.** (HIGH / S) The single cheapest credibility win. Today red on a P/E and green on a margin actively *miscommunicate* and dilute the directional colors that matter. One sweep across the stats sidebar, financials strip, and intelligence columns.
2. **B2 — Make Alerts rows informative.** (HIGH / M) The "what changed" body content already exists in the sidebar ALARMS panel; moving it into the alerts row + `SeverityBadge` + severity sort converts 30 placeholder rows into the app's most useful feed.
3. **B1 — Rebuild Watchlists.** (HIGH / L) It is now the worst-looking page in the app and the only one that still reads as "unfinished." Master-detail or card-grid reusing the working sidebar component.
4. **C1 — Surface contradictions as first-class cards.** (HIGH / M) This is the differentiator no incumbent has, and the data now flows. It is the single highest-leverage way to make Worldview feel like *more* than a Koyfin clone.
5. **B3 — Peer-percentile conditional formatting.** (HIGH / M) The *right* answer to the valuation-color problem and a headline Bloomberg/Koyfin affordance — context-aware heat instead of bull/bear color.
6. **A2 + A3 — Number-hygiene sweep + NL error in an `Alert`.** (MED / S) Bundle the cheap formatter fixes (drop `+` on levels, neutralize signed-zero, cap extremes) with wrapping the NL failure in a proper `Alert`. A half-day that removes the last "looks like a bug" tells.
7. **B4 — Make ⌘K discoverable.** (MED / S) Worldview already ships a real command palette — ahead of Koyfin/TIKR. A persistent `⌘K` chip + first-run nudge turns an invisible asset into a premium signal for nearly free.
8. **C3 — Cited, structured Morning Briefing.** (MED / M) Turn the brief from prose into linked, cited catalysts. Makes the LLM layer visibly the product on the very first screen the user sees.

> **Strategic note.** Items 1, 2, 3, 6 are *table-stakes finishing* — they remove the last reasons a user would say "this looks unfinished." Items 4, 5, 7, 8 are where Worldview stops competing with Koyfin on its own turf and starts competing on the one axis the incumbents can't follow: an intelligence layer (contradictions, cited briefs, the entity graph, chat-on-any-object) surfaced as first-class, beautifully-rendered UI. Do the finishing first (fast, cheap, high-credibility), then ship the differentiators.

---

## Sources

- [Bloomberg EQS / Advanced Company Screening — Business Research Plus](https://bizlib247.wordpress.com/2017/03/31/advanced-company-screening-in-bloomberg-professional/)
- [Using Equity Screening to Identify Growth Ahead of Peers — Bodleian (Oxford)](https://www.bodleian.ox.ac.uk/sites/default/files/bodreader/documents/media/bloomberg-equity-screening.pdf)
- [Bloomberg Terminal Essentials: Best equities functions — Bloomberg Professional Services](https://www.bloomberg.com/professional/insights/technology/bloomberg-terminal-essentials-best-equities-functions/)
- [Koyfin vs TIKR — feature-by-feature comparison (Find My Moat)](https://www.findmymoat.com/vs/koyfin-vs-tikr)
- [Koyfin vs TIKR (2026) Best Research Terminal Comparison — TraderHQ](https://traderhq.com/koyfin-vs-tikr/)
- [Best S&P Capital IQ Alternatives (2026) — Gainify](https://www.gainify.io/blog/best-capital-iq-alternatives)
- [Koyfin — Powerful customizable watchlists](https://www.koyfin.com/features/watchlists/)
- [Koyfin — Powerful customizable dashboards](https://www.koyfin.com/features/custom-dashboards/)
- [Koyfin — My Views for Watchlists and Dashboards](https://www.koyfin.com/help/my-views/)
- [Command Palette UI Design best practices — Mobbin](https://mobbin.com/glossary/command-palette)
- [How to build a remarkable command palette — Superhuman](https://blog.superhuman.com/how-to-build-a-remarkable-command-palette/)
- [Command Palette Pattern — UX Patterns for Developers](https://uxpatterns.dev/patterns/advanced/command-palette)

*Read-only design-strategy audit. No source or component files were modified. Screenshot capture script (`apps/worldview-web/scripts/qa-capture-0619.mjs`) and screenshots were written under acceptEdits.*
