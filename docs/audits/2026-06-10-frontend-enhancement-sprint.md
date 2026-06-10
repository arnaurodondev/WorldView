# Frontend Enhancement Sprint — 2026-06-10

Branch: `feat/frontend-enhancement-sprint` (off `feat/plan-0099-w4`). 24 commits across 4 rounds × 6 surfaces.
Gates after every round: vitest (no drop), `tsc --noEmit` clean, `next build` success — all four rounds passed.
**Test count: 2358 → 2957 passing (+599), 0 failures. tsc 0 errors. Build green.**

## Round 1 — Foundation (data-path fixes + structural features)

| Surface | What shipped | Commit |
|---|---|---|
| Dashboard | SPY/QQQ/IWM/VIX with price/change$/arrow (quote.change was fetched but never rendered); proportional heatmap scale; TopMovers tabs + sparklines; hydrator key-mismatch fix (`transformTopMoversResponse`); MorningBrief named empty state + Regenerate | `317771576` |
| Screener | 52W range bars w/ derived low/high tooltips; 28 numeric cols right-aligned; all numeric cols sortable; ticker navigation (was UUID vs ticker route); empty state + Reset CTA; flattener verified against S3 source | `b5fe310e5` |
| Instrument | OHLCV cache-key mismatch fixed (dead data path to SessionStatsStrip); period selector 1D–5Y with shared-fetch windowing; CrosshairLegend; VOL was rendering a % through formatVolume; contradictions source A/B; named empty states | `2bbba5720` |
| Portfolio | Cash/BuyingPwr KPIs wired via useExposure (props existed, never passed); sparkline keyed by instrument_id not ticker (100% miss) + dead `var(--color-*)` tokens fixed; pinned TOTAL computed; tx pagination; empty-portfolio state | `b9b961395` |
| Chat | Streaming typing-dots (no empty-bubble flash); URL-less citations no longer `<a href="#">`; orphaned tool spinners cleared; ToolTraceDrawer (?debug=1); Retry without duplicate echo; collapsible+date-grouped thread sidebar | `1a10261d7` |
| Shell | Global command palette ⌘K: route nav + debounced instrument search + recent conversations; ranking lib; shouldFilter fix (cmdk fuzzy filter hid uuid-keyed results) | `5e16ed429` |

## Round 2 — Enhancement

| Surface | What shipped | Commit |
|---|---|---|
| Dashboard | MarketClock (Intl-based DST-safe session engine, 2026 NYSE holidays, 1Hz isolated tick, SSR-safe) + WatchlistQuickView (top-5 by value, +1 network call total) | `496a4d966` |
| Screener | Pinned ticker/name columns; sort-aware export (forEachNodeAfterFilterAndSort); dual-thumb log/linear range sliders (geometric-mean midpoint, ends-mean-unbounded); server-side avg_volume_30d filter (live-verified 596→7 rows) | `94efff949` |
| Instrument | KeyStatsBar (zero new fetches); Income/Balance/CashFlow mini-tables w/ Annual/TTM toggle (strict 4Q sums, MRQ never summed); RelatedEntitiesPanel from graph cache; NarrativeTimeline (no fabricated sentiment); BP-379-class cache-corruption fix | `1dbfdc2c8` |
| Portfolio | Sector donut + click-to-filter holdings (URL-backed ?sector=, EODHD↔GICS alias table — exact match silently filtered 0 rows for ~6/11 sectors); TWR chart rebased to 0% + SPY/QQQ overlay; client risk metrics (Sharpe rf=0, max DD, vol, beta) w/ hand-computed test fixtures; RiskSidebar stale-cache fix | `d3fb881e2` |
| Chat | Entity overview cards (ticker-extract lib w/ ~230-token blocklist, resolve-before-render); deterministic suggested follow-ups (FNV-1a template rotation); ?thread= deep links consumed | `cc7404a21` |
| Shared | AgGridBase rowHeight/headerHeight props; dead `--color-positive/negative` token fix (9 usages); CitationV2 canonical type; EmptyState icon+action API | `121959713` |

## Round 3 — Polish

| Surface | What shipped | Commit |
|---|---|---|
| Dashboard | 13 widget skeletons shape-matched; EmptyState migration (16 keys); 10px ADR floor; focus-visible rings everywhere; discrete 900ms price flash (NFR-6-compliant, reduced-motion-safe) | `c8bf12b0d` |
| Screener | 20px density (T-IA-14 guard forbids 22px on screener); MiniChart no-paint fix (raw HSL triplets as stroke); ScreenerTableSkeleton; cold-start vs filtered-to-zero distinct states | `2e593ab4a` |
| Instrument | Local EmptyState stopgap deleted, 9 call sites → shared primitive + registry keys; accent-bar headers unified across Financials + Intelligence; ChartSkeleton/GraphSkeleton; Enter-activation a11y fix on article rows | `a6a474c4f` |
| Portfolio | DrawdownChart no-paint fix (`var(--negative, #hex)` invalid); placeholderData on all 6 period queries (no skeleton flash on period switch); signed-zero convention unified; KPI skeleton drift 7→8 tiles | `264fcf0ad` |
| Chat | Welcome state + starter chips (found+fixed composer-clobber bug: setInput before handleNewChat's reset); bubble-shaped skeletons (alternation was dead under space-y); instant scroll while streaming; old-amber rgba → bg-primary/10 | `8888f0a93` |
| Shell | ⌘K migrated into hotkey registry (visible in "?" cheat sheet; single keydown dispatcher); toasts pinned max-3/4s; IndexStrip animate-pulse removed; skeleton convention codified §6.2 | `7c3400bfa` |

## Round 4 — Hardening

| Surface | What shipped | Commit |
|---|---|---|
| Dashboard | Error+Retry on 8 widgets that had none (failures masqueraded as "No portfolio yet"/"not ingested"); role=region landmarks ×13; 3 duplicate fetches deduped onto shared query keys; MarketClock isolation pinned | `8fa6bc017` |
| Screener | Error overlay + Retry (error was destructured, never rendered → blank grid); columnDefs identity bug (fresh `{}` per render rebuilt 34 ColDefs on hover); null-row contract tests; slider aria-valuetext | `b80131ff9` |
| Instrument | 404 → InstrumentNotFound finally wired (isError discarded → permanent dash header); per-section error isolation (news failure masqueraded as "no articles"); NaN bar filtering; roving tabindex; FundamentalsTimeseriesChart (dead) deleted | `dbb065ac0` |
| Portfolio | Page-level Retry; 4 silent watchlist mutation failures fixed (rename onError was a no-op comment); benchmark failure isolation (portfolio line always draws); AG Grid rowData identity stable under sector filter | `4554ef909` |
| Chat | Interrupted SSE streams surfaced (was silent truncation presented as complete); ThrottledMarkdown (~33ms frames vs full re-parse per token); mod+d into hotkey registry; role=log announce-on-completion | `9788db740` |
| Shared | Route error boundaries (group + global + indices); HotkeyCheatSheet focus trap (docstring claimed native dialog, trapped nothing); contrast table from live tokens; QueryClient pins; animate-pulse retired in orphan surfaces | `a6a418fbc` |

## Validation result

- vitest: **2957 passed | 16 skipped, 0 failed** (baseline 2358 → +599)
- `tsc --noEmit`: **0 errors** · `next build`: **success** — after every round
- Live smoke (S9 @ :8000, 77 containers): SPY quote 759.57/-25.47 ✓ · screener 666 instruments ✓ · portfolio exposure + sector-breakdown ✓ · chat /v1/threads ✓ · AAPL page-bundle full ✓ · NVDA entity-card chain (search→overview) verified live in R2 · real SSE stream terminates with `event: done` verified in R4

## Backend data gaps (not fixable frontend-side)

1. **Screener POST projection**: filtered view only projects filtered metrics — MKT CAP/P/E/CHG% go "—" once any filter applies. *Highest-leverage backend fix* (union key_metrics into POST projection, market-data `fundamental_metrics_query.py`).
2. `market_impact_score` does not exist in S3 — SCORE column can never populate.
3. Default screener view missing `dist_from_52w_low/high_pct`; no absolute 52W low/high; no daily `volume` field (vol-vs-avg brightening impossible).
4. Top-movers payload has no price (S3 SQL returns ticker/name/return only) — every consumer pays a second batch call.
5. No morning-brief force-regenerate endpoint (`POST /v1/briefings/morning/generate`).
6. No per-sector top-mover in `/v1/market/heatmap` (client-side join used).
7. quote payload lacks bid/ask (S9 PriceSnapshot chain); header has B×A cells ready.
8. No per-version sentiment on narratives; S9 doesn't proxy S3 balance-sheet/cash-flow routes; zero ANNUAL statement records ingested (quarterly only).
9. No flow-adjusted TWR endpoint (chart honestly labeled NAV-relative); sector-breakdown segments lack instrument_ids (name-alias join required); risk-metrics endpoint floors lookback at 10 days.
10. asset_class missing from holdings/overviews payloads; no buying-power field (cash used); beta absent from overviews (β-ADJ defaults 1.0).
11. S8 chat stream has no `suggestions` SSE event (follow-ups client-templated); `tool_result` lacks `duration_ms` and result payload; no ticker→overview endpoint (entity cards cost 2 requests each).
12. `lib/api/_client.ts` apiFetch has no request timeout — hung connections wait on browser defaults.
13. Contrast: opacity-stepped `text-muted-foreground/70|60|50` fails WCAG AA at 10px (documented §2.4; needs a dim token decision).

## Design system additions (docs/ui/DESIGN_SYSTEM.md)

§2.4 contrast table + 10px floor approvals · §6.2 skeleton rules (static default, slow opt-in >2s, raw animate-pulse banned) · §6.7.1 route error-boundary chain · §6.12 keyboard map (verified g d/s/p/c) + "?" overlay contract · §6.15 command palette pattern · §6.16 toast pattern (max 3, 4s) · §9 QueryClient defaults + sanctioned raw-fetch list · §15.10 22px adoption path + screener 20px exception · §15.11 color-token decision table · §15.12 EmptyState API + copy-key registry

## Parallel-session note

A sibling session is working on nlp-pipeline (`entity_refresh_consumer_main.py`, `config.py`, tests, `infra/kafka/init/create-topics.sh` uncommitted in this worktree — left untouched). A stray conversational message was found pasted atop `services/rag-chat/.../citation_accuracy_cron.py` (syntax-breaking); the file was restored to HEAD and the text preserved in the session log.
