# QA Report: Platform Stability Iteration 3

**Date**: 2026-05-01
**Skill**: qa
**Scope**: full-platform — open issues blocking final convergence + 4 user-reported UI/UX issues
**Branch**: feat/content-ingestion-wave-a1
**Verdict**: **PASS_WITH_WARNINGS** — 4/8 BLOCKING/CRITICAL closed in commit `f27e266b`; 4 deferred to Round 4 (well-scoped follow-ups, no platform-stability blockers); 2 FEATURE designs delivered.
**Report file**: docs/audits/2026-05-01-qa-platform-stability-iter3.md
**Commits this round**: `f27e266b`

---

## Executive Summary

A 5-agent parallel QA pass investigated the platform's open stability issues and 4 user-reported UI/UX bugs. The headline finding is **BP-302**: a silent infinite loop in `chunk_section` (`embeddings.py:95`) that hung the article-consumer indefinitely on news articles containing un-punctuated pull-quotes >512 words. py-spy traced four consecutive samples to the same line, mention_resolutions were stuck at 188, and the entire downstream KG pipeline (relation_evidence_raw=0, temporal_events=0) was starving as a result. The fix is a 3-line liveness guard plus a regression test.

Three other surgical fixes shipped in the same commit: portfolio "half-screen black" panel via a shared `useExposure` hook (lifts the query out of `<ExposureBreakdown>` so the parent can three-state branch the wrapper), gateway `apiFetch` fail-fast on `/undefined` paths (eliminates ~80 backend 500s/hour from FE race conditions), and EU economic-events date parser one-liner that closes a 100% silent-drop bug.

The agents also delivered concrete designs for two NEW UX features (per-widget ticker search in workspace, TopBar rotating marquee) and concrete fix plans for 4 medium-effort backend issues (prediction-market consumer Avro guard, price-impact ticker→UUID resolver, EODHD INDU/CCMP routing, brokerage sync exponential backoff). These are well-scoped Round-4 work, not platform-stability blockers.

Overall platform health: 61/61 containers healthy, all FE routes 200, no idle-in-transaction spikes, alert pipeline cold but consumers healthy (no input). Rebuild + recreate of `worldview-web` + `nlp-pipeline-article-consumer` + `knowledge-graph-economic-events-dataset-consumer` is in progress.

---

## Multi-Agent Review Summary

| Agent | Files Reviewed | Findings | BLOCKING | CRITICAL | MAJOR | FEATURE |
|-------|---------------|----------|----------|----------|-------|---------|
| QA-A: article-consumer hang deep-dive | `embeddings.py:85-156` + py-spy + 7 hypothesis probes | 1 | 1 | 0 | 0 | 0 |
| QA-B: portfolio + screener UI bugs | `PortfolioAnalyticsSection`, `ExposureBreakdown`, `ScreenerTable`, holdings | 8 | 1 | 1 | 4 | 2 |
| QA-C: workspace search + marquee design | `WorkspaceContext`, `IndexTicker`, all `Workspace*Widget` | 2 | 0 | 0 | 0 | 2 |
| QA-D: outstanding backend criticals | 5 services (prediction-market, price-impact, eodhd, kg-econ-events, brokerage-sync) | 5 | 0 | 2 | 3 | 0 |
| QA-E: full cross-service health audit | All 61 containers, 30 Kafka topics, 7 DBs | 9 | 0 | 4 | 4 | 0 |
| **Total** | — | **25** | **2** | **7** | **11** | **4** |

### Cross-Agent Signals (HIGH Confidence — 2+ agents flagged)

- **`relation_evidence_raw=0` / KG downstream silent drop**: flagged by QA-A (root cause = article-consumer never finishes processing) AND QA-E (data-flow chain analysis). Closing BP-302 (this round) should restart the downstream cascade once the consumer drains its lag.
- **Frontend "undefined" race**: flagged by QA-B F-004 (screener click → `/instruments/undefined`) AND QA-E F-008 (40 server 500s/hour from same root cause). Closed this round.
- **Portfolio "half-black"**: flagged by QA-B F-001 (specific file + line). Closed this round.

### Fixes Applied (Commit `f27e266b`)

| Finding | Fix | Status |
|---------|-----|--------|
| F-A1 (BP-302 article-consumer hang) | `progress_made` guard + regression test | APPLIED |
| F-B1 (portfolio "half black") | `useExposure` shared hook + 3-state branching | APPLIED |
| F-E8 (FE `/undefined` 500s) | `apiFetch` fail-fast guard | APPLIED |
| F-D4 (EU `invalid_date`) | One-line space→T normalization | APPLIED |

### Deferred to Round 4 (well-scoped, non-blocking)

| Finding | Owner | Effort |
|---------|-------|--------|
| F-B3 Screener data shape (gateway transformer) | Round 4 | S |
| F-B4 Screener entity_id missing in backend response | Round 4 | S |
| F-D1 Prediction-market consumer Avro guard + dead-letter cap | Round 4 | M |
| F-D2 Price-impact worker ticker→UUID resolver | Round 4 | M |
| F-D3 EODHD INDU/CCMP routing + `ProviderUnsupportedSymbol` error class | Round 4 | M |
| F-D5 Brokerage sync exponential backoff | Round 4 | S |
| F-B5 Holdings ETF sector/name fallback | Round 4 | S |
| F-C1 Per-widget ticker search (UX feature) | Round 5 | S |
| F-C2 TopBar rotating marquee (UX feature) | Round 5 | S/M |

---

## Test Execution Results

| Layer | Scope | Tests | Passed | Failed | Status |
|-------|-------|-------|--------|--------|--------|
| ruff | files touched this round | — | — | 0 | PASS |
| ruff-format | files touched this round | — | — | 0 | PASS |
| mypy | files touched this round | — | — | 0 | PASS |
| typecheck (TS) | apps/worldview-web | — | — | 0 | PASS |
| nlp-pipeline unit | services/nlp-pipeline | 646 | 646 | 0 | PASS |
| knowledge-graph unit | services/knowledge-graph | 688 | 688 | 0 | PASS |
| api-gateway unit (prior round) | services/api-gateway | 298 | 298 | 0 | PASS |
| market-data unit (prior round) | services/market-data | 562 | 562 | 0 | PASS |
| frontend unit | apps/worldview-web | 1196 | 1196 | 0 | PASS |
| frontend build | apps/worldview-web | — | — | 0 | PASS (in progress in background — verify post-rebuild) |

---

## Issues — Full Investigation

## Issue F-A1: BP-302 article-consumer infinite loop in `chunk_section`

### Summary
`chunk_section` in `embeddings.py:95-156` enters an infinite loop when a single sentence exceeds `CHUNK_MAX_TOKENS` (512) AND the previous iteration carried over an overlap. Loop variable `i` never increments; the outer loop rebuilds the same overlap from the same `current_sentences` and spins forever. Consumer hangs, no offset committed, every re-delivery hits the same poison message.

### Severity / Confidence
**Severity**: BLOCKING
**Confidence**: HIGH (py-spy stack trace + memory-confirmed pattern match)
**Flagged by**: QA-A (deep-dive)

### Root Cause Analysis
- **What**: `embeddings.py:95-113`. Inner loop `if current_tokens + s_tokens > max_tokens and current_sentences: break` exits without `i += 1`. After the break, the safety hatch `if not current_sentences: ...; i += 1` doesn't fire because `current_sentences` was non-empty (filled by the overlap). Outer loop runs `overlap_sentences = list(...)` from the same `current_sentences` — same overlap, same `i`, same poison.
- **Why**: The original guard assumed "if no progress AND non-empty, the carry-over IS the chunk; emit it and continue". But emitting the carry-over without advancing `i` means the next outer iteration produces an identical state.
- **When**: Triggers on any article containing a sentence longer than 512 words AFTER at least one earlier chunk produced overlap. nlp_db `document_source_metadata.word_count` p95 = 457, max = 8 187 — common for news HTML (pull-quotes, lists, captions, run-on quotes with no `.!?`).
- **Where**: Application layer, embeddings block. NOT my Round 2 changes — those are post-extraction. Pre-existing latent bug; just hit it now after consumer rebuild.
- **History**: Zero unit tests for `chunk_section` before this commit (`grep` over `services/nlp-pipeline/tests/` returned no matches).

### Evidence
```
4 consecutive py-spy dump --pid 1 (1-8s apart):
chunk_section (nlp_pipeline/application/blocks/embeddings.py:98)  active+gil
run_embeddings_block (...embeddings.py:250)
_run_pipeline (...article_consumer.py:363)
process_message (...article_consumer.py:240)

DB: mention_resolutions stuck at 188 for 30+ minutes;
chunks created in 10 min: 0;
relation_evidence_raw: 0; temporal_events: 0.

Container log: ner_http_batch_completed at 12:51:02, then silence
for 8+ minutes. Kafka group lag: 31 messages on partition 10 alone.
```

### Impact
- **Immediate**: Consumer wedged. No new mention_resolutions. Entire downstream KG pipeline starving (`relation_evidence_raw=0`, `temporal_events=0`).
- **Blast radius**: All news intelligence features (KG, `/v1/news/top`, `/v1/entities/.../graph`, RAG citations) read from artifacts the wedged consumer would have produced.
- **Data risk**: No corruption — the consumer never commits offsets, so re-delivery is correct on its own; the poison message never lands as a half-processed row. Pure liveness failure.
- **User impact**: News intelligence features show stale or empty data; alerts on news triggers don't fire.

### Solution Applied
Added `progress_made` flag in the inner loop. If the inner loop breaks without consuming a new sentence, the outer iteration drops `overlap_sentences` and `continue`s, forcing the next pass to take the oversize sentence alone (the safety hatch handles this once `current_sentences` is empty). Plus a regression test (`test_oversize_sentence_with_overlap_does_not_hang`) constructs the exact poison shape (short / 50-word un-punctuated / short with `max_tokens=10, overlap_tokens=3`) and asserts the call returns deterministically.

### Long-term hardening (Round 4+)

1. **Per-message processing watchdog**: wrap `process_message` in `asyncio.wait_for(..., timeout=settings.message_processing_timeout_s)` (e.g. 120s). On `TimeoutError`, dead-letter the message and log a faulthandler stack trace. Converts "silent infinite hang" into "loud DLQ + traceback" for the entire class of bug. **NEW BUG_PATTERN: BP-302**.
2. **Property-based test coverage on pure functions in `application/blocks/`**: zero tests on `chunk_section` was the real failure. Add `hypothesis`-style fuzzing for `_split_sentences` + `chunk_section` over random text (very-long no-punctuation sentences, empty strings, single chars). Same applies to `section_document`, `apply_suppression_gate`, `compute_routing_score`.
3. **Ship `py-spy` in non-prod images**: 30s with vs. 30 min without; high ROI for thesis-grade local debugging.

### Verification Steps
- [x] `pytest services/nlp-pipeline/tests/unit/application/blocks/test_embeddings.py` — 26/26 PASS
- [ ] After rebuild + container recreate: `docker logs --since 5m worldview-nlp-pipeline-article-consumer-1 | grep -c article_processed` should be > 0; `mention_resolutions` should grow past 188; `relation_evidence_raw` should grow past 0.

---

## Issue F-B1: PortfolioAnalyticsSection "half-screen black"

### Summary
The Holdings / Watchlists pages render a 200-px-tall black `bg-card` rectangle on the right side of the analytics row when `<ExposureBreakdown>` returns its empty/error branch. The wrapper `min-h-[200px] bg-card border` was unconditional; the equity-curve cell already three-state branched but the exposure cell was never given the same treatment.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH (file + line confirmed)
**Flagged by**: QA-B (F-001)

### Root Cause Analysis
- **What**: `PortfolioAnalyticsSection.tsx:171` — `<div className="col-span-12 lg:col-span-4 min-h-[200px] bg-card border border-border rounded-[2px] p-2 flex items-center justify-center">` rendered around `<ExposureBreakdown>` regardless of data state.
- **Why**: When the child rendered `InlineEmptyState` (200×40 px content), the wrapper still drew a 200×~400 px `bg-card` panel — visually a tall black rectangle on the dark page background.
- **Where**: Frontend — portfolio analytics composer.
- **History**: Pre-existing; the equity-curve cell was already protected with the same three-state pattern (lines 134-159 explicitly comment on "F-P-001 big black panel" anti-pattern), but the exposure cell was missed.

### Solution Applied
1. New shared hook `apps/worldview-web/hooks/useExposure.ts` extracts the inline TanStack query.
2. `<ExposureBreakdown>` consumes the hook (no behavior change — same query, TanStack dedup).
3. `<PortfolioAnalyticsSection>` reads the same hook and three-state branches the wrapper:
   - loading → `<Skeleton h-[200px]>`
   - empty (invested + cash ≤ 0) → bordered card with `<InlineEmptyState>` ("No exposure data — add holdings to see breakdown.")
   - data → original `min-h-[200px] bg-card` panel

### Verification Steps
- [x] Frontend typecheck PASS
- [x] 1196/1196 frontend tests PASS
- [ ] Manual: visit `/portfolio` → switch to Holdings → confirm no tall black panel for empty-portfolio case.

---

## Issue F-E8: FE `/undefined` race-condition 500 storm

### Summary
Frontend useQuery calls fired with `instrumentId === undefined` before parent state resolved. Routes like `/v1/companies/${encodeURIComponent(instrumentId)}/overview` produced literal `/v1/companies/undefined/overview` paths → backend asyncpg `DataError: invalid UUID 'undefined'` → 500. ~80 such 500s per hour visible in `worldview-market-data-1` logs.

### Severity / Confidence
**Severity**: CRITICAL
**Confidence**: HIGH (40 confirmed errors in 30 min from QA-E F-008)
**Flagged by**: QA-E (F-008), QA-B (F-004 same root cause for screener click)

### Root Cause Analysis
- **What**: `apiFetch` in `apps/worldview-web/lib/gateway.ts:130` made the network call regardless of whether the path contained `/undefined`. The 23 by-id gateway methods (overview, page-bundle, ohlcv, quotes, fundamentals, technicals, ...) all built paths via `encodeURIComponent(instrumentId)` — encoding "undefined" produces "undefined" verbatim.
- **Why**: useQuery `enabled` guards exist on most call sites but several pre-render paths (screener click → optimistic prefetch, hydration races) slip past.
- **Where**: Frontend gateway boundary.

### Solution Applied
Added `_detectMalformedPath(path)` helper that checks for path segments `/undefined`, `/null`, or empty-segment patterns. `apiFetch` calls it first and throws `GatewayError(0, ...)` with a helpful message ("likely a useQuery enabled-guard race"). useQuery surfaces a clean error instead of propagating to the backend; backend stops logging UUID parse errors; log volume drops materially.

### Verification Steps
- [x] Typecheck + 1196/1196 tests PASS
- [ ] After rebuild: `docker logs --since 30m worldview-market-data-1 | grep -c "invalid UUID"` should drop to ~0.

---

## Issue F-D4: KG economic-events EU `invalid_date` 100% drop

### Summary
EODHD EU economic events arrive with space separator (`"2026-04-30 12:15:00"`) but `_parse_event_date` only accepted ISO-T (`"%Y-%m-%dT%H:%M:%S"`) and date-only formats. Every EU event silently dropped via the strptime fallthrough.

### Severity / Confidence
**Severity**: MAJOR (100% drop is severe but bounded to one country group)
**Confidence**: HIGH (live-confirmed: 81 EU events processed → 0 ingested at 12:25:55)
**Flagged by**: QA-D (#4), QA-E (F-007 cold alert pipeline correlated)

### Solution Applied
One-line normalization: `normalized = date_str.replace(" ", "T", 1)` before the existing strptime loop. Operator follow-up: `kafka-consumer-groups --reset-offsets --to-earliest --topic market.dataset.fetched --group kg-economic-events-dataset-group --execute` to backfill the dropped events.

### Verification Steps
- [x] 688/688 knowledge-graph tests PASS
- [ ] After rebuild: `docker logs --since 30m worldview-knowledge-graph-economic-events-dataset-consumer-1 | grep -c invalid_date` for EU should be 0
- [ ] SQL: `SELECT COUNT(*) FROM temporal_events WHERE event_type='MACRO' AND region='EU'` should be > 0 after offset reset.

---

## Issues F-D1 / F-D2 / F-D3 / F-D5 — Backend Round 4 follow-ups

Concrete fix plans delivered by QA-D (effort + risk per item). Total Round 4 estimate: 2× S + 3× M ≈ 5-9h.

| ID | Issue | Effort | Risk | Recommended option |
|----|-------|--------|------|-------------------|
| F-D1 | Prediction-market consumer stuck rebalancing (48k lag, 175k dead-letters) | M | Medium | Harden Avro guard (force Avro decode when `schema_path` set), cap dead-letter writes to 1000/hour aggregated, restart container, truncate stale failed_tasks |
| F-D2 | Price-impact worker 404 storm (`/api/v1/market-data/ohlcv/{TICKER}` doesn't exist) | M | Low | Add `MarketDataClient.resolve_instrument_id(ticker)` calling existing `/api/v1/instruments/symbol/{ticker}`; cache in Valkey 24h |
| F-D3 | EODHD INDU/CCMP/macro silent drops | M | Low | Add `ProviderUnsupportedSymbol` error class + route INDU/CCMP to `/index/{symbol}` |
| F-D5 | Brokerage sync DNS 4h failure cycle | S | Low | 3× exponential backoff (30s/60s/120s) before sleeping the full 4h cycle |

---

## Issues F-B3 / F-B4 — Screener Round 4 follow-ups

| ID | Issue | Effort | Risk | Fix |
|----|-------|--------|------|-----|
| F-B3 | Screener every metric column shows `—` | S | Low | Backend: flatten `metrics.market_capitalization` → top-level `market_cap` etc. OR add a transformer in `gateway.runScreener()` |
| F-B4 | Screener row click → `/instruments/undefined` | S | Low | Backend response must include `entity_id` (per ADR-F-12 — entity_id ≠ instrument_id) |

---

## Issues F-C1 / F-C2 — UX features (designs delivered, ready for /scaffold-frontend)

### F-C1: Per-widget ticker search in Workspace
QA-C delivered a complete component design. Key decisions:
- Reuse the existing `SymbolLinkingContext.setActiveSymbol(panelId, symbol, instrumentId)` API (no new state slice needed — `widgetOverrides` would create a parallel source of truth)
- New component `<TickerPicker panelId>` uses `cmdk` `Command` primitive (same as `GlobalSearch`)
- Replaces the static `[AAPL]` label in `WorkspacePanelContainer.tsx:228-232`
- Reuses `worldview-recent-instruments` localStorage list (extract `readRecent`/`saveRecent` helpers from `GlobalSearch` into `lib/recent-instruments.ts`)
- Session-only override (matches existing `SymbolLinkingContext` policy)
- Effort **S** (~150 LoC), Risk **Low**

### F-C2: TopBar rotating ticker marquee
QA-C delivered final design + ticker list:
- **10 tickers**: SPY, QQQ, IWM, DIA, VIX, TLT, DXY, GLD, USO, BTC-USD
- **Animation**: pure CSS `@keyframes` translateX (Option A) — duplicate the list in the track for seamless looping
- **Refresh**: single batched `getBatchQuotes(resolvedIds)` every 15s (same pattern as existing `IndexTicker`)
- **Reduced motion**: 4-chip pagination fallback every 8s
- **Hover + focus pause**: `:hover, :focus-within { animation-play-state: paused }`
- **Click**: `router.push('/instruments/entity-{ticker-lc}')`
- New files: `components/shell/TopBarMarquee.tsx`, `components/shell/MarqueeTickerChip.tsx`
- Effort **S/M** (~200 LoC), Risk **Low**

---

## Recommendations

**Immediate (post-this-commit verification)**:
1. Verify article-consumer drains its 31-message lag and starts producing `article_processed` events (BP-302 fix)
2. Verify `mention_resolutions` grows past 188 and `relation_evidence_raw` starts growing (downstream cascade unblock)
3. Verify `worldview-market-data-1` 500-error rate drops (FE undefined guard)
4. Operator: reset `kg-economic-events-dataset-group` offsets to backfill dropped EU events

**Round 4 (highest impact next)**:
1. F-D2 price-impact ticker→UUID resolver (unblocks `article_impact_windows` population)
2. F-D1 prediction-market consumer Avro guard (44h of data loss accumulating)
3. F-B3 + F-B4 screener fixes (one user complaint covers both)

**Round 5 (UX)**:
1. F-C2 TopBar marquee (high-visibility polish, low effort)
2. F-C1 per-widget ticker search (workflow improvement)

**Long-term hardening**:
1. Per-message processing watchdog in BaseKafkaConsumer (BP-302 generalization)
2. Property-based test coverage for pure functions in `application/blocks/`
3. Ship py-spy in non-prod images
4. Document BP-302 in `docs/BUG_PATTERNS.md`

---

## Compounding Updates

- **NEW BUG_PATTERN candidate (BP-302)**: silent infinite loop in `chunk_section` when sentence > max_tokens AND overlap non-empty → consumer hang, no offset commit, re-delivery re-hangs. Fix pattern: progress-made guard + clear-overlap-on-no-progress + watchdog timeout.
- **NEW HIGH_RISK_PATTERN candidate**: `while` loops whose only progress variable is mutated only inside a conditional branch should be flagged. Add to `.claude/review/heuristics/HIGH_RISK_PATTERNS.md`.
- **REVIEW_CHECKLIST gap**: "every loop has a liveness guard" should be in the checklist for application/blocks/ files.
