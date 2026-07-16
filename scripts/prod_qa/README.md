# prod-QA harness (`scripts/prod_qa`)

A **large, durable, read-only** production QA suite for the live worldview
platform (Hetzner single-node k3s). It extends the philosophy of the single-file
`scripts/prod_e2e_smoke.py` with **granular, per-service functional assertions**
so any small regression is detectable on a re-run — not just "is it up?".

131 checks across 8 layers, every one PASS / WARN / FAIL with an actionable
message. **Nothing writes to prod**: DB access is `SELECT`-only, the API prober
only reads (plus one idempotent, rate-limited description-refresh trigger), and
no cluster state is mutated.

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
| `rag_chat` (S8) | grounded chat | golden Q → answer names the company + grounds a `$` price; `rag_db` persistence schema present |
| `portfolio` (S1+S2) | tenant + upstream ingest | schema present, `/readyz`, instrument-cache populated, S2 ingestion throughput + no stuck leases |
| `alert` (S10+S9) | alerts + gateway contract | alert schema + rule-type CHECK includes `PREDICTION`, worker pods up, **N backend families reachable via the prober** (BFF proxy wired), gateway `/healthz` |

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
    ├── rag_chat.py         # S8
    ├── portfolio.py        # S1 + S2
    └── alert.py            # S10 + S9 gateway contract
```
