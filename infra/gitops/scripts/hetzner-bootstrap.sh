#!/usr/bin/env bash
# hetzner-bootstrap.sh — Idempotent Hetzner server setup
#
# Run once on a fresh Ubuntu 24.04 Hetzner server as root or sudo user:
#   curl -fsSL https://raw.githubusercontent.com/your-org/worldview-gitops/main/scripts/hetzner-bootstrap.sh | bash
#   OR: scp this file to server and run: sudo bash hetzner-bootstrap.sh
#
# Idempotent: safe to re-run if partially executed.
# Does NOT clone repos (do that manually with deploy keys).

set -euo pipefail

echo "=== Worldview Hetzner Bootstrap ==="
echo "Server: $(hostname)"
echo ""

# ── 1. System updates ─────────────────────────────────────────────────────────
echo "[1/6] System update..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq curl wget git unzip jq openssl postgresql-client

# ── 2. Docker (official install, not snap) ────────────────────────────────────
echo "[2/6] Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    # Add current user to docker group (re-login required to take effect)
    usermod -aG docker "${SUDO_USER:-$USER}" || true
    echo "  Docker installed: $(docker --version)"
else
    echo "  Docker already installed: $(docker --version)"
fi

# Docker Compose plugin
if ! docker compose version &>/dev/null 2>&1; then
    apt-get install -y -qq docker-compose-plugin
fi
echo "  Docker Compose: $(docker compose version)"

# ── 3. Swap (prevent OOM under NLP/embedding load) ────────────────────────────
echo "[3/6] Swap..."
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    if ! grep -q '/swapfile' /etc/fstab; then
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
    fi
    echo "  4 GB swap created and enabled"
else
    echo "  Swap already configured ($(swapon --show))"
fi

# ── 4. UFW firewall ────────────────────────────────────────────────────────────
echo "[4/6] UFW firewall..."
if command -v ufw &>/dev/null; then
    # Allow SSH (CRITICAL: do this before enabling, or you'll lock yourself out)
    ufw allow 22/tcp comment 'SSH'
    # Allow HTTP (Let's Encrypt HTTP-01 challenge + Traefik redirect to HTTPS)
    ufw allow 80/tcp comment 'HTTP (Let'\''s Encrypt + redirect)'
    # Allow HTTPS (all production traffic via Traefik)
    ufw allow 443/tcp comment 'HTTPS'
    # Enable (--force to avoid interactive prompt in scripts)
    ufw --force enable
    echo "  UFW enabled: ports 22, 80, 443 open"
    echo "  All other ports (5432, 6379, 9092, 8000-8010, etc.) are BLOCKED"
else
    echo "  WARNING: ufw not found. Install with: apt-get install ufw"
fi

# ── 5. Directory structure ─────────────────────────────────────────────────────
echo "[5/6] Directory structure..."
mkdir -p /opt/worldview /opt/backups
chmod 755 /opt/worldview /opt/backups
echo "  Created: /opt/worldview /opt/backups"

# ── 6. Deploy key hint ────────────────────────────────────────────────────────
echo "[6/6] SSH deploy key..."
DEPLOY_KEY="${HOME}/.ssh/id_deploy"
if [ ! -f "${DEPLOY_KEY}" ]; then
    ssh-keygen -t ed25519 -C "hetzner-worldview-deploy" -f "${DEPLOY_KEY}" -N ""
    echo ""
    echo "  Deploy key generated: ${DEPLOY_KEY}"
    echo ""
    echo "  === ACTION REQUIRED ==="
    echo "  Add this public key to worldview-gitops GitHub repo:"
    echo "  Repository → Settings → Deploy keys → Add deploy key (read-only)"
    echo ""
    cat "${DEPLOY_KEY}.pub"
    echo ""
    echo "  Then configure SSH to use this key:"
    cat >> "${HOME}/.ssh/config" << 'EOF'

Host github.com
  IdentityFile ~/.ssh/id_deploy
  IdentitiesOnly yes
EOF
    echo "  SSH config updated."
else
    echo "  Deploy key already exists at ${DEPLOY_KEY}"
fi

echo ""
echo "=== Bootstrap complete! ==="
echo ""
echo "Next steps:"
echo "  1. Add the deploy key above to worldview-gitops GitHub repo (if newly generated)"
echo "  2. Clone repos:"
echo "     cd /opt/worldview"
echo "     git clone git@github.com:your-org/worldview.git worldview"
echo "     git clone git@github.com:your-org/worldview-gitops.git worldview-gitops"
echo "  3. Set up production env files:"
echo "     cd /opt/worldview/worldview-gitops"
echo "     cp templates/platform.env.template env/prod/platform.env"
echo "     # Edit env/prod/platform.env with your DOMAIN, ACME_EMAIL, ZITADEL_URL"
echo "     ./scripts/setup-prod.sh"
echo "  4. Start the stack:"
echo "     cd /opt/worldview/worldview"
echo "     export \$(grep -v '^#' ../worldview-gitops/env/prod/platform.env | xargs)"
echo "     make prod"
