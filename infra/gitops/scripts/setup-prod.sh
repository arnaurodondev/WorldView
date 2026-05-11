#!/usr/bin/env bash
# setup-prod.sh — Copy production env files to worldview services
#
# Run from worldview-gitops directory on the Hetzner server:
#   ./scripts/setup-prod.sh [--worldview-dir /opt/worldview/worldview]
#
# What it does:
#   1. Reads env/prod/*.env from THIS repo (worldview-gitops)
#   2. Copies each file to worldview/services/<service>/configs/docker.env
#   3. Injects DOMAIN/ACME_EMAIL/ZITADEL vars from platform.env into compose env
#
# WHY a separate script (not setup-dev.sh):
#   Production env files contain real secrets (Postgres passwords, API keys, RS256 keys).
#   They live only in worldview-gitops (private), never in the worldview repo.
#   This script is the only path for secrets to reach the running services.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GITOPS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORLDVIEW_DIR="${1:-/opt/worldview/worldview}"

if [ ! -d "${WORLDVIEW_DIR}" ]; then
    echo "ERROR: worldview directory not found at ${WORLDVIEW_DIR}"
    echo "Usage: $0 [--worldview-dir <path>]"
    exit 1
fi

PROD_ENV_DIR="${GITOPS_DIR}/env/prod"
if [ ! -d "${PROD_ENV_DIR}" ]; then
    echo "ERROR: ${PROD_ENV_DIR} not found. Create env/prod/ with production env files."
    echo "Template: templates/platform.env.template"
    exit 1
fi

# Map: env/prod/<name>.env → services/<service>/configs/docker.env
declare -A SERVICE_MAP=(
    ["portfolio"]="portfolio"
    ["market-ingestion"]="market-ingestion"
    ["market-data"]="market-data"
    ["content-ingestion"]="content-ingestion"
    ["content-store"]="content-store"
    ["nlp-pipeline"]="nlp-pipeline"
    ["knowledge-graph"]="knowledge-graph"
    ["rag-chat"]="rag-chat"
    ["api-gateway"]="api-gateway"
    ["alert"]="alert"
)

echo "=== Worldview Production Env Setup ==="
echo "Source: ${PROD_ENV_DIR}"
echo "Target: ${WORLDVIEW_DIR}/services/"
echo ""

COPIED=0
MISSING=0

for name in "${!SERVICE_MAP[@]}"; do
    src="${PROD_ENV_DIR}/${name}.env"
    svc="${SERVICE_MAP[$name]}"
    dst="${WORLDVIEW_DIR}/services/${svc}/configs/docker.env"

    if [ ! -f "${src}" ]; then
        echo "  MISSING: env/prod/${name}.env (skipping ${svc})"
        ((MISSING++)) || true
        continue
    fi

    mkdir -p "$(dirname "${dst}")"
    cp "${src}" "${dst}"
    echo "  OK: ${name}.env → services/${svc}/configs/docker.env"
    ((COPIED++)) || true
done

# Intelligence-migrations uses inline environment: in docker-compose, not env_file.
# Its vars (INTELLIGENCE_DB_URL etc.) should be in env/prod/api-gateway.env or a
# dedicated env/prod/intelligence-migrations.env that gets injected via compose override.
echo ""
echo "Copied: ${COPIED} files, Skipped (missing): ${MISSING} files"

if [ "${MISSING}" -gt 0 ]; then
    echo ""
    echo "WARNING: ${MISSING} service env files are missing."
    echo "Create them in env/prod/ using services/*/configs/prod.env.example as templates."
fi

echo ""
echo "Done. Run: cd ${WORLDVIEW_DIR} && make prod"
