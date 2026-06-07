# Grafana Dashboard Validation Harness

`scripts/grafana_validation.sh` walks every dashboard JSON in
`infra/grafana/dashboards/`, extracts every panel's PromQL/LogQL `expr`, and
posts each query to the local Grafana datasource-proxy
(`POST /api/ds/query`). Results are classified and emitted as a TSV.

## How to run

```bash
make grafana-validate
```

Prerequisites:

- Grafana available at `http://localhost:3000` (default `make dev` stack)
- Prometheus + Loki provisioned (recording rules + scrape targets up)
- `admin:admin` credentials (default `make dev`)
- `python3`, `curl`, `jq`-free (script uses Python for JSON)

To stream the TSV to stdout instead of writing a file:

```bash
bash scripts/grafana_validation.sh --stdout
```

## Output

Default location: `build/grafana_validation_results.tsv` (gitignored).

Columns:

| Column        | Meaning                                                |
|---------------|--------------------------------------------------------|
| dashboard     | Dashboard filename without `.json`                     |
| panel_title   | Panel `title` field                                    |
| datasource    | `prometheus` or `loki`                                 |
| query         | The `expr` (newlines flattened to spaces)              |
| frames        | Number of frames Grafana returned                      |
| series        | Number of non-empty series                             |
| sample_value  | Last numeric value from the first numeric column       |
| status        | One of `OK`, `EMPTY-OK`, `BROKEN`, `LOGQL-SKIP`        |
| error         | Error message if `BROKEN`                              |

## Status categories

- **OK** — Prometheus returned at least one frame with at least one non-empty series. Sample value populated.
- **EMPTY-OK** — Query parsed and executed successfully but returned zero series. Common for low-traffic or recently-deployed metrics; not an error.
- **BROKEN** — Prometheus returned a 4xx/5xx response, a `results.A.error`, or the proxy raised an exception. Query string is malformed, a metric label is wrong, or the recording rule is missing.
- **LOGQL-SKIP** — Loki query; the harness does not currently validate LogQL. Inspect manually in Explore.

## Exit codes

- `0` if `BROKEN == 0`
- `1` otherwise

This makes the script CI-safe: any panel breakage fails the pipeline.

## Typical workflow

1. Edit a dashboard JSON or rename a metric.
2. `make dev` is running locally.
3. `make grafana-validate`.
4. If any rows show `BROKEN`, inspect the `error` column for the failing PromQL and fix the dashboard or the recording rule.
5. Re-run until the script exits 0.

## Related

- `scripts/check_dashboard_datasource_uids.py` — datasource-UID contract test (runs in `tests/observability/`).
- `infra/prometheus/rules/recording-rules.yml` — recording rules dashboards rely on (`job:outbox_dispatched:rate5m`, etc.).
- `docs/plans/0107-observability-followups-plan.md` §C — origin of this harness.
