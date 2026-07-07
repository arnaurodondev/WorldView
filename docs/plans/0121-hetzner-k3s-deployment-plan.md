# PLAN-0121 — Hetzner k3s + ArgoCD Deployment (Route 2)

**Date**: 2026-07-06
**Source report**: [docs/audits/2026-07-06-hetzner-k3s-deployment-investigation.md](../audits/2026-07-06-hetzner-k3s-deployment-investigation.md)
**Repos touched**: `worldview` (application/IaC) + `worldview-gitops` (Helm chart, ArgoCD apps, values, secrets, bootstrap)
**Supersedes/relates**: PLAN-0113 (Kafka resilience + gitops StatefulSet groundwork — already partly on the gitops working tree).

## Revision log (2026-07-06)

Adversarial plan-review pass (verified against `infra/compose/docker-compose.yml`, `worldview-gitops/`, and `services/*/src/*/app.py`). Changes applied:

1. **Worker-count reconciliation (SP-1 header + T-3.4).** Spot-checked all 10 services' `command:` lines against compose. Every module path in the inventory table is **faithful** (no hallucinated/missing units). But the aggregate summary was internally inconsistent: compose has **53 worker containers** (not 54) → **52 K8s workloads** (not 53), = **53 pods** with the nlp article fleet at replicas:2. By-kind breakdown corrected to 8 dispatchers / 28 consumers / 17 schedulers-workers (8+28+17=53). Fixed the header sentence and T-3.4's "9 singleton workers" → **8 singleton workers** (nlp singletons: dispatcher, watchlist, document-deletion, entity-refresh, price-impact, relevance-scoring, unresolved-resolution, embedding-retry).
2. **Added "## Implementation partitioning"** section (before the DAG): a file→task ownership map plus 6 conflict-free parallel batches, so no two concurrent agents edit the same file. Flags the three serialize-only hotspots (`_helpers.tpl`, `manifests/gliner.yaml`, `apps/infra-postgres.yaml`) and the per-`values/<svc>.yaml` multi-task contention.
3. **Verification notes recorded** (no change needed, but confirmed): R22 holds — `services/nlp-pipeline/src/nlp_pipeline/app.py` lifespan explicitly runs no consumers, so the plan's design-note fix (article fleet = worker workload, revert the API StatefulSet flip) is correct. `values/nlp-pipeline.prod.yaml` is currently **untracked** and its whole body is the (mis-premised) API StatefulSet flip — T-3.4 must preserve its `resources:` block onto the article-consumer worker while reverting the API to a Deployment. All 20 blockers B1–B20 have an owning task; B13 (DeepInfra keys) and the Ollama drop are correctly treated as done/commit-only, not re-planned. All 15 Category-A env vars are covered (6+3+2+3+1). B5/B6 confirmed: initdb uses invalid `CREATE DATABASE IF NOT EXISTS` and omits `kg_db`. Probe paths confirmed both `/health` in `_helpers.tpl`. Domain placeholders confirmed in the exact paths T-13.1 names.

## Goal

Make the full Worldview platform (10 services + ~52 background worker units + infra) deployable and **functionally validated** on a Hetzner k3s cluster driven by ArgoCD from `worldview-gitops`, by closing every blocker **B1–B20** and the §7b env-sync gaps in the investigation report. This is **Route 2** (fix the k3s+ArgoCD path), not the Docker-Compose fallback (Route 1).

## Definition of "Done"

**Done = every code / manifest / chart / tofu / config / docs change is committed and pushed to `origin/main` in BOTH repos, such that the only remaining actions are irreducibly-manual provisioning** (buy domain, create cloud accounts/tokens, generate the age key, run `tofu apply`, run the interactive `setup-secrets.sh` + `setup.sh`, point DNS, flip LE staging→prod). After the manual track runs, a fresh `argocd app sync` of `worldview-root` brings up a cluster that passes the §6 endpoint checklist (items 7/8/11 — the consumer-pipeline probes — must pass, not just `/healthz`).

**Non-goals**: multi-region HA, RF>1 migration of pre-existing topics (fresh cluster → topics born RF=3), historical data backfill, frontend rich features (Vercel deploy of `worldview-web` is in scope as a target; feature work is not).

---

## Track split

Every task below is tagged **[AUTO]** (an agent / CI can complete and commit it — the bulk) or **[MANUAL]** (only the user can do it — money, accounts, secrets, DNS, `apply`). The two tracks are listed separately; the critical-path DAG at the end shows how they interlock.

---

# AUTOMATABLE TRACK

## SP-1 — Helm chart topology (B1, B3, B8, B18)  — *largest effort*

The chart (`worldview-gitops/charts/worldview-service`) today renders exactly one API Deployment per service. It must additionally render: (a) one workload per background worker, (b) correct probe paths, (c) a Secret template, and per-service migration Jobs (SP-2). Worker enumeration below is taken verbatim from `infra/compose/docker-compose.yml` (`command:` overrides) and has been spot-verified module-by-module (2026-07-06 review). **53 worker containers** across 10 services (8 outbox dispatchers, 28 Kafka consumers, 17 schedulers/pollers/workers) — collapsing to **52 K8s workloads** when the two `nlp-pipeline` `article_consumer_main` compose containers become one StatefulSet, replicas:2 (= **53 pods**). Separately, **9 migration one-shots** (8 per-service `alembic upgrade head` + `intelligence-migrations` custom entrypoint) become PreSync Jobs (SP-2). Knowledge-graph has **no** migrate (intelligence_db DDL is owned by intelligence-migrations).

### Worker inventory (drives the `workers:` values list)

| Service | Worker key | `command` (module) | kind |
|---|---|---|---|
| portfolio | dispatcher | `portfolio.infrastructure.messaging.outbox.dispatcher_main` | outbox |
| portfolio | instrument-consumer | `portfolio.infrastructure.messaging.consumers.instrument_consumer_main` | consumer |
| portfolio | manual-holdings-consumer | `portfolio.infrastructure.messaging.consumers.manual_holdings_consumer_main` | consumer |
| portfolio | manual-holdings-worker | `portfolio.workers.manual_holdings_worker` | scheduler |
| portfolio | snapshot-worker | `portfolio.workers.portfolio_snapshot_worker` | scheduler |
| portfolio | brokerage-sync | `portfolio.workers.brokerage_sync_worker` | scheduler |
| market-ingestion | scheduler | `market_ingestion.infrastructure.scheduler.scheduler_main` | scheduler |
| market-ingestion | worker | `market_ingestion.infrastructure.workers.worker_main` | worker |
| market-ingestion | dispatcher | `market_ingestion.infrastructure.messaging.outbox.dispatcher_main` | outbox |
| content-ingestion | scheduler | `content_ingestion.infrastructure.scheduler.scheduler_main` | scheduler |
| content-ingestion | worker | `content_ingestion.infrastructure.workers.worker_main` | worker |
| content-ingestion | dispatcher | `content_ingestion.infrastructure.messaging.outbox.dispatcher_main` | outbox |
| market-data | dispatcher | `market_data.infrastructure.messaging.outbox.dispatcher_main` | outbox |
| market-data | ohlcv-consumer | `market_data.infrastructure.messaging.consumers.ohlcv_consumer_main` | consumer |
| market-data | quotes-consumer | `market_data.infrastructure.messaging.consumers.quotes_consumer_main` | consumer |
| market-data | fundamentals-consumer | `market_data.infrastructure.messaging.consumers.fundamentals_consumer_main` | consumer |
| market-data | insider-transactions-consumer | `market_data.infrastructure.messaging.consumers.insider_transactions_consumer_main` | consumer |
| market-data | prediction-market-consumer | `market_data.infrastructure.messaging.consumers.prediction_market_consumer_main` | consumer |
| market-data | intraday-resampling-consumer | `market_data.infrastructure.messaging.consumers.intraday_resampling_consumer_main` | consumer |
| content-store | dispatcher | `content_store.infrastructure.messaging.outbox.dispatcher_main` | outbox |
| content-store | consumer | `content_store.infrastructure.messaging.consumers.article_consumer_main` | consumer |
| content-store | dedup-consumer | `content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer_main` | consumer |
| nlp-pipeline | dispatcher | `nlp_pipeline.infrastructure.messaging.outbox.dispatcher_main` | outbox |
| nlp-pipeline | **article-consumer** (StatefulSet, replicas:2, `instanceIdEnv`) | `nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main` | consumer-fleet |
| nlp-pipeline | watchlist-consumer | `nlp_pipeline.infrastructure.messaging.consumers.watchlist_consumer_main` | consumer |
| nlp-pipeline | document-deletion-consumer | `nlp_pipeline.infrastructure.messaging.consumers.document_deletion_consumer_main` | consumer |
| nlp-pipeline | entity-refresh-consumer | `nlp_pipeline.infrastructure.messaging.consumers.entity_refresh_consumer_main` | consumer |
| nlp-pipeline | price-impact-worker | `nlp_pipeline.workers.price_impact_labelling_worker` | scheduler |
| nlp-pipeline | relevance-scoring | `nlp_pipeline.workers.article_relevance_scoring_worker` | scheduler |
| nlp-pipeline | unresolved-resolution-worker | `nlp_pipeline.workers.unresolved_resolution_worker_main` | scheduler |
| nlp-pipeline | embedding-retry-worker | `nlp_pipeline.workers.embedding_retry_worker_main` | scheduler |
| knowledge-graph | dispatcher | `knowledge_graph.infrastructure.messaging.outbox.dispatcher_main` | outbox |
| knowledge-graph | scheduler | `knowledge_graph.infrastructure.scheduler.scheduler_main` | scheduler |
| knowledge-graph | enriched-consumer | `knowledge_graph.infrastructure.messaging.consumers.enriched_consumer_main` | consumer |
| knowledge-graph | provisional-queued-consumer | `knowledge_graph.infrastructure.messaging.consumers.provisional_queued_consumer_main` | consumer |
| knowledge-graph | entity-consumer | `knowledge_graph.infrastructure.messaging.consumers.entity_consumer_main` | consumer |
| knowledge-graph | fundamentals-consumer | `knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer_main` | consumer |
| knowledge-graph | instrument-consumer | `knowledge_graph.infrastructure.messaging.consumers.instrument_consumer_main` | consumer |
| knowledge-graph | instrument-discovered-consumer | `knowledge_graph.infrastructure.messaging.consumers.instrument_discovered_consumer_main` | consumer |
| knowledge-graph | temporal-event-consumer | `knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer_main` | consumer |
| knowledge-graph | economic-events-dataset-consumer | `knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer_main` | consumer |
| knowledge-graph | macro-indicator-dataset-consumer | `knowledge_graph.infrastructure.messaging.consumers.macro_indicator_dataset_consumer_main` | consumer |
| knowledge-graph | insider-transactions-dataset-consumer | `knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer_main` | consumer |
| knowledge-graph | earnings-calendar-dataset-consumer | `knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer_main` | consumer |
| knowledge-graph | path-insight-worker | `knowledge_graph.infrastructure.workers.path_insight_worker_main` | scheduler |
| alert | dispatcher | `alert.infrastructure.messaging.outbox.dispatcher_main` | outbox |
| alert | intelligence-consumer | `alert.infrastructure.messaging.consumers.intelligence_consumer_main` | consumer |
| alert | watchlist-consumer | `alert.infrastructure.messaging.consumers.watchlist_consumer_main` | consumer |
| alert | email-scheduler | `alert.infrastructure.email.scheduler_main` | scheduler |
| alert | rule-poller | `alert.infrastructure.rules.poller_main` (gate `ALERT_RULE_POLLER_ENABLED`) | scheduler |
| rag-chat | brief-scheduler | `rag_chat.infrastructure.scheduling.brief_scheduler_main` | scheduler |
| api-gateway | bundle-prewarmer | `api_gateway.workers.bundle_prewarmer_main` | scheduler |

> **Design note — R22 correctness fix**: the existing `values/nlp-pipeline.prod.yaml` flips the *API* release to StatefulSet/replicas:2 intending "article fleet". Per R22 the API lifespan does **not** run consumers, so that flip does nothing useful. The article fleet must be a **worker workload** (`article-consumer`, StatefulSet, replicas:2, `instanceIdEnv=NLP_PIPELINE_KAFKA_CONSUMER_INSTANCE_ID`) as in the table — and the API prod overlay should revert to a plain single-replica Deployment. Fix this in W1/W5.

### Wave SP1-W1 — worker template + values schema  *(gates all worker tasks)*
- **T-1.1 [AUTO]** New `charts/worldview-service/templates/worker.yaml`: `range .Values.workers` → one `Deployment` (or `StatefulSet` when `.statefulSet` set) per entry, reusing `worldview-service.podTemplate` but with `command:` override, per-worker name `{{fullname}}-{{.name}}`, per-worker `replicaCount`, `resources`, optional `instanceIdEnv`, and **NO** HTTP `ports`/`Service`. Accept: `helm template` renders N extra workloads for a values file with a `workers:` list; existing services with no `workers:` render unchanged. Validate: `helm template charts/worldview-service -f values/knowledge-graph.yaml | grep -c 'kind: Deployment'`.
- **T-1.2 [AUTO]** Worker pod-template variant in `_helpers.tpl`: a `worldview-service.workerPodTemplate` that omits `ports`, `livenessProbe`/`readinessProbe` HTTP (workers have no HTTP server) and instead uses an `exec`/process liveness or none; keeps `envFrom`/`env`/`resources`/`imagePullSecrets`/`nodeSelector`. Accept: rendered worker pod has no `httpGet` probe, shares the service `envFrom` secretRef. Validate: `helm template … | yq 'select(.kind=="Deployment") | .spec.template.spec.containers[0].livenessProbe'` empty for workers.
- **T-1.3 [AUTO]** Chart `values.yaml`: add default `workers: []` + documented per-item schema (`name`, `command` (list), `replicaCount`, `statefulSet`, `instanceIdEnv`, `resources`, `nodeSelector`). Accept: `helm lint charts/worldview-service` clean.
- **T-1.4 [AUTO]** Fix probe paths (B3) in `_helpers.tpl podTemplate`: `livenessProbe.path /health→/healthz`, `readinessProbe.path /health→/readyz`. Accept: rendered API pod has `livenessProbe.httpGet.path: /healthz` and `readinessProbe.httpGet.path: /readyz`. Validate: `helm template … -f values/api-gateway.yaml | grep -A2 'Probe' | grep -E '/healthz|/readyz'`.
- **T-1.5 [AUTO]** Fix probe path in `manifests/gliner.yaml` — confirm GLiNER server exposes `/health` (it does per `infra/gliner`); leave as-is if so, else align. Accept: documented decision inline.

### Wave SP1-W2 — Secret template + GitOps-native secrets (B8)
- **T-2.1 [AUTO]** New `charts/worldview-service/templates/secret.yaml` guarded by `.Values.secret.create` rendering a `Secret` from `.Values.secret.stringData` (populated by the `secrets+age-import://` valueFile). This makes helm-secrets actually create the runtime Secret via ArgoCD (self-heal + prune), replacing the one-shot `kubectl apply` in `setup.sh:110-119`. Accept: `helm template … -f <decrypted-secret-values>` emits a `kind: Secret`. Validate with a fixture secret values file.
- **T-2.2 [AUTO]** Repoint each `values/<svc>.yaml` `envFrom.secretRef` to the chart-rendered Secret name; ensure the `secrets+age-import://…?…/<svc>-secrets.yaml` valueFile maps into `secret.stringData`. Accept: decrypt→render→apply round-trips for one service in `helm template`.
- **T-2.3 [AUTO]** Update `bootstrap/setup.sh` to drop Step-9's "ArgoCD will manage secrets after this" claim; keep the age-key secret (Step-7) but let ArgoCD render app Secrets. Accept: setup.sh no longer `kubectl apply`s `secrets/*.yaml`.
- **T-2.4 [AUTO]** Preflight assertion script `scripts/preflight-secrets.sh`: fail if `.sops.yaml` still contains `age1REPLACE…` or any referenced `secrets/<svc>-secrets.yaml` is missing. Wire into `.github/workflows/validate.yml`. Accept: script exits non-zero on placeholder recipient.

### Wave SP1-W3 — populate `workers:` in every service values file
- **T-3.1 [AUTO]** Add the `workers:` list (from the inventory table) to `values/portfolio.yaml`, `values/market-ingestion.yaml`, `values/content-ingestion.yaml`. Accept: `helm template` renders the exact worker count per service (6/3/3). Validate per service.
- **T-3.2 [AUTO]** Same for `values/market-data.yaml` (7), `values/content-store.yaml` (3), `values/alert.yaml` (5 — incl. `rule-poller`). Accept: counts match.
- **T-3.3 [AUTO]** Same for `values/knowledge-graph.yaml` (14), `values/rag-chat.yaml` (1), `values/api-gateway.yaml` (1). Accept: counts match.
- **T-3.4 [AUTO]** `values/nlp-pipeline.yaml`: add the **8 singleton workers** (dispatcher, watchlist-consumer, document-deletion-consumer, entity-refresh-consumer, price-impact-worker, relevance-scoring, unresolved-resolution-worker, embedding-retry-worker) + the `article-consumer` StatefulSet fleet (replicas:2, `instanceIdEnv`); **revert** the API-level StatefulSet flip in `values/nlp-pipeline.prod.yaml` to a plain Deployment (per design note). **NOTE**: `values/nlp-pipeline.prod.yaml` is currently *untracked* and its entire body IS the (mis-premised) API StatefulSet flip — preserve its right-sized `resources:` block by moving it onto the `article-consumer` worker entry, don't just delete the file. Accept: article-consumer renders as StatefulSet replicas 2 with downward-API instance id; API renders as single Deployment. Validate: `helm template … -f nlp-pipeline.yaml -f nlp-pipeline.prod.yaml | yq 'select(.kind=="StatefulSet").metadata.name'` == `nlp-pipeline-article-consumer`.
- **T-3.5 [AUTO]** Node placement: workers inherit service `nodeSelector` (`stateless` for app services); confirm the 3 stateful-adjacent workers (GLiNER-heavy nlp workers) still target `stateless` (GLiNER itself is the only stateful ML pod). Accept: no worker targets `node-role: stateful` unless intended.

### Wave SP1-W4 — sync-waves (B18)
- **T-4.1 [AUTO]** Add `argocd.argoproj.io/sync-wave` annotations on the `apps/*.yaml` Application objects: infra (postgres/kafka/minio/valkey/schema-registry/gliner) = `-2`; schema-registry = `-1`; migration apps (SP-2) = `0`; API services = `1`; workers ride with their service app (same wave `1`, but gate on migration via PreSync). Accept: `grep -l sync-wave apps/*.yaml` covers all. Validate: `grep -rc sync-wave apps/ | awk -F: '{s+=$2} END{print s}'` > 0.
- **T-4.2 [AUTO]** Ensure traefik/cert-manager sync after services (`1`) but issuers can be `2`. Accept: documented ordering table in `docs/OPERATIONS.md`.

**Effort SP-1: ~14–18h** (worker template + 10 values files + secret template).

---

## SP-2 — Database bootstrap & migrations (B5, B6, B2)

### Wave SP2-W1 — Postgres initdb correctness (B5, B6)
- **T-5.1 [AUTO]** Rewrite `apps/infra-postgres.yaml` `initdb.scripts.init.sql` to the valid `\gexec` idiom (mirror `infra/postgres/init-intelligence/init-databases.sh`): `SELECT 'CREATE DATABASE '||d FROM (VALUES …) WHERE NOT EXISTS(SELECT FROM pg_database WHERE datname=d)\gexec` for all 11 DBs — **add `kg_db`** (currently missing). Accept: initdb creates all DBs without `ON_ERROR_STOP` abort. Validate: `kubectl exec … psql -c '\l'` lists 11 DBs (test in a kind/minikube dry-run or document as post-provision check).
- **T-5.2 [AUTO]** Add a second initdb script `10-extensions.sql` that runs, per intelligence_db + kg_db: `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS age; LOAD 'age'; SET search_path=ag_catalog,"$user",public; SELECT create_graph('worldview_graph');` guarded idempotently. Accept: mirrors `init-databases.sh:38-67`. Validate: documented.
- **T-5.3 [AUTO]** Confirm the custom `ghcr.io/arnaurodondev/worldview-postgres` image bundles the AGE + pgvector binaries (it must, since `LOAD 'age'` needs the shared lib). If the Bitnami-referenced image is the stock one, switch `image.repository` to the custom postgres image (it is already set to `worldview-postgres`). Accept: inline note confirming the image has AGE.

### Wave SP2-W2 — migration Jobs + intelligence-migrations app (B2)
- **T-6.1 [AUTO]** New `charts/worldview-service/templates/migrate-job.yaml` guarded by `.Values.migrate.enabled`: a `Job` with `argocd.argoproj.io/hook: PreSync` + `hook-delete-policy: BeforeHookCreation`, command `["alembic","upgrade","head"]` (or per-service `alembic -c alembic.ini upgrade head` for market-ingestion), same image + `envFrom` secret. Accept: `helm template … -f values/portfolio.yaml` with `migrate.enabled:true` renders a PreSync Job. Validate: `yq 'select(.kind=="Job").metadata.annotations'` shows the hook.
- **T-6.2 [AUTO]** Enable `migrate:` in the 8 services that own Alembic DDL: portfolio, market-ingestion (`alembic.ini`), content-ingestion, market-data, content-store, nlp-pipeline (owns nlp_db), alert, rag-chat. **Do NOT** enable for knowledge-graph (intelligence_db owned by intelligence-migrations; keep `ALEMBIC_ENABLED=false`). Accept: 8 migrate Jobs render, KG none.
- **T-6.3 [AUTO]** New ArgoCD app `apps/worldview-intelligence-migrations.yaml` + `values/intelligence-migrations.yaml` running the `intelligence-migrations` image as a **sync-wave 0 Job/PreSync** (image `ghcr.io/arnaurodondev/worldview-intelligence-migrations`). This owns all intelligence_db DDL (AGE graph tables, etc.). Add it to CI build matrix if not already built (see SP-6/B20). Accept: app renders a Job that runs before S6/S7. Validate: `helm template`/`kubectl apply --dry-run`.
- **T-6.4 [AUTO]** Verify a `gateway_db` migration path exists (api-gateway) — if S9 has Alembic, enable `migrate:`; else document that gateway_db needs no DDL. Accept: explicit decision recorded.
- **T-6.5 [AUTO]** Ordering: intelligence-migrations (wave 0) must complete before KG/NLP workers (wave 1). Encode via sync-wave + PreSync. Accept: documented DAG.

**Effort SP-2: ~6–8h.**

---

## SP-3 — Infra sizing & reliability (B10, B11, B12-partial, single-Postgres decision)

### Wave SP3-W1 — ML + Kafka sizing
- **T-7.1 [AUTO]** `manifests/gliner.yaml`: raise `resources.limits.memory 4Gi→8Gi` (requests 4Gi), add env `OMP_NUM_THREADS/MKL_NUM_THREADS/OPENBLAS_NUM_THREADS/NUMEXPR_NUM_THREADS/TORCH_NUM_THREADS=4` + `GLINER_MODEL_PATH`/`NER_MODEL_ID=urchade/gliner_large-v2.1`, and set `resources.limits.cpu: "4"` with matching thread pin (BP: GLiNER OOM-137 <8Gi + thread-thrash). Accept: manifest limit ≥8Gi, 5 thread env vars present. Validate: `yq '.spec.template.spec.containers[0].resources.limits.memory' manifests/gliner.yaml` == `8Gi`.
- **T-7.2 [AUTO]** `apps/infra-kafka.yaml`: add `broker.heapOpts` and `controller.heapOpts` `-Xmx3072m -Xms3072m` (in each sub-tree — the chart ignores top-level). Accept: both sub-trees carry heapOpts. Validate: `grep -c heapOpts apps/infra-kafka.yaml` == 2.
- **T-7.3 [AUTO]** Right-size KG/NLP worker resources in values (heaviest: enriched-consumer, article-consumer). Set per-worker `resources` in the `workers:` entries (requests ~256Mi/100m for outbox/scheduler; ~512Mi–1Gi for consumers; article-consumer 1Gi/500m). Accept: sum of worker limits documented for capacity check.

### Wave SP3-W2 — Postgres topology decision (single vs OLAP split)
- **T-8.1 [AUTO]** Decision doc in `docs/CONFIG_MANAGEMENT.md`: **single Postgres** for the thesis (100Gi PVC, 4Gi limit) — reject the OLAP split (market_data heavy rollups) as premature; document the `*_DATABASE_URL_READ` R27 replica URLs pointing at the **same primary** (`postgres.infra.svc`) so read UoWs are configured, not misrouted (§7b Category-B). Accept: every service's `*_DATABASE_URL_READ` env set (SP-5). Validate: `grep -rc DATABASE_URL_READ values/` covers nlp/knowledge-graph/market-ingestion/rag-chat.
- **T-8.2 [AUTO]** Raise Postgres `resources.limits.memory 4Gi→6Gi` + `shared_buffers`/`work_mem` tuning via `primary.extendedConfiguration` for the AGE/vector workload on one node. Accept: config present.

**Effort SP-3: ~4–5h.**

---

## SP-4 — Tofu / provisioning (B4, B16, B12)

### Wave SP4-W1 — node-role labels (B4)  *(fatal-blocker fix)*
- **T-9.1 [AUTO]** Split `infra/tofu/cloud-init/worker.yml` into `worker-stateful.yml` + `worker-stateless.yml`, each appending `--node-label node-role=stateful` / `--node-label node-role=stateless` to the `k3s … agent` install (INSTALL_K3S_EXEC or `K3S_NODE_LABEL`). Accept: worker1 joins labelled `stateful`, worker2 `stateless`. Validate: `grep node-label infra/tofu/cloud-init/worker-*.yml` → 2 hits.
- **T-9.2 [AUTO]** `infra/tofu/main.tf` locals: render two `templatefile()` blocks (`worker1_user_data` stateful, `worker2_user_data` stateless) and wire `hcloud_server.worker1.user_data`/`worker2.user_data` to the correct one. Accept: `tofu validate` clean, `tofu plan` shows distinct user_data. Validate: `cd infra/tofu && tofu validate`.
- **T-9.3 [AUTO]** Node-count/size: keep 1 stateful (cx52/CCX-class ≥32GB) + 1 stateless; document in `terraform.tfvars.example` that stateful must have ≥32GB for GLiNER 8Gi + Kafka 3×(4Gi) + Postgres 6Gi + MinIO. Accept: comment + var defaults updated.

### Wave SP4-W2 — swap + ingress IP resolution (B12, B16)
- **T-10.1 [AUTO]** Add swap to both worker cloud-inits (mirror Stack B's bootstrap): `fallocate -l 8G /swapfile; chmod 600; mkswap; swapon; echo … >> /etc/fstab; sysctl vm.swappiness=10`. Accept: cloud-init `runcmd` creates swap. Validate: `grep swapon infra/tofu/cloud-init/worker-*.yml`.
- **T-10.2 [AUTO]** Resolve floating-IP vs LB (B16): **keep the Hetzner managed LB** provisioned by Traefik `type: LoadBalancer` (`apps/traefik.yaml` already annotates `nbg1`); **remove** the floating IP from `infra/tofu/ip.tf` + `outputs.tf` (or repurpose as CP API SAN only) and update `outputs.tf`/docs so DNS guidance points at the **Traefik LB IP** (discovered post-sync via `kubectl -n traefik get svc`). Accept: no doc tells the user to point app DNS at the floating IP. Validate: `grep -rn floating_ip infra/tofu docs` reviewed; `outputs.tf` LB-IP retrieval command added.
- **T-10.3 [AUTO]** `outputs.tf`: add `traefik_lb_ip_command` = `kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}'`. Accept: output present.

**Effort SP-4: ~4–6h.**

---

## SP-5 — Env sync (report §7b) (B13-config, Category-A + Category-B)

### Wave SP5-W1 — Category-A missing vars (must-add, deliberate prod values)
- **T-11.1 [AUTO]** `values/content-ingestion.yaml` (+`.prod.yaml`): add `CONTENT_INGESTION_EODHD_DAILY_QUOTA`, `_EODHD_MONTHLY_QUOTA`, `_EODHD__GENERAL_NEWS_FIREHOSE_ENABLED=true`, `_GENERAL_NEWS_POLL_INTERVAL_SECONDS`, `_GENERAL_NEWS_SHADOW_MODE=false` (deliberate: firehose live in prod, NOT copied from dev), `APP_ENV=production`. Accept: all 6 present. Validate: `grep -c EODHD_DAILY_QUOTA values/content-ingestion.yaml`.
- **T-11.2 [AUTO]** `values/market-ingestion.yaml`: add `MARKET_INGESTION_EODHD_DAILY_QUOTA`, `_EODHD_MONTHLY_QUOTA`, `APP_ENV=production`. Accept: present.
- **T-11.3 [AUTO]** `values/market-data.yaml`: add `COMPUTED_METRICS_REFRESH_HOUR_UTC`, `MARKET_DATA_INTELLIGENCE_ROLLUP_HOUR_UTC`. Accept: present.
- **T-11.4 [AUTO]** `values/alert.yaml`: add `ALERT_S7_INTERNAL_JWT` (secret), `ALERT_S7_KNOWLEDGE_GRAPH_BASE_URL=http://knowledge-graph.worldview.svc:8007`, `APP_ENV=production` — without S7 wiring alert can't reach KG. Accept: present; `ALERT_S7_INTERNAL_JWT` added to `alert-secrets` in `setup-secrets.sh`.
- **T-11.5 [AUTO]** `values/content-store.yaml`: add `APP_ENV=production`. Accept: present.

### Wave SP5-W2 — Category-B (prod-safety + read replicas + tokens)
- **T-12.1 [AUTO]** Add `APP_ENV=production` (or the per-service prefixed form each service actually reads — verify against each `config.py`) to alert/content-ingestion/content-store/market-data/market-ingestion/rag-chat values. **Critical**: set `API_GATEWAY_APP_ENV=production` in `values/api-gateway.yaml` (guards dev-login SEC-003 + OIDC-optional). Accept: `grep -rl APP_ENV values/` covers all 7+gateway. Validate: `grep -c 'APP_ENV' values/api-gateway.yaml`.
- **T-12.2 [AUTO]** Set `*_DATABASE_URL_READ` for nlp-pipeline/knowledge-graph/market-ingestion/rag-chat → same primary `postgres.infra.svc` (R27). Accept: present. Validate: `grep -rc DATABASE_URL_READ values/`.
- **T-12.3 [AUTO]** Confirm `*_SERVICE_ACCOUNT_TOKEN` (api-gateway↔rag-chat S9↔S8) match and are minted in `setup-secrets.sh` as a shared value. Accept: same token var in both secrets.
- **T-12.4 [AUTO]** MinIO alt-name check: verify content-ingestion/content-store read the `*_STORAGE_*` form (values use STORAGE_*, dev uses MINIO_*); add aliases if the service reads `*_MINIO_ENDPOINT`. Accept: inline decision per service.
- **T-12.5 [AUTO]** Confirm no service defaults `*_INTERNAL_JWT_SKIP_VERIFICATION=true`; leave absent (secure default). Accept: `grep -r SKIP_VERIFICATION values/` empty (documented).

**Effort SP-5: ~4–5h.** (B13 secret-side already closed by the completed `setup-secrets.sh` DeepInfra fan-out; this is the *values/config* side.)

---

## SP-6 — External / edge (B14, B15, B17, B20, ghcr)

### Wave SP6-W1 — domain parameterization (B15)  *(config side of a manual purchase)*
- **T-13.1 [AUTO]** Choose a `<DOMAIN>` substitution strategy: introduce a top-level `global.domain` values key + a `scripts/set-domain.sh <domain>` that `sed`-replaces `<DOMAIN>` across `k8s/ingress/*.yaml`, `k8s/cert-manager/cluster-issuers.yaml`, and the CORS/redirect vars in `values/api-gateway.yaml`/`values/portfolio.yaml`/`values/alert.yaml`. Accept: one command fills every placeholder. Validate: `grep -rn '<DOMAIN>' worldview-gitops/` returns 0 after running against a test domain.
- **T-13.2 [AUTO]** Parameterize the ACME email in `cluster-issuers.yaml` (`admin@<DOMAIN>` → `global.acmeEmail`). Accept: no hardcoded placeholder email.
- **T-13.3 [AUTO]** Add `app.<DOMAIN>`/`api.<DOMAIN>`/`ws.<DOMAIN>` host table to `docs/OPERATIONS.md` DNS section. Accept: doc lists exact records.

### Wave SP6-W2 — Zitadel config wiring (B14)
- **T-14.1 [AUTO]** `values/api-gateway.yaml`: keep `OIDC_DISCOVERY_OPTIONAL=false`; ensure issuer/client-id/secret/audience come from `api-gateway-secrets` (already in `setup-secrets.sh` Step S9). Add `API_GATEWAY_FRONTEND_URL=https://app.<DOMAIN>`, `_CORS_ORIGINS=https://app.<DOMAIN>`. Accept: gateway reads OIDC from secret; CORS parameterized.
- **T-14.2 [AUTO]** Document the Zitadel Cloud PKCE app setup as a MANUAL runbook step in `docs/OPERATIONS.md` (redirect URIs `https://app.<DOMAIN>/api/auth/callback`, etc.). Accept: runbook present.

### Wave SP6-W3 — frontend target (B17) — Vercel
- **T-15.1 [AUTO]** Add `apps/worldview-web/` deploy config for **Vercel** (recommended for thesis): `vercel.json` + env `NEXT_PUBLIC_API_BASE_URL=https://api.<DOMAIN>` in `apps/worldview-web`. Document that the frontend talks only to S9 (R14). Accept: build config present; no in-cluster frontend App added.
- **T-15.2 [AUTO]** Add CORS origin `https://app.<DOMAIN>` (Vercel prod domain / custom domain) to gateway (covered T-14.1). Accept: origin present.
- **T-15.3 [AUTO]** Document (OPERATIONS.md) the Vercel project connect + custom-domain + env-var steps as MANUAL. Accept: runbook present.

### Wave SP6-W4 — image promotion (B20) + ghcr
- **T-16.1 [AUTO]** Fix or delete ArgoCD Image Updater: the `image-list` annotation must live on the **Application** object, not the pod template. **Decision: delete** the updater (`apps/argocd-image-updater.yaml`) and the pod-template annotation in `_helpers.tpl`; rely on the existing `deploy.yml` PR-bump path (single promotion authority). Accept: no image-updater app; one promotion path. Validate: `grep -rn image-updater worldview-gitops/` → 0.
- **T-16.2 [AUTO]** Stop shipping `latest`: change `deploy.yml` to write the `sha7` tag into `values/<svc>.yaml` `image.tag` (and set `pullPolicy: IfNotPresent`), giving a git-recorded, rollback-able SHA. Accept: bump PR sets a SHA tag.
- **T-16.3 [AUTO]** Add `intelligence-migrations` + (if chosen) any missing image to the `deploy.yml` build matrix; confirm `gliner` image built. Accept: matrix covers all deployed images.
- **T-16.4 [AUTO]** Document the ghcr choice: **make packages public** (drops the `ghcr-credentials` imagePullSecret) OR keep private + PAT. Recommend public for thesis simplicity; if public, remove `imagePullSecrets` from chart + `pullSecrets` from infra-postgres. Accept: decision recorded; if public, secret refs removed. (The *act* of making packages public is MANUAL.)

**Effort SP-6: ~6–8h.**

---

## SP-7 — Validation & observability (B19) + commit/push (B9)

### Wave SP7-W1 — k8s-native validation
- **T-17.1 [AUTO]** New `scripts/verify-prod-health-k8s.sh`: replace `docker ps`/`ss` with `kubectl get pods -A --field-selector=status.phase!=Running`, ArgoCD app health (`argocd app list -o json`), and the §6 endpoint checklist against `https://api.<DOMAIN>` (items 1–12, with 7/8/11 as the pipeline-liveness gates). Accept: script runs read-only against a kubeconfig. Validate: `bash -n scripts/verify-prod-health-k8s.sh`.
- **T-17.2 [AUTO]** Port `synthetic_monitor.py` into gitops as an in-cluster `CronJob`/Deployment manifest (`apps/synthetic-monitor.yaml` + values) hitting DeepInfra `/models` (silent-401 watch, B12/§6 item 12) + the §6 endpoints, emitting Prometheus metrics scraped by kube-prometheus-stack. Accept: manifest renders; alert rule on `synthetic_probe_failed`.
- **T-17.3 [AUTO]** Encode the §6 checklist as an executable smoke test `scripts/smoke-endpoints.sh` (curl matrix, asserts item-7 edges>0, item-8 populated, item-11 items<24h). Accept: exits non-zero if any pipeline probe fails. Validate: `bash -n`.
- **T-17.4 [AUTO]** BUG_PATTERNS.md (both repos): add "chart deploys API-only, workers/migrations absent → all-green/zero-output at deploy-topology level" + "k8s health-probe path drift (`/health` vs `/healthz`/`/readyz`)". Accept: 2 new BP entries.

### Wave SP7-W2 — docs reconciliation + commit/push (B9)  *(final gate)*
- **T-18.1 [AUTO]** Resolve the Stack A vs Stack B contradiction: update `infra/gitops/docs/hetzner-setup.md` (says "no k8s") to point at this plan / clarify the two stacks. Accept: contradiction resolved.
- **T-18.2 [AUTO]** Update `docs/plans/TRACKING.md` with PLAN-0121 row; update `worldview-gitops/docs/OPERATIONS.md` + `docs/CONFIG_MANAGEMENT.md` with the new topology, sync-waves, migration flow, DNS/LB, Vercel, secrets-native model. Accept: docs current.
- **T-18.3 [AUTO]** Run repo validation gates: `helm lint charts/worldview-service`, `helm template` for all 10 services + infra render clean, `tofu validate`, `scripts/preflight-secrets.sh` (expected to *warn* until MANUAL age key), `.github/workflows/validate.yml` green. Accept: all pass except the deliberately-manual secret preflight.
- **T-18.4 [AUTO]** **Commit + push `worldview` repo**: the completed Ollama-drop (`enriched_consumer_main.py` + test + `manifests/ollama.yaml` removal already staged) + tofu changes (SP-4) + docs. Branch → PR → merge to `origin/main`. Accept: `git -C worldview status` clean, pushed.
- **T-18.5 [AUTO]** **Commit + push `worldview-gitops`**: the 12 local commits + ~18 modified + ~17 untracked files (all `values/*.prod.yaml`, StatefulSet/worker/secret/migrate templates, `infra-gliner` rename, `setup-secrets.sh`, this plan's chart changes). This is B9 — **nothing ArgoCD sees matters until this lands**. Accept: `git -C worldview-gitops status` clean, `origin/main` == local. Validate: `git -C worldview-gitops rev-list --count origin/main..HEAD` == 0.

**Effort SP-7: ~5–6h.**

---

# MANUAL TRACK (only the user can do these)

Ordered. Each blocks the automatable/sync steps noted.

1. **[MANUAL] Buy a domain** (any registrar). *Blocks*: T-13.1 real run, DNS, ACME, OIDC redirect URIs.
2. **[MANUAL] Hetzner account + API token** (`export TF_VAR_hcloud_token=…`). *Blocks*: `tofu apply`.
3. **[MANUAL] Hetzner Object Storage bucket for tfstate** — Console → Object Storage → create `worldview-tfstate` (nbg1, private); Security → S3 credentials → generate; write `~/.config/tofu/hetzner-s3.tfbackend` with `access_key`/`secret_key`. *Blocks*: `tofu init`.
4. **[MANUAL] Generate + back up the age key**: `age-keygen -o ~/.config/sops/age/keys.txt`; copy the `age1…` **public** key into `worldview-gitops/.sops.yaml` (replaces `age1REPLACE…`); back up `keys.txt` offline (losing it = unrecoverable secrets). *Blocks*: `setup-secrets.sh`, secret rendering, preflight.
5. **[MANUAL] Zitadel Cloud PKCE app**: create instance at zitadel.cloud → project → Web app (PKCE) → copy issuer URL / client-id / client-secret; set redirect `https://app.<DOMAIN>/api/auth/callback`. *Blocks*: `setup-secrets.sh` S9 prompts, gateway boot.
6. **[MANUAL] ghcr packages**: make `ghcr.io/arnaurodondev/worldview-*` packages **public** (Settings → Package → Change visibility) OR create a GitHub PAT with `read:packages`. *Blocks*: image pulls / `setup.sh` Step-5.
7. **[MANUAL] Fill `.sops.yaml` recipient (done in step 4) then run `tofu init -backend-config=~/.config/tofu/hetzner-s3.tfbackend && tofu apply`** in `infra/tofu/` (after SP-4 pushed). *Blocks*: cluster exists.
8. **[MANUAL] Retrieve kubeconfig**: `ssh root@$(tofu output -raw cp_ip) 'cat /tmp/kubeconfig' > ~/.kube/config-worldview; export KUBECONFIG=~/.kube/config-worldview`. *Blocks*: `setup.sh`.
9. **[MANUAL] Run `bash bootstrap/setup-secrets.sh`** (interactive — needs EODHD, DeepInfra, Brevo, Zitadel, optional Cohere/Finnhub/etc. keys); it encrypts `secrets/*.yaml`. Then run `scripts/set-domain.sh <yourdomain>`. Commit the encrypted `secrets/*.yaml` + domain-filled files, push. *Blocks*: ArgoCD secret rendering.
10. **[MANUAL] Run `bash bootstrap/setup.sh`** (installs CCM/CSI, ghcr secret, ArgoCD, age-key secret, repo cred, root-app). *Blocks*: sync.
11. **[MANUAL] Point DNS**: after Traefik LB provisions, get its IP (`kubectl -n traefik get svc traefik …`), create A-records `api`/`app`/`ws`/`grafana` → LB IP. *Blocks*: ACME HTTP-01.
12. **[MANUAL] LE staging→prod**: after staging cert verifies, switch Ingresses to `letsencrypt-prod` issuer (or leave prod if confident). *Blocks*: trusted TLS.
13. **[MANUAL] Vercel**: connect `apps/worldview-web`, set `NEXT_PUBLIC_API_BASE_URL=https://api.<DOMAIN>`, attach `app.<DOMAIN>` custom domain. *Blocks*: frontend reachable.

---

# Implementation partitioning (parallel-agent file ownership)

To run multiple implementation agents concurrently **without two agents editing the same file**, partition by *file ownership*, not by task. The table below is the authoritative file→task map; the batches under it are conflict-free (no file appears in two concurrently-running batches). Repo prefix: files are in `worldview-gitops/` unless marked `[wv]` (= `worldview/`).

### File → task map (contention hotspots in **bold**)

| File | Tasks that write it | Note |
|---|---|---|
| **`charts/worldview-service/templates/_helpers.tpl`** | T-1.2, T-1.4, T-16.1 | **serialize** — 3 tasks, one agent only |
| **`manifests/gliner.yaml`** | T-1.5, T-7.1 | **serialize** — 2 tasks, one agent |
| **`apps/infra-postgres.yaml`** | T-5.1, T-5.2, T-5.3 | **serialize** — 3 tasks, one agent |
| `charts/worldview-service/templates/worker.yaml` (NEW) | T-1.1 | |
| `charts/worldview-service/templates/secret.yaml` (NEW) | T-2.1 | |
| `charts/worldview-service/templates/migrate-job.yaml` (NEW) | T-6.1 | |
| `charts/worldview-service/values.yaml` | T-1.3 | |
| **`values/portfolio.yaml`** | T-3.1, T-13.1(domain) | serialize per-file |
| **`values/market-ingestion.yaml`** | T-3.1, T-11.2, T-12.1, T-12.2 | serialize per-file |
| **`values/content-ingestion.yaml`** (+`.prod.yaml`) | T-3.1, T-11.1, T-12.1 | serialize per-file |
| **`values/market-data.yaml`** | T-3.2, T-11.3, T-12.1 | serialize per-file |
| **`values/content-store.yaml`** | T-3.2, T-11.5, T-12.1 | serialize per-file |
| **`values/alert.yaml`** | T-3.2, T-11.4, T-12.1, T-13.1(domain) | serialize per-file |
| **`values/knowledge-graph.yaml`** | T-3.3, T-12.2 | serialize per-file |
| **`values/rag-chat.yaml`** | T-3.3, T-12.1, T-12.2 | serialize per-file |
| **`values/api-gateway.yaml`** | T-3.3, T-12.1, T-14.1, T-13.1(domain) | serialize per-file |
| **`values/nlp-pipeline.yaml`** (+`.prod.yaml`) | T-3.4, T-12.2 | serialize per-file |
| `apps/*.yaml` (sync-wave) | T-4.1, T-4.2 | edits every Application; run alone or last |
| `apps/infra-kafka.yaml` | T-7.2 | (also touched by T-4.1 sync-wave — sequence T-4.1 after T-7.2 or same agent) |
| `apps/worldview-intelligence-migrations.yaml` + `values/intelligence-migrations.yaml` (NEW) | T-6.3 | |
| `apps/argocd-image-updater.yaml` (DELETE) | T-16.1 | (pairs with `_helpers.tpl` annotation removal — same agent as hotspot #1) |
| `bootstrap/setup.sh` | T-2.3 | |
| **`bootstrap/setup-secrets.sh`** | T-11.4, T-12.3 | serialize |
| `scripts/preflight-secrets.sh` (NEW) | T-2.4 | |
| `scripts/set-domain.sh` (NEW) | T-13.1 | |
| `scripts/verify-prod-health-k8s.sh` (NEW) | T-17.1 | |
| `scripts/smoke-endpoints.sh` (NEW) | T-17.3 | |
| `apps/synthetic-monitor.yaml` + values (NEW) | T-17.2 | |
| `k8s/ingress/*.yaml`, `k8s/cert-manager/cluster-issuers.yaml` | T-13.1, T-13.2 | |
| `.github/workflows/validate.yml` | T-2.4 | |
| `[wv] .github/workflows/deploy.yml` | T-16.2, T-16.3 | |
| `[wv] infra/tofu/cloud-init/worker-*.yml` (NEW split) | T-9.1, T-10.1 | |
| `[wv] infra/tofu/main.tf` | T-9.2 | |
| `[wv] infra/tofu/ip.tf`, `outputs.tf`, `terraform.tfvars.example` | T-10.2, T-10.3, T-9.3 | |
| **`docs/OPERATIONS.md`** | T-4.2, T-13.3, T-14.2, T-15.3, T-18.2 | serialize — one docs agent |
| **`docs/CONFIG_MANAGEMENT.md`** | T-8.1, T-18.2 | serialize |
| `apps/worldview-web/` (Vercel) | T-15.1 | |

### Conflict-free parallel batches

Run batches **in the numbered order**; within a batch every listed agent touches a disjoint file set, so they run concurrently. (Batch 0 = the already-done Ollama-drop commit; see execution order §1.)

- **Batch A (chart scaffolding — gates B & C):**
  - Agent A1 → `_helpers.tpl` + `apps/argocd-image-updater.yaml` (T-1.2, T-1.4, T-16.1) — the hotspot, one agent.
  - Agent A2 → new templates `worker.yaml`, `secret.yaml`, `migrate-job.yaml` + `values.yaml` (T-1.1, T-2.1, T-6.1, T-1.3).
  - Agent A3 → `manifests/gliner.yaml` (T-1.5, T-7.1) + `apps/infra-kafka.yaml` (T-7.2) + `apps/infra-postgres.yaml` (T-5.1, T-5.2, T-5.3).
  - Agent A4 `[wv]` → all tofu files (T-9.1, T-9.2, T-9.3, T-10.1, T-10.2, T-10.3) — independent repo.
- **Batch B (values — one agent PER service file, all parallel; depends on Batch A worker/secret schema):**
  - One agent each for `portfolio` / `market-ingestion` / `content-ingestion` / `market-data` / `content-store` / `alert` / `knowledge-graph` / `rag-chat` / `api-gateway` / `nlp-pipeline` values files, each doing that file's full task set (workers + env-sync + gateway/domain vars). 10 disjoint files → up to 10 concurrent agents. Do NOT run T-13.1's `set-domain.sh` sed here — leave `<DOMAIN>` literal; the domain fill is a later single pass.
- **Batch C (apps + migrations + secrets + bootstrap):**
  - Agent C1 → `apps/worldview-intelligence-migrations.yaml` + `values/intelligence-migrations.yaml` (T-6.3), enable `migrate:` — note this only edits the intelligence-migrations values/app, NOT the 8 service values (those `migrate:` toggles belong to each service's Batch-B agent to avoid re-touching the file).
  - Agent C2 → `bootstrap/setup.sh` (T-2.3) + `bootstrap/setup-secrets.sh` (T-11.4, T-12.3).
  - Agent C3 → `scripts/*` new scripts + `apps/synthetic-monitor.yaml` (T-2.4, T-17.1, T-17.3, T-17.2) + `.github/workflows/validate.yml`.
  - Agent C4 → `k8s/ingress/*` + `k8s/cert-manager/*` + `scripts/set-domain.sh` (T-13.1 script authoring, T-13.2).
  - Agent C5 `[wv]` → `deploy.yml` image-promotion (T-16.2, T-16.3).
- **Batch D (sync-waves — touches every `apps/*.yaml`, so runs ALONE after A & C):** Agent D1 → T-4.1, T-4.2 sync-wave annotations across all `apps/*.yaml`. Must be serialized against A3/C1 (which also edit `apps/` files).
- **Batch E (docs — 2 serial agents, after everything else lands so they describe final state):** Agent E1 → `docs/OPERATIONS.md` (T-4.2 table, T-13.3, T-14.2, T-15.3, T-18.2); Agent E2 → `docs/CONFIG_MANAGEMENT.md` (T-8.1, T-18.2). Plus `apps/worldview-web/` Vercel config (T-15.1) — independent.
- **Batch F (final gate — single agent, serial):** T-18.3 validation gates, then T-18.4/T-18.5 commit+push BOTH repos (B9). Never parallelize; this is the pivot.

**Hard serialization rules for orchestrators:** (1) never run two Batch-B agents on the same file — they are already partitioned one-per-file; (2) `apps/*.yaml` is edited by A3 (infra-kafka/postgres), C1 (new migrations app), and D1 (sync-wave sweep) — sequence D1 **after** A3+C1; (3) `_helpers.tpl` is single-owner (A1); (4) run E (docs) and F (commit) strictly last.

---

# Critical path & ordering (DAG)

```
[AUTO all SP-1..SP-7] ──► T-18.4/18.5 COMMIT+PUSH BOTH REPOS (B9)  ◄── the pivot; nothing downstream works before this
        │
        ├─ MANUAL 1 (domain) ─┐
        ├─ MANUAL 2,3 (hetzner token+tfstate) ─┤
        ├─ MANUAL 4 (age key → .sops.yaml) ────┤
        ├─ MANUAL 5 (zitadel) ─────────────────┤
        └─ MANUAL 6 (ghcr public) ─────────────┤
                                               ▼
                              MANUAL 7  tofu apply (needs 2,3,4-pubkey, SP-4 pushed)
                                               ▼
                              MANUAL 8  kubeconfig
                                               ▼
                              MANUAL 9  setup-secrets.sh + set-domain (needs 1,4,5) → commit secrets
                                               ▼
                              MANUAL 10 setup.sh → root-app sync
                                               ▼
              ArgoCD sync-waves:  infra(-2) → schema-registry(-1) → migrations(0) → services+workers(1) → issuers(2)
                                               ▼
                              MANUAL 11 DNS → LB IP   →   ACME issues cert   →   MANUAL 12 LE prod
                                               ▼
                              MANUAL 13 Vercel frontend
                                               ▼
                    [AUTO] scripts/verify-prod-health-k8s.sh + smoke-endpoints.sh (§6 items 1–12)
```

**Blocking notes**: The single hard gate is **T-18.4/18.5 (B9 commit+push)** — every ArgoCD behaviour depends on `origin/main`. Within the manual track: age-key (4) gates both `tofu apply` (pubkey unrelated but secrets flow) and `setup-secrets`; domain (1) gates `set-domain`, DNS, ACME, Zitadel redirect. Migrations (sync-wave 0, SP-2) gate all DB-touching services — without them the §6 items 3–11 return 500s.

---

# Risk register (top 5)

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | **Cross-repo / cross-session conflict** — gitops is 12 commits ahead + many untracked; a sibling session (per R42/BP-590) mutates the same tree. | Lost work, silent conflict markers, ArgoCD deploys stale state. | Do all gitops work in a dedicated `git worktree`; `git commit` never `stash`; run `scripts/orphan_commit_check.sh` before push; land B9 (T-18.5) as the first merged change so the baseline is visible. |
| R2 | **Worker-topology fidelity vs compose** — 52 hand-transcribed `command:` modules; one wrong module path → a silent dead consumer (all-green/zero-output). | Pipeline stage silently dead; §6 item 7/8/11 fail. | The inventory table is copied verbatim from compose `command:` lines; SP7 smoke test asserts item-7 edges>0 / item-8 populated / item-11 <24h to catch any dead consumer; helm-template count assertions per service. |
| R3 | **RF=1 vs RF=3 on a partly-existing cluster** — the Kafka RF=3 config only applies to *net-new* topics; a re-used broker keeps RF=1 (documented caveat). | Under broker loss, RF=1 topics unavailable. | Fresh cluster only (no topic migration in scope); topics born RF=3 via provisioning Job; `docs/runbooks/kafka-rf-migration.md` documents the reassign path if ever needed. |
| R4 | **Secrets not natively GitOps** — even with the new Secret template, the age *private* key lives only in the ArgoCD namespace secret + the user's laptop; rotation is manual. | Secret drift; unrecoverable on age-key loss. | New `secret.yaml` template + helm-secrets makes rendering self-healing (B8 closed); `preflight-secrets.sh` blocks placeholder recipient; MANUAL step 4 mandates offline age-key backup; accept the residual "private key is out-of-band" tradeoff (documented in CONFIG_MANAGEMENT.md). |
| R5 | **Resource over-commit / OOM** — stateful node hosts GLiNER 8Gi + 3×Kafka(4Gi) + Postgres 6Gi + MinIO on one box; local history shows GLiNER thread-thrash OOM at oversubscription. | OOM-137 kills GLiNER → NER dead → whole NLP→KG pipeline stalls. | GLiNER thread pins (T-7.1) + 8Gi; Kafka heap capped 3G (T-7.2); swap on both workers (T-10.1); stateful node ≥32GB enforced (T-9.3); capacity sum documented; sync-wave startup avoids thundering-herd. |

---

# Effort estimate

| Sub-plan | Scope | Rough hrs |
|---|---|---|
| SP-1 | Chart topology: worker template + probes + secret template + 10 values worker lists + sync-waves | 14–18 |
| SP-2 | DB bootstrap: initdb `\gexec` + extensions/AGE + migration Jobs + intelligence-migrations app | 6–8 |
| SP-3 | Sizing: GLiNER/Kafka/worker resources + single-Postgres decision | 4–5 |
| SP-4 | Tofu: split cloud-init + node labels + swap + LB/floating-IP | 4–6 |
| SP-5 | Env sync: Category-A + Category-B into values | 4–5 |
| SP-6 | Edge: domain param + Zitadel + Vercel + image-promotion/ghcr | 6–8 |
| SP-7 | Validation scripts + synthetic monitor + docs + **commit/push both repos** | 5–6 |
| **AUTOMATABLE total** | | **~43–56 h (≈6–8 working days for one agent/dev)** |
| MANUAL track | domain/accounts/apply/secrets/DNS/Vercel (mostly wait time) | ~3–5 h active + provisioning waits |
| **Wall-clock to validated** | with review/QA/live-debug iterations | **~1.5–2 weeks** (matches report §2) |

---

# Suggested execution order (waves)

1. **SP-7 W2 partial first**: land B9 commit/push of the *already-done* work (Ollama drop + existing gitops tree) so there is a clean pushed baseline before adding more.
2. SP-4 (tofu) ∥ SP-1 W1 (worker template) — independent.
3. SP-1 W2/W3/W4, SP-2 (both depend on chart scaffolding).
4. SP-3, SP-5 (values-only, parallelizable).
5. SP-6 (edge/config).
6. SP-7 W1 (validation) then W2 final commit/push both repos.
7. Hand off the MANUAL track runbook to the user.
