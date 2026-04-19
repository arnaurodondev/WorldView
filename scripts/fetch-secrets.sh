#!/usr/bin/env bash
# scripts/fetch-secrets.sh — Fetch confidential environment variables from worldview-config repo
#
# Usage:
#   ./scripts/fetch-secrets.sh [--env dev|prod] [--repo owner/worldview-config]
#
# Prerequisites:
#   - gh CLI authenticated (`gh auth login`)
#   - Access to the worldview-config private repo
#
# The script clones/pulls the worldview-config repo to a temporary directory,
# copies the appropriate .env files for each service, and cleans up.
# No secrets are stored in the worldview repo — only in worldview-config.

set -euo pipefail

ENV="${1:-dev}"
REPO="${2:-arnaurodondev/worldview-config}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

echo "🔑 Fetching secrets for env=$ENV from $REPO..."

# Clone the config repo (shallow, single branch)
if ! gh repo clone "$REPO" "$TMP_DIR/config" -- --depth=1 --single-branch 2>/dev/null; then
    echo "❌ Failed to clone $REPO. Make sure:"
    echo "   1. You have gh CLI installed and authenticated (gh auth login)"
    echo "   2. You have access to the $REPO repository"
    echo "   3. The repository exists"
    echo ""
    echo "To create the worldview-config repo, see docs/runbooks/secrets-management.md"
    exit 1
fi

CONFIG_DIR="$TMP_DIR/config/$ENV"
if [ ! -d "$CONFIG_DIR" ]; then
    echo "❌ Directory '$ENV/' not found in $REPO"
    echo "   Expected structure:"
    echo "     worldview-config/"
    echo "       dev/"
    echo "         api-gateway.env"
    echo "         portfolio.env"
    echo "         ..."
    echo "       prod/"
    echo "         api-gateway.env"
    echo "         ..."
    exit 1
fi

# Copy env files to each service
COPIED=0
for env_file in "$CONFIG_DIR"/*.env; do
    [ -f "$env_file" ] || continue
    svc_name=$(basename "$env_file" .env)

    # Map service name to target path
    if [ "$svc_name" = "worldview-web" ]; then
        target="$ROOT_DIR/apps/worldview-web/.env.local"
    elif [ -d "$ROOT_DIR/services/$svc_name/configs" ]; then
        target="$ROOT_DIR/services/$svc_name/configs/docker.env"
    else
        echo "  ⚠ Skipping unknown service: $svc_name"
        continue
    fi

    cp "$env_file" "$target"
    echo "  ✅ $svc_name → $(basename "$target")"
    COPIED=$((COPIED + 1))
done

echo ""
echo "✅ Copied $COPIED secret files for env=$ENV"
echo "   These files are git-ignored and must NEVER be committed."
