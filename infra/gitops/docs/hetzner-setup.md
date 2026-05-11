# Hetzner Server Setup Guide

> **Target**: Ubuntu 24.04 on Hetzner Cloud
> **Stack**: Docker Compose + Traefik v3 (no Kubernetes required)
> **Minimum spec**: CPX31 (4 vCPU, 8 GB RAM, 160 GB NVMe) — ~€13/month
> **Recommended**: CPX41 (8 vCPU, 16 GB RAM) for NLP/embedding workloads

---

## 1. Hetzner Cloud Provisioning

In the Hetzner Cloud console (console.hetzner.cloud):

1. **Create server**:
   - Image: Ubuntu 24.04
   - Region: `nbg1` (Nuremberg, EU) or `hel1` (Helsinki)
   - Type: CPX31 minimum (CPX41 recommended for NLP pipeline)
   - SSH key: add your public key at provisioning time
   - **Do NOT use the "Cloud Firewall" yet** — configure UFW at OS level first

2. **Note the server's public IP address** — you'll need it for DNS.

---

## 2. DNS Configuration

Point all subdomains to the server IP. Use TTL 60 initially (for fast cert acquisition).

| Record | Type | Value |
|--------|------|-------|
| `worldview.example.com` | A | `<server-IP>` |
| `api.worldview.example.com` | A | `<server-IP>` |
| `ws.worldview.example.com` | A | `<server-IP>` |
| `grafana.worldview.example.com` | A | `<server-IP>` |
| `www.worldview.example.com` | A | `<server-IP>` |

After the stack is running and certs are confirmed, raise TTL to 3600.

**Wait for DNS propagation** before starting `make prod` — Let's Encrypt's HTTP-01 challenge
validates domain ownership by hitting `http://your-domain/.well-known/acme-challenge/...`.
If DNS is not propagated, certificate issuance fails.

---

## 3. Bootstrap the Server

SSH into the server and run the bootstrap script (idempotent):

```bash
ssh root@<server-IP>
curl -fsSL https://raw.githubusercontent.com/your-org/worldview-gitops/main/scripts/hetzner-bootstrap.sh | bash
```

Or copy and run manually:

```bash
scp infra/gitops/scripts/hetzner-bootstrap.sh root@<server-IP>:/tmp/
ssh root@<server-IP> "bash /tmp/hetzner-bootstrap.sh"
```

The script:
- Updates system packages
- Installs Docker (official method, not snap)
- Creates 4 GB swap file (prevents OOM under NLP load)
- Configures UFW: allows 22/tcp, 80/tcp, 443/tcp, blocks everything else
- Creates `/opt/worldview` directory
- Generates a deploy key for GitHub (read-only)

---

## 4. Deploy Key Setup

After running `hetzner-bootstrap.sh`, the script prints a deploy key. Add it to worldview-gitops:

1. Copy the key printed by the script (starts with `ssh-ed25519`)
2. In GitHub: worldview-gitops repository → Settings → Deploy keys → Add deploy key
   - Title: `hetzner-prod`
   - Key: paste the public key
   - Allow write access: **NO** (read-only is sufficient)

---

## 5. Clone Repositories

```bash
ssh root@<server-IP>
cd /opt/worldview

# Main platform (public or private)
git clone git@github.com:your-org/worldview.git worldview

# Secrets repo (private — requires the deploy key above)
git clone git@github.com:your-org/worldview-gitops.git worldview-gitops
```

---

## 6. Production Environment Files

```bash
cd /opt/worldview/worldview-gitops

# Copy the template and fill in your values:
cp templates/platform.env.template env/prod/platform.env
${EDITOR:-nano} env/prod/platform.env
# Set: DOMAIN, ACME_EMAIL, ZITADEL_URL, ZITADEL_CLIENT_ID, NEXT_PUBLIC_WS_BASE_URL

# Copy service env files to worldview:
./scripts/setup-prod.sh --worldview-dir /opt/worldview/worldview
```

**Required: Generate RS256 keypair for internal JWT auth**

The api-gateway signs internal JWTs (RS256) that all backend services verify.
Generate and store the keypair in env/prod/api-gateway.env:

```bash
cd /opt/worldview/worldview
python scripts/generate-internal-keypair.py > /tmp/keypair.txt
# Copy the output into env/prod/api-gateway.env under:
# API_GATEWAY_INTERNAL_JWT_PRIVATE_KEY=<...>
# API_GATEWAY_INTERNAL_JWT_PUBLIC_KEY=<...>
```

---

## 7. Verify Config Before Starting

```bash
cd /opt/worldview/worldview
export $(grep -v '^#' ../worldview-gitops/env/prod/platform.env | xargs)

# Validate the merged compose config:
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               --profile infra config > /dev/null
echo "Config valid"
```

---

## 8. First Production Deploy

```bash
cd /opt/worldview/worldview
export $(grep -v '^#' ../worldview-gitops/env/prod/platform.env | xargs)
make prod
```

**Wait 30–60 seconds** for Let's Encrypt to issue certificates on first run. Monitor:

```bash
docker logs worldview-traefik-1 2>&1 | grep -i "acme\|certificate\|error"
```

---

## 9. Post-Deploy Verification

```bash
cd /opt/worldview/worldview-gitops
export DOMAIN=worldview.example.com
./scripts/verify-prod-health.sh
```

---

## 10. Security Post-Checks

```bash
# Verify no infra ports are publicly accessible (should all be empty):
ss -tlnp | grep -E "8000|8001|8002|8003|8004|8005|8006|8007|8008|8010|5432|6379|9092"

# Verify HTTP → HTTPS redirect:
curl -I http://${DOMAIN}   # Must return 301 to https://

# Change Grafana default password IMMEDIATELY:
# Navigate to https://grafana.${DOMAIN} → admin/admin → change password

# Check Traefik access logs do not leak JWT tokens:
docker logs worldview-traefik-1 2>&1 | grep "token=" | head -5
# Should be empty. If tokens appear, see docs/references/traefik-ws-token-masking.md
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Certificate not issued after 5 min | DNS not propagated | `dig A ${DOMAIN}` — must return server IP |
| Certificate not issued | Port 80 blocked | Check UFW: `ufw status`; ensure `80/tcp ALLOW` |
| Services in `Created` state | Docker Compose v5 detach race | `docker ps -aq --filter status=created \| xargs docker start` |
| `Can't locate revision` in migrations | Stale image | `make prod-rebuild` (forces `--no-cache`) |
| `upgrade-insecure-requests` absent from CSP | `NEXT_PUBLIC_WS_BASE_URL` is `ws://` | Set `wss://` in env/prod/platform.env (BP-324) |
