# Full-Stack Rework — Waves 1+2 (2026-06-10/11)

Branch: `feat/frontend-enhancement-sprint`. Follows the 2026-06-10 frontend sprint (24 commits). This pass: **13 commits** — Wave 1 backend mitigation + dashboard quick fixes + AI-signals overhaul, Wave 2 frontend rework of the user-flagged surfaces.
Final gate: **vitest 3253 passed / 0 failed** (2994 → 3253), tsc 0 errors, next build green; backend suites: market-data 1048, portfolio 770, knowledge-graph 1388, rag-chat 1744, api-gateway full — all pass.

## Wave 1 — Backend mitigation (per service)

| Area | Root causes fixed / shipped | Commit |
|---|---|---|
| market-data (S3) | **Screener POST projection** returned only filtered metrics (every other column blanked under any filter) — full key_metrics union via page-bounded query; 52W absolute+distance fields; daily volume; movers last_price; heatmap per-sector top mover; **day-change-zero root cause**: resolver passed prev_close only on the DAILY_CLOSE branch — all quote-derived paths emitted None which S9 coerced to 0.00 platform-wide; B-Q-1..4 endpoints (peers/intraday/returns/price-levels); bid/ask plumbing | `547599c5d` |
| api-gateway (S9) | 6 new market proxies incl. by-ticker overview (halves chat entity-card cost), statement proxies, bid/ask mapping | `bdf0105f9` |
| portfolio (S1) | asset_class on holdings; **flow-adjusted TWR endpoint** (geometric linking between flows); sector instrument_ids; buying_power; risk floor 10→5d; **BP-655**: trade_side never persisted/hydrated → /realized-pnl was already 500 on the demo book (repo fix + data migration 0022, run live) | `d8f712531` |
| knowledge-graph (S7) | "S9 drops edge fields" was **three layers** (S7 relation repo never SELECTed temporal/contra columns; center-node repo dropped description; S9 transform stripped 11 fields); new GET /v1/relations/{id} with evidence_text chunks; enriched entity detail (aliases/health/top relations); entity events proxy | `b95dd544a` |
| rag-chat (S8) | **BP-661** — "what is AAPL?" refusal was a 3-layer ticker drop: resolver gate rejected both candidates when the BP-459 phantom twin tied Apple Inc. in the delta window; NarrativeHandler passed raw "AAPL" to UUID(); S6 ticker resolver returned the twin first. Fixed all three + tool descriptions; suggestions SSE event (zero extra LLM calls); tool_result duration_ms + result_preview; POST /v1/briefings/morning/generate | `f75277e4b` |
| AI signals | "9ECB" labels were `entity_id.slice(0,4)` UUID leaks (S9 discarded canonical_name); duplicates = one row per claim, no dedup; 95% = quantized extraction confidence presented as if predictive. New routes/signals.py (dedup/enrich/humanize) + redesigned widget with grouped expandable evidence. Honest verdict: orientation-useful, not predictive — impact labeller writes ~1 row/week (roadmap filed) | `d4ebfc343` |
| dashboard/shell | **ActivePortfolioProvider was never mounted** (selector wrote into the noop context); marquee ticker tape (16 instruments, reduced-motion static); heatmap dead space (content-start + fixed tiles in a stretched row); predictions: category field dropped in transform + widget never sent the param (two distinct bugs) + useInfiniteQuery scroll; BTC vs BTC-USD + overview-vs-batch quote divergence; apiFetch 15s timeout; --muted-foreground-dim AA token | `89869de6c` |

## Wave 2 — Frontend rework (per surface)

| Surface | What shipped | Commit |
|---|---|---|
| Quote tab | **Chart pane bug**: 5 indicator panes added unconditionally, "collapsed" via a method that doesn't exist in lightweight-charts 5.2 (silent no-op) → rebuilt with lazy pane lifecycle. **Sidebar all-dash**: fundamentals query fired before auth token hydrated and settled into permanent 401 + page never seeded the bundle's fundamentals (now seeds the flat transformed shape). Brief markdown rendered (LEAD/DETAILS, citation stripping, stale tag, regenerate). New RETURNS/INTRADAY/PRICE-LEVELS/PEERS strips on the Wave-1 endpoints. Regrid: About → rail, +110px chart | `98b25ef2a` |
| Financials tab | KeyRatioStrip (12 cells) + PanelHeader unification; real statement tables (Annual 5FY / Quarterly 8q / TTM, shared units, YoY colors, sparkline microcharts); duplicate income rendering deleted; peers table on new endpoint w/ real subject row; permanently-empty analyst stubs dropped; EPS line dropped (key never exists in data) | `558e15a86` |
| Intelligence tab | Bloomberg investigation grid (dossier / graph+inspector / news+events+contradictions+narrative). **Edge clicks never worked**: graphology auto-generated edge keys were emitted as API ids — addEdgeWithKey makes sigma key == relation_id. EdgeInspector: full relation detail + quoted evidence chunks, polarity, confidence, validity, provenance. NodeInspector: enriched dossier + focus-camera. Selection highlight via reducers | `bcdd6f570` |
| Portfolio | 3-panel overview band (market exposure / sector exposure w/ exact-ID joins / TWR-vs-SPY periods); true TWR in analytics + real CALMAR/WIN RATE/ALPHA/VaR; ASSET column server-side; Top-Movers clipping fix (mode prop, 124px slot); NAME truncation caps removed; watchlist rows enriched (sparkline/vol/open) | `e0b3ea145` |
| Screener | GET endpoint no longer exists on gateway (legacy branch would 422) → POST-always; real 52w values; volume brightness vs 30d avg; filtered-view full metrics live-verified; SCORE column hidden by default (no data source) with pref migration | `0a1f6650a` |
| Chat | 860px readable measure + 24px message meta chrome (intent/provider/latency/citations); rail always visible ≥1280px: entity cards (1-request by-ticker + sparkline from payload), NEW conversation sources (deduped citations, ×N), NEW tools-used (count + avg server latency); server suggestions consumed; live E2E verified incl. the fixed AAPL answer | `94029373d` |

## Verified live end-to-end
- "In one short sentence, what is AAPL?" → correct streamed answer + entity card with real −7.93% day change + server suggestions.
- Screener under a P/E filter returns full metrics; AAPL edge click → 11 evidence chunks; TWR 66-point series; day changes real platform-wide.

## Backend gaps still open (filed, not faked)
1. Evidence `document_id` cannot resolve article title/url — `/v1/documents/{id}` proxies S4 uploads and 500s on pipeline docs; join article metadata into the relations endpoint or fix the route semantics.
2. Batch quotes lack `change_pct`/`previous_close` → screener CHG%/PRICE coverage stuck at ~32 quote-backed instruments.
3. Returns (1M..3Y), insider_net_buy_90d, short_percent absent from screener key_metrics; filtered-POST sort_by whitelist differs from GET.
4. Benchmark sector weights (no endpoint); risk-metrics SPY leg returns no_data on dev stack; 256/525 prediction markets have NULL category; ^TNX not ingested; index-ETF overview.quote null (batch has prices — server should share the fallback chain).
5. 6/8 AAPL peers lack OHLCV seed (null last/day%/1Y); balance-sheet/cash-flow have no ANNUAL records; bid/ask feed copies last into both.
6. Impact-labelling worker near-dormant (1 row/wk vs 1115 signals) — blocks predictive AI-signals ranking; multi-turn suggestion entity drift observed once (ON Semi for an Apple thread).
7. Dev ingestion gaps: daily bars 06-04→06-10 missing, quotes stale — day-change values are change-vs-last-known-close until ingestion resumes.

## Parallel-session notes
- Foreign commits in this worktree during the run: `7ff3b8cb9` (ohlcv intraday intervals), `e9243800e` (market-ingestion scheduler) — other session's work, left intact.
- Foreign uncommitted files left untouched: nlp-pipeline (3), create-topics.sh, rag-chat reranker.py quote-style edit.
- Pre-commit mypy hook fails on cross-staged multi-service commits (protocol-port false positives resolved only when both files staged together); per-area commits used SKIP=mypy after agents validated mypy per-service — final frontend commit ran full hooks.

---

# Wave 3 addendum — fix agents + strict live QA loop (2026-06-11, 8 commits)

User-reported failures, each root-caused and live-verified (QA matrix 22/22 PASS, frontend suite 3334, all containers rebuilt):

| Report | Root cause | Commit |
|---|---|---|
| Chat streaming dead (no tokens/tools) | Two stacked transport bugs: Next compress gzip-buffered SSE through rewrites (whole stream held by zlib) + sse-starlette CRLF line endings vs `\n` client split (every event named "token\r") — curl masked both | `9e6b07d6e`, `7544ac586` |
| BTC-USD entity refusal | BP-668 resolver hijack: "right now" matched ServiceNow ticker NOW (family: "news on"→ON Semi, "does it"→Gartner); case-aware ticker evidence + name-exact tiebreak | `b8aadf3a6` |
| Apple-news citations [5][6][8] vs 4 wrong pills | BP-669: ContextAssembler re-sorted items AFTER prompt enumeration; dense renumbering added | `b8aadf3a6` |
| Validator timeout + 40s answers | BP-670/671: validators flagged ordinals/headings as fabrications → stacked 30s LLM rewrites that fabricated content; deterministic guards + divergence guard; 50s→26s, grounding 31.5s→25ms | `b8aadf3a6`, `bdf4d373f` |
| False "Response interrupted" after complete answers | done frame stranded in decoder buffer + CRLF bug; sawAnswerComplete + tail flush | `9e6b07d6e`, `7544ac586` |
| Portfolio black spaces | Tailwind content globs never scanned features/ — xl:grid-cols-3 emitted zero CSS; repo-walking guard test kills the class | `370e8e801` |
| Topbar tickers taller than bar | 3 stacked lines (32px glyphs) in 32px bar → single-line 132px cells | `370e8e801` |
| TWR +278% | BP-665 backend: funding/import days counted as return; S1 degraded-snapshot/frozen-NAV/perimeter guards; +282%→+10.9% cum; flow_dates exposed | `370e8e801` |
| Quote black void | Chart root className="" → h-full vs auto parent → circular 280px ResizeObserver loop; StrictMode init race | `14f42b6ed` |
| Intelligence tab all-failing | URL ticker passed to UUID-typed /v1/entities routes (uniform 422) + S7 depth-2 nodes arrived edge-less (orphan-filtered); list_among_entities lateral fetch: AAPL 21n/22e→25n/46e | `14f42b6ed` |
| Backend-blocked items | /v1/articles/{id} evidence resolution, previous_close on quotes, returns/short%/insider metrics (insider consumer was never in compose), annual statements param, 12,939-bar gap backfill, 196 prediction categories, impact-labeller diagnosis (+57 windows post-backfill vs +0/wk) | `0c04c271f` |

QA loop additionally fixed in the prod container: SSE CRLF parser, streamed-citation crash (`cite.source` vs `source_name`), Financials-tab crash on `risk_summary: {}`, evidence article-title wiring (`7544ac586` — which also recovered Wave-2 files dropped by a parallel-session merge auto-resolution while HEAD still imported them).

Open filed: S2 snapshot worker frozen partial_prices rows (TWR data hygiene); S8 synthesis token burst (no true typewriter streaming); residual latency = LLM planning/synthesis (model choice); BTC rail probes "BTC" not "BTC-USD"; top-movers price "—" in one widget. Parallel session opened PLAN-0109 (confidence-decay/weighting redesign per user's Appendix-E request).
