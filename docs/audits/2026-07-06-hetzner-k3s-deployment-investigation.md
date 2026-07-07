# Investigation Report: Hetzner Deployment of the Worldview Platform

**Date**: 2026-07-06
**Investigator**: Claude (investigate skill, 6-agent parallel orchestration)
**Severity**: HIGH — deployment is blocked on multiple independent hard failures
**Status**: Root causes identified; go/no-go decision required before execution

---

## 1. Issue Summary

The user wants to deploy the full Worldview platform to Hetzner "in the next couple of days" using a **k3s cluster + ArgoCD** connected to the **worldview-gitops** repo, plus external tools (a user authenticator and image storage). This investigation audits the *actual on-disk state* of the IaC, GitOps, and supporting config across six dimensions to determine what exists, what is broken, and the exact next steps to a **validated** deployment.

**Headline finding**: This is **not** greenfield — a large amount of infrastructure already exists (OpenTofu for Hetzner k3s, an ArgoCD app-of-apps, a shared Helm chart, prod value overlays, Zitadel integration, ghcr.io CI). **But the k3s/GitOps path has at least 8 independent hard blockers, several of which each *alone* prevent a working platform.** The "couple of days" timeline is realistic only for the **single-server Docker Compose** path (which is a tested, linear runbook); the multi-node k3s+ArgoCD path needs roughly **1–2 weeks** of chart/manifest work before it can produce a *validated* deployment.

---

## 2. Two Divergent Deployment Stacks (the first thing to understand)

The repo contains **two parallel, non-interoperable deployment models**. You must pick one.

| | **Stack A — k3s + ArgoCD (what the user asked for)** | **Stack B — single-server Docker Compose** |
|---|---|---|
| Provisioning | `infra/tofu/` (OpenTofu) → 3 Hetzner nodes | `infra/gitops/scripts/hetzner-bootstrap.sh` → 1 Ubuntu box |
| Orchestration | k3s + ArgoCD app-of-apps (`worldview-gitops/`) | `docker compose -f docker-compose.prod.yml` (`make prod`) |
| Runbook | `worldview-gitops/bootstrap/setup.sh` + `docs/hetzner-setup.md` says "no k8s" (contradicts) | `infra/gitops/docs/hetzner-setup.md`, `production-deployment.md` |
| Workers | **MISSING** (chart deploys API-only, see B1) | ✅ all 49 workers as containers |
| Migrations | **MISSING** (no Job/app, see B2) | ✅ `*-migrate` one-shots + `intelligence-migrations` |
| Maturity | Many unfinished edges | Linear, tested, has swap + known-good sizing |
| Cost | ~€78/mo (3 nodes + LB + storage) | ~€25/mo (1 CPX41) |
| Timeline to *validated* | ~1–2 weeks | ~1–2 days |

`infra/gitops/docs/hetzner-setup.md:3-6` literally says "Docker Compose + Traefik v3 (no Kubernetes required)" while `infra/tofu/` + `worldview-gitops/` build Kubernetes. This contradiction is unresolved in the repo.

---

## 3. Blocker Register (k3s / Stack A)

Severity: 🔴 = platform will not function; 🟠 = high; 🟡 = medium. Each 🔴 is independently fatal.

### Deploy-topology blockers

- **🔴 B1 — No worker/consumer/dispatcher workloads exist on k3s.** The Helm chart (`worldview-gitops/charts/worldview-service`) renders exactly **one API pod per service**. Per **R22**, the FastAPI lifespan deliberately does *not* start background work (`services/nlp-pipeline/src/nlp_pipeline/app.py:128-134`). Docker Compose runs **49 separate worker containers** (outbox dispatchers, Kafka consumers, schedulers). On k3s these have **no equivalent** → outbox never drains, no events consumed, the entire event-driven pipeline (ingestion → NLP → KG → alerts) is dead even though every pod reports "Ready". This is the project's signature "all-green / zero-output" trap, at the deployment-topology level.

- **🔴 B2 — No database migrations run on k3s.** Service `Dockerfile` CMD is `uvicorn` only (`services/portfolio/Dockerfile:75`); there are no `*-migrate` Jobs, no `intelligence-migrations` ArgoCD Application, and no PreSync hooks (`grep kind:Job apps/ charts/` → none). Fresh cluster → empty schemas → universal 500s. `bootstrap/setup.sh:134` leaves "run intelligence-migrations" as a manual step with **no artifact to run**.

- **🔴 B3 — Health-probe path mismatch → pods never become Ready.** The chart hardcodes liveness/readiness `path: /health` (`charts/.../_helpers.tpl`), but services expose only `/healthz` + `/readyz`. api-gateway explicitly *removed* bare `/health` (`api-gateway/.../middleware.py:25`); market-data has only `/healthz`+`/readyz` (`market_data/app.py:1061,1065`). Probe → 404 → NotReady → CrashLoop for at least api-gateway and market-data (likely all).

### Provisioning blockers

- **🔴 B4 — Worker nodes are never labeled `node-role`.** `infra/tofu/cloud-init/worker.yml` joins both agents with **no `--node-label`**; only the control-plane gets a label. But *every* workload has `nodeSelector: node-role: stateful|stateless`. **No node satisfies either selector → every pod stays `Pending` forever.** Both workers also share one identical cloud-init template, so they're indistinguishable. Guaranteed total failure on a fresh `tofu apply`.

- **🔴 B5 — Postgres init uses invalid SQL → zero databases created.** `apps/infra-postgres.yaml:33-42` uses `CREATE DATABASE IF NOT EXISTS …`, which **PostgreSQL does not support**. With `ON_ERROR_STOP=1`, the first statement errors and initdb aborts → none of the 10 DBs are created → every service crash-loops on connect. (Compose uses the `SELECT … WHERE NOT EXISTS … \gexec` idiom instead.)

- **🔴 B6 — Postgres extensions never enabled + `kg_db` missing.** The gitops initdb only issues `CREATE DATABASE`; it never runs `CREATE EXTENSION vector/pg_trgm/age` or `create_graph('worldview_graph')` (which the compose image does in `infra/postgres/init-intelligence/init-databases.sh:38-67`). Even with B5 fixed, KG's `LOAD 'age'` and pgvector columns fail. `kg_db` is also absent from the DB list.

### Secrets / config blockers

- **🔴 B7 — `.sops.yaml` is an unconfigured placeholder** (`age1REPLACE_WITH_YOUR_AGE_PUBLIC_KEY`, `.sops.yaml:5`) and `secrets/` is **empty** (only README). Every `worldview-*` app references `secrets/<svc>-secrets.yaml` via helm-secrets. On a fresh sync those files don't exist → every app fails to render. Nothing can be encrypted until the age recipient is real.

- **🟠 B8 — Secrets are not actually GitOps-managed.** The chart has **no `Secret` template**, so the `secrets+age-import://` valueFiles are a **no-op for Secret creation**. Runtime `<svc>-secrets` Secrets exist only because `setup.sh:110-119` applies them **once, manually**. No self-heal, no prune, and rotating a secret in git does **not** propagate to pods. `setup.sh:111`'s claim "ArgoCD will manage secrets after this" is false.

### Deployment-state blocker

- **🔴 B9 — All prod work is uncommitted and unpushed.** worldview-gitops local `main` is **11 commits ahead of `origin/main`** *plus* ~18 modified + ~17 untracked files. Every `values/*.prod.yaml` overlay, the StatefulSet template, the multi-broker Kafka rewrite, and `docs/CONFIG_MANAGEMENT.md` exist **only in the local working tree**. ArgoCD syncs from GitHub `origin/main` → a fresh sync today deploys the **old pre-prod state**, not what the docs describe.

### Sizing / reliability (high)

- **🟠 B10 — GLiNER memory limit 4Gi → OOM.** `manifests/gliner.yaml:33-39` caps at 4Gi with no thread-pinning env. Project memory records GLiNER OOM-137 at <8Gi with `urchade/gliner_large-v2.1`. Needs limit ≥8Gi + `*_NUM_THREADS=4` (OMP/MKL/OPENBLAS/NUMEXPR/TORCH) + `GLINER_MODEL_PATH`.
- **🟠 B11 — Kafka JVM heap defaults to 1G in a 4Gi container.** `apps/infra-kafka.yaml` sets no `heapOpts`; Bitnami 32.x defaults `-Xmx1024m`. Reproduces the documented 1G-heap GC-freeze wedge. Set `broker.heapOpts`/`controller.heapOpts` ≈ 3G.
- **🟠 B12 — worker-1 (cx52, 32GB) memory over-commit, no swap.** Sum of limits on the stateful pool (Ollama 20Gi + 3×Kafka 4Gi + Postgres 4Gi + GLiNER 4Gi + …) ≈ 46Gi > 32GB, and k3s cloud-init configures **no swap** (only Stack B's script does). OOM-killer under real ML+Kafka load.
- **🟠 B13 — 6 of 8 DeepInfra keys never generated for prod.** `setup-secrets.sh` writes only `RAG_CHAT_DEEPINFRA_API_KEY`. The 4 NLP keys, 2 KG keys, and the gateway screener key are absent → S6/S7/S9 ML paths silently degrade.
- **🟠 B14 — No prod Zitadel provisioned; S9 won't boot without it.** No k8s manifest for Zitadel (only local docker-compose). Intended path is **Zitadel Cloud** (managed, free ≤25k MAU) but the issuer/client-id are placeholders. `values/api-gateway.yaml` sets `OIDC_DISCOVERY_OPTIONAL=false` → gateway crashes on boot without valid OIDC.

### Ingress / external (high/critical)

- **🔴 B15 — `<DOMAIN>` is an unfilled placeholder everywhere** (2 Ingresses, 2 ClusterIssuers, CORS, redirect URIs). The user **must buy a domain** and **manually create DNS A-records** → Hetzner LB IP (which only exists after Traefik provisions the LB). ACME HTTP-01 fails until DNS resolves. ClusterIssuer email is also `admin@<DOMAIN>`.
- **🟠 B16 — Floating-IP vs Hetzner-LB conflict.** Tofu provisions a floating IP on cp-1 and docs point DNS there, but Traefik is `type: LoadBalancer` → CCM provisions a **separate** managed LB with its own IP. The floating IP is unused; DNS guidance is wrong. Pick one.
- **🟠 B17 — No frontend deployment target on k3s.** No `apps/worldview-web.yaml`, no `values/worldview-web.yaml`, no `app.<DOMAIN>` Ingress, and CI (`deploy.yml`) does **not** build/push a frontend image. Options: Vercel (recommended for thesis) or author the full in-cluster App + Ingress + CI job.

### Ordering / validation (critical)

- **🔴 B18 — No startup ordering on k3s.** Zero ArgoCD sync-waves/hooks (`grep sync-wave apps/` → 0). All ~20 apps sync in parallel; ordering relies on crash-loop-and-retry. Combined with B2, services never recover schema-wise.
- **🟠 B19 — Validation tooling is compose-only.** `verify-prod-health.sh` uses `docker ps`/`ss` (won't validate k3s pods); `synthetic_monitor.py` is absent from gitops → no synthetic probe on k3s → the recurring DeepInfra silent-401 death would go unalerted.

### Image promotion (high)

- **🟠 B20 — ArgoCD Image Updater is inert / contradictory.** The `image-list` annotation renders on the **pod template**, not the **Application** object (where the updater reads it), and the global `updateStrategy: semver` can't match `latest`/SHA tags. Meanwhile the monorepo `deploy.yml` opens a per-service PR to bump `values/<svc>.yaml` — a *second*, contradictory promotion path. All images are pinned `latest` + `pullPolicy: Always`, so there's no SHA record and no clean git rollback.

**Registry finding (good news)**: Image storage is **already fully wired to ghcr.io** (`ghcr.io/arnaurodondev/worldview-*`). CI builds and pushes per-service images; the chart injects `imagePullSecrets: [ghcr-credentials]`. **No new/paid registry is needed.** Simplest fix: make the packages **public** (drops the pull secret entirely) or supply a `read:packages` PAT.

---

## 4. What Already Works (so we don't rebuild it)

- **OpenTofu Hetzner provisioning** (`infra/tofu/`): 3 nodes (cx32 CP + cx52 stateful + cx42 stateless), private network, firewall (80/443 public, 22/6443 dev-IP-only), S3 tfstate backend, floating IP, 5 volumes. k3s v1.31.4 via cloud-init, Flannel CNI, Hetzner CCM + CSI (`hcloud-volumes`), Traefik/servicelb disabled.
- **ArgoCD app-of-apps** (`apps/root-app.yaml`): one root app → ~20 children (6 infra Helm charts, ollama/gliner manifests, traefik, cert-manager, kube-prometheus-stack, image-updater, 10 services). Auto-sync + selfHeal. Stateful infra correctly `prune:false`.
- **Shared Helm chart** parametrised by `values/<svc>.yaml`, with 7 `.prod.yaml` overlays.
- **Edge/TLS story is solid**: Traefik v3 + cert-manager + Let's Encrypt (staging + prod issuers), HTTP→HTTPS redirect, rate-limit middleware, HSTS/security headers, host-port closure. `verify-prod-health.sh` checks all of this (for the compose path).
- **Secrets model** (SOPS + age, helm-secrets in argocd repo-server) and a **DeepInfra rotation runbook**. Dev already de-fragilizes the 8→1 DeepInfra key via `@@DEEPINFRA_API_KEY@@` tokens.
- **ghcr.io CI**: `deploy.yml` builds a python-base + per-service matrix, tags `latest`+`sha7`, pushes, and opens gitops bump PRs.
- **Auth safety**: `POST /v1/auth/dev-login` is hard-blocked when `app_env=production` (SEC-003) — *provided* `API_GATEWAY_APP_ENV=production` is actually set (it is **not** in `values/api-gateway.yaml` today — must be added).

---

## 5. Resource Footprint & Cluster Sizing

**As gitops is configured today (workers absent):** ~16 vCPU / ~37 GiB in *requests*; ~44+ vCPU / ~75+ GiB in *limits*. Dominators: Ollama (4→12 vCPU, 8→20 GiB), Kafka 4 KRaft pods (2→8 vCPU, 8 GiB), GLiNER, Postgres.

**With the 49 workers added back (required for function):** +~5–8 vCPU / +12–16 GiB → floor ~22–24 vCPU / ~50 GiB. Do **not** oversubscribe (local ran 48 containers on 14 cores at load ~150 → GLiNER thread-thrash OOM). Realistic Hetzner layout: 1 stateful node CCX33/43 (8–16 vCPU / 32–64 GiB) + 1–2 stateless nodes (8 vCPU / 16–32 GiB).

**RESOLVED (2026-07-06) — Ollama can be dropped.** Traced every consumer:
- rag-chat reranker (`bge-reranker-v2-m3`) is **dead code** — the model doesn't exist in the Ollama registry, so it always fails to fusion_score sort; the real reranker is Cohere. rag-chat's Ollama LLM tier is "emergency"-only and `chat_with_tools`/`stream_chat` skip it.
- Every KG/NLP embedding, relevance-scoring, unresolved-resolution, and deep-extraction site selects DeepInfra when `embedding_provider=deepinfra`/key present (prod values already set this), falling back to Ollama only when misconfigured — **except** `knowledge-graph/.../enriched_consumer_main.py`, which **hardcoded** `OllamaEmbeddingAdapter` ("required — exits if unavailable"). **Fixed** on 2026-07-06 to use the same provider switch as the sibling consumers (commit pending). DeepInfra `BAAI/bge-large-en-v1.5` and Ollama `bge-large:latest` are both 1024-dim → vector-compatible; on a fresh cluster the "re-embed on provider switch" caveat is moot.
- KG extraction fallback chain is DeepInfra → Ollama → **Gemini**; dropping the Ollama middle tier is covered by the Gemini tertiary (`GEMINI_API_KEY` already a KG secret).

**Coupling:** dropping Ollama is safe **only if the DeepInfra keys are actually provisioned in prod (blocker B13)** — otherwise the fallback branches try to reach a now-deleted `ollama.infra.svc` and fail hard. Remaining drop steps: (1) delete `worldview-gitops/manifests/ollama.yaml` + the ollama-model-pull Job (KEEP `gliner.yaml` — GLiNER is a separate NER server, not Ollama; the `infra-ollama` app serves both via `path: manifests`, so rename it to `infra-gliner` after); (2) close B13 (add the 6 missing DeepInfra keys to `setup-secrets.sh`/prod secrets); (3) optionally set a Cohere key for real reranking, else accept fusion_score fallback. This removes the single biggest resource line item (Ollama req 4 vCPU/8 GiB, limits 12 vCPU/20 GiB, 30 GiB PVC) — materially shrinks the stateful node.

---

## 6. Post-Deploy Validation Checklist (endpoint-level, S9 only)

The critical principle: **checks that only hit `/healthz`+`/readyz` will falsely pass** on the current worker-less config. Items 7, 8, 11 exercise the consumer pipeline and are the ones that catch "all-green / zero-output".

| # | Method + endpoint (via `api.<DOMAIN>`) | Expect | Proves |
|---|---|---|---|
| 1 | `GET /healthz` | 200 | gateway up |
| 2 | `GET /readyz` | 200 | gateway dep graph healthy |
| 3 | `GET /v1/instruments?query=AAPL` | 200 non-empty | market-data DB + migration applied |
| 4 | `GET /v1/quotes/{id}` | 200 w/ price | market-data + ingestion live |
| 5 | `GET /v1/instruments/{id}/financials` | 200 | fundamentals consumer ran |
| 6 | `GET /v1/holdings/{portfolio_id}` (auth) | 200 | portfolio DB + snapshot worker |
| 7 | `GET /v1/entities/{id}/graph` | 200, edges>0 | **KG consumers + AGE sync alive** |
| 8 | `GET /v1/morning-brief` | 200 populated | rag-chat pregen worker + DeepInfra key |
| 9 | `POST /v1/chat` (stream) | SSE incremental tokens | rag-chat + streaming + DeepInfra |
| 10 | `WS wss://ws.<DOMAIN>/v1/alerts/stream` | upgrade/heartbeat | alert WS + IntelligenceConsumer |
| 11 | `GET /v1/news` (momentum) | 200, items <24h | ingestion→NLP→KG end-to-end freshness |
| 12 | DeepInfra `GET /models` w/ prod key | 200 | shared-key freshness (no silent 401) |

---

## 7. Recommended Path & Next Steps

See the conversation for the go/no-go decision. Two viable routes:

### Route 1 — Stack B (single-server Docker Compose) — *fits the 2-day timeline*
Lowest risk; tested linear runbook; workers + migrations already handled. Steps: provision 1 Hetzner box (`infra/gitops/scripts/hetzner-bootstrap.sh`), buy domain + DNS, fill secrets (`env/prod` + platform.env), `make prod`, run `verify-prod-health.sh` + §6 checklist. Loses: multi-node HA, ArgoCD GitOps. ~€25/mo.

### Route 2 — Stack A (k3s + ArgoCD) — *the requested architecture, ~1–2 weeks to validated*
Requires closing B1–B20. Ordered work:
1. **Commit + push** worldview-gitops prod work to `origin/main` (B9) — nothing else matters until ArgoCD can see it.
2. **Chart: add worker workloads** (B1) — a `worker`/`consumer` Deployment (or StatefulSet) per background entry point, command-overridden, ~49 units templated by a `workers:` list in values. Largest single effort.
3. **Chart: add migration Jobs + `intelligence-migrations` app** with PreSync hooks / sync-wave 0 (B2).
4. **Chart: fix probe paths** `/health` → `/healthz` (liveness) + `/readyz` (readiness) (B3).
5. **Fix Postgres initdb** to valid `\gexec` idiom + extensions + AGE graph + `kg_db` (B5, B6).
6. **Tofu: label worker nodes** (`--node-label node-role=stateful|stateless`, split the two cloud-inits) (B4); add swap (B12).
7. **Resolve ingress**: keep Hetzner LB, drop floating IP (B16); add sync-waves infra(-2)→schema-reg(-1)→migrations(0)→services(1)→workers(2) (B18).
8. **Secrets**: real age recipient (B7); add a `Secret` template so helm-secrets renders (B8); add the 6 missing DeepInfra keys (B13); set `API_GATEWAY_APP_ENV=production`.
9. **Sizing**: GLiNER ≥8Gi + thread pins (B10); Kafka heap ~3G (B11).
10. **External**: Zitadel Cloud PKCE app + seal OIDC secrets (B14); buy domain + DNS + real ACME email (B15); pick frontend host — Vercel recommended (B17); make ghcr packages public or supply PAT.
11. **Fix or delete** ArgoCD Image Updater; stop shipping `latest`; pin SHAs (B20).
12. **Port validation to k8s**: add synthetic-monitor manifest; adapt/replace `verify-prod-health.sh`; run §6 checklist (B19).

---

## 7b. Env-Sync Audit — docker.env vs worldview-gitops (2026-07-06)

Name-level diff of every `services/<svc>/configs/docker.env` against gitops (`env/dev/*.env`, `values/*.yaml`, `values/*.prod.yaml`, `setup-secrets.sh`). Script: `scratchpad/env_sync_audit.py`.

**Category A — vars with NO home in gitops at all (15, must be added before deploy):**
| Service | Missing vars | Notes |
|---|---|---|
| content-ingestion | `CONTENT_INGESTION_EODHD_DAILY_QUOTA`, `_EODHD_MONTHLY_QUOTA`, `_EODHD__GENERAL_NEWS_FIREHOSE_ENABLED`, `_GENERAL_NEWS_POLL_INTERVAL_SECONDS`, `_GENERAL_NEWS_SHADOW_MODE`, `APP_ENV` | Recent EODHD daily-quota + general-news firehose features (never propagated to gitops) |
| market-ingestion | `MARKET_INGESTION_EODHD_DAILY_QUOTA`, `_EODHD_MONTHLY_QUOTA`, `APP_ENV` | Same EODHD daily-quota work |
| market-data | `COMPUTED_METRICS_REFRESH_HOUR_UTC`, `MARKET_DATA_INTELLIGENCE_ROLLUP_HOUR_UTC` | Rollup scheduling |
| alert | `ALERT_S7_INTERNAL_JWT`, `ALERT_S7_KNOWLEDGE_GRAPH_BASE_URL`, `APP_ENV` | alert→KG (S7) wiring absent → alert can't reach KG in prod |
| content-store | `APP_ENV` | prod-safety flag |

**Category B — present in dev/shared but MISSING FROM k8s `values/*.yaml` (deploy-relevant):**
- **`APP_ENV`** across alert/content-ingestion/content-store/market-data/market-ingestion/rag-chat — **prod-safety**: without `APP_ENV=production` (or the per-service prefixed form), dev-mode guards (e.g. dev-login, OIDC-optional) may stay active. Verify each service reads the prefixed vs global form and set it in prod.
- **`RAG_CHAT_COHERE_API_KEY`** — Cohere is now the ONLY real reranker after the Ollama drop; without it, rag-chat silently falls back to fusion_score sort. Added to `setup-secrets.sh` as optional (2026-07-06).
- **`*_DATABASE_URL_READ`** (nlp, knowledge-graph, market-ingestion, rag-chat) — R27 read-replica URLs. On single-Postgres prod they can point at the primary, but must be set explicitly or reads may misconfigure.
- **`*_SERVICE_ACCOUNT_TOKEN`** (api-gateway, rag-chat) — paired S9↔S8 token; must match and be in prod secrets.
- **`*_INTERNAL_JWT_SKIP_VERIFICATION`** (all) — correctly ABSENT from values (defaults to secure/false in prod); no action, but confirm no service defaults it to true.
- MINIO_* alternate names (content-ingestion/content-store) — dev uses `*_MINIO_ENDPOINT/ACCESS/SECRET`; values use `*_STORAGE_*`. Confirm the service reads the STORAGE_* form or add aliases.

**Recommendation**: treat Category A as a required pre-deploy sync wave (copy dev values, but set `APP_ENV=production` and firehose `SHADOW_MODE=false` deliberately, not copied from dev). This is exactly the "dev↔k8s values maintained separately → drift" risk flagged in §3 (BLOCKER register, gitops audit).

## 8. Compounding Recommendations
- **BUG_PATTERNS.md**: add "chart deploys API-only, workers/migrations absent → all-green/zero-output at deploy-topology level" and "k8s health-probe path drift vs app (`/health` vs `/healthz`)".
- **worldview-gitops docs**: resolve the Stack A vs Stack B contradiction in `hetzner-setup.md` (says "no k8s") vs the k3s repo.
- **Preflight check**: a CI/script assertion that every referenced `secrets/*.yaml` exists and `.sops.yaml` has a non-placeholder recipient before allowing a prod sync.

## 9. Open Questions
1. Stack A (k3s) vs Stack B (compose) — the decision that reframes everything.
2. ~~Is Ollama still required in prod?~~ **RESOLVED — drop Ollama** (see §5). Code fix landed in `enriched_consumer_main.py`; remaining: gitops manifest removal + close B13.
3. Frontend: Vercel vs in-cluster.
4. Is multi-node HA a hard thesis requirement, or is a single robust node acceptable?
