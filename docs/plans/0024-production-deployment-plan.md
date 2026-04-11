---
id: PLAN-0024
title: Production Deployment Infrastructure
prd: docs/specs/0024-production-deployment-infrastructure.md
status: in-progress
created: 2026-04-11
updated: 2026-04-11
---

# PLAN-0024 — Production Deployment Infrastructure

> Deploys the worldview platform to Hetzner Cloud using k3s + ArgoCD + OpenTofu.
> Two-repo GitOps pattern: `worldview` (app code) + `worldview-gitops` (Helm charts + secrets).

---

## Wave A-0: worldview-gitops Repository Scaffold ✅

**Status**: **DONE** — 2026-04-11 · repository live at `https://github.com/arnaurodondev/worldview-gitops`

**Scope**: Create the `worldview-gitops` private GitHub repository with all GitOps artifacts.

**Files created** (in `worldview-gitops` repo):
- `apps/root-app.yaml` — ArgoCD bootstrap root Application (App-of-Apps)
- `apps/worldview-<svc>.yaml` (×10) — ArgoCD Application specs with Image Updater annotations
- `apps/argocd-image-updater.yaml` — ArgoCD Image Updater deployment
- `apps/infra-postgres.yaml`, `apps/infra-kafka.yaml`, `apps/infra-minio.yaml`, `apps/infra-valkey.yaml` — Infra Applications
- `apps/monitoring.yaml` — kube-prometheus-stack + Loki + Tempo + Alloy
- `apps/ingress.yaml` — Traefik + cert-manager
- `charts/worldview-service/` — Generic Helm chart (Chart.yaml, deployment.yaml, service.yaml, hpa.yaml)
- `values/<svc>.yaml` (×10) — Per-service Helm values with `image.tag: latest` (CI bumps to SHA)
- `secrets/` — SOPS-encrypted Kubernetes Secret stubs (one per service + shared)
- `k8s/argocd/argocd-values.yaml` — ArgoCD Helm values with helm-secrets + SOPS init container
- `k8s/argocd/image-updater-values.yaml` — Image Updater Helm values (ghcr.io credentials)
- `k8s/manifests/ollama.yaml`, `k8s/manifests/gliner.yaml` — Raw k8s manifests for ML services
- `renovate.json` — Renovate config (1 PR per chart)
- `bootstrap/setup.sh` — Full cluster bootstrap script
- `bootstrap/generate-secrets.sh` — SOPS-encrypt all secret stubs
- `.github/workflows/validate.yml` — PR CI: Helm lint, helm template, kubeconform, SOPS check

**Validation gate**:
- [x] Repository created and accessible
- [x] `apps/root-app.yaml` references correct repo URL
- [x] All 10 service Application specs have Image Updater annotations
- [x] `charts/worldview-service/` passes `helm lint`
- [x] `validate.yml` CI workflow runs on PRs

---

## Wave A-1: OpenTofu Infrastructure Files ✅

**Status**: **DONE** — 2026-04-11 · HCL files created at `infra/tofu/`

**Scope**: All OpenTofu HCL files for Hetzner Cloud infrastructure + cloud-init templates.

**Files created** (in `worldview` repo):
- `infra/tofu/main.tf` — Provider config + **Hetzner S3 backend** (`nbg1.your-objectstorage.com`)
- `infra/tofu/variables.tf` — All variables (`hcloud_token`, `k3s_token` sensitive; `region`, node types, `ssh_public_key`, `developer_ip`, `domain`)
- `infra/tofu/nodes.tf` — 3 `hcloud_server` resources; CP has `lifecycle.prevent_destroy = true`
- `infra/tofu/storage.tf` — 5 `hcloud_volume` resources; postgres/kafka/minio have `lifecycle.prevent_destroy = true`; S3 bucket chicken-and-egg documented
- `infra/tofu/firewall.tf` — Strict firewall: 80/443 open; 6443/22 restricted to `developer_ip`; internal 10.0.0.0/8 open
- `infra/tofu/network.tf` — Private network `worldview-net` 10.0.0.0/8
- `infra/tofu/ip.tf` — Floating IP + assignment to CP
- `infra/tofu/outputs.tf` — IPs, volume devices, kubeconfig command, SSH command
- `infra/tofu/cloud-init/cp.yml` — k3s server with `--disable traefik --disable servicelb --tls-san <floating_ip> --node-taint NoSchedule`
- `infra/tofu/cloud-init/worker.yml` — k3s agent; waits for CP on port 6443 before joining
- `infra/tofu/terraform.tfvars.example` — Template for `terraform.tfvars` (gitignored)

**Key decisions**:
- S3 backend endpoint: `https://nbg1.your-objectstorage.com` (`force_path_style = true`)
- Init command: `tofu init -backend-config=~/.config/tofu/hetzner-s3.tfbackend`
- `worldview-tfstate` bucket must be created manually in Hetzner Console before `tofu init`

**Validation gate**:
- [x] `tofu validate` passes on all `.tf` files
- [x] `tofu plan` can be run (requires `terraform.tfvars` with real credentials)
- [x] `terraform.tfvars.example` documents all required variables

---

## Wave A-2: GitHub Actions Deploy Workflow ✅

**Status**: **DONE** — 2026-04-11 · workflow at `.github/workflows/deploy.yml`

**Scope**: GitHub Actions CI/CD pipeline for building Docker images and opening GitOps PRs.

**Files created** (in `worldview` repo):
- `.github/workflows/deploy.yml` — Full deploy pipeline

**Workflow structure**:
1. `detect-changes` — `dorny/paths-filter@v3`; outputs JSON array of changed services; `libs/**` changes trigger all services
2. `build-and-push` (matrix) — `docker/build-push-action@v6`; tags `:<sha7>` + `:latest`; per-service GHA cache scope; `fail-fast: false`
3. `build-postgres` (conditional) — only when `infra/postgres/**` changes
4. `bump-image-tag` (matrix, excludes `intelligence-migrations`) — GitHub App token via `tibdex/github-app-token@v2`; `yq v4.44.3` to update `values/<svc>.yaml`; idempotent (checks for existing open PR); branch pattern: `deploy/<service>/<sha7>`

**Required secrets** (set in `worldview` repo Settings → Secrets):
- `GITOPS_APP_ID` — GitHub App numeric ID
- `GITOPS_APP_PRIVATE_KEY` — base64-encoded PEM private key

**Validation gate**:
- [x] Workflow YAML is syntactically valid
- [x] GitHub App token generation uses `tibdex/github-app-token@v2` (not PAT)
- [x] 1 PR per service (matrix exclude: `intelligence-migrations`)
- [x] Idempotency guard (existing PR check before create)
- [x] Image tag is `${GITHUB_SHA::7}` (short SHA, not `:latest` for pinned deploys)

---

## Wave A-3: GitHub App Creation (Manual) — pending

**Status**: **pending** — requires GitHub account access

**Scope**: One-time manual setup to create the `worldview-deploy-bot` GitHub App and configure secrets.

**Steps** (see PRD §6.7.7 for full detail):
1. Go to GitHub → Settings → Developer settings → GitHub Apps → New GitHub App
2. Name: `worldview-deploy-bot`
3. Permissions: Contents (R/W), Pull requests (R/W), Metadata (R)
4. Install on `worldview-gitops` repo only
5. Generate private key → download `.pem`
6. Add to `worldview` repo secrets:
   - `GITOPS_APP_ID` = App ID number
   - `GITOPS_APP_PRIVATE_KEY` = `cat <file>.pem | base64 | tr -d '\n'`

**Estimated effort**: 15 minutes

**Validation gate**:
- [ ] GitHub App created and installed on `worldview-gitops`
- [ ] Both secrets added to `worldview` repo
- [ ] Push a test commit to `main` and verify the `bump-image-tag` job completes successfully
- [ ] PR opens automatically in `worldview-gitops` with correct `image.tag` diff

---

## Wave A-4: Cluster Bootstrap — pending

**Status**: **pending** — requires Hetzner account, API token, and domain

**Scope**: Provision Hetzner infrastructure and bootstrap the k3s cluster with all services.

**Pre-requisites** (must be done before this wave):
- [ ] Hetzner Cloud account created
- [ ] Hetzner API token generated (Read & Write)
- [ ] `worldview-tfstate` Object Storage bucket created in NBG1 (Hetzner Console)
- [ ] Hetzner S3 credentials obtained (`~/.config/tofu/hetzner-s3.tfbackend` populated)
- [ ] SSH key generated (ed25519 recommended)
- [ ] `infra/tofu/terraform.tfvars` populated from `terraform.tfvars.example`
- [ ] Age keypair generated (`age-keygen -o ~/.config/sops/age/keys.txt`)
- [ ] All secrets filled in `worldview-gitops/bootstrap/generate-secrets.sh`
- [ ] GitHub PAT (or SSH key) with access to `worldview-gitops` for ArgoCD repo credentials

**Execution steps**:
```bash
# 1. Provision infrastructure
cd infra/tofu
tofu init -backend-config=~/.config/tofu/hetzner-s3.tfbackend
tofu plan    # review what will be created
tofu apply   # provisions 3 nodes, floating IP, 5 volumes, firewall, network

# 2. Get kubeconfig (wait ~5 minutes for cloud-init to complete)
$(tofu output -raw kubeconfig_command)
export KUBECONFIG=~/.kube/config-worldview
kubectl get nodes   # should show 3 nodes: Ready

# 3. Bootstrap cluster
cd /path/to/worldview-gitops
chmod +x bootstrap/setup.sh bootstrap/generate-secrets.sh
./bootstrap/generate-secrets.sh   # generates SOPS-encrypted secrets
./bootstrap/setup.sh               # installs CCM, CSI, ArgoCD, applies secrets, bootstraps root-app
```

**Expected result**: ArgoCD syncs all Applications; all services are Running within ~15 minutes.

**Validation gate**:
- [ ] `kubectl get nodes` shows 3 × Ready
- [ ] `kubectl -n argocd get pods` — all pods Running
- [ ] `kubectl -n worldview get pods` — all 10 service pods Running
- [ ] `kubectl -n infra get pods` — Kafka, Postgres, MinIO, Valkey, Ollama, GLiNER Running
- [ ] ArgoCD UI accessible at `https://argocd.<DOMAIN>` (after A-5)

---

## Wave A-5: DNS + TLS + Ingress + Vercel — pending

**Status**: **pending** — requires domain + cluster running (A-4 done)

**Scope**: Configure DNS, provision Let's Encrypt TLS certificates, and deploy the Vercel frontend.

**Steps**:
```bash
# 1. Get floating IP from Tofu output
FLOATING_IP=$(cd infra/tofu && tofu output -raw floating_ip)

# 2. Create DNS records at your registrar/Cloudflare:
#    A  @         → $FLOATING_IP
#    A  *         → $FLOATING_IP  (wildcard for all subdomains)
#    CNAME www    → @

# 3. Apply ClusterIssuers for Let's Encrypt
kubectl apply -f worldview-gitops/k8s/cert-manager/cluster-issuer-staging.yaml
kubectl apply -f worldview-gitops/k8s/cert-manager/cluster-issuer-prod.yaml

# 4. Verify cert-manager issues certificates (can take 2-3 min after DNS propagates)
kubectl get certificates -n worldview
kubectl get certificates -n argocd

# 5. Vercel frontend
#    - Connect GitHub repo in Vercel dashboard
#    - Set VITE_API_BASE_URL=https://api.<DOMAIN>
#    - Auto-deploys on push to main
```

**Validation gate**:
- [ ] `curl https://api.<DOMAIN>/health` returns 200
- [ ] `curl https://app.<DOMAIN>` serves the React frontend (via Vercel)
- [ ] TLS certificate is valid (not self-signed, not staging LE)
- [ ] `kubectl get certificaterequests -A` — no Failed certificates
- [ ] Alertmanager fires test alert → email received via Brevo

---

## Notes

### Chicken-and-egg: Hetzner S3 bucket for Tofu state

The `worldview-tfstate` bucket cannot be managed by Tofu (it's needed before `tofu init`).
Create it manually via Hetzner Console: **Object Storage → Create Bucket → Name: `worldview-tfstate`, Location: Nuremberg (NBG1)**.

### Branch protection on worldview-gitops

GitHub Free does not support branch protection on private repos.
Options:
1. Make `worldview-gitops` public (recommended for thesis — easier for evaluators too)
2. Upgrade to GitHub Pro (~$4/month)
3. Accept risk: ArgoCD Image Updater may push directly without PR review

### ArgoCD Image Updater vs GitHub Actions bump-image-tag

Both mechanisms write image tag updates to `worldview-gitops`. To avoid conflicts, choose one:
- **Image Updater** (automatic, no PR): ArgoCD Image Updater commits directly to `worldview-gitops/values/<svc>.yaml` when it detects a new image. No human review before deployment.
- **GitHub Actions bump-image-tag** (human-reviewed PR): Deployment is gated behind a PR review. Slightly slower but gives a clear audit trail.

The current setup has **both configured**. To disable Image Updater and use GitHub Actions only, remove the `argocd-image-updater.argoproj.io/write-back-method: git` annotation from the ArgoCD Application specs in `worldview-gitops/apps/`.

### intelligence-migrations exclusion

`intelligence-migrations` builds a Docker image (for running Alembic migrations) but has no corresponding `Deployment` in `worldview-gitops` — it runs as a one-off Kubernetes `Job`. The `bump-image-tag` job explicitly excludes it via `exclude: [{service: intelligence-migrations}]`.
