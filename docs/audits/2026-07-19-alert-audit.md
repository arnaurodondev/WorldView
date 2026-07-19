# Alert & Smoke-Check False-Positive Audit — 2026-07-19

**Scope:** the two systems that email the operator (`arnaurodondev@gmail.com`) via Brevo:
1. **prod-smoke CronJob** (`worldview-gitops/manifests/prod-smoke-cronjob.yaml`, runs
   `scripts/prod_e2e_smoke.py` every 30m; any FAIL → `ProdSmokeTestFailed` → Brevo).
2. **PrometheusRules → Alertmanager → Brevo** (kube-prometheus-stack bundled rules +
   worldview rules: storage-alerts, dlq-alerts, gliner-memory-alerts, prod-smoke rule).

**Method:** read-only diagnosis against prod (`https://116.203.198.118:6443`).
Alertmanager `/api/v2/alerts` for active alerts; Prometheus `count_over_time(ALERTS{alertstate="firing"}[2d])`
for firing frequency; latest prod-smoke Job logs for failing checks.

**Alertmanager routing (relevant):** default route → `email-operator` (everything not
null-routed reaches Brevo). Already null-routed: `Watchdog`, `KubeSchedulerDown`,
`KubeControllerManagerDown`, `KubeProxyDown`, `InfoInhibitor`, and `KubeJobFailed`
for `job_name=~"prod-smoke.*"` in `monitoring`.

---

## Ranked findings

Frequency = distinct firing series-samples over the last 2 days (`count_over_time`).

| # | Alert / smoke check | Fires (2d) | Reaches operator | Verdict | Evidence | Fix |
|---|---------------------|-----------:|:----------------:|:-------:|----------|-----|
| 1 | `KubeJobFailed` (postgres-backup) | 15546* | yes | **FALSE-POSITIVE** | 3 backup Jobs (29739240/600/960, 12–24h old) failed — `pg_dumpall: connection refused` during the Postgres OOM/6Gi-bump window. Newer runs (29740320, 29740680) `Complete`; smoke shows a fresh 2.4 GiB dump @ 00:08. Stale Failed Jobs linger (`failedJobsHistoryLimit=3`, no TTL) and re-fire for ~24h after recovery. | **gitops `cd2283d`** — `ttlSecondsAfterFinished=1800` + `failedJobsHistoryLimit=1` so a real failure notifies once then evicts. Persistent failures still re-fire each 6h cycle. |
| 2 | `KubeContainerWaiting` (postgres-backup `upload`) | 10090 | yes | **FALSE-POSITIVE** | Same root cause: the init `dump` container errored, so the `upload` sidecar sits in `PodInitializing` forever → bundled rule fires "waiting >1h". Not a real slow-start; the pod is dead. Redundant with #1. | **gitops `cd2283d`** — TTL evicts the orphaned pod before the 1h threshold trips. |
| 3 | `KubeDeploymentReplicasMismatch` | 12123 | yes | **TRANSIENT (self-resolving)** | 0 active now. Fired 07-16..18 during rollouts (Postgres 6Gi mem-limit bump, `maxSurge=0` migrate-hook scheduling on the single node). Resolves once the pod schedules. | No change — genuine-but-transient; would be wrong to silence structurally. |
| 4 | `KubePersistentVolumeInodesFillingUp` | 6630 | yes | **REAL (early-warning) — KEEP** | 0 active now. minio PVC inodes at **53.5%** and climbing (MinIO = many small objects); `predict_linear` early-warning. | No change. |
| 5 | `ProdSmokeTestNotRunning` (critical) | 5760 | yes | **FALSE-POSITIVE (cascade)** | The smoke script exits non-zero on the 2 stale-migration FAILs (#7), so the CronJob never records a success → `time() - last_successful_time > 5400` fires "health monitor is blind." Purely a downstream effect of #7. | **code `5c1b8b2c1`** — fixing #7 makes smoke exit 0 → success recorded → clears. |
| 6 | `TargetDown` (`job=minio-console`) | 5760 | yes | **FALSE-POSITIVE** | The `minio-cluster-metrics` ServiceMonitor selected BOTH Helm services sharing `app=minio,release=infra-minio`: the `minio` metrics svc (9000, up) and the `minio-console` UI svc (9001). The console port returns `text/html`, not `/metrics` → permanently-down target. Only the metrics svc carries `monitoring=true`. | **gitops `cd2283d`** — add `monitoring: "true"` to the SM selector; metrics scrape preserved (verified label present), console excluded. |
| 7 | `ProdSmokeTestFailed` (critical) | 5605 | yes | **FALSE-POSITIVE** | Two checks FAIL every run: `migrations ingestion_db — STALE IMAGE: pod bundles 0025, release head 0024` and `market_data_db — 045 vs 044`. The harness `EXPECTED_ALEMBIC_HEADS` map lagged the deployed reality (prod DB = image = 0025/045; both are legit heads on main). | **code `5c1b8b2c1`** — bump map to 0025/045 in `thresholds.py` + `prod_e2e_smoke.py`; add `tests/scripts/test_expected_alembic_heads.py` freshness gate. |
| 8 | `KubePodCrashLooping` (path-insight-worker) | 2488 | yes | **REAL — KEEP** | `knowledge-graph-path-insight-worker` = 151 restarts/46h, `exitCode 1` ~3s after start. Genuine crash-loop; smoke flags it as WARN too. | No change — real bug; out of alert-audit scope, flagged for `/investigate`. |
| 9 | `KubeStatefulSetReplicasMismatch` | 1240 | yes | **TRANSIENT** | 0 active now; Postgres/Kafka rollout during the 6Gi bump. Self-resolves. | No change. |
| 10 | `KubePersistentVolumeFillingUp` | 1026 | yes | **REAL (early-warning) — KEEP** | Postgres PVC 45.8%, minio 31.4% bytes. Legit capacity signal. | No change. |
| 11 | `CPUThrottlingHigh` (info) | 171 | yes (info) | **EXPECTED on lean node** | `info` severity, throttling on the constrained single node. Not a critical page. | No change. |
| 12 | `GlinerOOMKilled` (critical) | 87 | yes | **REAL — KEEP** | Our alert; GLiNER OOM is a real recurring failure mode. | No change. |
| 13 | `KubeletTooManyPods` (info) | 4 | yes (info) | **EXPECTED on lean node** | Near pod cap on a single node. | No change. |

\* `KubeJobFailed` total includes prod-smoke jobs, which are **already null-routed**; the
operator-reaching portion is the postgres-backup jobs.

### Not firing — no action (verified)

- **`KubeCPUOvercommit` / `KubeMemoryOvercommit`** — listed as suspected false positives,
  but Prometheus shows **0 firings in 2d**. The bundled expressions carry a
  `count(kube_node_status_allocatable) > 1` guard; this is a **single-node** cluster
  (node count = 1), so they are structurally inert. Nothing to silence.

---

## Fixes applied

**Code repo** (`worldview`, branch `fix/alert-false-positives`, commit `5c1b8b2c1`):
- `scripts/prod_qa/thresholds.py`, `scripts/prod_e2e_smoke.py` — `EXPECTED_ALEMBIC_HEADS`:
  `ingestion_db 0024→0025`, `market_data_db 044→045`.
- `tests/scripts/test_expected_alembic_heads.py` (new) — computes each service's true
  Alembic DAG head from the version files and asserts the harness map matches, so a
  future migration that forgets to bump the map fails CI instead of paging months later.
  Also asserts the two copies of the map (thresholds + standalone smoke) never diverge.
  Runs green (11 tests).

**GitOps repo** (`worldview-gitops`, branch `fix/alert-false-positives`, commit `cd2283d`):
- `manifests/minio-servicemonitor.yaml` — add `monitoring: "true"` to the selector
  (excludes the `minio-console` UI service → kills `TargetDown{job="minio-console"}`).
- `manifests/postgres-backup-cronjob.yaml` — `ttlSecondsAfterFinished=1800` +
  `failedJobsHistoryLimit=1` (evicts stale Failed backup Jobs/pods → kills the 24h
  re-fire of `KubeJobFailed` + `KubeContainerWaiting`).

Both manifests validated offline (`kubectl apply --dry-run=client` → `configured (dry run)`).
**Not deployed** (per instruction). No PrometheusRule expressions were changed, so no
rule needed re-validation against live Prometheus.

## Real signals confirmed still firing (not silenced)

- `ProdSmokeTestFailed` still pages on any **genuine** smoke FAIL — only the stale-map
  false trigger was removed (the check itself is unchanged).
- `GlinerOOMKilled`, `worldview-storage-alerts`, `worldview-dlq-alerts` — untouched.
- `KubePodCrashLooping` (path-insight), `KubePersistentVolume*` — left firing (real).
- minio metrics scrape (`job=minio`, 9000) still up — selector still matches
  `monitoring=true` on the metrics service.
- postgres-backup `KubeJobFailed` still fires on a **persistent** (every-cycle) failure.

## Latent real issue surfaced (not a false positive; out of no-deploy scope)

- **intelligence_db is one migration behind main.** Main head is `0068`
  (`0068_relation_evidence_default_partition` — DEFAULT partition that unblocks the
  evidence promoter); prod DB is at `0067`. The harness map is intentionally left at
  `0067` (matches prod) and annotated in `_KNOWN_PROD_LAG` so the test documents the gap
  rather than masking it. **Action for the operator:** apply migration `0068` to
  `intelligence_db`, then bump the map to `0068` and drop the `_KNOWN_PROD_LAG` entry.

## Residual cleanup (operator, optional)

The 3 already-stuck Failed backup Jobs (`postgres-backup-29739240/600/960`) predate the
TTL change and won't be evicted retroactively. They clear on their own as
`failedJobsHistoryLimit=1` prunes them after GitOps applies the new CronJob, or
immediately via `kubectl delete job -n infra postgres-backup-29739240 postgres-backup-29739600 postgres-backup-29739960`.
