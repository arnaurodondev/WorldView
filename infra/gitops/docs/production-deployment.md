# Production Deployment Runbook

> **First-time setup**: Follow `hetzner-setup.md` before this guide.
> **Stack**: Hetzner + Docker Compose + Traefik v3
> **Deploy command**: `make prod` (requires `DOMAIN` and `ACME_EMAIL` set)

---

## First Deploy

### Prerequisites
- Hetzner server bootstrapped (`hetzner-setup.sh` completed)
- DNS A records pointing to server IP
- worldview-gitops cloned to `/opt/worldview/worldview-gitops`
- All env files in `env/prod/` (run `setup-prod.sh`)
- RS256 keypair stored in `env/prod/api-gateway.env`

### Steps

```bash
cd /opt/worldview/worldview
export $(grep -v '^#' ../worldview-gitops/env/prod/platform.env | xargs)

make prod
```

Wait 30–60 seconds for Traefik to obtain Let's Encrypt certificates, then verify:

```bash
export DOMAIN=worldview.example.com
./infra/gitops/scripts/verify-prod-health.sh
```

---

## Update Workflow (Subsequent Deploys)

### Standard update (pull + rebuild)

```bash
ssh user@<server-IP>
cd /opt/worldview/worldview
git pull origin main

# If env files changed in worldview-gitops:
cd ../worldview-gitops && git pull && ./scripts/setup-prod.sh && cd ../worldview

export $(grep -v '^#' ../worldview-gitops/env/prod/platform.env | xargs)
make prod-rebuild
```

### Zero-downtime update (stateless services only)

For api-gateway, worldview-web, and rag-chat (stateless — no consumer lag risk):

```bash
COMPOSE_PROD="docker compose -f infra/compose/docker-compose.yml -f infra/compose/docker-compose.prod.yml --profile infra"
$COMPOSE_PROD build api-gateway
$COMPOSE_PROD up -d --no-deps api-gateway
```

Kafka consumers (nlp-pipeline, knowledge-graph, content-ingestion, etc.) accumulate
consumer lag during restart but are safe — Kafka retains messages. Brief downtime is acceptable.

---

## Rollback

```bash
cd /opt/worldview/worldview
git log --oneline -10   # Find previous commit

git checkout <previous-commit-hash>
export $(grep -v '^#' ../worldview-gitops/env/prod/platform.env | xargs)
make prod-rebuild

# Return to main after investigation:
git checkout main
```

If only env changed (no code change):

```bash
cd ../worldview-gitops
# Restore previous env file values
./scripts/setup-prod.sh
cd ../worldview
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               --profile infra restart <service>
```

---

## Monitoring Stack

The monitoring stack (Grafana, Prometheus, Loki, Tempo, Alertmanager) is separate
from the core infra stack. Start it after the core stack is healthy:

```bash
export $(grep -v '^#' ../worldview-gitops/env/prod/platform.env | xargs)
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               --profile monitoring up -d
```

Or include `--profile monitoring` in `COMPOSE_PROD` in the Makefile for all-in-one start.

Grafana is accessible at `https://grafana.${DOMAIN}`. **Change the default password immediately.**

---

## Useful Commands

```bash
# Check all container statuses:
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               --profile infra ps

# Follow all worldview-web logs:
docker logs -f worldview-worldview-web-1

# Follow api-gateway logs:
docker logs -f worldview-api-gateway-1

# Follow Traefik logs (TLS cert acquisition, routing):
docker logs -f worldview-traefik-1

# Check Kafka consumer lag (requires kafka container):
docker exec worldview-kafka-1 \
  kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --all-groups | grep -v "^$"

# Enter a running container:
docker exec -it worldview-api-gateway-1 /bin/bash

# Manual Postgres connection:
docker exec -it worldview-postgres-1 psql -U postgres
```

---

## Traefik Certificate Management

Let's Encrypt certificates are stored in the `traefik_letsencrypt` Docker volume
and renewed automatically 30 days before expiry.

```bash
# View certificate status:
docker logs worldview-traefik-1 2>&1 | grep -i "certificate\|acme\|renew"

# Force cert renewal (rarely needed):
docker exec worldview-traefik-1 kill -USR1 1

# Backup certificates (do this regularly):
docker run --rm -v traefik_letsencrypt:/data busybox \
  tar cvf - /data > /opt/backups/letsencrypt-$(date +%Y%m%d).tar
```

**WARNING**: Let's Encrypt rate-limits certificate issuance to 5 duplicate certificates
per domain per week. Never delete the `traefik_letsencrypt` volume unless you understand
this limit. Use staging resolver for testing:
```
--certificatesresolvers.le.acme.caServer=https://acme-staging-v02.api.letsencrypt.org/directory
```

---

## Cron: Nightly Database Backup

Add to crontab (`crontab -e`) on the Hetzner server:

```cron
# Worldview DB backup — runs at 3:00 AM daily
0 3 * * * docker exec worldview-postgres-1 pg_dumpall -U postgres | gzip > /opt/backups/worldview-$(date +\%Y\%m\%d).sql.gz

# Rotate backups — keep 7 days
15 3 * * * find /opt/backups -name "worldview-*.sql.gz" -mtime +7 -delete
```
