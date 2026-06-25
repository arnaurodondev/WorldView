# Dashboards — EMPTY-OK Panel Registry

## Purpose

A panel that returns zero series is **not** automatically a bug. Many Worldview panels
are correctly defined but only render data once the relevant traffic flows
(scheduled fetchers tick, consumers commit, errors fire, Loki ships logs). The
`scripts/grafana_validation.sh` harness (PLAN-0107 C-2) classifies each panel as
**OK**, **EMPTY-OK**, **BROKEN**, or **LOGQL-SKIP**; any panel listed in the
registry below is intentionally allowed to be empty under low local traffic and
should not be filed as a regression unless it stays empty after the documented
precondition is met.

## EMPTY-OK panel registry

| Dashboard | Panel(s) | Traffic precondition |
|---|---|---|
| `kafka-pipeline.json` | 10 panels using `kafka_messages_produced_total` / `kafka_consumer_lag` | Active Kafka producers/consumers; locally requires `make seed` and at least one ingest tick. |
| `eodhd-health.json` | 7 panels in the `s2_mi_provider_*` family | First scheduled provider fetch (hourly cron in `market-ingestion-scheduler`). |
| `worker-pipeline-throughput.json` | 2 path-insight panels | Knowledge-graph path-insight worker tick (driven by graph mutations). |
| `api-usage-analytics.json` | 4 LogQL panels | Loki ingestion of HTTP access logs from `api-gateway` (see C-5 audit). |
| `error-observability.json` | 5 LogQL panels | At least one `unhandled_exception` structlog event in Loki. |
| `service-overview.json` | Panels gated by the `$job` template variable | Harness limitation, not a dashboard bug: the validator substitutes a placeholder that does not match any series. Renders correctly in Grafana UI. |

Counts are approximate (snapshot from the most recent harness run); the source
of truth is the TSV under `build/grafana_validation_results.tsv`.

## Re-running the harness

```
make grafana-validate
```

Requires a local Prometheus + Grafana stack (`make dev`). The target writes
`build/grafana_validation_results.tsv` and exits non-zero only when `BROKEN > 0`.

## Adding a new panel to the registry

If you add a panel that legitimately renders empty under low local traffic:

1. Confirm the underlying query is well-formed (not BROKEN) by running
   `make grafana-validate` and inspecting the row for your panel.
2. Append a row to the table above with: dashboard filename, panel title (or
   count), and the precondition that must hold for the panel to render.
3. If the panel depends on a worker that does not yet emit traffic in default
   local dev, cross-link to the relevant PLAN/PRD that will eventually wire it.
4. Do **not** add panels whose queries reference non-existent metrics or labels
   (BROKEN). Those must be fixed at the dashboard or recording-rule layer, not
   suppressed via the registry.
