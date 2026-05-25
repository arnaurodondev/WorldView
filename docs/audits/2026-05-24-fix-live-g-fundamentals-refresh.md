# FIX-LIVE-G — FundamentalsRefreshWorker `market_data_unavailable` investigation

**Date**: 2026-05-24
**Agent**: FIX-LIVE-G
**Branch**: `feat/plan-0093-remediation`
**Source of truth**: `docs/audits/2026-05-24-qa-plan-0093-phase-5c-investigation-report.md` (INV-LIVE-E)
**Status**: PARTIAL FIX shipped (observability) + 2 follow-up plans recommended

---

## TL;DR

INV-LIVE-E hypothesised that the 100% `fundamentals_refresh_market_data_unavailable`
failure rate was caused by missing service-account JWT / auth misconfiguration
between `knowledge-graph-scheduler` and `market-data`. **The hypothesis was wrong.**

The actual root cause is **two compounding data/contract issues**, neither of
which is fixable inside the worker:

1. **Data-availability gap (98% of failures)** — 49/50 sampled tickers in
   `entity_embedding_state` (view_type=`fundamentals_ohlcv`) do not exist as
   instruments in market-data. Knowledge graph seeds ticker entities from
   news mentions (foreign exchanges, crypto pairs, obscure US tickers), but
   market-data only ingested ~629 US large-cap instruments. The lookup
   returns 404 and the worker correctly aborts that entity.

2. **Response-shape mismatch (latent — would block the remaining 2% anyway)** —
   `_build_fundamentals_narrative` reads fields (`revenue_usd_millions`,
   `gross_margin_pct`, `pe_ratio`, `price`, `week_52_high`, `week_52_low`)
   that do **not** exist on the `/api/v1/fundamentals/{id}` response. That
   endpoint returns sectioned records (`{security_id, records: [{section,
   period_type, data}]}`). All field reads return None, the deterministic
   narrative builder emits the stub "No financial data available", and the
   embedding written would be useless even for the 2% of entities that have
   ingested fundamentals.

This document captures the investigation, the partial observability fix that
WAS shipped, and the two follow-up plans needed to close the SLO gap
(`fundamentals_ohlcv: 0/2405` embedding coverage).

---

## Reproduction (what INV-LIVE-E would have found with one more step)

```bash
# Step 1 — confirm warning is real (it is)
docker logs worldview-knowledge-graph-scheduler-1 2>&1 | grep -c "fundamentals_refresh_market_data_unavailable"

# Step 2 — confirm JWT auth actually works (it does — the hypothesis was wrong)
docker exec worldview-knowledge-graph-scheduler-1 python -c "
import httpx, jwt, time
payload = {'iss':'worldview-gateway','sub':'system:test','user_id':'00000000-0000-0000-0000-000000000000','tenant_id':'00000000-0000-0000-0000-000000000000','role':'system','iat':int(time.time()),'exp':int(time.time())+3600}
token = jwt.encode(payload, 'dev-skip-verification-key-for-kg-fundamentals', algorithm='HS256')
r = httpx.get('http://market-data:8003/api/v1/instruments/lookup?symbol=AAPL', headers={'X-Internal-JWT': token}, timeout=10.0)
print('status:', r.status_code, 'body:', r.text[:200])
"
# → status: 200 — AAPL resolves, JWT accepted
```

```text
KG scheduler env:
  KNOWLEDGE_GRAPH_INTERNAL_JWT_SKIP_VERIFICATION=true  # client-side hint
  KNOWLEDGE_GRAPH_MARKET_DATA_BASE_URL=http://market-data:8003
  (no KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY — falls back to HS256 dev token)

market-data env:
  MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true  # accepts any JWT in dev
```

Auth is correctly wired. The startup-time warning `structured_enrichment_no_rs256_key`
is informational — the HS256 dev fallback is the *expected* dev-mode path.

## Real root-cause measurement (100-ticker sample of due entities)

```text
Total due entities sampled: 100 (with non-null ticker)
  lookup OK (instrument exists in market-data):     1
  lookup 404 (no instrument):                      99
  fundamentals OK (200 + valid data):               0
  fundamentals 404 (instrument w/o fundamentals):   1
  fundamentals body had revenue_usd_millions field: 0   ← shape mismatch
```

## Embedding-state composition (`entity_embedding_state` rows where view_type=fundamentals_ohlcv)

```text
total_rows       : 2405
with_ticker      : 1100   ← currently chase a market-data lookup
null_ticker      : 1305   ← skipped (no-ticker entities — handled by tombstone path)
distinct_tickers : 946
```

## Market-data instrument coverage

```text
canonical_entities distinct tickers : 949
market_data instruments             : 629   ← ~34% gap; covers ~8/10 top US tickers
```

Foreign exchanges (`.KS`, `.SZ`, `.HK`, `.T`, `.MI`, `.F`, `.DU`, `.MX`,
`.HM`, `.PA`), crypto pairs (`AAVE-USD`, `BTC-USD`, `SOL.USD`), and many
obscure US tickers (`ACKY`, `ACMR`, `XSD`, `T-PA`, `JPM-PD`) are absent
from market-data.

---

## Why INV-LIVE-E's auth hypothesis felt plausible

The HS256 dev fallback emits a startup warning that *reads* like an auth
problem (`KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY is empty; MarketDataClient
will sign HS256 dev tokens — production S3 will return 401 unless
MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true`). That warning + the 100%
`market_data_unavailable` rate triggered the JWT hypothesis. The
hypothesis was disprovable in one curl, but the generic warning name
encouraged confirmation bias.

This is the root cause of the **observability gap** that FIX-LIVE-G addresses.

---

## Fix shipped (observability only)

`services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py`:

1. `_build_fundamentals_narrative` now returns `(narrative, failure_reason)`
   where `failure_reason ∈ {None, "fundamentals_transport_error",
   "fundamentals_http_{status}", "fundamentals_json_decode_failed"}`. It also
   emits the same per-call `market_data_call_ok` / `market_data_call_client_error` /
   `market_data_call_server_error` log lines as `_fetch_json` (with URL,
   ticker, latency, body size, status code) so the fundamentals path is no
   less observable than the lookup / earnings / profile paths.

2. `_process_entity_io` carries the precise `failure_reason` (either
   `"instrument_lookup_failed"` from the resolve step, or the narrative
   tuple's failure_reason from the fetch step) on the result dict.

3. Phase 3 `fundamentals_refresh_market_data_unavailable` warning now
   includes `failure_reason=<reason>`. A per-cycle `failure_counts` dict
   aggregates the categories and is surfaced as `failure_breakdown` on the
   summary `fundamentals_refresh_worker_complete` event.

### Live before/after

```text
Before:
  fundamentals_refresh_market_data_unavailable entity_id=… ticker=NFLX
  fundamentals_refresh_worker_complete refreshed=0 skipped_non_ticker=0
    earnings_events_inserted=0 relations_upserted=0 backoff_escalations=50
    backoff_resets=0

After:
  fundamentals_refresh_market_data_unavailable
    entity_id=0195daad-… failure_reason=fundamentals_http_404 ticker=NFLX
  fundamentals_refresh_market_data_unavailable
    entity_id=fd3dbc07-… failure_reason=instrument_lookup_failed ticker=VGT
  fundamentals_refresh_worker_complete
    refreshed=0 skipped_non_ticker=0 earnings_events_inserted=0
    relations_upserted=0 backoff_escalations=50 backoff_resets=0
    failure_breakdown={'fundamentals_http_404': 1, 'instrument_lookup_failed': 49}
```

### Regression tests (`TestFundamentalsRefreshFailureObservability`)

- `test_instrument_lookup_404_emits_failure_reason` — pins that lookup 404
  yields `failure_reason=instrument_lookup_failed` AND appears in the
  `worker_complete` breakdown.
- `test_fundamentals_http_404_emits_failure_reason_with_status` — pins that
  a fundamentals 404 yields `failure_reason=fundamentals_http_404`
  (distinct from the lookup-miss case).
- `test_fundamentals_http_401_emits_failure_reason_with_status` — pins that
  if auth ever really does break (the INV-LIVE-E hypothesis), the log will
  say `failure_reason=fundamentals_http_401` explicitly + emit
  `market_data_call_client_error status_code=401` on the per-call line.
  No more guessing for the next investigator.

20/20 unit tests pass (17 pre-existing + 3 new).

---

## What is NOT fixed and why

### Embedding coverage `fundamentals_ohlcv: 0/2405`

This SLO gap is unchanged. The coverage will stay at zero (or near zero)
until BOTH of the following are addressed in separate plans:

**Plan A — market-data instrument backfill (or KG seeding filter)**

The KG seeds ~950 distinct tickers into `entity_embedding_state` from news
mentions, but market-data only has ~629 US large-cap instruments. Options:

- A1: expand market-data EODHD ingestion to cover foreign exchanges / crypto /
  obscure US tickers actually referenced in news (likely impractical — would
  triple the EODHD bill).
- A2: filter KG `entity_embedding_state` seeding to only tickers that
  resolve in market-data (a one-time `DELETE` + an INSERT-time guard).
- A3: leave the gap as-is, but tombstone unresolved tickers with a long
  `next_refresh_at` so the worker stops retrying them every 2h (current
  backoff escalation already does this partially).

**A2 + A3 combined is the recommended minimum.**

**Plan B — response-shape contract fix in `_build_fundamentals_narrative`**

Even for the ~2% of entities whose lookup succeeds, the narrative builder
reads field names (`revenue_usd_millions`, `gross_margin_pct`, `pe_ratio`,
`price`, `week_52_high`, `week_52_low`) that **do not exist** in any
market-data response.

- The `/api/v1/fundamentals/{id}` endpoint returns sectioned records
  (`{security_id, records: [{section, period_type, data: {...EODHD raw...}}]}`).
- The `/api/v1/fundamentals/{id}/snapshot` endpoint returns a flat object
  with `eps_ttm`, `beta`, `avg_volume_30d`, `free_cash_flow`, etc. — but
  NOT `revenue_usd_millions` or `gross_margin_pct`.
- The `/api/v1/fundamentals/screen` endpoint returns instruments with a
  `metrics: {pe_ratio, revenue_usd, gross_margin_pct, ...}` dict — the
  only place where the worker's expected field set actually lives.

`build_fundamentals_narrative` is a deterministic builder that gracefully
emits the stub "No financial data available" when all fields are None — so
even for the 2% with valid lookups, the worker would write a useless
embedding. The fix is either:

- B1: change `_build_fundamentals_narrative` to call `/fundamentals/screen`
  filtered to the single instrument (it returns the right shape).
- B2: build a new market-data endpoint (`/fundamentals/{id}/narrative` or
  similar) that returns the exact field set the narrative builder needs.

**B1 is the lower-risk option** because it reuses an existing, tested
endpoint. It belongs in a `Worker 13D-3 narrative source` follow-up plan.

---

## Validation

- 20/20 unit tests pass (`tests/unit/infrastructure/workers/test_fundamentals_refresh_worker.py`)
- `ruff check` clean on touched files
- `mypy` — only pre-existing missing-stub warnings on `openai` / `attr` in
  unrelated libs; no new errors from this change
- Live re-verify: rebuilt + restarted `worldview-knowledge-graph-scheduler-1`,
  ran the worker manually on 50 due entities, confirmed
  `failure_breakdown={'fundamentals_http_404': 1, 'instrument_lookup_failed': 49}`
  appears on the summary event and each per-entity warning carries
  `failure_reason=…`. Embedding coverage remains 0/2405 (expected — this
  is an observability fix, not a coverage fix).

---

## Surprises

1. **The auth hypothesis from INV-LIVE-E was wrong.** Both
   `KNOWLEDGE_GRAPH_INTERNAL_JWT_SKIP_VERIFICATION=true` (client hint) and
   `MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true` (server bypass) are
   set, and JWT requests succeed with 200. The startup warning is misleading
   in dev mode and contributed to the wrong hypothesis.
2. **The narrative builder's field set has no matching market-data
   endpoint.** Even if the data gap were fixed, the worker would still
   produce stub narratives. This is a latent bug that has been present
   since the worker was first implemented and that no embedding-coverage
   metric would have caught — `entity_embedding_state.embedding` would
   simply contain vectors for "No financial data available" strings.
3. **The pre-existing per-call logging from PLAN-0093 D-2
   (`market_data_call_client_error` with status_code) was already strong**
   — the gap was purely at the *aggregate* level. Ops could see "this one
   ticker got 404" but had to manually count 1100 log lines to see "98%
   were lookup-misses, 2% were data-misses, 0% were auth." The
   `failure_breakdown` summary closes that loop.

---

## Recommended follow-up plans (out of scope for FIX-LIVE-G)

1. **PLAN-XXXX-A** — KG / market-data ticker coverage alignment (Plan A2 + A3
   above). Estimated 1-2 waves: schema migration + backfill script + dev
   smoke test. Closes 95% of the SLO gap by definition.
2. **PLAN-XXXX-B** — Worker 13D-3 narrative source contract (Plan B1
   above). Estimated 1 wave: rewire `_build_fundamentals_narrative` to call
   `/fundamentals/screen?...&filters=[{instrument_id: ...}]`, map metric
   names, regression test. Closes the remaining gap for instruments that
   DO have fundamentals data.
