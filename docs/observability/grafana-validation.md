# Grafana / Observability Validation Notes

Operational notes for validating Grafana, Loki, Tempo and Alloy in the
worldview platform. Owned by PLAN-0107 (observability follow-ups).

---

## C-5 — Loki / Alloy service label

### Symptom

`GET /loki/api/v1/label/service_name/values` returns only
`["unknown_service"]`. Every log stream collapses into a single bucket
and the `workers-up.json` "Workers Ready (last 5 min)" panel (added in
PLAN-0107 B-5) returns zero series because its query is:

```logql
count_over_time({job=~".+"} |= "_ready" [5m]) by (service_name)
```

### Root cause

Alloy's `loki.relabel "docker"` block (`infra/alloy/config.alloy`) only
wrote the `service` target label:

```alloy
rule {
  source_labels = ["__meta_docker_container_name"]
  target_label  = "service"
  regex         = "/worldview-(.*)-\\d+"
  replacement   = "$1"
}
```

But Loki's built-in auto-label axis is `service_name` (not `service`).
Without an explicit `service_name` target label, Loki drops every stream
into the `unknown_service` default and `service` never appears as a
label at all (`GET /loki/api/v1/labels` returns `["service_name"]`
only). All panels that group by `service_name` therefore see one
collapsed series.

### Fix landed

Added a parallel `rule` block in `infra/alloy/config.alloy` (do NOT
rename the existing `service` rule — other dashboards may reference
it):

```alloy
rule {
  source_labels = ["__meta_docker_container_name"]
  target_label  = "service_name"
  regex         = "/worldview-(.*)-\\d+"
  replacement   = "$1"
}
```

Regex matches the compose-generated container naming convention
(`/worldview-<service>-<n>`) and captures the service slug so values
like `portfolio`, `rag-chat`, `content-ingestion-worker` appear instead
of `unknown_service`.

### Verification queries

After Alloy restart and ~30 s of fresh log shipping:

```bash
# Expect: count > 1 and first10 includes real container slugs
curl -s http://localhost:3100/loki/api/v1/label/service_name/values \
  | python3 -c "import json,sys; d=json.loads(sys.stdin.read()).get('data',[]); print(f'service_name values: count={len(d)} first10={d[:10]}')"

# Expect: result count > 0
curl -s 'http://localhost:3100/loki/api/v1/query?query=sum%20by%20%28service_name%29%20%28count_over_time%28%7Bservice_name%3D~%22.%2B%22%7D%5B5m%5D%29%29' \
  | python3 -c "import json,sys; print('result count:', len(json.loads(sys.stdin.read())['data']['result']))"
```

### Live-stack validation note (2026-06-05)

The fix was implemented and committed on branch `feat/plan-0099-w4` in
worktree `.claude/worktrees/agent-a7d8d9eb`. The running Alloy
container mounts the file from the **main** worktree
(`/Users/arnaurodon/Projects/University/final_thesis/worldview/infra/alloy/config.alloy`),
so live verification against `localhost:3100` was deferred to avoid a
parallel-session conflict (R42 / BP-590) with the main worktree. Once
the branch lands on `main` the running Alloy will pick up the new rule
on the next `docker compose restart alloy`.

Baseline confirmed on live stack before the merge:

- `GET /loki/api/v1/labels` → `["service_name"]` (no `service` label)
- `GET /loki/api/v1/label/service_name/values` → `["unknown_service"]`
  (count 1)

This matches the predicted symptom exactly, confirming the diagnosis.
