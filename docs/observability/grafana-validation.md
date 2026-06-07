# Grafana Validation Harness

> Stub — full content authored by PLAN-0107 C-2 (recording rules + harness
> promotion). This file currently hosts the C-5 Loki ingestion audit only.

The harness lives at `scripts/grafana_validation.sh` (after C-2 lands) and is
invoked via `make grafana-validate`. Output categories (OK / EMPTY-OK / BROKEN /
LOGQL-SKIP) are documented in `docs/observability/dashboards.md`.

## Loki ingestion coverage

*Audit timestamp:* 2026-06-05 (PLAN-0107 C-5).

### Current state (queried via Loki HTTP API)

- `GET /loki/api/v1/labels` → `data: ["service_name"]` (1 label).
- `GET /loki/api/v1/label/service_name/values` → `data: ["unknown_service"]`
  (1 value; **all** container logs are bucketed under a single stream).
- `GET /loki/api/v1/label/container/values` → empty.
- `GET /loki/api/v1/label/service/values` → empty.

Querying `{service_name="unknown_service"}` over the last 5 min returns logs,
confirming Alloy is shipping to Loki and the docker discovery + keep regex are
working at the ingest layer — but the per-container identity is not propagating
to indexed stream labels.

### Running container coverage

`docker ps` reports 76 containers, 59 of which match the worldview app prefix
list (portfolio, market-ingestion, market-data, content-ingestion, content-store,
api-gateway, nlp-pipeline, knowledge-graph, rag-chat, alert, worldview-web). All
59 are matched by the current Alloy `keep` regex; the PLAN-0107 B-3 worker
container names (alert-dispatcher, content-ingestion-scheduler,
knowledge-graph-instrument-discovered-consumer, market-data-ohlcv-consumer,
market-data-dispatcher, nlp-pipeline-entity-refresh-consumer,
portfolio-instrument-consumer, rag-chat-brief-scheduler) all share one of those
service prefixes and are therefore captured by the existing alternation. **No
container is dropped by the keep regex.**

### Current Alloy keep regex

```
/(portfolio|market-ingestion|market-data|content-ingestion|content-store|api-gateway|nlp-pipeline|knowledge-graph|rag-chat|alert|worldview-web).*
```

(see `infra/alloy/config.alloy` `loki.relabel "docker"` block).

### Gap identified — NOT the keep regex

The keep regex is correct; the gap is the **service-name relabel target**. The
current rule writes the captured group to target_label `service`, but Loki's
default stream label set indexes `service_name` (not `service`). Result: every
log stream collapses to `service_name=unknown_service` and the B-5 panel
(`sum by (service_name) (count_over_time({job=~".+"} |= "_ready" [5m]))`) cannot
distinguish workers. Likewise the existing `api-usage-analytics` and
`error-observability` LogQL panels lose their `service`/`job` axis.

### Recommended fix (deferred — not in this wave's scope)

Add a second relabel rule in `infra/alloy/config.alloy` writing the captured
service name to `service_name` (and a `job` label mirroring it), e.g.:

```
rule {
  source_labels = ["__meta_docker_container_name"]
  target_label  = "service_name"
  regex         = "/worldview-(.*)-\\d+"
  replacement   = "$1"
}
rule {
  source_labels = ["__meta_docker_container_name"]
  target_label  = "job"
  regex         = "/worldview-(.*)-\\d+"
  replacement   = "$1"
}
```

Restart Alloy (`docker compose restart alloy`), then re-verify with
`curl -s http://localhost:3100/loki/api/v1/label/service_name/values | jq .data`
— the list should expand from `["unknown_service"]` to one entry per running
worker.

This fix is scoped to a follow-up wave because it is paired with the B-4 banner
sweep (which emits the `_ready` events the new label axis is designed to
surface). Filing as **FU-OBS-LOKI-LABELS** for cross-reference.

### Happy-state acceptance for this audit

- Alloy is up, shipping, and the keep regex covers every running worldview
  app container — confirmed.
- No new worker container introduced by PLAN-0107 B-3 is excluded by the
  keep alternation — confirmed.
- The next-layer issue (single-stream collapse to `unknown_service`) is
  documented above and tracked as a follow-up rather than left silent.
