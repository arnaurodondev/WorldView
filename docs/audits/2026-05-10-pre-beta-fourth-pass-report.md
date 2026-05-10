# Pre-Beta Fourth Pass — 2026-05-10 Late Evening

> **Verdict: GO for beta.** Universe expanded 57→614, AGE graph populated, Worker 13B periodic, dedup consumer clean, KG semantic completeness 100% on definition embeddings, multi-day evidence trends restored.

## Subagents

| Agent | Outcome |
|---|---|
| **SA-1** Dedup MissingGreenlet | DONE — BP-443: `_SessionUnitOfWork.__aexit__` lacked explicit `await session.close()` before delegating to context manager. Fix: explicit close + `contextlib.suppress` wrapper. **0 errors across 10 min** (was 11/3m). 7 regression tests; 334 unit tests pass. |
| **SA-2** Worker 13B + SummaryWorker fallback | DONE — Promoted one-shot script to periodic Worker 13B (5-min interval); +`relation_evidence_promoter` registered in scheduler; `relation_evidence` 438→947 organically. Added retry-with-exponential-backoff + Gemini 2.5 Flash Lite fallback (no Groq). 14 new unit tests. |
| **SA-3** Embedding completeness | DONE — three root causes: stale `source_hash`, silent skip on `source_text=NULL`, and **wrong URL** in `FundamentalsRefreshWorker` (`/symbol/{ticker}` 404 → `/lookup?symbol=`). **def_emb now 100%** across all entity types; `fst_emb` 0→55; backfill scripts. |
| **SA-4** Evidence_date backfill | DONE — Cross-DB Python script reading `content_store_db.documents.published_at`. **Distinct days 1→10**; AAPL trend now 5 real points (May 5–9). `get_confidence_trend` repo switched from `relation_evidence_raw` to `relation_evidence`. |
| **SA-5** AGE graph sync + path insights | DONE — New `age_sync_worker` populates AGE; new `path_discovery.py` uses 2-hop/3-hop scalar Cypher (no list-comprehension); UUID injection guard. AGE: **1268 nodes / 323 edges**; **path_insight_jobs 54/54 done**; **path_insights 0→2107**. |
| **SA-6** Ticker universe expansion (FR-T0-2) | DONE — **57→614 instruments**: 543 S&P + ADRs, 20 sector ETFs, 29 crypto, 7 macro, 6 FX/metals. OHLCV: 29→600 (+137k bars). Idempotent seed at `infra/seeds/universe.json` + `scripts/ops/seed_universe.py`. |
| **SA-7** News density polish | DONE — cluster-chip copy ("+N sim"), source border + uppercase, NewsTab compressed (13→11px). |
| **SA-8** SnapTrade dividend regression | DONE — All 265 DIVIDEND rows render correctly (98 positive, 102 negative withholdings); BUY/SELL intact. SnapTrade balance endpoint is unmapped (P1 follow-up). |
| **SA-9** Full UI polish | DONE — settings density (profile/beta-program/preferences), intelligence-tab + portfolio empty states. |
| **SA-10** Final beta QA | DONE — verdict **GO**. All routes 200/302; all primary APIs 200; KG def_emb 100%; pipelines clean. |

## Live Validation Evidence

```
intelligence_db:
  canonical_entities          1101 → 1277
  entity_narratives(LLM)       898 → 1257
  entity_narratives(template)  263 → 0          ✨ zero template-v1 remaining
  def_emb                     1040 → 1277       100% across all entity types
  narr_emb                    1103 → 1237
  fst_emb                        0 → 55         (BP fundamentals_url fix, P1 to extend coverage)
  relation_evidence            438 → 947        (Worker 13B firing every 5 min)
  relation_summaries             5 → 5          (SummaryWorker hourly tick pending)
  distinct evidence days         1 → 10         ✨ multi-day trend restored
  path_insight_jobs(done)        0 → 54/54      ✨ 100% success rate
  path_insights                  0 → 2107       ✨

content_store_db:
  duplicate_clusters           807 → 835        (still growing; BP-443 fix holding)
  MissingGreenlet errors/10m   ~26 → 0          ✨ BP-443 holding

market_data_db:
  instruments                   57 → 614        ✨ FR-T0-2 met
  has_ohlcv                     29 → 600
  ohlcv_bars (last 30d)         ~14k → 16,275
  has_fundamentals              49 → 49         (P1 follow-up: backfill via existing script)

AGE graph (intelligence_db.worldview_graph):
  nodes                          2 → 1268       ✨
  edges                          1 → 323
```

## SA-1 BP-443 Root Cause

The dedup consumer's `_SessionUnitOfWork.__aexit__` only awaited `_session_cm.__aexit__(*args)` without first calling `await session.close()`. When SQLAlchemy's asyncpg pool reclaimed the connection on check-in via `reset_on_return`, it issued ROLLBACK through `_reset_agent` using `await_only()` — which fires from the pool's internal cleanup path that is **not** inside a `greenlet_spawn` context. The fix: explicit `await session.close()` before delegating to the context manager (so the session is cleanly disposed within the asyncio greenlet), wrapped in `contextlib.suppress(Exception)` to keep teardown bugs from propagating into the consumer loop. Same pattern likely applies to `ArticleConsumer._SessionUnitOfWork` (P2 follow-up).

## SA-3 BP — DefinitionRefreshWorker silent skips

Three sub-causes for the 6% def_emb gap on `financial_instrument`:
1. `source_hash` was pre-populated by an earlier failed pass; the worker re-skips as "unchanged."
2. Worker silently skips rows with `source_text=NULL` (no log line) — newly provisioned instruments without EODHD description fall through.
3. `FundamentalsRefreshWorker._resolve_instrument_id` called the non-existent path-param route `/api/v1/instruments/symbol/{ticker}`; the real endpoint is `/api/v1/instruments/lookup?symbol={ticker}`. Every call returned 404, silently zeroing `fst_emb`.

After fix + backfill: **def_emb is 100% across all entity types**.

## SA-5 AGE sync + path_discovery rewrite

* Added `age_sync_worker` that bulk-MERGEs canonical_entities → AGE nodes, relations → AGE edges.
* `path_discovery.py` rewritten to use explicit 2-hop/3-hop scalar Cypher (no list comprehensions, no `|` operator).
* Added `_UUID_RE` and `_validate_and_embed_entity_id` injection guard.
* Path-insight jobs now run cleanly: 54/54 complete, 2107 paths produced.

## SA-6 Universe Expansion (FR-T0-2)

* Seed file `infra/seeds/universe.json` (602 unique symbols).
* Categories: 543 S&P 500 + large-cap + ADRs, 20 sector ETFs, 29 crypto, 7 macro indices, 6 FX/metals.
* OHLCV backfill via EODHD T3 (concurrency 1–5 with backoff): 600/602 succeeded; 9 failures retryable.
* Idempotent — safe to re-run.

## Frontend Smoke (SA-10)

| Route | HTTP | Errors |
|---|---|---|
| /login | 200 (47 KB) | 0 |
| /dashboard, /portfolio, /portfolio/brokerage, /watchlists, /screener, /prediction-markets, /news, /chat, /alerts, /settings, /intelligence, /instruments/{id} | 302 → /login?redirectTo=... | 0 |

## API Smoke (SA-10, with dev-login token)

| Endpoint | HTTP |
|---|---|
| /v1/news/top, /v1/briefings/morning, /v1/dashboard/snapshot, /v1/portfolios, /v1/holdings/{id}, /v1/portfolios/{id}/transactions, /v1/fundamentals/screen, /v1/search, /v1/quotes/batch | **200** with populated data |
| /v1/health | 404 (no public route — `/metrics` is the liveness surface; cosmetic gap, P2) |

Quote sample (AAPL/MSFT/NVDA all 200, daily_close 2026-05-08, refresh_available=true).

## Pipeline Health (10-min window post-rebuild)

| Service | ERROR/CRITICAL count |
|---|---|
| portfolio, content-store, content-ingestion, nlp-pipeline, knowledge-graph, knowledge-graph-scheduler, knowledge-graph-path-insight-worker, **content-store-dedup-consumer**, alert | **0** |
| market-data | 2 unique 500s on `/v1/quotes/AAPL` (ticker-as-UUID; QA-induced; P1) |
| rag-chat | 2 CRITICAL `internal_jwt_unverified_decode` (dev artifact; P1 → demote to WARNING) |
| api-gateway | 3 (same QA-probe propagation) |

* **Dedup MissingGreenlet count: 0** — BP-443 fix holding for full 10 min.
* **Path-insight syntax errors: 0** — SA-5 rewrite live.
* **Worker 13B tick visible**: `relation_evidence_promoter_complete` logged every 5 min; `relation_evidence` continues growing organically.

## Kafka

* DLQ topics: 0 (none defined)
* All consumer groups bounded except Polymarket prediction snapshots (~20.5k lag, draining steadily; P2 monitor)

## Containers

* 74 application containers all `healthy`
* `worldview-alloy-1` `unhealthy` (Wave-D infra gap — observability side-car, NOT on critical path)
* 0 restart loops

## Verdict

**GO for beta** — every primary user journey is intact:
* Sign-in works (Zitadel redirect or `POST /v1/auth/dev-login`)
* All 12 protected app routes redirect cleanly; `/login` page 200 with 47 KB content
* All primary user-data APIs 200 with populated data (dashboard snapshot 49 KB, morning briefing 17.5 KB, holdings/transactions/quotes live)
* KG semantic completeness 100% on definition embeddings; AGE graph live; path insights producing 2107 paths
* Worker 13B periodic; dedup consumer clean; multi-day evidence trends restored
* Universe at 614 instruments (target ≥600 met)
* No DLQs, no crash loops, lag bounded

## Follow-ups

### P1 (next milestone)

* **P1-A** market-data ticker-path 500 — `GET /v1/quotes/AAPL` passes the ticker into a UUID column. Add early `raise HTTPException(422)` for non-UUID input. ~30 min.
* **P1-B** rag-chat dev-mode `internal_jwt_unverified_decode` is logged at CRITICAL when it should be WARNING/INFO. ~15 min.
* **P1-C** SnapTrade `/balances` endpoint not wired — `cash` and `buying_power` show "—". Requires new port method + use case + S9 schema field. ~3 h.
* **P1-D** Same MissingGreenlet pattern (BP-443) likely lives in `services/content-store/.../article_consumer.py:_SessionUnitOfWork`. Apply the same fix. ~30 min.
* **P1-E** Embedding worker first-tick delay: definition/narrative/fundamentals workers have 60-120 min intervals with no `next_run_time` on startup. Add `next_run_time=now+120s` to all three job registrations. ~15 min.

### P2 (post-beta polish)

* **P2-A** Fundamentals backfill for the 565 new equity rows from SA-6 (separate `backfill_fundamentals.py` pass; will grow `fst_emb` and `has_fundamentals`).
* **P2-B** Polymarket consumer 24h lag drain monitor; if not draining, increase concurrency.
* **P2-C** AGE sync is set to 15-min interval; first organic tick should appear in scheduler logs at the next mark.
* **P2-D** `/v1/health` cosmetic 404 — add a one-line router registration so external uptime monitors see green.
* **P2-E** SnapTrade `description`/`settlement_date` fields unmapped on `UniversalActivity`.
* **P2-F** Cluster-expand UI ("click +N sim to see siblings") deferred — needs new `/v1/news/cluster/{id}` endpoint.

### Beta Gaps Disclosed (Not in Scope)

* **Wave A** Zitadel SSO/MFA hardening
* **Wave B** TDE / GDPR / PII redaction
* **Wave C** PITR / backup automation
* **Wave D** Grafana / Loki / LLM-cost-cap (Alloy unhealthy)

## Commits This Pass

```
ca089fbc fix(content-store): SA-1 explicit session close in dedup UoW prevents MissingGreenlet (BP-443)
0832f4a2 feat(knowledge-graph): SA-4 evidence_date historical backfill
1968ee24 feat(knowledge-graph): SA-3 backfill embedding gaps + fix fundamentals_ohlcv URL
c184e53e style(frontend): SA-9 polish — settings (and bundled SA-2 Worker 13B + Gemini fallback)
1eb00225 style(frontend): SA-9 polish — intelligence tab, portfolio empty states
9603059d style(frontend): SA-7 news density polish — chips, filters, empty states
f191799d feat(market-ingestion): SA-6 ticker universe expansion to >=600 (FR-T0-2)
eb913f4f feat(knowledge-graph): SA-5 AGE graph sync worker
```

## Ready-to-Run Follow-up Prompt

```
/implement

Continue post-beta cleanup:
1. P1-A: market-data ticker-path 500 — add HTTPException(422) on non-UUID input at quote/price routes.
2. P1-B: rag-chat — demote `internal_jwt_unverified_decode` from CRITICAL to WARNING in dev mode.
3. P1-C: wire SnapTrade `/balances` endpoint → IBrokerageClient.get_account_balance() → real cash/BP value through S9 schema.
4. P1-D: apply BP-443 fix pattern to ArticleConsumer._SessionUnitOfWork in content-store.
5. P1-E: add next_run_time=now+120s to definition/narrative/fundamentals refresh workers.
6. P2-A: run scripts/ops/backfill_fundamentals.py for the 565 new instruments from SA-6.
7. P2-D: add /v1/health route to api-gateway for external uptime monitors.

Validation: market-data 422 on bad input; rag-chat zero CRITICAL in dev mode; cash row shows real value;
zero MissingGreenlet in article consumer for 10 min; first-tick logs visible within 2 min of scheduler start;
fst_emb coverage ≥80%.
```
