---
id: PRD-0024
title: Production Deployment Infrastructure — Complete Runbook
status: draft
created: 2026-04-09
updated: 2026-04-09
authors: [arnau]
---

# PRD-0024 — Production Deployment Infrastructure: Complete Runbook

> **Purpose**: Single source of truth for deploying the worldview platform to Hetzner Cloud.
> Covers every account, credential, Helm value, Kubernetes resource, and operational procedure
> required to go from zero to a fully operational production cluster.

---

## §1 Problem Statement

The worldview platform runs exclusively on Docker Compose locally. There is no production
deployment, no public URL, and no way for thesis evaluators to access the system.
Before the thesis evaluation deadline the platform must:

1. Be publicly accessible at `https://api.<DOMAIN>` with valid TLS
2. Be deployed on reproducible, version-controlled infrastructure (no snowflake servers)
3. Be continuously deployable: pushing to `main` updates the running cluster in < 10 minutes
4. Be observable: metrics, logs, and traces visible in Grafana; alerts delivered by email
5. Recover automatically from transient failures (pod restarts, network blips)

---

## §2 Target Users

| User | Goal | Interaction |
|------|------|------------|
| **Thesis evaluator** | Access platform over HTTPS | Browser → Vercel → S9 API |
| **Developer** | Deploy changes, monitor health | git push → ArgoCD sync |
| **Operator** | Receive alerts on failures | Alertmanager → Brevo → email |

---

## §3 Functional Requirements

### F-01 Infrastructure Provisioning (OpenTofu)
- All Hetzner Cloud resources provisioned via **OpenTofu** (`tofu` CLI, open-source Terraform fork)
- Provider: `hcloud` v≥1.49 (`registry.opentofu.org/providers/hetznercloud/hcloud`)
- Resources: servers, private network, firewall, floating IP, SSH key, volumes
- Reproducible: `tofu apply` on fresh checkout → identical cluster
- State file: local `.tfstate` committed to `infra/tofu/` (acceptable for single developer)
  - Alternative: Hetzner Object Storage backend (deferred, OQ-003)

### F-02 Kubernetes Cluster (k3s)
- k3s v1.31.x, 3 nodes, installed via cloud-init (Terraform provisioner)
- Built-in Traefik disabled (`--disable traefik`); built-in ServiceLB disabled (`--disable servicelb`)
- Hetzner Cloud Controller Manager (hcloud-ccm) for `LoadBalancer` service support
- Hetzner CSI driver for `PersistentVolumeClaim` → Hetzner Volume mapping
- Flannel CNI (k3s default); pod CIDR `10.42.0.0/16`

### F-03 GitOps (ArgoCD)
- ArgoCD v2.13 in namespace `argocd`
- App-of-Apps: root Application at `infra/argocd/root-app.yaml` → `infra/argocd/apps/`
- Automated sync with self-healing and pruning
- `helm-secrets` plugin with SOPS + Age for encrypted values

### F-04 Helm Charts
- Generic `worldview-service` chart reused by all 10 services
- Third-party charts: Bitnami Kafka/Postgres/Valkey, MinIO official, kube-prometheus-stack,
  Grafana Loki/Tempo, Traefik v3, cert-manager, ArgoCD, hcloud-ccm, hcloud-csi
- All chart versions pinned in ArgoCD Application specs

### F-05 Ingress & TLS
- Traefik v3 in namespace `traefik`, LoadBalancer IP = Hetzner floating IP
- cert-manager v1.20 with ClusterIssuers for Let's Encrypt staging + production
- All public endpoints at `https://*.<DOMAIN>` (wildcard A record → floating IP)

### F-06 Email Notifications (Alertmanager)
- Alertmanager configured with Brevo SMTP receiver
- Fires for: ServiceDown, CriticalErrorRate, DLQNonEmpty, HighP95Latency, OutboxBacklog
- Shared `smtp-credentials` Kubernetes Secret referenced by both Alertmanager and S10

### F-07 Email Delivery (S10 Alert Service)
- S10 reads SMTP config via `envFrom.secretRef: smtp-credentials`
- Provider: `EMAIL_PROVIDER=smtp`
- Email fields: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM_ADDRESS

### F-08 Secret Management (SOPS + Age)
- All Kubernetes Secrets encrypted with SOPS + Age before committing to git
- Age private key stored as GitHub Actions secret `SOPS_AGE_KEY` only
- ArgoCD `helm-secrets` plugin decrypts at sync time

### F-09 CI/CD (GitHub Actions → ghcr.io → ArgoCD)
- On push to `main`: build changed service images → push to `ghcr.io` → commit updated image tags
- ArgoCD detects changed tags → rolling update
- Frontend: Vercel GitHub integration (auto-deploys on `apps/frontend/**` change)

### F-10 Frontend (Vercel)
- `apps/frontend/` deployed to Vercel
- `VITE_API_BASE_URL=https://api.<DOMAIN>`
- S9 CORS must whitelist production domain + `*.vercel.app`

### F-11 Persistent Storage
- Hetzner CSI driver; StorageClass `hcloud-volumes`
- PVCs for: Postgres (100 GB), Kafka (50 GB), MinIO (100 GB), Valkey (10 GB)

### F-12 Observability Stack
- kube-prometheus-stack (Prometheus + Alertmanager + Grafana) in namespace `monitoring`
- Grafana Loki (log aggregation) + Grafana Alloy (log/metric collection)
- Grafana Tempo (distributed tracing, monolithic mode)
- All 10 services expose `/metrics` on their service port

---

## §4 Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Deploy time (push → live) | < 10 minutes |
| TLS cert provisioning | < 2 minutes after DNS propagates |
| Alert email delivery | < 5 minutes after alert fires |
| Cluster bootstrap from scratch | < 30 minutes |
| Monthly infra cost | ≤ €65/month |
| No plaintext secrets in git | Always (SOPS enforcement) |

---

## §5 Out of Scope

- HA control-plane (3 etcd nodes) — single CP acceptable for thesis
- GPU nodes for Ollama — CPU inference only
- Multi-region, multi-AZ deployment
- Service mesh (Istio/Linkerd)
- Offsite backups — local Hetzner Volume snapshots only
- Multi-environment (dev/staging/prod) — single prod environment
- WAF / DDoS protection (Cloudflare can be added later)
- Kubernetes RBAC fine-grained policies

---

## §6 Architecture Design

### §6.1 OpenTofu Infrastructure

**Toolchain**: OpenTofu (`tofu`) — functionally identical to Terraform, HCL syntax.
Install: `brew install opentofu`

**Directory: `infra/tofu/`**
```
infra/tofu/
├── main.tf          # Provider config
├── variables.tf     # Input variables
├── network.tf       # Private network + subnet
├── firewall.tf      # Firewall rules
├── nodes.tf         # 3 hcloud_server resources
├── storage.tf       # 4 hcloud_volume resources
├── ip.tf            # Floating IP + assignment
├── outputs.tf       # IPs, volume IDs
└── cloud-init/
    ├── common.yml   # Base packages + k3s binary download
    ├── cp.yml       # k3s server init
    └── worker.yml   # k3s agent join
```

**`main.tf`:**
```hcl
terraform {
  required_version = ">= 1.8"
  required_providers {
    hcloud = {
      source  = "registry.opentofu.org/providers/hetznercloud/hcloud"
      version = "~> 1.49"
    }
  }
}

provider "hcloud" {
  token = var.hcloud_token
}
```

**`variables.tf`:**
```hcl
variable "hcloud_token"        { sensitive = true }
variable "region"              { default = "nbg1" }
variable "cp_type"             { default = "cx32"  }  # 4 vCPU, 8 GB
variable "worker1_type"        { default = "cx52"  }  # 16 vCPU, 32 GB
variable "worker2_type"        { default = "cx42"  }  # 8 vCPU, 16 GB
variable "ssh_public_key"      { }                    # content of ~/.ssh/id_ed25519.pub
variable "k3s_token"           { sensitive = true }   # random 64-char string
variable "domain"              { default = "" }       # fill when domain purchased
```

**`network.tf`:**
```hcl
resource "hcloud_network" "main" {
  name     = "worldview-net"
  ip_range = "10.0.0.0/8"
}
resource "hcloud_network_subnet" "main" {
  network_id   = hcloud_network.main.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.0.1.0/24"
}
```

**`firewall.tf`:**
```hcl
resource "hcloud_firewall" "main" {
  name = "worldview-fw"

  rule { direction = "in"; protocol = "tcp"; port = "80";   source_ips = ["0.0.0.0/0", "::/0"] }
  rule { direction = "in"; protocol = "tcp"; port = "443";  source_ips = ["0.0.0.0/0", "::/0"] }
  rule { direction = "in"; protocol = "tcp"; port = "6443"; source_ips = ["0.0.0.0/0", "::/0"] }
  rule { direction = "in"; protocol = "tcp"; port = "22";   source_ips = [var.developer_ip] }
  rule { direction = "in"; protocol = "tcp"; port = "any";  source_ips = ["10.0.0.0/8"] }
  rule { direction = "in"; protocol = "udp"; port = "any";  source_ips = ["10.0.0.0/8"] }
  rule { direction = "out"; protocol = "tcp"; destination_ips = ["0.0.0.0/0", "::/0"]; port = "any" }
  rule { direction = "out"; protocol = "udp"; destination_ips = ["0.0.0.0/0", "::/0"]; port = "any" }
}
```

**`nodes.tf`:**
```hcl
resource "hcloud_ssh_key" "main" {
  name       = "worldview-key"
  public_key = var.ssh_public_key
}

# Template for cloud-init
locals {
  cp_user_data = templatefile("${path.module}/cloud-init/cp.yml", {
    k3s_token    = var.k3s_token
    floating_ip  = hcloud_floating_ip.main.ip_address
  })
  worker_user_data = templatefile("${path.module}/cloud-init/worker.yml", {
    k3s_token  = var.k3s_token
    cp_private_ip = hcloud_server_network.cp.ip
  })
}

resource "hcloud_server" "cp" {
  name        = "worldview-cp-1"
  server_type = var.cp_type
  image       = "ubuntu-24.04"
  location    = var.region
  ssh_keys    = [hcloud_ssh_key.main.id]
  user_data   = local.cp_user_data
  network { network_id = hcloud_network.main.id; ip = "10.0.1.10" }
  firewall_ids = [hcloud_firewall.main.id]
  depends_on   = [hcloud_network_subnet.main]
}
resource "hcloud_server_network" "cp" {
  server_id  = hcloud_server.cp.id
  network_id = hcloud_network.main.id
  ip         = "10.0.1.10"
}

resource "hcloud_server" "worker1" {
  name        = "worldview-worker-1"
  server_type = var.worker1_type
  image       = "ubuntu-24.04"
  location    = var.region
  ssh_keys    = [hcloud_ssh_key.main.id]
  user_data   = local.worker_user_data
  network { network_id = hcloud_network.main.id; ip = "10.0.1.11" }
  firewall_ids = [hcloud_firewall.main.id]
  depends_on   = [hcloud_server.cp]
}
resource "hcloud_server_network" "worker1" {
  server_id  = hcloud_server.worker1.id
  network_id = hcloud_network.main.id
  ip         = "10.0.1.11"
}

resource "hcloud_server" "worker2" {
  name        = "worldview-worker-2"
  server_type = var.worker2_type
  image       = "ubuntu-24.04"
  location    = var.region
  ssh_keys    = [hcloud_ssh_key.main.id]
  user_data   = local.worker_user_data
  network { network_id = hcloud_network.main.id; ip = "10.0.1.12" }
  firewall_ids = [hcloud_firewall.main.id]
  depends_on   = [hcloud_server.cp]
}
```

**`storage.tf`:**
```hcl
resource "hcloud_volume" "postgres" {
  name      = "worldview-postgres"
  size      = 100
  location  = var.region
  format    = "ext4"
}
resource "hcloud_volume_attachment" "postgres" {
  volume_id = hcloud_volume.postgres.id
  server_id = hcloud_server.worker1.id
  automount = true
}

resource "hcloud_volume" "kafka" {
  name = "worldview-kafka"; size = 50; location = var.region; format = "ext4"
}
resource "hcloud_volume_attachment" "kafka" {
  volume_id = hcloud_volume.kafka.id; server_id = hcloud_server.worker1.id; automount = true
}

resource "hcloud_volume" "minio" {
  name = "worldview-minio"; size = 100; location = var.region; format = "ext4"
}
resource "hcloud_volume_attachment" "minio" {
  volume_id = hcloud_volume.minio.id; server_id = hcloud_server.worker1.id; automount = true
}

resource "hcloud_volume" "valkey" {
  name = "worldview-valkey"; size = 10; location = var.region; format = "ext4"
}
resource "hcloud_volume_attachment" "valkey" {
  volume_id = hcloud_volume.valkey.id; server_id = hcloud_server.worker1.id; automount = true
}
```

**`ip.tf`:**
```hcl
resource "hcloud_floating_ip" "main" {
  type          = "ipv4"
  home_location = var.region
  description   = "worldview ingress IP"
}
resource "hcloud_floating_ip_assignment" "main" {
  floating_ip_id = hcloud_floating_ip.main.id
  server_id      = hcloud_server.cp.id  # assigned to CP; CCM routes via k8s
}
```

**`outputs.tf`:**
```hcl
output "cp_ip"         { value = hcloud_server.cp.ipv4_address }
output "worker1_ip"    { value = hcloud_server.worker1.ipv4_address }
output "worker2_ip"    { value = hcloud_server.worker2.ipv4_address }
output "floating_ip"   { value = hcloud_floating_ip.main.ip_address }
output "postgres_vol"  { value = hcloud_volume.postgres.linux_device }
output "kafka_vol"     { value = hcloud_volume.kafka.linux_device }
output "minio_vol"     { value = hcloud_volume.minio.linux_device }
output "valkey_vol"    { value = hcloud_volume.valkey.linux_device }
```

**cloud-init/cp.yml** (abbreviated):
```yaml
#cloud-config
package_update: true
packages: [curl, socat, conntrack, jq]
runcmd:
  - curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.31.4+k3s1"
      K3S_TOKEN="${k3s_token}"
      sh -s - server
      --disable traefik
      --disable servicelb
      --tls-san "${floating_ip}"
      --node-label "node-role=control-plane"
      --node-taint "node-role/control-plane:NoSchedule"
  - until kubectl get nodes 2>/dev/null | grep -q Ready; do sleep 5; done
  - cat /etc/rancher/k3s/k3s.yaml | sed "s/127.0.0.1/${floating_ip}/" > /tmp/kubeconfig
```

**cloud-init/worker.yml** (abbreviated):
```yaml
#cloud-config
packages: [curl, socat, conntrack]
runcmd:
  - until nc -z ${cp_private_ip} 6443; do sleep 5; done
  - curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.31.4+k3s1"
      K3S_URL="https://${cp_private_ip}:6443"
      K3S_TOKEN="${k3s_token}"
      sh -s - agent
```

**Cost summary:**

| Resource | Spec | Monthly |
|----------|------|---------|
| cp-1 | CX32 (4 vCPU, 8 GB) | ~€6 |
| worker-1 | CX52 (16 vCPU, 32 GB) — stateful services | ~€24 |
| worker-2 | CX42 (8 vCPU, 16 GB) — app services | ~€12 |
| Floating IP | IPv4 | ~€4 |
| Volumes (260 GB) | 260 × €0.05 | ~€13 |
| **Total** | | **~€59/mo** |

---

### §6.2 k3s Cluster Configuration

**Namespaces:**

| Namespace | Contents |
|-----------|---------|
| `kube-system` | hcloud-ccm, hcloud-csi, Flannel CNI |
| `traefik` | Traefik Deployment + IngressClass |
| `cert-manager` | cert-manager + ClusterIssuers |
| `argocd` | ArgoCD server, repo-server, app-controller |
| `infra` | Kafka, Schema Registry, Postgres, MinIO, Valkey, Ollama, GLiNER |
| `worldview` | All 10 app services + their workers |
| `monitoring` | kube-prometheus-stack, Loki, Tempo, Alloy |

**Node labels (applied via cloud-init node-label flags):**

| Node | Label | Taint |
|------|-------|-------|
| cp-1 | `node-role=control-plane` | `node-role/control-plane:NoSchedule` |
| worker-1 | `node-role=stateful` | none |
| worker-2 | `node-role=stateless` | none |

**Hetzner CCM (required for LoadBalancer):**
```bash
kubectl -n kube-system create secret generic hcloud \
  --from-literal=token=<HCLOUD_TOKEN> \
  --from-literal=network=worldview-net

helm install hccm hcloud/hcloud-cloud-controller-manager \
  -n kube-system \
  --set networking.enabled=true \
  --set networking.clusterCIDR="10.42.0.0/16"
```

**Hetzner CSI (required for PVCs):**
```bash
helm install hcloud-csi hcloud/hcloud-csi -n kube-system \
  --set node.kubeletDir=/var/lib/rancher/k3s/agent/kubelet
```
Note: k3s kubelet dir is `/var/lib/rancher/k3s/agent/kubelet` (not the default `/var/lib/kubelet`).

---

### §6.3 Helm Chart Catalog

All third-party charts are pinned to exact versions in ArgoCD Application specs.

| Chart | Repo | Version | Namespace | Notes |
|-------|------|---------|-----------|-------|
| `hcloud/hcloud-cloud-controller-manager` | `https://charts.hetzner.cloud` | `1.21.0` | `kube-system` | LoadBalancer support |
| `hcloud/hcloud-csi` | `https://charts.hetzner.cloud` | `2.9.0` | `kube-system` | PVC → Hetzner Volume |
| `traefik/traefik` | `https://traefik.github.io/charts` | `34.4.1` | `traefik` | Ingress controller v3 |
| `cert-manager/cert-manager` | `https://charts.jetstack.io` | `v1.17.2` | `cert-manager` | TLS automation |
| `argo/argo-cd` | `https://argoproj.github.io/argo-helm` | `7.8.26` | `argocd` | GitOps operator |
| `bitnami/kafka` | `https://charts.bitnami.com/bitnami` | `32.4.3` | `infra` | KRaft mode (no ZooKeeper) |
| `bitnami/schema-registry` | `https://charts.bitnami.com/bitnami` | `26.0.5` | `infra` | Confluent Schema Registry |
| `bitnami/postgresql` | `https://charts.bitnami.com/bitnami` | `16.7.5` | `infra` | **Custom image** (see §6.3.1) |
| `minio/minio` | `https://charts.min.io` | `5.4.0` | `infra` | Object storage |
| `bitnami/valkey` | `https://charts.bitnami.com/bitnami` | `3.0.10` | `infra` | Redis-compatible cache |
| `prometheus-community/kube-prometheus-stack` | `https://prometheus-community.github.io/helm-charts` | `69.8.2` | `monitoring` | Prometheus + Alertmanager + Grafana |
| `grafana/loki` | `https://grafana.github.io/helm-charts` | `6.27.0` | `monitoring` | Log aggregation |
| `grafana/tempo` | `https://grafana.github.io/helm-charts` | `1.21.0` | `monitoring` | Distributed tracing |
| `grafana/alloy` | `https://grafana.github.io/helm-charts` | `0.12.5` | `monitoring` | Agent: scrapes logs + metrics |

#### §6.3.1 Custom Postgres Image

The standard `bitnami/postgresql` image does **not** include TimescaleDB, pgvector, or Apache AGE.
Use the custom image from `infra/postgres/Dockerfile` (already in the repo):

```yaml
# In bitnami/postgresql values.yaml
image:
  registry: ghcr.io
  repository: <GITHUB_USER>/worldview-postgres
  tag: latest
  pullPolicy: Always
```

The CI pipeline builds and pushes `ghcr.io/<GITHUB_USER>/worldview-postgres` on changes to `infra/postgres/`.

#### §6.3.2 Ollama & GLiNER Deployment

Ollama and GLiNER run as Kubernetes Deployments in namespace `infra` (not Helm charts — managed by ArgoCD raw manifests):

```yaml
# infra/argocd/manifests/ollama.yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: ollama, namespace: infra }
spec:
  replicas: 1
  selector: { matchLabels: { app: ollama } }
  template:
    metadata: { labels: { app: ollama } }
    spec:
      nodeSelector: { node-role: stateful }
      containers:
        - name: ollama
          image: ollama/ollama:0.5.13
          ports: [{ containerPort: 11434 }]
          env:
            - { name: OLLAMA_KEEP_ALIVE, value: "24h" }
          resources:
            requests: { memory: "8Gi", cpu: "4" }
            limits:   { memory: "20Gi", cpu: "12" }
          volumeMounts:
            - { name: models, mountPath: /root/.ollama }
      volumes:
        - name: models
          persistentVolumeClaim: { claimName: ollama-models }
---
apiVersion: v1
kind: Service
metadata: { name: ollama, namespace: infra }
spec:
  selector: { app: ollama }
  ports: [{ port: 11434, targetPort: 11434 }]
```

Ollama model pull Job (runs once after Ollama pod is ready):
```yaml
apiVersion: batch/v1
kind: Job
metadata: { name: ollama-model-pull, namespace: infra }
spec:
  template:
    spec:
      restartPolicy: OnFailure
      initContainers:
        - name: wait-for-ollama
          image: busybox
          command: ["sh", "-c", "until nc -z ollama 11434; do sleep 5; done"]
      containers:
        - name: pull
          image: curlimages/curl:8.11.0
          command:
            - sh
            - -c
            - |
              curl -s http://ollama:11434/api/pull -d '{"name":"qwen2.5:3b"}' && \
              curl -s http://ollama:11434/api/pull -d '{"name":"nomic-embed-text"}' && \
              curl -s http://ollama:11434/api/pull -d '{"name":"bge-reranker-v2-m3"}' && \
              curl -s http://ollama:11434/api/pull -d '{"name":"bge-large"}' && \
              curl -s http://ollama:11434/api/pull -d '{"name":"qwen2.5:7b"}'
```

GLiNER deployment:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: gliner, namespace: infra }
spec:
  replicas: 1
  selector: { matchLabels: { app: gliner } }
  template:
    spec:
      nodeSelector: { node-role: stateful }
      containers:
        - name: gliner
          image: ghcr.io/<GITHUB_USER>/worldview-gliner:latest
          ports: [{ containerPort: 8090 }]
          resources:
            requests: { memory: "2Gi", cpu: "1" }
            limits:   { memory: "4Gi",  cpu: "4" }
```

---

### §6.4 Generic `worldview-service` Helm Chart

**Location**: `infra/helm/worldview-service/`

This chart is reused by all 10 app services. Per-service customisation is done via `values.yaml` files only.

```
infra/helm/worldview-service/
├── Chart.yaml
├── values.yaml          # defaults (mostly empty/placeholder)
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    ├── hpa.yaml
    ├── serviceaccount.yaml
    └── _helpers.tpl
```

**`Chart.yaml`:**
```yaml
apiVersion: v2
name: worldview-service
description: Generic Helm chart for worldview microservices
type: application
version: 1.0.0
appVersion: "latest"
```

**`templates/deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "worldview-service.fullname" . }}
  namespace: {{ .Values.namespace | default "worldview" }}
  labels: {{ include "worldview-service.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount | default 1 }}
  selector:
    matchLabels: {{ include "worldview-service.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels: {{ include "worldview-service.selectorLabels" . | nindent 8 }}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "{{ .Values.service.port }}"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: {{ include "worldview-service.serviceAccountName" . }}
      {{- if .Values.nodeSelector }}
      nodeSelector: {{ .Values.nodeSelector | toYaml | nindent 8 }}
      {{- end }}
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy | default "Always" }}
          ports:
            - name: http
              containerPort: {{ .Values.service.port }}
              protocol: TCP
          env: {{ .Values.env | default list | toYaml | nindent 12 }}
          {{- if .Values.envFrom }}
          envFrom: {{ .Values.envFrom | toYaml | nindent 12 }}
          {{- end }}
          livenessProbe:
            httpGet: { path: /health, port: http }
            initialDelaySeconds: 30
            periodSeconds: 10
            failureThreshold: 3
          readinessProbe:
            httpGet: { path: /health, port: http }
            initialDelaySeconds: 10
            periodSeconds: 5
          resources: {{ .Values.resources | toYaml | nindent 12 }}
      imagePullSecrets:
        - name: ghcr-credentials
```

**`templates/service.yaml`:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "worldview-service.fullname" . }}
  namespace: {{ .Values.namespace | default "worldview" }}
spec:
  selector: {{ include "worldview-service.selectorLabels" . | nindent 4 }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
      name: http
```

**`templates/hpa.yaml`** (optional, only rendered if `autoscaling.enabled: true`):
```yaml
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "worldview-service.fullname" . }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "worldview-service.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: { type: Utilization, averageUtilization: 70 }
{{- end }}
```

---

### §6.5 Per-Service Helm Values

All values files at `infra/helm/values/<service>.yaml`.
Secrets are referenced via `envFrom.secretRef` pointing to SOPS-encrypted Kubernetes Secrets.

#### §6.5.1 portfolio (S1) — port 8001

```yaml
# infra/helm/values/portfolio.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-portfolio
  tag: latest
service: { port: 8001 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "256Mi", cpu: "100m" }
  limits:   { memory: "512Mi", cpu: "500m" }
envFrom:
  - secretRef: { name: portfolio-secrets }
env:
  - { name: PORTFOLIO_HOST,                            value: "0.0.0.0" }
  - { name: PORTFOLIO_PORT,                            value: "8001" }
  - { name: PORTFOLIO_DEBUG,                           value: "false" }
  - { name: PORTFOLIO_DATABASE_URL,                    value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/portfolio_db" }
  - { name: PORTFOLIO_KAFKA_BOOTSTRAP_SERVERS,         value: "kafka.infra.svc:9092" }
  - { name: PORTFOLIO_SCHEMA_REGISTRY_URL,             value: "http://schema-registry.infra.svc:8081" }
  - { name: PORTFOLIO_KAFKA_AUTO_REGISTER_SCHEMAS,     value: "false" }
  - { name: PORTFOLIO_STORAGE_ENDPOINT,                value: "http://minio.infra.svc:9000" }
  - { name: PORTFOLIO_VALKEY_URL,                      value: "redis://valkey.infra.svc:6379/0" }
  - { name: PORTFOLIO_LOG_LEVEL,                       value: "INFO" }
  - { name: PORTFOLIO_LOG_FORMAT,                      value: "json" }
  - { name: PORTFOLIO_OTLP_ENDPOINT,                   value: "http://alloy.monitoring.svc:4317" }
  - { name: PORTFOLIO_TOPIC_PORTFOLIO_EVENTS,          value: "portfolio.events.v1" }
  - { name: PORTFOLIO_TOPIC_INSTRUMENT_CREATED,        value: "market.instrument.created" }
  - { name: PORTFOLIO_TOPIC_INSTRUMENT_UPDATED,        value: "market.instrument.updated" }
  - { name: PORTFOLIO_CONSUMER_GROUP_INSTRUMENT,       value: "portfolio-instrument-sync" }
# portfolio-secrets contains: PORTFOLIO_STORAGE_ACCESS_KEY, PORTFOLIO_STORAGE_SECRET_KEY
```

#### §6.5.2 market-ingestion (S2) — port 8002

```yaml
# infra/helm/values/market-ingestion.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-market-ingestion
  tag: latest
service: { port: 8002 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "512Mi", cpu: "200m" }
  limits:   { memory: "1Gi",   cpu: "1000m" }
envFrom:
  - secretRef: { name: market-ingestion-secrets }
env:
  - { name: MARKET_INGESTION_HOST,                        value: "0.0.0.0" }
  - { name: MARKET_INGESTION_PORT,                        value: "8002" }
  - { name: MARKET_INGESTION_DEBUG,                       value: "false" }
  - { name: MARKET_INGESTION_DATABASE_URL,                value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/ingestion_db" }
  - { name: MARKET_INGESTION_KAFKA_BOOTSTRAP_SERVERS,     value: "kafka.infra.svc:9092" }
  - { name: MARKET_INGESTION_SCHEMA_REGISTRY_URL,         value: "http://schema-registry.infra.svc:8081" }
  - { name: MARKET_INGESTION_STORAGE_ENDPOINT,            value: "http://minio.infra.svc:9000" }
  - { name: MARKET_INGESTION_STORAGE_BUCKET,              value: "market-ingestion" }
  - { name: MARKET_INGESTION_BRONZE_BUCKET,               value: "market-bronze" }
  - { name: MARKET_INGESTION_CANONICAL_BUCKET,            value: "market-canonical" }
  - { name: MARKET_INGESTION_VALKEY_URL,                  value: "redis://valkey.infra.svc:6379/0" }
  - { name: MARKET_INGESTION_LOG_LEVEL,                   value: "INFO" }
  - { name: MARKET_INGESTION_OTLP_ENDPOINT,               value: "http://alloy.monitoring.svc:4317" }
  - { name: MARKET_INGESTION_WORKER_CONCURRENCY,          value: "4" }
  - { name: MARKET_INGESTION_DISPATCHER_LEASE_SECONDS,    value: "60" }
# market-ingestion-secrets: MARKET_INGESTION_STORAGE_ACCESS_KEY, MARKET_INGESTION_STORAGE_SECRET_KEY,
#   MARKET_INGESTION_EODHD_API_KEY, MARKET_INGESTION_INTERNAL_SERVICE_TOKEN
```

#### §6.5.3 market-data (S3) — port 8003

```yaml
# infra/helm/values/market-data.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-market-data
  tag: latest
service: { port: 8003 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "256Mi", cpu: "100m" }
  limits:   { memory: "512Mi", cpu: "500m" }
envFrom:
  - secretRef: { name: market-data-secrets }
env:
  - { name: MARKET_DATA_HOST,                      value: "0.0.0.0" }
  - { name: MARKET_DATA_PORT,                      value: "8003" }
  - { name: MARKET_DATA_DEBUG,                     value: "false" }
  - { name: MARKET_DATA_DATABASE_URL,              value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/market_data_db" }
  - { name: MARKET_DATA_KAFKA_BOOTSTRAP_SERVERS,   value: "kafka.infra.svc:9092" }
  - { name: MARKET_DATA_SCHEMA_REGISTRY_URL,       value: "http://schema-registry.infra.svc:8081" }
  - { name: MARKET_DATA_STORAGE_ENDPOINT,          value: "http://minio.infra.svc:9000" }
  - { name: MARKET_DATA_VALKEY_URL,                value: "redis://valkey.infra.svc:6379/0" }
  - { name: MARKET_DATA_LOG_LEVEL,                 value: "INFO" }
# market-data-secrets: MARKET_DATA_STORAGE_ACCESS_KEY, MARKET_DATA_STORAGE_SECRET_KEY,
#   MARKET_DATA_INTERNAL_SERVICE_TOKEN
```

#### §6.5.4 content-ingestion (S4) — port 8004

```yaml
# infra/helm/values/content-ingestion.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-content-ingestion
  tag: latest
service: { port: 8004 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "512Mi", cpu: "200m" }
  limits:   { memory: "1Gi",   cpu: "1000m" }
envFrom:
  - secretRef: { name: content-ingestion-secrets }
env:
  - { name: CONTENT_INGESTION_HOST,                     value: "0.0.0.0" }
  - { name: CONTENT_INGESTION_PORT,                     value: "8004" }
  - { name: CONTENT_INGESTION_DEBUG,                    value: "false" }
  - { name: CONTENT_INGESTION_DATABASE_URL,             value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/content_ingestion_db" }
  - { name: CONTENT_INGESTION_KAFKA_BOOTSTRAP_SERVERS,  value: "kafka.infra.svc:9092" }
  - { name: CONTENT_INGESTION_SCHEMA_REGISTRY_URL,      value: "http://schema-registry.infra.svc:8081" }
  - { name: CONTENT_INGESTION_STORAGE_ENDPOINT,         value: "http://minio.infra.svc:9000" }
  - { name: CONTENT_INGESTION_VALKEY_URL,               value: "redis://valkey.infra.svc:6379/0" }
  - { name: CONTENT_INGESTION_LOG_LEVEL,                value: "INFO" }
  - { name: CONTENT_INGESTION_OTLP_ENDPOINT,            value: "http://alloy.monitoring.svc:4317" }
  - { name: CONTENT_INGESTION_POLYMARKET__BASE_URL,     value: "https://gamma-api.polymarket.com/markets" }
  - { name: CONTENT_INGESTION_SEC_EDGAR__MARKET_HOURS_INTERVAL_SECONDS, value: "60" }
  - { name: CONTENT_INGESTION_SEC_EDGAR__OFF_HOURS_INTERVAL_SECONDS,    value: "1800" }
# content-ingestion-secrets: CONTENT_INGESTION_STORAGE_ACCESS_KEY, CONTENT_INGESTION_STORAGE_SECRET_KEY,
#   CONTENT_INGESTION_ADMIN_TOKEN, INTERNAL_SERVICE_TOKEN
#   (EODHD key optional for S4 — only used for EDGAR market-hours polling)
```

#### §6.5.5 content-store (S5) — port 8005

```yaml
# infra/helm/values/content-store.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-content-store
  tag: latest
service: { port: 8005 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "256Mi", cpu: "100m" }
  limits:   { memory: "512Mi", cpu: "500m" }
envFrom:
  - secretRef: { name: content-store-secrets }
env:
  - { name: CONTENT_STORE_HOST,                     value: "0.0.0.0" }
  - { name: CONTENT_STORE_PORT,                     value: "8005" }
  - { name: CONTENT_STORE_DEBUG,                    value: "false" }
  - { name: CONTENT_STORE_DATABASE_URL,             value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/content_store_db" }
  - { name: CONTENT_STORE_KAFKA_BOOTSTRAP_SERVERS,  value: "kafka.infra.svc:9092" }
  - { name: CONTENT_STORE_SCHEMA_REGISTRY_URL,      value: "http://schema-registry.infra.svc:8081" }
  - { name: CONTENT_STORE_STORAGE_ENDPOINT,         value: "http://minio.infra.svc:9000" }
  - { name: CONTENT_STORE_VALKEY_URL,               value: "redis://valkey.infra.svc:6379/0" }
  - { name: CONTENT_STORE_LOG_LEVEL,                value: "INFO" }
# content-store-secrets: CONTENT_STORE_STORAGE_ACCESS_KEY, CONTENT_STORE_STORAGE_SECRET_KEY,
#   INTERNAL_SERVICE_TOKEN
```

#### §6.5.6 nlp-pipeline (S6) — port 8006

```yaml
# infra/helm/values/nlp-pipeline.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-nlp-pipeline
  tag: latest
service: { port: 8006 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "1Gi",  cpu: "500m" }
  limits:   { memory: "3Gi",  cpu: "2000m" }
envFrom:
  - secretRef: { name: nlp-pipeline-secrets }
env:
  - { name: NLP_PIPELINE_HOST,                      value: "0.0.0.0" }
  - { name: NLP_PIPELINE_PORT,                      value: "8006" }
  - { name: NLP_PIPELINE_DEBUG,                     value: "false" }
  - { name: NLP_PIPELINE_DATABASE_URL,              value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/nlp_db" }
  - { name: NLP_PIPELINE_KAFKA_BOOTSTRAP_SERVERS,   value: "kafka.infra.svc:9092" }
  - { name: NLP_PIPELINE_SCHEMA_REGISTRY_URL,       value: "http://schema-registry.infra.svc:8081" }
  - { name: NLP_PIPELINE_STORAGE_ENDPOINT,          value: "http://minio.infra.svc:9000" }
  - { name: NLP_PIPELINE_VALKEY_URL,                value: "redis://valkey.infra.svc:6379/0" }
  - { name: NLP_PIPELINE_LOG_LEVEL,                 value: "INFO" }
  - { name: NLP_PIPELINE_OTLP_ENDPOINT,             value: "http://alloy.monitoring.svc:4317" }
  # Ollama endpoints (in-cluster)
  - { name: NLP_PIPELINE_OLLAMA_BASE_URL,           value: "http://ollama.infra.svc:11434" }
  - { name: NLP_PIPELINE_GLINER_BASE_URL,           value: "http://gliner.infra.svc:8090" }
  # intelligence_db (shared with S7 — read-write same connection)
  - { name: NLP_PIPELINE_INTELLIGENCE_DATABASE_URL, value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/intelligence_db" }
  - { name: NLP_PIPELINE_ALEMBIC_ENABLED,           value: "false" }
# nlp-pipeline-secrets: NLP_PIPELINE_STORAGE_ACCESS_KEY, NLP_PIPELINE_STORAGE_SECRET_KEY,
#   NLP_PIPELINE_ADMIN_TOKEN
```

#### §6.5.7 knowledge-graph (S7) — port 8007

```yaml
# infra/helm/values/knowledge-graph.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-knowledge-graph
  tag: latest
service: { port: 8007 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "1Gi",  cpu: "500m" }
  limits:   { memory: "4Gi",  cpu: "2000m" }
envFrom:
  - secretRef: { name: knowledge-graph-secrets }
env:
  - { name: KNOWLEDGE_GRAPH_HOST,                     value: "0.0.0.0" }
  - { name: KNOWLEDGE_GRAPH_PORT,                     value: "8007" }
  - { name: KNOWLEDGE_GRAPH_DEBUG,                    value: "false" }
  - { name: KNOWLEDGE_GRAPH_DATABASE_URL,             value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/intelligence_db" }
  - { name: KNOWLEDGE_GRAPH_ALEMBIC_ENABLED,          value: "false" }
  - { name: KNOWLEDGE_GRAPH_KAFKA_BOOTSTRAP_SERVERS,  value: "kafka.infra.svc:9092" }
  - { name: KNOWLEDGE_GRAPH_SCHEMA_REGISTRY_URL,      value: "http://schema-registry.infra.svc:8081" }
  - { name: KNOWLEDGE_GRAPH_STORAGE_ENDPOINT,         value: "http://minio.infra.svc:9000" }
  - { name: KNOWLEDGE_GRAPH_VALKEY_URL,               value: "redis://valkey.infra.svc:6379/0" }
  - { name: KNOWLEDGE_GRAPH_LOG_LEVEL,                value: "INFO" }
  - { name: KNOWLEDGE_GRAPH_OTLP_ENDPOINT,            value: "http://alloy.monitoring.svc:4317" }
  - { name: KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER,     value: "gemini" }
  - { name: KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD, value: "10.0" }
  - { name: KNOWLEDGE_GRAPH_EODHD_BASE_URL,           value: "https://eodhd.com/api" }
  - { name: KNOWLEDGE_GRAPH_ECONOMIC_EVENT_COUNTRIES,     value: "US,DE,GB,JP,CN,EU" }
  - { name: KNOWLEDGE_GRAPH_MACRO_INDICATOR_COUNTRIES,    value: "USA,GBR,DEU,JPN,CHN" }
  - { name: KNOWLEDGE_GRAPH_CYPHER_ENABLED,           value: "false" }
# knowledge-graph-secrets: KNOWLEDGE_GRAPH_STORAGE_ACCESS_KEY, KNOWLEDGE_GRAPH_STORAGE_SECRET_KEY,
#   KNOWLEDGE_GRAPH_GEMINI_API_KEY, KNOWLEDGE_GRAPH_EODHD_API_KEY
```

#### §6.5.8 rag-chat (S8) — port 8008

```yaml
# infra/helm/values/rag-chat.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-rag-chat
  tag: latest
service: { port: 8008 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "512Mi", cpu: "200m" }
  limits:   { memory: "1Gi",   cpu: "1000m" }
envFrom:
  - secretRef: { name: rag-chat-secrets }
env:
  - { name: RAG_CHAT_HOST,                          value: "0.0.0.0" }
  - { name: RAG_CHAT_PORT,                          value: "8008" }
  - { name: RAG_CHAT_DEBUG,                         value: "false" }
  - { name: RAG_CHAT_RAG_DB_URL,                    value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/rag_db" }
  - { name: RAG_CHAT_VALKEY_URL,                    value: "redis://valkey.infra.svc:6379/0" }
  - { name: RAG_CHAT_OLLAMA_BASE_URL,               value: "http://ollama.infra.svc:11434" }
  - { name: RAG_CHAT_OLLAMA_CLASSIFICATION_MODEL,   value: "qwen2.5:3b" }
  - { name: RAG_CHAT_OLLAMA_RERANKER_MODEL,         value: "bge-reranker-v2-m3" }
  - { name: RAG_CHAT_COMPLETION_PROVIDER,           value: "deepinfra" }
  - { name: RAG_CHAT_COMPLETION_MODEL,              value: "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B" }
  - { name: RAG_CHAT_S6_BASE_URL,                   value: "http://nlp-pipeline.worldview.svc:8006" }
  - { name: RAG_CHAT_S7_BASE_URL,                   value: "http://knowledge-graph.worldview.svc:8007" }
  - { name: RAG_CHAT_S3_BASE_URL,                   value: "http://market-data.worldview.svc:8003" }
  - { name: RAG_CHAT_S1_BASE_URL,                   value: "http://portfolio.worldview.svc:8001" }
  - { name: RAG_CHAT_LOG_LEVEL,                     value: "INFO" }
  - { name: RAG_CHAT_LOG_JSON,                      value: "true" }
  - { name: RAG_CHAT_OTLP_ENDPOINT,                 value: "http://alloy.monitoring.svc:4317" }
  - { name: RAG_CHAT_CYPHER_ENABLED,                value: "false" }
  - { name: RAG_CHAT_RATE_LIMIT_PER_TENANT,         value: "10" }
# rag-chat-secrets: RAG_CHAT_DEEPINFRA_API_KEY, RAG_CHAT_OPENROUTER_API_KEY (optional fallback),
#   RAG_CHAT_INTERNAL_SERVICE_TOKEN, RAG_CHAT_S1_INTERNAL_TOKEN
```

#### §6.5.9 api-gateway (S9) — port 8000

```yaml
# infra/helm/values/api-gateway.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-api-gateway
  tag: latest
service: { port: 8000 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "256Mi", cpu: "200m" }
  limits:   { memory: "512Mi", cpu: "1000m" }
envFrom:
  - secretRef: { name: api-gateway-secrets }
env:
  - { name: API_GATEWAY_HOST,                    value: "0.0.0.0" }
  - { name: API_GATEWAY_PORT,                    value: "8000" }
  - { name: API_GATEWAY_DEBUG,                   value: "false" }
  - { name: API_GATEWAY_DATABASE_URL,            value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/gateway_db" }
  - { name: API_GATEWAY_KAFKA_BOOTSTRAP_SERVERS, value: "kafka.infra.svc:9092" }
  - { name: API_GATEWAY_SCHEMA_REGISTRY_URL,     value: "http://schema-registry.infra.svc:8081" }
  - { name: API_GATEWAY_STORAGE_ENDPOINT,        value: "http://minio.infra.svc:9000" }
  - { name: API_GATEWAY_VALKEY_URL,              value: "redis://valkey.infra.svc:6379/0" }
  - { name: API_GATEWAY_LOG_LEVEL,               value: "INFO" }
  - { name: API_GATEWAY_OTLP_ENDPOINT,           value: "http://alloy.monitoring.svc:4317" }
  # Downstream service URLs
  - { name: API_GATEWAY_S1_BASE_URL,   value: "http://portfolio.worldview.svc:8001" }
  - { name: API_GATEWAY_S2_BASE_URL,   value: "http://market-ingestion.worldview.svc:8002" }
  - { name: API_GATEWAY_S3_BASE_URL,   value: "http://market-data.worldview.svc:8003" }
  - { name: API_GATEWAY_S4_BASE_URL,   value: "http://content-ingestion.worldview.svc:8004" }
  - { name: API_GATEWAY_S5_BASE_URL,   value: "http://content-store.worldview.svc:8005" }
  - { name: API_GATEWAY_S6_BASE_URL,   value: "http://nlp-pipeline.worldview.svc:8006" }
  - { name: API_GATEWAY_S7_BASE_URL,   value: "http://knowledge-graph.worldview.svc:8007" }
  - { name: API_GATEWAY_S8_BASE_URL,   value: "http://rag-chat.worldview.svc:8008" }
  - { name: API_GATEWAY_S10_BASE_URL,  value: "http://alert.worldview.svc:8010" }
  # CORS
  - { name: API_GATEWAY_CORS_ORIGINS,  value: "https://<DOMAIN>,https://worldview-*.vercel.app" }
# api-gateway-secrets: API_GATEWAY_JWT_SECRET, API_GATEWAY_STORAGE_ACCESS_KEY,
#   API_GATEWAY_STORAGE_SECRET_KEY, API_GATEWAY_INTERNAL_SERVICE_TOKEN
```

#### §6.5.10 alert (S10) — port 8010

```yaml
# infra/helm/values/alert.yaml
image:
  repository: ghcr.io/<GITHUB_USER>/worldview-alert
  tag: latest
service: { port: 8010 }
replicaCount: 1
nodeSelector: { node-role: stateless }
resources:
  requests: { memory: "256Mi", cpu: "100m" }
  limits:   { memory: "512Mi", cpu: "500m" }
envFrom:
  - secretRef: { name: alert-secrets }
  - secretRef: { name: smtp-credentials }
env:
  - { name: ALERT_HOST,                        value: "0.0.0.0" }
  - { name: ALERT_PORT,                        value: "8010" }
  - { name: ALERT_DEBUG,                       value: "false" }
  - { name: ALERT_DATABASE_URL,                value: "postgresql+asyncpg://postgres:<PG_PASS>@postgres.infra.svc:5432/alert_db" }
  - { name: ALERT_KAFKA_BOOTSTRAP_SERVERS,     value: "kafka.infra.svc:9092" }
  - { name: ALERT_KAFKA_SCHEMA_REGISTRY_URL,   value: "http://schema-registry.infra.svc:8081" }
  - { name: ALERT_S1_PORTFOLIO_BASE_URL,       value: "http://portfolio.worldview.svc:8001" }
  - { name: ALERT_S8_BASE_URL,                 value: "http://rag-chat.worldview.svc:8008" }
  - { name: ALERT_VALKEY_URL,                  value: "redis://valkey.infra.svc:6379/0" }
  - { name: ALERT_LOG_LEVEL,                   value: "INFO" }
  - { name: ALERT_LOG_JSON,                    value: "true" }
  - { name: ALERT_OTLP_ENDPOINT,               value: "http://alloy.monitoring.svc:4317" }
  - { name: ALERT_EMAIL_PROVIDER,              value: "smtp" }
  - { name: ALERT_EMAIL_FROM_ADDRESS,          value: "alerts@<DOMAIN>" }
  - { name: ALERT_SMTP_HOST,                   value: "smtp-relay.brevo.com" }
  - { name: ALERT_SMTP_PORT,                   value: "587" }
  - { name: ALERT_ALERT_DEDUP_WINDOW_SECONDS,  value: "300" }
  - { name: ALERT_PENDING_ALERT_TTL_DAYS,      value: "7" }
# alert-secrets: ALERT_ADMIN_TOKEN, INTERNAL_SERVICE_TOKEN,
#   ALERT_S8_INTERNAL_TOKEN, ALERT_S1_INTERNAL_TOKEN
# smtp-credentials: ALERT_SMTP_USER, ALERT_SMTP_PASSWORD (= SMTP_USER, SMTP_PASSWORD for Alertmanager)
```

---

### §6.6 Secret Management (SOPS + Age)

#### §6.6.1 Setup — Age key pair

```bash
# 1. Install Age
brew install age

# 2. Generate key pair (do this ONCE — store private key safely)
age-keygen -o ~/.config/sops/age/keys.txt

# 3. View public key
cat ~/.config/sops/age/keys.txt | grep "public key"
# → age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

#### §6.6.2 `.sops.yaml` (repo root)

```yaml
creation_rules:
  - path_regex: infra/k8s/secrets/.*\.yaml$
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

#### §6.6.3 Encrypted secret files

**Location**: `infra/k8s/secrets/`

Each file is a standard Kubernetes Secret YAML that is encrypted with SOPS before committing:

```bash
# Create a secret file (unencrypted)
cat > /tmp/portfolio-secrets.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: portfolio-secrets
  namespace: worldview
stringData:
  PORTFOLIO_STORAGE_ACCESS_KEY: "minioadmin"
  PORTFOLIO_STORAGE_SECRET_KEY: "minioadmin"
EOF

# Encrypt with SOPS
sops --encrypt /tmp/portfolio-secrets.yaml > infra/k8s/secrets/portfolio-secrets.yaml

# Never commit the plaintext version — only commit the sops-encrypted file
```

**Secrets inventory** (all files that must exist in `infra/k8s/secrets/`):

| Secret Name | Namespace | Contains |
|-------------|-----------|---------|
| `portfolio-secrets` | `worldview` | `PORTFOLIO_STORAGE_ACCESS_KEY`, `PORTFOLIO_STORAGE_SECRET_KEY` |
| `market-ingestion-secrets` | `worldview` | `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `EODHD_API_KEY`, `INTERNAL_SERVICE_TOKEN` |
| `market-data-secrets` | `worldview` | `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `INTERNAL_SERVICE_TOKEN` |
| `content-ingestion-secrets` | `worldview` | `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `ADMIN_TOKEN`, `INTERNAL_SERVICE_TOKEN` |
| `content-store-secrets` | `worldview` | `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `INTERNAL_SERVICE_TOKEN` |
| `nlp-pipeline-secrets` | `worldview` | `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `ADMIN_TOKEN` |
| `knowledge-graph-secrets` | `worldview` | `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `GEMINI_API_KEY`, `EODHD_API_KEY` |
| `rag-chat-secrets` | `worldview` | `DEEPINFRA_API_KEY`, `OPENROUTER_API_KEY`, `INTERNAL_SERVICE_TOKEN`, `S1_INTERNAL_TOKEN` |
| `api-gateway-secrets` | `worldview` | `JWT_SECRET`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, `INTERNAL_SERVICE_TOKEN` |
| `alert-secrets` | `worldview` | `ADMIN_TOKEN`, `INTERNAL_SERVICE_TOKEN`, `S8_INTERNAL_TOKEN`, `S1_INTERNAL_TOKEN` |
| `smtp-credentials` | `worldview` | `ALERT_SMTP_USER`, `ALERT_SMTP_PASSWORD` |
| `minio-root-credentials` | `infra` | `rootUser`, `rootPassword` |
| `postgres-credentials` | `infra` | `postgres-password`, `replication-password` |
| `kafka-credentials` | `infra` | `client-passwords` |
| `hcloud` | `kube-system` | `token`, `network` |
| `ghcr-credentials` | `worldview` | `.dockerconfigjson` (for pulling from ghcr.io) |
| `ghcr-credentials` | `infra` | Same (needed for custom postgres image) |

#### §6.6.4 ArgoCD helm-secrets plugin setup

ArgoCD must have the `helm-secrets` plugin to decrypt SOPS values at sync time.

```yaml
# Patch ArgoCD repo-server Deployment to add init container + sidecar
# Applied via Helm values for argo/argo-cd chart:

repoServer:
  extraInitContainers:
    - name: install-helm-secrets
      image: alpine/helm:3.17.0
      command: ["sh", "-c"]
      args:
        - |
          helm plugin install https://github.com/jkroepke/helm-secrets --version v4.6.3 || true
          cp -r /root/.local/share/helm/plugins /helm-plugins
      volumeMounts:
        - name: helm-plugins
          mountPath: /helm-plugins

  extraVolumes:
    - name: helm-plugins
      emptyDir: {}
    - name: sops-age-key
      secret:
        secretName: sops-age-key

  extraVolumeMounts:
    - name: helm-plugins
      mountPath: /root/.local/share/helm/plugins
    - name: sops-age-key
      mountPath: /sops-age
      readOnly: true

  extraEnv:
    - name: HELM_PLUGINS
      value: /root/.local/share/helm/plugins
    - name: SOPS_AGE_KEY_FILE
      value: /sops-age/key.txt
```

Create the Age key secret in ArgoCD namespace:
```bash
kubectl -n argocd create secret generic sops-age-key \
  --from-file=key.txt=~/.config/sops/age/keys.txt
```

---

### §6.7 ArgoCD App-of-Apps

**Root Application** (`infra/argocd/root-app.yaml`):
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: worldview-root
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/<GITHUB_USER>/worldview
    targetRevision: main
    path: infra/argocd/apps
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**App directory structure** (`infra/argocd/apps/`):
```
infra/argocd/apps/
├── infra-kafka.yaml
├── infra-schema-registry.yaml
├── infra-postgres.yaml
├── infra-minio.yaml
├── infra-valkey.yaml
├── infra-ollama.yaml          # raw manifest
├── monitoring.yaml
├── traefik.yaml
├── cert-manager.yaml
├── worldview-portfolio.yaml
├── worldview-market-ingestion.yaml
├── worldview-market-data.yaml
├── worldview-content-ingestion.yaml
├── worldview-content-store.yaml
├── worldview-nlp-pipeline.yaml
├── worldview-knowledge-graph.yaml
├── worldview-rag-chat.yaml
├── worldview-api-gateway.yaml
└── worldview-alert.yaml
```

**Example — `worldview-portfolio.yaml`:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: worldview-portfolio
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/<GITHUB_USER>/worldview
    targetRevision: main
    path: infra/helm/worldview-service
    helm:
      valueFiles:
        - secrets+age-import:///sops-age/key.txt?../values/portfolio.yaml
        - secrets+age-import:///sops-age/key.txt?../../k8s/secrets/portfolio-secrets.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: worldview
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**Example — `infra-kafka.yaml`:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: infra-kafka
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://charts.bitnami.com/bitnami
    chart: kafka
    targetRevision: 32.4.3
    helm:
      valuesObject:
        replicaCount: 1
        controller:
          replicaCount: 1
        kraft:
          enabled: true
        zookeeper:
          enabled: false
        persistence:
          enabled: true
          storageClass: hcloud-volumes
          size: 50Gi
        nodeSelector:
          node-role: stateful
        resources:
          requests: { memory: "2Gi", cpu: "500m" }
          limits:   { memory: "4Gi", cpu: "2000m" }
        extraConfig: |
          log.retention.hours=168
          log.retention.bytes=10737418240
          message.max.bytes=10485760
        listeners:
          client:
            protocol: PLAINTEXT
          controller:
            protocol: PLAINTEXT
          interbroker:
            protocol: PLAINTEXT
  destination:
    server: https://kubernetes.default.svc
    namespace: infra
  syncPolicy:
    automated: { prune: true, selfHeal: true }
    syncOptions: [CreateNamespace=true]
```

**Example — `infra-postgres.yaml`** (custom image):
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: infra-postgres
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://charts.bitnami.com/bitnami
    chart: postgresql
    targetRevision: 16.7.5
    helm:
      valuesObject:
        image:
          registry: ghcr.io
          repository: <GITHUB_USER>/worldview-postgres
          tag: latest
          pullSecrets: [ghcr-credentials]
        auth:
          existingSecret: postgres-credentials
          secretKeys:
            adminPasswordKey: postgres-password
        primary:
          nodeSelector: { node-role: stateful }
          persistence:
            enabled: true
            storageClass: hcloud-volumes
            size: 100Gi
          initdb:
            scripts:
              init.sql: |
                CREATE DATABASE portfolio_db;
                CREATE DATABASE ingestion_db;
                CREATE DATABASE market_data_db;
                CREATE DATABASE content_ingestion_db;
                CREATE DATABASE content_store_db;
                CREATE DATABASE nlp_db;
                CREATE DATABASE intelligence_db;
                CREATE DATABASE rag_db;
                CREATE DATABASE alert_db;
                CREATE DATABASE gateway_db;
        resources:
          requests: { memory: "2Gi", cpu: "500m" }
          limits:   { memory: "4Gi", cpu: "2000m" }
  destination:
    server: https://kubernetes.default.svc
    namespace: infra
  syncPolicy:
    automated: { prune: false, selfHeal: true }  # prune=false: never drop Postgres
    syncOptions: [CreateNamespace=true]
```

---

### §6.8 CI/CD — GitHub Actions

**File**: `.github/workflows/ci.yaml`

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_PREFIX: ghcr.io/${{ github.repository_owner }}

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      services: ${{ steps.filter.outputs.changes }}
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            portfolio:       ['services/portfolio/**', 'libs/**']
            market-ingestion: ['services/market-ingestion/**', 'libs/**']
            market-data:     ['services/market-data/**', 'libs/**']
            content-ingestion: ['services/content-ingestion/**', 'libs/**']
            content-store:   ['services/content-store/**', 'libs/**']
            nlp-pipeline:    ['services/nlp-pipeline/**', 'libs/**']
            knowledge-graph: ['services/knowledge-graph/**', 'libs/**']
            rag-chat:        ['services/rag-chat/**', 'libs/**']
            api-gateway:     ['services/api-gateway/**', 'libs/**']
            alert:           ['services/alert/**', 'libs/**']
            postgres:        ['infra/postgres/**']

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - name: Install dependencies
        run: |
          pip install uv
          uv sync --all-groups
      - name: Run unit tests
        run: |
          for svc in services/*/; do
            (cd "$svc" && python -m pytest tests/ -m "unit" -q --tb=short) || exit 1
          done

  build-and-push:
    needs: [detect-changes, test]
    if: github.ref == 'refs/heads/main' && needs.detect-changes.outputs.services != '[]'
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: ${{ fromJson(needs.detect-changes.outputs.services) }}
    steps:
      - uses: actions/checkout@v4

      - name: Login to ghcr.io
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push ${{ matrix.service }}
        uses: docker/build-push-action@v6
        with:
          context: .
          file: services/${{ matrix.service }}/Dockerfile
          push: true
          tags: |
            ${{ env.IMAGE_PREFIX }}/worldview-${{ matrix.service }}:latest
            ${{ env.IMAGE_PREFIX }}/worldview-${{ matrix.service }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  build-postgres:
    needs: [detect-changes, test]
    if: github.ref == 'refs/heads/main' && contains(needs.detect-changes.outputs.services, 'postgres')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/setup-buildx-action@v3
      - uses: docker/build-push-action@v6
        with:
          context: infra/postgres/
          push: true
          tags: ${{ env.IMAGE_PREFIX }}/worldview-postgres:latest
```

**Required GitHub Actions secrets** (`Settings → Secrets and Variables → Actions`):

| Secret | Value | Notes |
|--------|-------|-------|
| `GITHUB_TOKEN` | automatic | ghcr.io push |
| `SOPS_AGE_KEY` | content of `~/.config/sops/age/keys.txt` | For local decrypt if needed |

---

### §6.9 Ingress & TLS (Traefik + cert-manager)

#### §6.9.1 Traefik Helm values (`infra/argocd/apps/traefik.yaml`)

```yaml
source:
  chart: traefik
  targetRevision: 34.4.1
  helm:
    valuesObject:
      deployment:
        replicas: 1
      nodeSelector:
        node-role: stateless
      service:
        type: LoadBalancer
        annotations:
          load-balancer.hetzner.cloud/location: nbg1
          load-balancer.hetzner.cloud/use-private-ip: "true"
      ports:
        web:
          port: 80
          redirectTo: websecure
        websecure:
          port: 443
          tls:
            enabled: true
      ingressClass:
        enabled: true
        isDefaultClass: true
      providers:
        kubernetesIngress:
          enabled: true
        kubernetesCRD:
          enabled: true
      logs:
        access:
          enabled: true
          format: json
      metrics:
        prometheus:
          enabled: true
          serviceMonitor:
            enabled: true
```

#### §6.9.2 cert-manager ClusterIssuers

```yaml
# infra/k8s/cert-manager/cluster-issuers.yaml
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: <YOUR_EMAIL>
    privateKeySecretRef: { name: letsencrypt-staging-key }
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: <YOUR_EMAIL>
    privateKeySecretRef: { name: letsencrypt-prod-key }
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
```

#### §6.9.3 Ingress for S9 API Gateway

```yaml
# infra/k8s/ingress/api-gateway-ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-gateway
  namespace: worldview
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    traefik.ingress.kubernetes.io/router.middlewares: worldview-rate-limit@kubernetescrd
spec:
  ingressClassName: traefik
  tls:
    - hosts: [api.<DOMAIN>]
      secretName: api-tls
  rules:
    - host: api.<DOMAIN>
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: api-gateway
                port: { number: 8000 }
```

#### §6.9.4 Ingress for Grafana

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana
  namespace: monitoring
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: traefik
  tls:
    - hosts: [grafana.<DOMAIN>]
      secretName: grafana-tls
  rules:
    - host: grafana.<DOMAIN>
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: kube-prometheus-stack-grafana
                port: { number: 80 }
```

---

### §6.10 Observability Stack

#### §6.10.1 kube-prometheus-stack values

```yaml
# Key values for kube-prometheus-stack 69.8.2
grafana:
  enabled: true
  adminPassword: "<GRAFANA_ADMIN_PASSWORD>"  # put in secret
  persistence:
    enabled: true
    storageClassName: hcloud-volumes
    size: 10Gi
  nodeSelector: { node-role: stateless }
  additionalDataSources:
    - name: Loki
      type: loki
      url: http://loki.monitoring.svc:3100
      access: proxy
    - name: Tempo
      type: tempo
      url: http://tempo.monitoring.svc:3100
      access: proxy

prometheus:
  prometheusSpec:
    nodeSelector: { node-role: stateless }
    retention: 30d
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: hcloud-volumes
          resources: { requests: { storage: 50Gi } }
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false

alertmanager:
  alertmanagerSpec:
    nodeSelector: { node-role: stateless }
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: hcloud-volumes
          resources: { requests: { storage: 5Gi } }
  config:
    global:
      smtp_smarthost: 'smtp-relay.brevo.com:587'
      smtp_from: 'alerts@<DOMAIN>'
      smtp_auth_username: '<BREVO_SMTP_LOGIN>'
      smtp_auth_password: '<BREVO_SMTP_KEY>'
      smtp_require_tls: true
    route:
      receiver: email-alerts
      group_by: ['alertname', 'namespace']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 4h
    receivers:
      - name: email-alerts
        email_configs:
          - to: '<ALERT_EMAIL_RECIPIENT>'
            send_resolved: true
            headers:
              Subject: '[worldview] {{ .CommonAnnotations.summary }}'

nodeExporter:
  enabled: true

kubeStateMetrics:
  enabled: true
```

#### §6.10.2 Loki values

```yaml
# grafana/loki 6.27.0 — monolithic (simple scalable mode, single replica)
loki:
  commonConfig:
    replication_factor: 1
  storage:
    type: filesystem
  schemaConfig:
    configs:
      - from: 2026-01-01
        store: tsdb
        object_store: filesystem
        schema: v13
        index: { prefix: index_, period: 24h }
  limits_config:
    retention_period: 744h  # 31 days
singleBinary:
  replicas: 1
  nodeSelector: { node-role: stateless }
  persistence:
    enabled: true
    storageClass: hcloud-volumes
    size: 50Gi
```

#### §6.10.3 Grafana Alloy (log + metric collection)

```yaml
# grafana/alloy 0.12.5 — DaemonSet, collects pod logs + forwards metrics
alloy:
  configMap:
    create: true
    content: |
      loki.write "default" {
        endpoint { url = "http://loki.monitoring.svc:3100/loki/api/v1/push" }
      }
      discovery.kubernetes "pods" {
        role = "pod"
        namespaces { names = ["worldview", "infra"] }
      }
      loki.source.kubernetes "pods" {
        targets    = discovery.kubernetes.pods.targets
        forward_to = [loki.write.default.receiver]
      }
      prometheus.remote_write "default" {
        endpoint { url = "http://kube-prometheus-stack-prometheus.monitoring.svc:9090/api/v1/write" }
      }
```

#### §6.10.4 Prometheus scrape rules (from `infra/prometheus/prometheus.yml`)

The existing `infra/prometheus/prometheus.yml` rules must be migrated to a Kubernetes ConfigMap
and referenced in the kube-prometheus-stack `additionalScrapeConfigs` values:

```yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: "portfolio"
        static_configs: [{ targets: ["portfolio.worldview.svc:8001"] }]
      - job_name: "market-ingestion"
        static_configs: [{ targets: ["market-ingestion.worldview.svc:8002"] }]
      - job_name: "market-data"
        static_configs: [{ targets: ["market-data.worldview.svc:8003"] }]
      - job_name: "content-ingestion"
        static_configs: [{ targets: ["content-ingestion.worldview.svc:8004"] }]
      - job_name: "content-store"
        static_configs: [{ targets: ["content-store.worldview.svc:8005"] }]
      - job_name: "api-gateway"
        static_configs: [{ targets: ["api-gateway.worldview.svc:8000"] }]
      - job_name: "nlp-pipeline"
        static_configs: [{ targets: ["nlp-pipeline.worldview.svc:8006"] }]
      - job_name: "knowledge-graph"
        static_configs: [{ targets: ["knowledge-graph.worldview.svc:8007"] }]
      - job_name: "rag-chat"
        static_configs: [{ targets: ["rag-chat.worldview.svc:8008"] }]
      - job_name: "alert"
        static_configs: [{ targets: ["alert.worldview.svc:8010"] }]
```

---

### §6.11 Email Configuration

Two separate email use cases, both using Brevo SMTP:

#### §6.11.1 Brevo Account Setup

1. Create account at `brevo.com` (free tier: 300 emails/day)
2. Navigate to **SMTP & API** → **SMTP** → **Generate a new SMTP key**
   - Note: SMTP key is different from API key; shown **only once**
   - SMTP login = your Brevo account email
   - SMTP password = the generated SMTP key (starts with `xsmtp...`)
3. Verify sender domain: **Senders & IP** → **Domains** → add `<DOMAIN>`
   - Add SPF: `TXT @ "v=spf1 include:sendinblue.com ~all"`
   - Add DKIM: provided by Brevo (CNAME record)
   - Add DMARC: `TXT _dmarc "v=DMARC1; p=none; rua=mailto:dmarc@<DOMAIN>"`

#### §6.11.2 Kubernetes `smtp-credentials` Secret

This secret is shared between Alertmanager and S10:

```yaml
# infra/k8s/secrets/smtp-credentials.yaml (BEFORE SOPS encryption)
apiVersion: v1
kind: Secret
metadata:
  name: smtp-credentials
  namespace: worldview
stringData:
  ALERT_SMTP_USER: "<BREVO_SMTP_LOGIN>"       # your Brevo account email
  ALERT_SMTP_PASSWORD: "<BREVO_SMTP_KEY>"     # generated SMTP key
```

Alertmanager references the same credentials via its Helm values (`smtp_auth_username` / `smtp_auth_password`).
These are set from the same SOPS secret via `valuesFrom` in the ArgoCD Application:

```yaml
# In monitoring.yaml ArgoCD application
helm:
  valuesObject:
    alertmanager:
      config:
        global:
          smtp_smarthost: 'smtp-relay.brevo.com:587'
          smtp_from: 'alerts@<DOMAIN>'
  valueFiles:
    - secrets+age-import:///sops-age/key.txt?../../k8s/secrets/alertmanager-smtp.yaml
```

---

### §6.12 Frontend — Vercel

#### §6.12.1 Vercel Setup

1. Sign up at `vercel.com` (free Hobby plan is sufficient)
2. Import project from GitHub: `<GITHUB_USER>/worldview`, subdirectory `apps/frontend`
3. Framework preset: **Vite**
4. Build command: `pnpm build`
5. Output directory: `dist`
6. Install command: `pnpm install --frozen-lockfile`

#### §6.12.2 Environment Variables (in Vercel dashboard)

| Variable | Value | Scope |
|----------|-------|-------|
| `VITE_API_BASE_URL` | `https://api.<DOMAIN>` | Production |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Preview / Development |

#### §6.12.3 CORS — S9 must whitelist Vercel

In `api-gateway` Helm values:
```yaml
env:
  - name: API_GATEWAY_CORS_ORIGINS
    value: "https://<DOMAIN>,https://*.vercel.app"
```

#### §6.12.4 Custom Domain on Vercel (optional)

1. Vercel dashboard → Project Settings → Domains → Add `app.<DOMAIN>`
2. DNS: add CNAME `app` → `cname.vercel-dns.com`
3. Vercel issues TLS automatically via Let's Encrypt

---

### §6.13 Resource Limits Summary

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit | Node |
|---------|------------|-----------|---------------|-------------|------|
| portfolio | 100m | 500m | 256 Mi | 512 Mi | stateless |
| market-ingestion | 200m | 1000m | 512 Mi | 1 Gi | stateless |
| market-data | 100m | 500m | 256 Mi | 512 Mi | stateless |
| content-ingestion | 200m | 1000m | 512 Mi | 1 Gi | stateless |
| content-store | 100m | 500m | 256 Mi | 512 Mi | stateless |
| nlp-pipeline | 500m | 2000m | 1 Gi | 3 Gi | stateless |
| knowledge-graph | 500m | 2000m | 1 Gi | 4 Gi | stateless |
| rag-chat | 200m | 1000m | 512 Mi | 1 Gi | stateless |
| api-gateway | 200m | 1000m | 256 Mi | 512 Mi | stateless |
| alert | 100m | 500m | 256 Mi | 512 Mi | stateless |
| **Kafka** | 500m | 2000m | 2 Gi | 4 Gi | stateful |
| **Postgres** | 500m | 2000m | 2 Gi | 4 Gi | stateful |
| **MinIO** | 200m | 1000m | 512 Mi | 2 Gi | stateful |
| **Valkey** | 100m | 500m | 256 Mi | 512 Mi | stateful |
| **Ollama** | 4000m | 12000m | 8 Gi | 20 Gi | stateful |
| **GLiNER** | 1000m | 4000m | 2 Gi | 4 Gi | stateful |
| **Schema Registry** | 200m | 500m | 512 Mi | 1 Gi | stateless |

Worker-1 (CX52 — 16 vCPU, 32 GB) hosts all stateful workloads. Estimated utilisation: ~14 vCPU, ~28 GB.
Worker-2 (CX42 — 8 vCPU, 16 GB) hosts all 10 app services. Estimated utilisation: ~4 vCPU, ~8 GB (well within limits).

---

## §7 External Account & API Setup

Every account that must exist before first deployment:

### §7.1 Hetzner Cloud

| Step | Action |
|------|--------|
| 1 | Create account at `hetzner.com/cloud` |
| 2 | Create new project: `worldview` |
| 3 | Generate API token: Project → Security → API Tokens → Generate (Read/Write) |
| 4 | Set in `infra/tofu/terraform.tfvars` (gitignored): `hcloud_token = "<TOKEN>"` |
| 5 | Upload SSH public key manually or via OpenTofu `hcloud_ssh_key` resource |
| 6 | Enable Hetzner Object Storage (optional — for Tofu state backend, OQ-003) |

### §7.2 EODHD

| Plan | Monthly | Notes |
|------|---------|-------|
| All-in-One (Academic) | €29.99 (50% discount with `.edu` email) | Required for production |
| Fundamentals Feed | €59.99 | Production option without discount |
| Demo key | free | `demo` key; limited to AAPL, MSFT only |

**Setup**:
1. Register at `eodhd.com` with academic email → apply for 50% discount
2. API key in dashboard → My API Tokens
3. Set `MARKET_INGESTION_EODHD_API_KEY` and `KNOWLEDGE_GRAPH_EODHD_API_KEY` (same key, two services)
4. Rate limits: 1,000 requests/day (All-in-One); pro-rata for Fundamentals Feed
5. Endpoints used: `/api/eod/<ticker>.US`, `/api/events/`, `/api/macro-indicator/`, `/api/insider-transactions/`

### §7.3 SEC EDGAR

- **No API key required** — public API
- Required header: `User-Agent: worldview/1.0 contact@<DOMAIN>` (EDGAR ToS)
- Rate limit: 10 req/s (enforced in S4 client)
- Set in S4 config: the `User-Agent` header is set in the EDGAR adapter class

### §7.4 DeepInfra

| Step | Action |
|------|--------|
| 1 | Register at `deepinfra.com` |
| 2 | Generate API key: Account → API Keys |
| 3 | Set `RAG_CHAT_DEEPINFRA_API_KEY` |
| 4 | Model: `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` |
| 5 | Base URL: `https://api.deepinfra.com/v1/openai` (OpenAI-compatible) |
| 6 | Cost: ~$0.0014/1K tokens; budget $5/month credit at start |
| 7 | Set spending limit in DeepInfra dashboard to prevent overruns |

### §7.5 Google AI Studio (Gemini)

| Step | Action |
|------|--------|
| 1 | Sign in at `aistudio.google.com` |
| 2 | Create API key: Get API Key → Create API Key |
| 3 | Set `KNOWLEDGE_GRAPH_GEMINI_API_KEY` |
| 4 | Model: `gemini-1.5-flash-latest` (or `gemini-3.1-flash-lite-preview` if available in your region) |
| 5 | Free tier: 1,500 req/day, 1M tokens/min — sufficient for thesis |
| 6 | KNOWLEDGE_GRAPH_DESCRIPTION_MAX_MONTHLY_USD: set to `5.0` as safety cap |

### §7.6 Brevo (Email)

See §6.11 for complete setup. Summary:

| Step | Action |
|------|--------|
| 1 | Register at `brevo.com` |
| 2 | Generate SMTP key (Settings → SMTP & API) |
| 3 | Verify sender domain (add SPF/DKIM/DMARC records) |
| 4 | Store credentials in `smtp-credentials` Kubernetes Secret (SOPS-encrypted) |
| 5 | Free: 300 emails/day — sufficient for alerts + user digest |

### §7.7 Polymarket (Gamma API)

- **No account or API key required** for read-only market data
- Base URL: `https://gamma-api.polymarket.com/markets` (public, unauthenticated)
- Set `CONTENT_INGESTION_POLYMARKET__BASE_URL` (already defaulted in config)

### §7.8 Vercel

| Step | Action |
|------|--------|
| 1 | Register at `vercel.com` |
| 2 | Import GitHub repo — select `apps/frontend` subdirectory |
| 3 | Set `VITE_API_BASE_URL=https://api.<DOMAIN>` |
| 4 | Vercel automatically deploys on `main` push |
| 5 | Free Hobby plan: 100 GB bandwidth/month — sufficient for thesis |

### §7.9 GitHub Container Registry (ghcr.io)

- Included with every GitHub account — no additional signup
- Images are public by default for public repos; set visibility to `private` in package settings if needed
- `GITHUB_TOKEN` secret is automatically available in GitHub Actions — no manual setup

### §7.10 OpenRouter (fallback LLM)

Optional S8 fallback chain. Register at `openrouter.ai`, generate API key, set `RAG_CHAT_OPENROUTER_API_KEY`. Only used if DeepInfra is unreachable.

### §7.11 NewsAPI

⚠️ **Production use prohibited** — NewsAPI Developer plan is free-tier for development only; the ToS explicitly prohibits production deployment. Options:
1. **Disable NewsAPI adapter in S4** for production (set source to inactive)
2. **Upgrade to Business plan** ($449/month) — likely not worth it for thesis
3. **Replace with RSS feeds** — configure the RSS adapter in S4 to replace NewsAPI sources

**Recommendation**: Disable the NewsAPI source for production. The thesis evaluator will not notice its absence given the SEC EDGAR, EODHD, and Polymarket data flows.

### §7.12 SnapTrade (PRD-0022 — when implemented)

- Register at `snaptrade.com` (free developer tier)
- Generate `SNAPTRADE_CLIENT_ID` and `SNAPTRADE_CONSUMER_KEY`
- Used only in S1 BrokerageConnection flow (portfolio sync)

---

## §8 Domain & DNS Setup

The domain has not yet been purchased. This section covers required DNS records once it is.

### §8.1 DNS Records

After `tofu apply` outputs the floating IP, create these records:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | `@` | `<FLOATING_IP>` | 300 |
| A | `*` | `<FLOATING_IP>` | 300 |
| CNAME | `app` | `cname.vercel-dns.com` | 300 (if using Vercel custom domain) |
| TXT | `@` | `v=spf1 include:sendinblue.com ~all` | 3600 |
| CNAME | `brevo._domainkey` | `<brevo-dkim-value>` | 3600 |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:dmarc@<DOMAIN>` | 3600 |

### §8.2 TLS Certificate Flow

1. DNS `api.<DOMAIN>` → floating IP (Traefik LoadBalancer Service)
2. cert-manager `ClusterIssuer` requests ACME challenge from Let's Encrypt
3. Let's Encrypt HTTP-01: `GET http://api.<DOMAIN>/.well-known/acme-challenge/<TOKEN>`
4. Traefik routes challenge to cert-manager ACME solver Service
5. cert-manager stores TLS cert in `api-tls` Secret
6. Traefik reads `api-tls` Secret for HTTPS termination

### §8.3 Domain Providers

Recommended providers that support modern DNS management:
- **Cloudflare Registrar** — at-cost pricing (~€8/year for `.com`); free DNS hosting; optional CDN/proxy
- **Namecheap** — competitive pricing; reasonable DNS UI
- **Hetzner DNS** — integrated with Hetzner Cloud; free DNS hosting

**Recommendation**: Cloudflare Registrar + Cloudflare DNS. Even without enabling the proxy (orange cloud), Cloudflare DNS gives instant propagation and an API for automation.

---

## §9 Security Analysis

### §9.1 Attack Surface

| Exposure | Risk | Mitigation |
|----------|------|-----------|
| S9 API Gateway (public HTTPS) | Auth bypass, injection, rate abuse | JWT validation, Pydantic input validation, Valkey rate limiting |
| Kubernetes API server (port 6443) | Unauthorized cluster control | Firewall: restrict 6443 to developer IP only |
| SSH (port 22) | Brute force | Firewall: restrict to developer IP; key-only auth |
| Grafana (HTTPS) | Admin credential exposure | Strong admin password in SOPS secret |
| ArgoCD (internal only) | Unauthorized GitOps ops | No external Ingress; port-forward only |
| SOPS private key | Full secret exposure | Never in git; only in GitHub Actions secret |
| Postgres (internal) | Cross-tenant queries | No external exposure; app-layer tenant_id filter |
| MinIO (internal) | Bucket traversal | No external exposure; per-service bucket policies |

### §9.2 Secrets in Git

All secrets must be SOPS-encrypted before committing. Pre-commit hook enforcement:

```bash
# .pre-commit-config.yaml addition
- repo: local
  hooks:
    - id: no-plaintext-k8s-secrets
      name: No plaintext Kubernetes secrets
      entry: bash -c 'git diff --cached --name-only | grep "infra/k8s/secrets/" | while read f; do grep -q "sops:" "$f" || (echo "ERROR: $f is not SOPS-encrypted" && exit 1); done'
      language: system
      pass_filenames: false
```

### §9.3 Network Segmentation

```
Internet → Floating IP (Hetzner LB)
         → Traefik (port 80/443) → S9 only (port 8000)
                                  → Grafana (port 80, protected)

All other services: ClusterIP only — no external exposure
Postgres/Kafka/MinIO/Valkey: ClusterIP in namespace infra — not reachable from outside cluster
```

### §9.4 JWT Secret Rotation

`API_GATEWAY_JWT_SECRET` should be a 256-bit random hex string:
```bash
openssl rand -hex 32
```
Store in SOPS-encrypted `api-gateway-secrets`. If rotated, all user sessions are invalidated.

---

## §10 Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Pod OOM killed | Alertmanager `KubePodCrashLooping` | k8s restarts pod; investigate memory limit |
| Postgres down | `ServiceDown` alert, 500s from all services | Postgres PVC persists; pod restarts — data intact |
| Kafka down | Consumer lags spike; Alertmanager alert | Kafka KRaft restarts; consumers resume from last offset |
| Floating IP lost (CCM reassigns) | Traefik LB IP changes | CCM re-assigns automatically on node recovery |
| Let's Encrypt rate limit hit | cert-manager error | Use staging issuer first; switch to prod after staging passes |
| DeepInfra API down | S8 returns 503 for chat requests | S8 fallback chain: OpenRouter → Groq (if configured) |
| EODHD API down | market-ingestion worker errors in logs | Scheduled tasks will retry on next tick (60s interval) |
| SOPS key lost | Cannot decrypt secrets | Keep `~/.config/sops/age/keys.txt` backed up locally; GitHub Actions secret is secondary copy |
| ArgoCD sync fails | ArgoCD UI/CLI shows degraded app | `argocd app sync <name> --force`; check events for RBAC or helm errors |
| Volume full | Disk pressure eviction | Expand Hetzner Volume in Cloud console; k8s PVC auto-resizes with `allowVolumeExpansion: true` |
| Node down | Pod eviction, reschedule on healthy node | Stateless services move to worker-2; stateful services (Postgres/Kafka) stay on worker-1 PVC |

---

## §11 Step-by-Step Deployment Procedure

This is the ordered bootstrap sequence from zero to running cluster.

### Phase 1 — Prerequisites (local machine)

```bash
# 1. Install tools
brew install opentofu age sops kubectl helm argocd

# 2. Install helm-secrets plugin
helm plugin install https://github.com/jkroepke/helm-secrets

# 3. Generate Age key pair (ONCE)
age-keygen -o ~/.config/sops/age/keys.txt
# → Note the public key for .sops.yaml

# 4. Update .sops.yaml with your Age public key
# → infra/.sops.yaml: age: age1xxxx...

# 5. Generate all secrets and encrypt them
./scripts/generate-secrets.sh   # helper script (write this once to generate random values)
# This should: generate passwords/tokens, create Secret YAMLs, encrypt with SOPS
```

### Phase 2 — Hetzner Infrastructure

```bash
cd infra/tofu

# 1. Create terraform.tfvars (gitignored)
cat > terraform.tfvars <<EOF
hcloud_token      = "<YOUR_HCLOUD_TOKEN>"
ssh_public_key    = "$(cat ~/.ssh/id_ed25519.pub)"
k3s_token         = "$(openssl rand -hex 32)"
developer_ip      = "<YOUR_PUBLIC_IP>/32"
EOF

# 2. Initialize and apply
tofu init
tofu plan -out=tfplan
tofu apply tfplan

# 3. Record outputs
tofu output  # → cp_ip, worker1_ip, worker2_ip, floating_ip

# 4. Wait for cloud-init to complete (2-3 minutes)
ssh root@<cp_ip> 'journalctl -u k3s -f'
# Wait until: "Node cp is ready"

# 5. Get kubeconfig
ssh root@<cp_ip> 'cat /tmp/kubeconfig' > ~/.kube/config-worldview
export KUBECONFIG=~/.kube/config-worldview
kubectl get nodes  # should show 3 Ready nodes
```

### Phase 3 — Core Kubernetes Setup

```bash
# 1. Install hcloud-ccm (Hetzner Cloud Controller Manager)
helm repo add hcloud https://charts.hetzner.cloud && helm repo update
kubectl -n kube-system create secret generic hcloud \
  --from-literal=token=<HCLOUD_TOKEN> \
  --from-literal=network=worldview-net
helm install hccm hcloud/hcloud-cloud-controller-manager \
  -n kube-system \
  --set networking.enabled=true \
  --set networking.clusterCIDR="10.42.0.0/16"

# 2. Install hcloud-csi
helm install hcloud-csi hcloud/hcloud-csi -n kube-system \
  --set node.kubeletDir=/var/lib/rancher/k3s/agent/kubelet

# 3. Create namespaces
kubectl create namespace traefik cert-manager argocd infra worldview monitoring

# 4. Create ghcr.io pull secret (for custom postgres image and service images)
kubectl -n infra create secret docker-registry ghcr-credentials \
  --docker-server=ghcr.io \
  --docker-username=<GITHUB_USER> \
  --docker-password=<GITHUB_PAT>
kubectl -n worldview create secret docker-registry ghcr-credentials \
  --docker-server=ghcr.io \
  --docker-username=<GITHUB_USER> \
  --docker-password=<GITHUB_PAT>
```

### Phase 4 — ArgoCD Bootstrap

```bash
# 1. Install ArgoCD
helm repo add argo https://argoproj.github.io/argo-helm && helm repo update
helm install argocd argo/argo-cd -n argocd \
  --version 7.8.26 \
  -f infra/argocd/argocd-values.yaml   # contains helm-secrets plugin config

# 2. Wait for ArgoCD to be ready
kubectl -n argocd wait --for=condition=available deploy/argocd-server --timeout=120s

# 3. Get initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d

# 4. Create SOPS Age key secret in ArgoCD namespace
kubectl -n argocd create secret generic sops-age-key \
  --from-file=key.txt=~/.config/sops/age/keys.txt

# 5. Apply SOPS-encrypted secrets to cluster (initial bootstrap only)
# ArgoCD will manage these after this point
for f in infra/k8s/secrets/*.yaml; do
  sops --decrypt "$f" | kubectl apply -f -
done

# 6. Apply root ArgoCD application
kubectl apply -f infra/argocd/root-app.yaml

# 7. Watch sync progress
argocd app list
argocd app sync worldview-root
```

### Phase 5 — Infrastructure Services (ArgoCD Sync Order)

ArgoCD syncs these automatically, but manual ordering is needed for first boot:

```bash
# Order matters for first boot:
argocd app sync infra-postgres       # wait for Postgres to be healthy
argocd app sync infra-kafka          # wait for Kafka broker ready
argocd app sync infra-schema-registry
argocd app sync infra-minio
argocd app sync infra-valkey

# Run database migrations
kubectl -n worldview create job migrate-once \
  --image=ghcr.io/<GITHUB_USER>/worldview-intelligence-migrations:latest
kubectl -n worldview wait --for=condition=complete job/migrate-once --timeout=300s
```

### Phase 6 — Application Services

```bash
# ArgoCD auto-syncs all worldview-* apps
# Watch until all are healthy:
argocd app list | grep worldview
# All should show Synced / Healthy within 5-10 minutes

# Verify critical services respond
kubectl -n worldview port-forward svc/api-gateway 8000:8000 &
curl http://localhost:8000/health
```

### Phase 7 — Observability

```bash
argocd app sync monitoring
# Wait for Prometheus, Grafana, Alertmanager to be ready
# Import existing Grafana dashboards from infra/grafana/
```

### Phase 8 — DNS & TLS

```bash
# 1. Add DNS records (see §8.1) pointing to FLOATING_IP from tofu output

# 2. Apply cert-manager ClusterIssuers
kubectl apply -f infra/k8s/cert-manager/cluster-issuers.yaml

# 3. Apply Ingress resources
kubectl apply -f infra/k8s/ingress/

# 4. Verify TLS certificate issuance (may take 2-5 minutes)
kubectl -n worldview describe certificate api-tls
# Should show: Ready True

# 5. Test public access
curl https://api.<DOMAIN>/health
```

### Phase 9 — Ollama Model Warm-up

```bash
# Apply Ollama manifests
kubectl apply -f infra/argocd/manifests/ollama.yaml
kubectl apply -f infra/argocd/manifests/ollama-model-pull-job.yaml

# Wait for model download (may take 10-30 minutes depending on internet speed)
kubectl -n infra logs job/ollama-model-pull -f

# Verify models are loaded
kubectl -n infra port-forward svc/ollama 11434:11434 &
curl http://localhost:11434/api/tags | jq '.models[].name'
```

### Phase 10 — Final Smoke Test

```bash
# 1. API Gateway health
curl https://api.<DOMAIN>/health  # → {"status":"ok"}

# 2. Create test user (requires JWT from S9)
curl -X POST https://api.<DOMAIN>/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test1234!"}'

# 3. Login and get JWT
TOKEN=$(curl -s -X POST https://api.<DOMAIN>/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test1234!"}' | jq -r '.access_token')

# 4. Test chat
curl -X POST https://api.<DOMAIN>/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the current market sentiment?"}'

# 5. Check Grafana
open https://grafana.<DOMAIN>  # login with admin / <GRAFANA_ADMIN_PASSWORD>
# Verify all 10 services appear in Prometheus targets
```

---

## §12 Test Strategy

### §12.1 Pre-Deployment Tests (Local)

Run before any `tofu apply`:

| Test | Command | What It Verifies |
|------|---------|-----------------|
| Unit tests (all services) | `for svc in services/*/; do (cd "$svc" && python -m pytest tests/ -m "unit" -q); done` | ~4,059 tests |
| Helm chart lint | `helm lint infra/helm/worldview-service` | Chart syntax |
| Helm template render | `helm template test infra/helm/worldview-service -f infra/helm/values/portfolio.yaml` | Values correct |
| OpenTofu plan dry-run | `cd infra/tofu && tofu plan` | No Tofu errors |
| SOPS decrypt test | `sops --decrypt infra/k8s/secrets/api-gateway-secrets.yaml` | Keys valid |
| kubeconfig check | `kubectl get nodes` | Cluster reachable |

### §12.2 Post-Deployment Integration Tests

| Test | What It Verifies |
|------|-----------------|
| `GET https://api.<DOMAIN>/health` | S9 is up, TLS works |
| `GET https://api.<DOMAIN>/api/v1/instruments?page=1&page_size=5` | S3 market data query |
| `POST https://api.<DOMAIN>/api/v1/chat` | S8 RAG pipeline end-to-end |
| `kubectl -n monitoring get pods` | All observability pods running |
| `kubectl -n infra get pods` | Kafka, Postgres, MinIO, Valkey running |
| Alertmanager test fire | `curl -X POST http://alertmanager:9093/api/v2/alerts -d '[{"labels":{"alertname":"TestAlert"}}]'` | Email received |
| Prometheus targets | `https://grafana.<DOMAIN>/api/datasources/proxy/1/api/v1/targets` | All 10 services active |

### §12.3 Smoke Tests (Table)

| Test ID | Test | Expected | Priority |
|---------|------|----------|----------|
| T-001 | `GET /health` on all 10 services via port-forward | HTTP 200 | HIGH |
| T-002 | Postgres `SELECT 1` in each of 10 databases | Returns 1 | HIGH |
| T-003 | Kafka topic list | 10+ topics visible | HIGH |
| T-004 | MinIO bucket list | 5+ buckets visible | HIGH |
| T-005 | S9 JWT login + authenticated request | HTTP 200 with token | HIGH |
| T-006 | S8 chat request completes | HTTP 200, message field present | HIGH |
| T-007 | Prometheus scrapes all 10 services | `up == 1` for each target | MEDIUM |
| T-008 | Grafana login | HTTP 200, dashboard loads | MEDIUM |
| T-009 | Alertmanager test fire → email received | Email in inbox within 5 min | MEDIUM |
| T-010 | EODHD fetch (S2) completes | Log shows `articles_fetched > 0` | MEDIUM |
| T-011 | ArgoCD all apps Synced/Healthy | ArgoCD UI shows green | HIGH |
| T-012 | TLS cert valid for `api.<DOMAIN>` | `curl -v` shows valid cert | HIGH |
| T-013 | Vercel deployment live at `https://app.<DOMAIN>` | React app loads | HIGH |

---

## §13 Open Questions

| ID | Question | Classification | Resolution |
|----|----------|---------------|-----------|
| OQ-001 | Which specific domain to buy? | DEFERRED | Purchase within days; placeholder `<DOMAIN>` used throughout |
| OQ-002 | Use Cloudflare proxy (orange cloud) or DNS-only? | DEFERRED | DNS-only recommended for first deployment (simpler TLS); Cloudflare proxy can be enabled later for DDoS protection |
| OQ-003 | Use Hetzner Object Storage as OpenTofu state backend? | DEFERRED | Local `.tfstate` is acceptable for single developer. If remote state is needed: create a Hetzner S3-compatible bucket, configure backend in `main.tf` |
| OQ-004 | Enable `KNOWLEDGE_GRAPH_CYPHER_ENABLED=true` in production? | DEFERRED | Requires AGE backfill job to populate the graph. Keep `false` for initial deployment; enable after backfill verified |
| OQ-005 | Is `gemini-3.1-flash-lite-preview` available via API? | DEFERRED | Use `gemini-1.5-flash-latest` as fallback; both are free-tier eligible. Check AI Studio for model availability |
| OQ-006 | Groq API key for S8 fallback chain? | DEFERRED | Optional: register at `groq.com`, free tier, set `RAG_CHAT_GROQ_API_KEY` if desired |
| OQ-007 | Intelligence-migrations service — when to run in production? | DEFERRED | Run as a Kubernetes Job (not a long-running service) after Postgres is ready. ArgoCD `PreSync` hook recommended |

---

## §14 Estimation

### §14.1 One-Time Setup Cost

| Task | Estimated Effort |
|------|-----------------|
| Create all external accounts (Hetzner, EODHD, DeepInfra, Gemini, Brevo, Vercel) | 2 hours |
| OpenTofu directory + HCL files | 3 hours |
| Write generic Helm chart + 10 values files | 4 hours |
| Write ArgoCD App-of-Apps manifests (20 files) | 2 hours |
| Generate + encrypt SOPS secrets (16 secret files) | 2 hours |
| Set up GitHub Actions CI/CD | 2 hours |
| Write cloud-init templates + test on Hetzner | 3 hours |
| DNS setup + TLS verification | 1 hour |
| Vercel frontend setup | 30 minutes |
| First full deployment + smoke tests | 4 hours |
| **Total** | **~23 hours** |

### §14.2 Recurring Monthly Cost

| Item | Monthly |
|------|---------|
| Hetzner servers + volumes + IP | ~€59 |
| EODHD (academic 50%) | ~€30 |
| DeepInfra (S8 chat) | ~$3-5 |
| Brevo (email) | €0 (free tier) |
| Vercel (frontend) | €0 (free Hobby) |
| Cloudflare DNS | €0 (free) |
| GitHub (Actions + ghcr.io) | €0 (free) |
| **Total** | **~€92/month** |

Within the €50-100/month budget. EODHD cost can be reduced by using demo key during thesis period and only upgrading for the evaluation window.

### §14.3 Implementation Waves (PLAN-0024)

This PRD maps to the following implementation plan:

| Wave | Scope | Dependencies |
|------|-------|-------------|
| A-1 | OpenTofu HCL files + cloud-init templates | none |
| A-2 | Generic Helm chart + per-service values | A-1 complete |
| A-3 | ArgoCD App-of-Apps manifests + SOPS encrypted secrets | A-2 complete |
| A-4 | GitHub Actions CI/CD workflow + Dockerfiles (if missing) | A-3 complete |
| A-5 | DNS + TLS + Ingress manifests + Vercel setup | A-4 complete |

Each wave produces working, testable artifacts. Waves A-1 through A-5 can be implemented before the domain is purchased (except for DNS records in A-5).
