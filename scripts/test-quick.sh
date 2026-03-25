#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Running quick test suite..."
echo "1) Architecture tests"
pytest tests/architecture -v --tb=short --maxfail=3

echo "2) Portfolio contract tests"
pytest services/portfolio/tests/contract -m contract -v --tb=short --maxfail=3

echo "3) Service fast-path tests (no integration/e2e/live/slow)"
for service in portfolio market-ingestion market-data content-ingestion content-store nlp-pipeline knowledge-graph rag-chat api-gateway alert; do
  if [[ -d "services/$service/tests" ]]; then
    echo "- services/$service"
    pytest "services/$service/tests" \
      -m "not integration and not e2e and not live and not slow" \
      -v --tb=short --maxfail=3
  fi
done

echo "Quick test suite passed."
