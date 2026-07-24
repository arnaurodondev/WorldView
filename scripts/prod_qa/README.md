# prod-QA harness (`scripts/prod_qa`)

A **large, durable, read-only** production QA suite for the live worldview
platform (Hetzner single-node k3s). It extends the philosophy of the single-file
`scripts/prod_e2e_smoke.py` with **granular, per-service functional assertions**
so any small regression is detectable on a re-run — not just "is it up?".

~161 checks across 8 layers, every one PASS / WARN / FAIL with an actionable
message. **Nothing writes to prod**: DB access is `SELECT`-only, the API prober
only reads (plus one idempotent, rate-limited description-refresh trigger, and
a read-only internal-JWT auth probe), and no cluster state is mutated.

> **v2 (2026-07-15 session regressions).** 20 checks were added so every P0/P1/
> HIGH issue this session surfaced — MinIO-full write-halt, the content-ingestion
> outbox backlog, empty `fundamentals_ohlcv` embeddings, the KG→market-data
> internal-JWT rejection, absent daily OHLCV, unlinked prediction markets, the
> gliner OOM + nlp poison-pill restart storms, missing `*-secrets`, and the chat
> false-refusal / no-citation defects — is caught on a re-run. See
> **v2 regression checks** below for each check and the regression it guards.

> **v3 (2026-07-16 edge-case hardening).** +11 checks closing gaps the byte-only /
> presence-only guards missed, plus flakiness recalibration:
>
> | New check (layer) | Regression it guards |
> |-------------------|----------------------|
> | `inodes free {vol}` — df **-i** on each state PVC (coarse) | Inode exhaustion from the tiny-object polymarket firehose — MinIO can hit its inode cap (75% used) with bytes only 41% full, halting all writes. The byte-check saw nothing. |
> | `MinIO lifecycle expiry on re-fetchable buckets` (coarse) | bronze/silver grow unbounded without an expiry rule → re-exhaust inodes. Catches `worldview-silver` having **no** rule (bronze got a 7-day one after the P0). |
> | `referenced *-secrets stable across two samples` (coarse) | A helm-secrets / GC prune deleting a secret still referenced by running pods — invisible to a single presence snapshot; caught by re-sampling and diffing. |
> | `internal-JWT signing keys non-empty (all signers)` (coarse) | The D1 empty-key 401 class generalised beyond KG→market-data: scans **every** signer pod's `*_INTERNAL_JWT_PRIVATE_KEY` for an empty/placeholder value. |
> | `schema-registry compat FULL_TRANSITIVE` (coarse) | Now reached from **inside** the gateway pod (was an always-WARN host-side curl that never verified). Asserts global compat + subject count. |
> | `intraday OHLCV per-timeframe fresh` (market_data) | A stalled resampler for ONE intraday timeframe — the aggregate freshness check hides it behind a fresh 1m bar. Judges the stalest intraday tf on its own clock. |
> | `daily OHLCV bar fresh (weekend-tolerant)` (market_data) | A dead daily feed, judged on a weekend-tolerant clock (daily closes once/session). |
> | `relevance scorer active (scored/24h)` (nlp_pipeline) | The LLM relevance scorer stalling — a backfill-dilution-proof liveness signal (recent scoring RATE) replacing the flappy coverage-% floor. |
> | `relation_evidence DEFAULT partition bounded` (knowledge_graph) | Rows falling through every monthly range into the DEFAULT partition (retention/partition-worker failure). |
> | `monthly-partition worker provisioned current+next month` (knowledge_graph) | The month-ahead partition worker wedging → next month's evidence lands in DEFAULT. |
>
> **Recalibrations (flakiness / miscalibration fixes):**
> - `consumer lag bounded` is now **member-aware**: a group WITH live members and a
>   large lag is a draining backfill → WARN, not FAIL (the 195k-doc news backfill
>   drove nlp-pipeline-group to ~187k while consuming healthily). FAIL only when the
>   worst group has **0 members** and real lag, or lag exceeds `KAFKA_LAG_FAIL_HARD`.
> - `relevance-scoring coverage %` floor 60→10 (structurally low; backfill/dedup docs
>   legitimately bypass scoring). The liveness signal moved to `scored/24h` above.
> - `intraday staleness` WARN 4h→6h (clears the 4h timeframe's own bar interval so it
>   doesn't flap at the boundary); `evidence promoter drain` floor 20→15 (its steady
>   state is ~18%, so 20 hugged the boundary and permanently WARNed).

## Running it

```bash
# tunnel to prod (only if the SSH tunnel is down):
ssh -f -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -L 6443:127.0.0.1:6443 root@116.203.198.118

export KUBECONFIG=~/.kube/config-worldview       # prod context

# from the repo root (it is a package — use -m):
python3 -m scripts.prod_qa.run                   # full suite (~3-4 min)
python3 -m scripts.prod_qa.run --only coarse,market_data
python3 -m scripts.prod_qa.run --skip rag_chat   # rag chat generation is slow
python3 -m scripts.prod_qa.run --json out.json --quiet
```

Exit code is `0` when there are no FAIL rows (WARNs are allowed), `1` otherwise —
so it drops straight into CI or a CronJob.

> The run makes many `kubectl exec` calls over the tunnel; each round-trip costs
> ~1-3 s, so a full run takes a few minutes. Postgres queries are **batched one
> `exec` per DB** (`harness.psql_many`) to keep it tractable.

## The in-pod JWT technique

Prod runs real Zitadel OIDC and `/v1/auth/dev-login` is disabled, so the public
front door needs an interactive browser token we cannot get headlessly. The
authenticated data-plane checks therefore run a prober **inside the api-gateway
pod** (`prober.py`): it loads the gateway's OWN internal RS256 signing key and
mints the exact `X-Internal-JWT` the gateway attaches when proxying downstream,
then calls each backend over ClusterIP. This exercises the real routes /
processes / data through the same trust path the gateway uses. Layer `coarse`
separately proves the public Zitadel gate is present and rejecting unauth
traffic (`401` on `/v1/...`, `403` on `/metrics`).

## Layers

| Layer | Scope | Sample assertions |
|-------|-------|-------------------|
| `coarse` | platform/infra | every pod Ready, no crashloops, all migrations at expected head (stale-image vs pending-migrate disambiguated), Kafka **and** Postgres DLQs empty, expected consumer groups present + live members + bounded lag, outbox dispatchers draining, schema-registry FULL compat, `:80→301`, HTTPS+TLS, unauth`→401`, MinIO buckets |
| `market_data` (S3) | quotes/OHLCV/fundamentals/prediction | non-stale OHLCV with sane closes, fundamentals coverage floor, all 7 timeframes, `is_partial⇒is_derived`, prediction snapshots/prices/trades floors + freshness, screener returns matches |
| `knowledge_graph` (S7) | entity intel + graph | AAPL grounded facts (name/type/ticker/**ISIN** — anti-fabrication), relation density + type diversity, description/embedding coverage, **AGE** vertex+edge liveness, evidence-promoter drain, prediction entity-linking |
| `nlp_pipeline` (S6) | enrichment | chunks + embeddings-ready %, NER mentions/24h (GLiNER-alive), routing 3-tier spread, relevance coverage, no poison embeddings, ANN search, synthetic CJK embed E2E |
| `content` (S4+S5) | ingestion/store | news freshness + 24h volume, title coverage (SEC primary-doc fix), source mix, task failure ratio, DLQ bounded |
| `duplicate_groups` | cross-service identity dedup | `GROUP BY <normalized-key> HAVING count(*) > 1` on `instruments`, `canonical_entities`, `prediction_markets`; junk exchange-prefixed canonical names; `event_id IS NULL` floor guard — see **duplicate-group scanner** below |
| `rag_chat` (S8) | grounded chat | golden Q → answer names the company + grounds a `$` price; `rag_db` persistence schema present |
| `portfolio` (S1+S2) | tenant + upstream ingest | schema present, `/readyz`, instrument-cache populated, S2 ingestion throughput + no stuck leases |
| `alert` (S10+S9) | alerts + gateway contract | alert schema + rule-type CHECK includes `PREDICTION`, worker pods up, **N backend families reachable via the prober** (BFF proxy wired), gateway `/healthz` |

## v2 regression checks (2026-07-15 session)

Each of these was **added to catch a specific issue this session surfaced** — it
FAILs (or WARNs) on the broken state and PASSes once fixed. They are wired into
the existing layers/runner, so `python3 -m scripts.prod_qa.run` includes them.

| Layer | Check | Guards against |
|-------|-------|----------------|
| `coarse` | `disk free {minio,postgres,kafka}` | **P0-B**: MinIO `/export` filled its PVC → `XMinioStorageFull` halted every PutObject and stalled the 88k content-store backlog. Free-% + absolute-bytes floors alert before a data volume wedges. |
| `coarse` | `outbox per-table backlog + age bounded` | content-ingestion hit **111k** undispatched outbox rows; a global sum can mask one wedged service, and a few *very old* undispatched rows signal a stuck dispatcher a `>10m`-count check misses. Judges every outbox table on backlog size **and** oldest-undispatched age. |
| `coarse` | `referenced *-secrets all present (roll-safe)` | roll-fragility: a running pod keeps its injected Secret in memory, so a deleted `*-secrets` is invisible until the next roll fails to start the pod. Diffs live non-optional refs vs present secrets. |
| `coarse` | `prod-smoke last N jobs succeeded` | the `monitoring/prod-smoke` synthetic CronJob was flapping `Failed 0/1`; asserts the most-recent N Jobs are all Complete (`KubeJobFailed` = earliest data-plane regression signal). |
| `coarse` | `restart-rate bounded ({gliner, nlp/content article-consumers})` | **P1-A** gliner OOM (~3/h at the 12Gi cap) and **P0-A** nlp article-consumer poison-pill. Uses restarts/pod-age-hours so a recently-recreated (count-reset) pod that is still storming is still caught. |
| `market_data` | `daily OHLCV distinct dates` / `bars/instrument` | **F1/D2**: `1d` held ~1 bar/instrument over 3 dates → returns/price-levels/heatmap all null. Asserts real multi-day daily history. |
| `market_data` | `prediction market→event linkage %` | **D6**: every one of 101 `prediction_markets` had `event_id` NULL despite a populated `prediction_events`. Asserts the market→event FK is set. |
| `knowledge_graph` | `fundamentals_ohlcv embedding coverage %` | **D1**: the view was 100% empty (NULL embedding + empty `source_text`) while `last_refreshed_at` was current. |
| `knowledge_graph` | `no stamped-but-empty embedding view` | generic form of D1: any `view_type` whose worker stamped `last_refreshed_at` on many rows but wrote `source_text` on almost none = "reports success, persists nothing". Applies across all view_types so a *new* view regressing the same way is caught. |
| `knowledge_graph` | `prediction consumer live+bounded ({kg-prediction-enriched,-move}-group)` | PLAN-0056 entity-linking: if these two Kafka consumers are absent/lagging, prediction temporal events + exposure polarity never populate. Asserts both present, with members, bounded lag. |
| `knowledge_graph` | `internal-JWT KG→market-data signs+verifies` | **D1 root cause / empty-key class**: mints the FundamentalsRefreshWorker's exact `X-Internal-JWT` inside the KG pod and calls market-data; a **401** means the signing key is empty and market-data rejects every call — silently deferring all fundamentals_ohlcv embeddings. |
| `rag_chat` | `grounded answer carries citation URLs` | **F3**: answers returned `citations:[]` / `{url:null}` — grounding source-links lost. |
| `rag_chat` | `date-anchored fundamentals returns stored value` | chat falsely refused ("not available") **and confabulated the period to Q4 2026** for MSFT FY-Q4-2024 revenue that IS in the store. Asserts no false refusal + the value appears. |
| `rag_chat` | `prediction-market question invokes the tool` | Trump-2028 markets are live but chat routed GENERAL and gave a generic "data unavailable" refusal. Asserts the answer engages the market rather than refusing. |

The chat golden questions are templated into the in-pod prober from
`thresholds.py` (single source of truth). Chat calls that time out on a
cold-start hang return `-1` → the check **WARNs** (a latency hazard, not a
correctness verdict) rather than crashing the run.

## Duplicate-group scanner (`checks/duplicate_groups.py`, 2026-07-24)

This platform has hit the same bug shape three times, each time only
discovered by hand-running a `GROUP BY <key> HAVING count(*) > 1` query after
a support ticket or manual audit: **BP-459** (two independent
`canonical_entities`-minting pipelines racing on the same ticker), **BP-743**
(a placeholder `exchange=''` `instruments` row coexisting with a later
real-exchange row for the same symbol), and **BP-700** (an unnormalized
exchange-suffixed ticker minting a duplicate tickerless canonical, and
producing junk `"NYSE: BCS"`-shaped canonical names). `duplicate_groups.py`
makes the detection queries from each of those bug-pattern write-ups a
standing, table-driven layer so a fourth occurrence surfaces on the next run:

| Check | Table | Guard |
|-------|-------|-------|
| duplicate symbol (case-insensitive) | `instruments` (market_data_db) | BP-743 |
| duplicate ticker | `canonical_entities` (intelligence_db) | BP-459 |
| duplicate name+type (secondary) | `canonical_entities` (intelligence_db) | BP-459 |
| duplicate `market_id` | `prediction_markets` (market_data_db) | BP-743 (sibling) |
| duplicate `market_slug` (case-insensitive) | `prediction_markets` (market_data_db) | BP-743 (sibling) |
| junk exchange-prefixed name (`^[A-Z]+:\s`) | `canonical_entities` (intelligence_db) | BP-700 |
| `event_id IS NULL` floor (SOFT — total-collapse guard, not zero-tolerance) | `prediction_markets` (market_data_db) | BP-743 (sibling) |

Every hard check is **zero-tolerance** (FAIL on any count > 0) — this is a
completeness scanner, not a coverage floor, and every historical nonzero
reading on one of these queries was a confirmed bug, never backfill noise.
Extend `DUP_GROUP_CHECKS` the next time this shape fires against a new table.

**Validation note**: this check's query-building/threshold logic is covered by
unit tests in `tests/prod_qa/test_duplicate_groups.py` (no live prod
Postgres access was available in the environment that authored this check —
see that test file for what was and wasn't exercised against a real cluster).

## Tuning

Every numeric floor is a **named constant in `thresholds.py`** with a HARD (FAIL)
/ SOFT (WARN) classification, calibrated just below the observed steady state so a
re-run catches a real regression without flapping. Update a floor there — never
inline — when the platform's healthy baseline moves. `EXPECTED_ALEMBIC_HEADS`
must be re-generated on every migration merge (same map the smoke test keeps).

## Structure

```
scripts/prod_qa/
├── run.py            # top-level runner (--only/--skip/--json/--quiet)
├── harness.py        # PASS/WARN/FAIL plumbing, kubectl/psql/kafka helpers, Ctx
├── prober.py         # consolidated in-pod API prober (mints internal JWT)
├── thresholds.py     # every floor + expected-heads map (the tuning knob)
└── checks/
    ├── coarse.py           # platform/infra
    ├── market_data.py      # S3
    ├── knowledge_graph.py  # S7 (+ AGE)
    ├── nlp_pipeline.py     # S6
    ├── content.py          # S4 + S5
    ├── duplicate_groups.py # cross-service identity dedup (BP-459/BP-743/BP-700)
    ├── rag_chat.py         # S8
    ├── portfolio.py        # S1 + S2
    └── alert.py            # S10 + S9 gateway contract
```
