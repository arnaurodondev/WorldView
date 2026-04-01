#!/usr/bin/env bash
# scripts/run-service-e2e.sh <service-name>
#
# Runs e2e tests for a single service with the correct database URL env var
# injected.  Requires the docker-compose test stack to be running:
#
#   make infra-up
#
# Usage:
#   ./scripts/run-service-e2e.sh content-store
#   ./scripts/run-service-e2e.sh nlp-pipeline
#   ./scripts/run-service-e2e.sh knowledge-graph
#   ./scripts/run-service-e2e.sh alert
#   ./scripts/run-service-e2e.sh content-ingestion
#
set -euo pipefail

SERVICE="${1:?Usage: $0 <service-name>}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_BASE="postgresql+asyncpg://postgres:postgres@localhost:55433"

case "$SERVICE" in
  content-ingestion)
    export CONTENT_INGESTION_E2E_DATABASE_URL="${PG_BASE}/content_ingestion_db"
    ;;
  content-store)
    export CONTENT_STORE_E2E_DATABASE_URL="${PG_BASE}/content_store_db"
    ;;
  nlp-pipeline)
    export NLP_PIPELINE_E2E_DATABASE_URL="${PG_BASE}/nlp_db"
    ;;
  knowledge-graph)
    export KNOWLEDGE_GRAPH_E2E_DATABASE_URL="${PG_BASE}/intelligence_db"
    ;;
  alert)
    export ALERT_E2E_DATABASE_URL="${PG_BASE}/alert_db"
    ;;
  portfolio)
    # Portfolio e2e tests hit a live service (localhost:8001), no DB URL needed
    ;;
  market-ingestion)
    # Market-ingestion e2e tests hit a live service (localhost:8002), no DB URL needed
    ;;
  market-data)
    # Market-data e2e tests hit a live service (localhost:8003), no DB URL needed
    ;;
  *)
    echo "ERROR: Unknown service: $SERVICE" >&2
    echo "Known services: content-ingestion content-store nlp-pipeline knowledge-graph alert" >&2
    echo "                portfolio market-ingestion market-data" >&2
    exit 1
    ;;
esac

SERVICE_DIR="$ROOT_DIR/services/$SERVICE"
E2E_DIR="$SERVICE_DIR/tests/e2e"

if [[ ! -d "$E2E_DIR" ]]; then
  echo "No e2e tests found for $SERVICE (expected: $E2E_DIR)" >&2
  exit 1
fi

SERVICE_PYTHON="$SERVICE_DIR/.venv/bin/python"
if [[ ! -x "$SERVICE_PYTHON" ]]; then
  SERVICE_PYTHON="python"
fi

echo "=== Running e2e tests for $SERVICE ==="
cd "$SERVICE_DIR"
"$SERVICE_PYTHON" -m pytest tests/e2e/ -m e2e -v --tb=short
