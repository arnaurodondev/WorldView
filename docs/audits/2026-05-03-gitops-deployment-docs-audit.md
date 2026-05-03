# Deployment Documentation Audit — worldview-gitops Blueprint

> **Date**: 2026-05-03
> **Scope**: Production deployment documentation — what exists in worldview, what must exist in worldview-gitops
> **Deployment target**: Hetzner single-server (Docker Compose + Traefik v3), optional Vercel frontend split
> **Health Score**: 42/100 — Core deployment machinery exists; gitops repo structure and production runbooks are absent

---

## Executive Summary

The worldview repo has a production Docker Compose overlay (`infra/compose/docker-compose.prod.yml`) with Traefik v3 TLS termination, and `make prod` / `make prod-rebuild` / `make prod-down` targets. However, the `worldview-gitops` private repo has no documented structure for production env files, no Hetzner server setup script, no production runbooks, and no production deployment checklist. All of these must be created. This report is the blueprint.

---

## Phase 1 — What Already Exists

### 1.1 Documents That Exist and Are Adequate

| File | Status | Notes |
|------|--------|-------|
| `docs/runbooks/secrets-management.md` | Adequate | Two-repo architecture explained, `setup-dev.sh` workflow documented, required secrets table |
| `infra/compose/docker-compose.prod.yml` | Adequate | Well-commented, Traefik v3 TLS, all non-public ports closed, WebSocket routing |
| `infra/zitadel/README.md` | Adequate | Option A (local), B (Zitadel Cloud), C (Terraform); required env vars table |
| `docs/references/traefik-ws-token-masking.md` | Adequate | Deep reference for WS JWT token leakage via Traefik access logs |
| `docs/workflows/local-dev.md` | Adequate | Comprehensive — Dev Login, profiles, Docker Compose, troubleshooting |
| `docs/PRODUCTION_READINESS.md` | Adequate as TODO tracker | 77-item checklist categorized P0/P1/P2/P3; last updated 2026-03-30 |
| `Makefile` (prod targets) | Adequate | `make prod`, `make prod-down`, `make prod-rebuild` with DOMAIN/ACME_EMAIL guards |
| `services/*/configs/prod.env.example` | Adequate as templates | 9 of 11 services have prod.env.example (missing: alert, intelligence-migrations) |

### 1.2 Documents That Exist but Are Incomplete

| File | Gap | Priority |
|------|-----|----------|
| `docs/workflows/release-process.md` | References "Deploy Production" step but has zero detail on Hetzner Docker Compose deployment | HIGH |
| `docs/workflows/local-dev.md` | Pre-deployment checklist references `local-k8s.sh` (k3s workflow) but current production target is Docker Compose + Hetzner; two deployment paths are not clearly separated | HIGH |
| `docs/PRODUCTION_READINESS.md` | Last updated 2026-03-30; predates Traefik overlay (added later), Zitadel auth (PRD-0025), and Next.js frontend completion (PLAN-0028); many P0 items marked "TODO" are now implemented | MEDIUM |
| `apps/worldview-web/.env.example` | Only covers local dev; no production env vars documented (missing `NEXT_PUBLIC_ZITADEL_URL`, `NEXT_PUBLIC_ZITADEL_CLIENT_ID`, production `NEXT_PUBLIC_WS_BASE_URL`) | HIGH |

### 1.3 Documents That Are Missing Entirely

| Missing Document | Where It Should Live | Priority |
|-----------------|---------------------|----------|
| Hetzner server setup guide | `worldview-gitops/docs/hetzner-setup.md` | P0 |
| Production deployment runbook | `worldview-gitops/docs/production-deployment.md` | P0 |
| Production env files (`env/prod/`) | `worldview-gitops/env/prod/*.env` | P0 |
| `setup-prod.sh` script | `worldview-gitops/scripts/setup-prod.sh` | P0 |
| Vercel deployment guide | `worldview-gitops/docs/vercel-deployment.md` | P1 |
| Production secrets rotation runbook | `worldview-gitops/docs/secrets-rotation.md` | P1 |
| Disaster recovery / backup runbook | `worldview-gitops/docs/disaster-recovery.md` | P2 |
| prod.env.example for alert service | `services/alert/configs/prod.env.example` | P1 |
| prod.env.example for intelligence-migrations | `services/intelligence-migrations/configs/prod.env.example` | P1 |

---

## Phase 2 — worldview-gitops: Recommended Structure

The `worldview-gitops` private repo should have the following layout for Hetzner Docker Compose production deployment:

```
worldview-gitops/
├── README.md                          # Overview: two-repo architecture, how to use this repo
├── docs/
│   ├── hetzner-setup.md               # Server provisioning from scratch
│   ├── production-deployment.md       # Step-by-step first-deploy + update workflow
│   ├── vercel-deployment.md           # Frontend split deployment guide
│   ├── zitadel-production.md          # Zitadel Cloud project setup (with screenshots)
│   ├── secrets-rotation.md            # How to rotate each class of secret
│   ├── disaster-recovery.md           # DB backup, volume restore, certificate recovery
│   └── monitoring-setup.md            # Grafana dashboards, alert rules, Loki retention
├── env/
│   ├── dev/                           # Dev env files (copied by setup-dev.sh)
│   │   ├── portfolio.env
│   │   ├── market-ingestion.env
│   │   ├── market-data.env
│   │   ├── content-ingestion.env
│   │   ├── content-store.env
│   │   ├── nlp-pipeline.env
│   │   ├── knowledge-graph.env
│   │   ├── rag-chat.env
│   │   ├── api-gateway.env
│   │   └── alert.env
│   └── prod/                          # Production env files (copied by setup-prod.sh)
│       ├── portfolio.env
│       ├── market-ingestion.env
│       ├── market-data.env
│       ├── content-ingestion.env
│       ├── content-store.env
│       ├── nlp-pipeline.env
│       ├── knowledge-graph.env
│       ├── rag-chat.env
│       ├── api-gateway.env
│       ├── alert.env
│       └── platform.env               # Cross-service: DOMAIN, ACME_EMAIL, ZITADEL vars
├── scripts/
│   ├── setup-dev.sh                   # Already exists: copies env/dev/* to worldview services
│   ├── setup-prod.sh                  # NEW: copies env/prod/* to worldview services/configs/docker.env
│   ├── hetzner-bootstrap.sh           # NEW: idempotent server setup (Docker, firewall, swap)
│   ├── generate-internal-keypair.sh   # Symlink or copy of worldview/scripts/generate-internal-keypair.sh
│   └── verify-prod-health.sh          # NEW: curl smoke tests for all public endpoints
└── templates/
    ├── prod.env.template              # Annotated template with all required vars and defaults
    └── platform.env.template          # Top-level DOMAIN/ACME_EMAIL/ZITADEL template
```

---

## Phase 3 — Production Env File Templates

### 3.1 `platform.env` (top-level, cross-service)

This file is sourced by `setup-prod.sh` and provides variables referenced in `docker-compose.prod.yml`:

```bash
# platform.env — Set these before running make prod
# These are referenced directly by docker-compose.prod.yml (${DOMAIN}, etc.)

# Root domain — all subdomains are derived from this
DOMAIN=worldview.example.com

# Let's Encrypt email — receives cert expiry warnings
ACME_EMAIL=ops@example.com

# Zitadel OIDC issuer URL (Zitadel Cloud instance)
ZITADEL_URL=https://<your-instance>.zitadel.cloud

# Zitadel PKCE client ID (create via Zitadel Cloud console)
ZITADEL_CLIENT_ID=<client-id-from-zitadel>

# WebSocket base URL — defaults to wss://ws.${DOMAIN} (matches Traefik alert router)
# Only override if you change the alert service subdomain
NEXT_PUBLIC_WS_BASE_URL=wss://ws.worldview.example.com
```

### 3.2 `env/prod/api-gateway.env` (critical — authentication)

The api-gateway production env needs additional vars not in `services/api-gateway/configs/prod.env.example`:

```bash
# api-gateway — Production
API_GATEWAY_HOST=0.0.0.0
API_GATEWAY_PORT=8000
API_GATEWAY_DEBUG=false
API_GATEWAY_LOG_LEVEL=INFO
API_GATEWAY_LOG_FORMAT=json

# Database
API_GATEWAY_DATABASE_URL=postgresql+asyncpg://postgres:<PASSWORD>@postgres:5432/gateway_db

# Kafka
API_GATEWAY_KAFKA_BOOTSTRAP_SERVERS=kafka:29092
API_GATEWAY_SCHEMA_REGISTRY_URL=http://schema-registry:8081

# Storage (MinIO)
API_GATEWAY_STORAGE_ENDPOINT=http://minio:9000
API_GATEWAY_STORAGE_ACCESS_KEY=<MINIO_ACCESS_KEY>
API_GATEWAY_STORAGE_SECRET_KEY=<MINIO_SECRET_KEY>

# Valkey
API_GATEWAY_VALKEY_URL=redis://valkey:6379/0

# OIDC (Zitadel Cloud — REQUIRED for production)
API_GATEWAY_OIDC_ISSUER_URL=https://<your-instance>.zitadel.cloud
API_GATEWAY_OIDC_CLIENT_ID=<zitadel-client-id>
API_GATEWAY_OIDC_CLIENT_SECRET=        # Leave empty — PKCE uses no client secret
API_GATEWAY_OIDC_AUDIENCE=<zitadel-client-id>
API_GATEWAY_OIDC_DISCOVERY_OPTIONAL=false   # MUST be false in production
API_GATEWAY_FRONTEND_URL=https://<DOMAIN>

# Cookie security
API_GATEWAY_COOKIE_SECURE=true         # MUST be true when serving HTTPS

# Internal JWT (RS256 — generate with scripts/generate-internal-keypair.sh)
API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY=<RSA-2048 PEM, single-line with \n>
API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY=<RSA-2048 PEM, single-line with \n>

# CORS — restrict to production domain only
API_GATEWAY_CORS_ORIGINS=https://<DOMAIN>

# Rate limiting
API_GATEWAY_RATE_LIMIT_ENABLED=true

# Observability
API_GATEWAY_OTLP_ENDPOINT=http://tempo:4317
```

### 3.3 Required Secrets Per Service

| Service | Variable(s) | Source | Required |
|---------|------------|--------|---------|
| api-gateway | `API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY` + `PUBLIC_KEY` | `scripts/generate-internal-keypair.sh` | P0 |
| api-gateway | `API_GATEWAY_OIDC_ISSUER_URL`, `OIDC_CLIENT_ID` | Zitadel Cloud console | P0 |
| market-ingestion | `MARKET_INGESTION_EODHD_API_KEY` | https://eodhd.com | P0 |
| rag-chat | `RAG_CHAT_DEEPINFRA_API_KEY` | https://deepinfra.com | P0 |
| knowledge-graph | `KNOWLEDGE_GRAPH_GEMINI_API_KEY` | https://aistudio.google.com | P1 |
| knowledge-graph | `KNOWLEDGE_GRAPH_EODHD_API_KEY` | https://eodhd.com | P1 |
| All services | `<SERVICE>_DATABASE_URL` | Hetzner Postgres password | P0 |
| All services | `<SERVICE>_STORAGE_ACCESS_KEY` + `SECRET_KEY` | MinIO production credentials | P0 |
| All services | `<SERVICE>_KAFKA_BOOTSTRAP_SERVERS=kafka:29092` | Internal Docker network | P0 |

---

## Phase 4 — Hetzner Server Setup Checklist

What `worldview-gitops/scripts/hetzner-bootstrap.sh` and `docs/hetzner-setup.md` must cover:

### 4.1 Server Provisioning

```
[ ] Order Hetzner Cloud server:
    - Minimum spec: CPX31 (4 vCPU, 8 GB RAM, 160 GB NVMe) ~€13/month
    - Recommended: CPX41 (8 vCPU, 16 GB RAM) for NLP/embedding workloads
    - OS: Ubuntu 24.04
    - Region: Choose closest to target users (nbg1 / hel1 / fsn1 for EU)
    - Add SSH key at provisioning time

[ ] Configure Hetzner Firewall:
    - Allow: 22/tcp (SSH) — restrict to your IP(s)
    - Allow: 80/tcp (HTTP — Let's Encrypt HTTP-01 challenge + redirect)
    - Allow: 443/tcp (HTTPS — all production traffic via Traefik)
    - Allow: 443/udp (HTTP/3 — optional, future)
    - Block: everything else (5432, 6379, 9092, 7480, 8000-8010 must NOT be reachable)

[ ] Point DNS records:
    - A record:     worldview.example.com → <server-IP>
    - A record:     api.worldview.example.com → <server-IP>
    - A record:     ws.worldview.example.com → <server-IP>
    - A record:     grafana.worldview.example.com → <server-IP>
    - A record:     www.worldview.example.com → <server-IP>
    TTL: 60s initially (speed up cert acquisition), raise to 3600s after confirmed working

[ ] SSH into server and run initial setup:
    apt update && apt upgrade -y
    # Install Docker (official method, not snap):
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker ubuntu   # or your user

    # Swap (prevent OOM on 8 GB nodes under NLP load):
    fallocate -l 4G /swapfile && chmod 600 /swapfile
    mkswap /swapfile && swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab

    # Docker Compose plugin (if not included):
    apt install docker-compose-plugin -y

    # Verify:
    docker --version   # 27+
    docker compose version   # 2.x
```

### 4.2 Repository Checkout

```
[ ] On the Hetzner server:
    mkdir -p /opt/worldview && cd /opt/worldview
    git clone <worldview-repo> worldview
    git clone <worldview-gitops-repo> worldview-gitops   # private — needs deploy key

[ ] Add deploy key to worldview-gitops (read-only):
    ssh-keygen -t ed25519 -C "hetzner-deploy" -f ~/.ssh/id_deploy -N ""
    # Add ~/.ssh/id_deploy.pub to worldview-gitops GitHub repo → Settings → Deploy keys

[ ] Set up SSH config for deploy key:
    cat >> ~/.ssh/config << EOF
    Host github.com
      IdentityFile ~/.ssh/id_deploy
    EOF
```

### 4.3 Environment Files

```
[ ] Copy production env files from worldview-gitops to worldview services:
    cd /opt/worldview/worldview-gitops
    ./scripts/setup-prod.sh

[ ] Verify all docker.env files are in place:
    ls /opt/worldview/worldview/services/*/configs/docker.env

[ ] Source platform.env (or export vars) before running make prod:
    export $(grep -v '^#' worldview-gitops/env/prod/platform.env | xargs)
    # OR: add to ~/.bashrc / ~/.profile
```

### 4.4 First Production Deploy

```
[ ] Change to worldview directory:
    cd /opt/worldview/worldview

[ ] Validate DOMAIN and ACME_EMAIL are set:
    echo $DOMAIN && echo $ACME_EMAIL

[ ] Start the production stack:
    make prod

[ ] Wait for Let's Encrypt certificates (30-60s):
    docker logs worldview-traefik-1 2>&1 | grep -i "acme\|certificate"

[ ] Verify all containers are healthy:
    docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.prod.yml \
      --profile infra ps

[ ] Run smoke tests:
    curl -I https://<DOMAIN>                    # → 200 (frontend)
    curl -I https://api.<DOMAIN>/v1/health      # → 200 (api-gateway)
    # WebSocket test via browser console:
    # new WebSocket('wss://ws.<DOMAIN>/ws/alerts')
```

### 4.5 Security Hardening (Post-Deploy)

```
[ ] Change Grafana default password immediately:
    # https://grafana.<DOMAIN> → admin/admin → change password

[ ] Verify no direct ports are exposed:
    ss -tlnp | grep -E "8000|8001|8002|8003|8004|8005|8006|8007|8008|8010|5432|6379|9092"
    # All should return empty — only 80 and 443 should appear

[ ] Verify HTTPS redirect:
    curl -I http://<DOMAIN>   # → 301 to https://

[ ] Check Traefik access log does not contain ?token= tokens:
    docker logs worldview-traefik-1 2>&1 | grep "token=" | head -5
    # Should return empty (Traefik v3.3 separates RequestQuery from RequestPath)
    # If tokens appear, add --accesslog.fields.names.RequestQuery=drop to Traefik command args
    # See docs/references/traefik-ws-token-masking.md

[ ] Restrict Grafana to internal access only (optional):
    # In docker-compose.prod.yml: add IP whitelist middleware to grafana labels
    # traefik.http.middlewares.grafana-ip.ipallowlist.sourcerange=<your-IP>/32

[ ] Enable UFW firewall at OS level (defense in depth):
    ufw allow 22/tcp
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw --force enable
```

---

## Phase 5 — Production Deployment Runbook

What `worldview-gitops/docs/production-deployment.md` must contain:

### 5.1 Update Workflow (Subsequent Deploys)

```bash
# On Hetzner server:
cd /opt/worldview/worldview
git pull origin main

# Update env files if changed:
cd /opt/worldview/worldview-gitops
git pull origin main
./scripts/setup-prod.sh   # Only if env files changed

# Rebuild and restart (note: brief downtime during image rebuild):
cd /opt/worldview/worldview
export $(grep -v '^#' ../worldview-gitops/env/prod/platform.env | xargs)
make prod-rebuild
```

### 5.2 Zero-Downtime Update Pattern

The current `make prod-rebuild` is NOT zero-downtime (it uses `--force-recreate`). For zero-downtime updates of stateless services (S9, S1, S3):

```bash
# Update one service at a time:
$(COMPOSE_PROD) pull <service>
$(COMPOSE_PROD) up -d --no-deps <service>
```

Kafka consumers (S4, S5, S6) can be restarted without message loss — Kafka retains messages until acknowledged. Brief consumer downtime is safe.

### 5.3 Rollback

```bash
# Roll back to a previous image tag:
cd /opt/worldview/worldview
git checkout <previous-commit>
make prod-rebuild

# If only env changed, no rebuild needed:
./scripts/setup-prod.sh
docker compose ... restart <service>
```

### 5.4 Health Verification Script

`worldview-gitops/scripts/verify-prod-health.sh` should test:

```bash
#!/usr/bin/env bash
set -euo pipefail
DOMAIN=${DOMAIN:?}

echo "=== Worldview Production Health Check ==="

# Frontend
status=$(curl -s -o /dev/null -w "%{http_code}" "https://${DOMAIN}/")
echo "Frontend (${DOMAIN}): ${status}"
[ "$status" = "200" ] || echo "  ERROR: expected 200"

# API Gateway health
status=$(curl -s -o /dev/null -w "%{http_code}" "https://api.${DOMAIN}/v1/health")
echo "API Gateway: ${status}"
[ "$status" = "200" ] || echo "  ERROR: expected 200"

# API Gateway readyz (checks all dependencies)
status=$(curl -s -o /dev/null -w "%{http_code}" "https://api.${DOMAIN}/readyz")
echo "API Gateway readyz: ${status}"
[ "$status" = "200" ] || echo "  WARNING: dependency unhealthy"

# WebSocket endpoint reachable (HTTP upgrade check)
status=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Upgrade: websocket" -H "Connection: Upgrade" \
  "https://ws.${DOMAIN}/v1/alerts/stream")
echo "Alert WebSocket endpoint: ${status}"
# 400 or 426 is fine — means Traefik reached the service but rejected the non-WS request

# TLS cert validity
expiry=$(echo | openssl s_client -servername "${DOMAIN}" -connect "${DOMAIN}:443" 2>/dev/null \
  | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
echo "TLS cert expiry: ${expiry}"

echo ""
echo "=== Container Status ==="
docker ps --format "table {{.Names}}\t{{.Status}}" | grep worldview
```

---

## Phase 6 — Zitadel Cloud Setup Checklist

The `infra/zitadel/README.md` covers this well, but `worldview-gitops/docs/zitadel-production.md` should consolidate with production-specific notes:

```
[ ] Create Zitadel Cloud account at https://zitadel.cloud
    - Free tier: up to 25,000 MAU (sufficient for thesis)
    - Choose instance name, e.g. worldview → https://worldview.zitadel.cloud

[ ] Create Project "worldview" in Zitadel console

[ ] Create Web Application (PKCE):
    - Name: worldview-web
    - Auth method: PKCE (no client secret)
    - Redirect URIs:
        https://<DOMAIN>/callback
    - Post-logout redirect URIs:
        https://<DOMAIN>
    - Token type: JWT (RS256)
    - Enable "User info inside ID token" (id_token userinfo assertion)

[ ] Note the Client ID (no secret for PKCE)

[ ] Set in worldview-gitops/env/prod/api-gateway.env:
    API_GATEWAY_OIDC_ISSUER_URL=https://worldview.zitadel.cloud
    API_GATEWAY_OIDC_CLIENT_ID=<copied-client-id>
    API_GATEWAY_OIDC_DISCOVERY_OPTIONAL=false
    API_GATEWAY_FRONTEND_URL=https://<DOMAIN>
    API_GATEWAY_COOKIE_SECURE=true

[ ] Set in worldview-gitops/env/prod/platform.env:
    ZITADEL_URL=https://worldview.zitadel.cloud
    ZITADEL_CLIENT_ID=<copied-client-id>

[ ] Test OIDC discovery endpoint is reachable from Hetzner server:
    curl https://worldview.zitadel.cloud/.well-known/openid-configuration | jq .issuer
```

---

## Phase 7 — Vercel Deployment Checklist

For the Vercel + Hetzner split architecture (frontend on Vercel, backends on Hetzner):

### 7.1 Why Vercel (Optional)

- Edge CDN for the Next.js frontend (faster global TTFB)
- Automatic preview deployments per PR
- The backend stack remains on Hetzner unchanged
- NOTE: The `worldview-web` service block in `docker-compose.prod.yml` can be removed when using Vercel (see comments in that file)

### 7.2 Vercel Setup Steps

```
[ ] Connect GitHub repo to Vercel:
    - Root directory: apps/worldview-web
    - Framework preset: Next.js
    - Build command: pnpm build
    - Install command: pnpm install --frozen-lockfile
    - Output directory: .next (auto-detected)
    - Node.js version: 20.x

[ ] Set Vercel environment variables (Settings → Environment Variables):

    # Server-side (not prefixed with NEXT_PUBLIC_):
    API_GATEWAY_URL=https://api.<DOMAIN>
      WHY: Next.js rewrites proxy /api/* server-side to this URL.
           Must be the HTTPS public URL (not the Docker-internal address).

    # Client-side (NEXT_PUBLIC_ prefix — baked in at build time):
    NEXT_PUBLIC_WS_BASE_URL=wss://ws.<DOMAIN>
      WHY: Frontend uses this to connect WebSocket directly to S10 alert service.
           Must match the Traefik alert router host (ws.${DOMAIN}).

    NEXT_PUBLIC_ZITADEL_URL=https://<your-instance>.zitadel.cloud
      WHY: OIDC login flow; frontend redirects to Zitadel for authentication.

    NEXT_PUBLIC_ZITADEL_CLIENT_ID=<zitadel-client-id>
      WHY: PKCE flow requires the client ID known at build/runtime.

    NEXT_PUBLIC_APP_NAME=Worldview
      WHY: Displayed in page titles and browser tabs.

[ ] Add Vercel deployment URL to Zitadel allowed redirect URIs:
    In Zitadel console → Application → Redirect URIs, add:
    https://<vercel-production-url>/callback
    https://<DOMAIN>/callback      (custom domain)

[ ] Configure custom domain in Vercel:
    - Add <DOMAIN> as custom domain in Vercel project settings
    - Update DNS: CNAME <DOMAIN> → cname.vercel-dns.com
    - NOTE: If using Hetzner for frontend too, remove this entry — keep A record pointing to Hetzner

[ ] Update CORS on api-gateway for Vercel domain:
    API_GATEWAY_CORS_ORIGINS=https://<DOMAIN>,https://<vercel-subdomain>.vercel.app

[ ] Update Zitadel redirect URIs for Vercel preview deployments (optional):
    Add regex pattern: https://worldview-*.vercel.app/callback
    (Zitadel supports wildcard/regex redirect URIs via Dev Mode setting)

[ ] Smoke test:
    - Visit https://<DOMAIN>/ → landing page loads
    - Click Login → redirects to Zitadel → callback succeeds → dashboard loads
    - Dashboard widgets load data from https://api.<DOMAIN>/
    - Alert bell connects via wss://ws.<DOMAIN>/v1/alerts/stream
```

### 7.3 Vercel vs Hetzner Decision Matrix

| Concern | Vercel (split) | Hetzner (all-in) |
|---------|---------------|-----------------|
| Frontend TTFB | Edge CDN, ~50ms globally | Single-region, ~50-200ms |
| Preview deploys | Automatic per PR | Manual |
| Cost | Free tier for thesis | Included in server cost |
| Complexity | Two deploy pipelines | One `make prod-rebuild` |
| WebSocket | Works (WS goes direct to Hetzner) | Works |
| CORS | Must whitelist Vercel domain | Not needed |

**Recommendation for thesis**: Use Hetzner-only (`make prod`) for simplicity. Switch to Vercel split only if global CDN matters.

---

## Phase 8 — Monitoring Setup Checklist

```
[ ] Start monitoring stack in production:
    $(COMPOSE_PROD) --profile monitoring up -d
    # OR add --profile monitoring to COMPOSE_PROD in Makefile

[ ] Verify Grafana accessible:
    https://grafana.<DOMAIN>  → 200

[ ] Change Grafana admin password:
    Login → Profile → Change Password

[ ] Create Grafana dashboards (datasources are auto-provisioned):
    - Service Health (RED: Request Rate / Error Rate / Duration per service)
    - Kafka Pipeline (consumer group lag per topic)
    - Cache Hit Ratio (Valkey hit/miss)
    - NLP Throughput (articles/hour through S4→S5→S6→S7)
    - LLM Cost (DeepInfra token usage, fallback frequency)

[ ] Set up alerting rules in Alertmanager:
    - Error rate > 5% on api-gateway (5m window)
    - Consumer lag > 10,000 messages on any topic
    - Service container down (scrape target missing)
    - TLS certificate expiry < 30 days
    - Disk usage > 80% on Hetzner volume

[ ] Configure Alertmanager email notifications:
    # infra/alertmanager/alertmanager.yml — set smtp_* vars
    ALERTMANAGER_SMTP_HOST=
    ALERTMANAGER_SMTP_FROM=
    ALERTMANAGER_SMTP_TO=
```

---

## Phase 9 — Backup and Disaster Recovery

What `worldview-gitops/docs/disaster-recovery.md` must cover:

### 9.1 What to Back Up

| Data | Location | Backup Method | Frequency |
|------|----------|--------------|-----------|
| All Postgres DBs (9 databases) | Docker volume `worldview_postgres_data` | `pg_dumpall` → S3/Backblaze | Daily |
| MinIO object storage (bronze/silver/gold) | Docker volume `worldview_minio_data` | `mc mirror` → Backblaze B2 | Daily |
| Let's Encrypt certificates | Docker volume `traefik_letsencrypt` | `docker cp` → worldview-gitops/backups/ | Weekly |
| Grafana dashboards | Docker volume `worldview_grafana_data` | Export JSON → worldview-gitops/grafana/ | After changes |
| Production env files | `worldview-gitops/env/prod/` | Git push (private repo) | After changes |

### 9.2 Database Backup Script

```bash
# Add to crontab (0 3 * * * = 3am daily)
docker exec worldview-postgres-1 pg_dumpall -U postgres \
  | gzip > /opt/backups/worldview-$(date +%Y%m%d).sql.gz
# Rotate: keep 7 days
find /opt/backups -name "worldview-*.sql.gz" -mtime +7 -delete
```

### 9.3 Certificate Recovery

```
WARNING: Deleting the `traefik_letsencrypt` Docker volume forces Let's Encrypt
re-registration. Let's Encrypt rate-limits certificate issuance to 5 duplicate
certificates per domain per week. If you hit the limit, use the Let's Encrypt
staging server to test, then switch back to production resolver.

To back up certificates:
  docker run --rm -v traefik_letsencrypt:/data busybox tar cvf - /data > letsencrypt-backup.tar

To restore:
  docker run --rm -v traefik_letsencrypt:/data busybox tar xvf - < letsencrypt-backup.tar
```

---

## Phase 10 — Identified Gaps in worldview Repo Docs (Fixes Needed Here)

These gaps are in the worldview repo itself (not gitops), and should be fixed:

### 10.1 docs/workflows/local-dev.md — Pre-Deployment Checklist Inconsistency

The "Pre-Deployment Checklist (Before Hetzner / Production)" section (lines 426-452) references `scripts/local-k8s.sh` (k3s workflow). The actual production target is now Docker Compose + Traefik. This section should be updated to reflect:

```markdown
### Tier 1 — Always Run (< 5 minutes)
make qa                          # Lint + typecheck + unit tests

### Tier 2 — Before First Deploy on Hetzner
make prod DOMAIN=<test-domain> ACME_EMAIL=<email>   # Verify compose is valid
docker compose ... config        # Validate merged compose files
./scripts/verify-prod-health.sh  # Smoke tests (from worldview-gitops)

### Tier 3 — Full Platform Validation
make dev && make seed            # Start dev stack
make qa-exhaustive               # Full QA against dev stack
```

### 10.2 docs/apps/worldview-web.md — Inconsistency: Two Docker Sections

The worldview-web.md file has two Docker sections: one at line 336 (stub saying "No Dockerfile yet") and one at line 362 (correct, describing multi-stage Dockerfile and Docker Compose). The first section at line 336 is stale and should be removed.

### 10.3 services/alert/configs/prod.env.example — Missing

The alert service (S10) does not have a `prod.env.example` file. It should be added (mirroring the pattern of other services).

### 10.4 services/intelligence-migrations/configs/prod.env.example — Missing

The `intelligence-migrations` init container does not have a `prod.env.example`. It needs at minimum `DATABASE_URL` for the intelligence_db.

### 10.5 apps/worldview-web/.env.example — Missing Production Vars

The `.env.example` only documents dev vars. A production section should be added as comments:

```bash
# ── Production (Hetzner Docker Compose) ─────────────────────────
# API_GATEWAY_URL=http://api-gateway:8000   (Docker-internal; set in compose.prod.yml)
# NEXT_PUBLIC_WS_BASE_URL=wss://ws.${DOMAIN}
# NEXT_PUBLIC_ZITADEL_URL=https://<instance>.zitadel.cloud
# NEXT_PUBLIC_ZITADEL_CLIENT_ID=<client-id>
#
# ── Production (Vercel split deployment) ─────────────────────────
# API_GATEWAY_URL=https://api.<DOMAIN>      (server-side; set as Vercel env var)
# NEXT_PUBLIC_WS_BASE_URL=wss://ws.<DOMAIN>
# NEXT_PUBLIC_ZITADEL_URL=https://<instance>.zitadel.cloud
# NEXT_PUBLIC_ZITADEL_CLIENT_ID=<client-id>
```

---

## Summary Table

### Category Health

| Category | Count | Complete | Stale | Missing | Issues |
|----------|-------|----------|-------|---------|--------|
| Service docs | 11 | 11 | 1 (worldview-web Docker) | 0 | 1 |
| Service context files | 11 | 11 | 0 | 0 | 0 |
| Prod env examples | 11 | 9 | 0 | 2 (alert, intelligence-migrations) | 2 |
| Runbooks | 6 | 4 | 1 (PRODUCTION_READINESS) | 0 | 1 |
| gitops docs | 0 | 0 | 0 | 8 | 8 |
| gitops env/prod | 0 | 0 | 0 | 11 | 11 |
| gitops scripts | 1 (setup-dev.sh) | 0 complete | 0 | 3 (setup-prod, hetzner-bootstrap, verify-health) | 3 |

### Priority-Ordered Recommendations

1. **[P0] Create `worldview-gitops/env/prod/platform.env`** — The `make prod` command requires `DOMAIN` and `ACME_EMAIL`; these need a home. Currently, you must export them manually every SSH session.

2. **[P0] Create `worldview-gitops/scripts/setup-prod.sh`** — Mirror of `setup-dev.sh` for production; copies `env/prod/*.env` to `worldview/services/*/configs/docker.env`.

3. **[P0] Create `worldview-gitops/docs/hetzner-setup.md`** — Server provisioning, firewall rules, Docker install, SSH deploy key setup. Without this, a server rebuild requires reverse-engineering from Makefile comments.

4. **[P0] Create `worldview-gitops/docs/production-deployment.md`** — First-deploy runbook, update workflow, rollback procedure. The production compose is ready; the runbook is not.

5. **[P0] Generate and store RS256 keypair** in `worldview-gitops/env/prod/api-gateway.env` — `API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY` and `PUBLIC_KEY` are required for all backend auth. Currently undocumented how to generate and store these for production.

6. **[P1] Create `worldview-gitops/scripts/verify-prod-health.sh`** — Smoke test script that validates all public endpoints post-deploy.

7. **[P1] Add `prod.env.example` for alert service and intelligence-migrations** in worldview repo.

8. **[P1] Create `worldview-gitops/docs/vercel-deployment.md`** — Complete the Vercel split deployment path with env var spec and CORS notes.

9. **[P1] Create `worldview-gitops/docs/disaster-recovery.md`** — Postgres backup, MinIO mirror, certificate backup, restore procedures.

10. **[P2] Update `docs/PRODUCTION_READINESS.md`** — It's 7 months stale (2026-03-30). Mark completed items (Traefik TLS, Zitadel auth, CORS, rate limiting, RS256 JWT) and add new P0s from this audit.

---

## Compounding Check

- **BUG_PATTERNS.md**: No new failure pattern discovered. No update needed.
- **STANDARDS.md**: No new convention identified. No update needed.
- **HIGH_RISK_PATTERNS.md**: WS JWT token leakage in Traefik logs already documented in `docs/references/traefik-ws-token-masking.md`. Consider adding HR entry cross-referencing this.
- **REVIEW_CHECKLIST.md**: Could add checklist item: "Production deploy: verify no direct service ports exposed (ss -tlnp); verify HTTPS redirect active; verify Grafana default password changed."
- **MASTER_PLAN.md**: Section 6 (Infrastructure) describes Docker Compose but doesn't mention `docker-compose.prod.yml` or Traefik. Consider adding a subsection for the production Traefik overlay.
- **Skill definitions**: No skill update needed — this is a documentation-only session.
